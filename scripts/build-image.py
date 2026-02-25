#!/usr/bin/env python3
"""
webBSD automated image builder.

Builds a FreeBSD disk image for v86 browser emulation.
Reads configuration from webbsd.conf and automates the entire
FreeBSD installation via QEMU serial console.

Usage:
    python3 scripts/build-image.py [--config webbsd.conf]
"""

import subprocess
import sys
import os
import time
import select
import signal
import argparse
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
IMAGES_DIR = os.path.join(PROJECT_DIR, "images")


def load_config(path):
    """Load shell-style config file."""
    config = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                # Strip quotes
                val = val.strip().strip('"').strip("'")
                config[key.strip()] = val
    return config


class QEMUAutomator:
    """Automates FreeBSD installation via QEMU serial console."""

    def __init__(self, config):
        self.config = config
        self.proc = None
        self.buffer = ""

    def start_qemu(self, iso_path, img_path):
        """Start QEMU with serial console."""
        cmd = [
            "qemu-system-i386",
            "-m", str(self.config.get("INSTALL_MEM", "256")),
            "-cdrom", iso_path,
            "-drive", f"file={img_path},format=raw,if=ide",
            "-boot", "d",
            "-net", "nic,model=ne2k_pci",
            "-net", "user",
            "-display", "none",
            "-serial", "stdio",
            "-no-reboot",
        ]

        print(f"Starting QEMU: {' '.join(cmd[:6])}...")
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def wait_for(self, text, timeout=300):
        """Wait for text in output. Returns True if found."""
        start = time.time()
        while time.time() - start < timeout:
            if self.proc.poll() is not None:
                return False
            ready, _, _ = select.select([self.proc.stdout], [], [], 0.5)
            if ready:
                try:
                    data = os.read(self.proc.stdout.fileno(), 8192)
                    if data:
                        decoded = data.decode("utf-8", errors="replace")
                        sys.stdout.write(decoded)
                        sys.stdout.flush()
                        self.buffer += decoded
                        if text in self.buffer:
                            # Keep only recent buffer
                            self.buffer = self.buffer[-10000:]
                            return True
                except OSError:
                    pass
        return False

    def wait_for_any(self, texts, timeout=300):
        """Wait for any of the texts. Returns which one matched or None."""
        start = time.time()
        while time.time() - start < timeout:
            if self.proc.poll() is not None:
                return None
            ready, _, _ = select.select([self.proc.stdout], [], [], 0.5)
            if ready:
                try:
                    data = os.read(self.proc.stdout.fileno(), 8192)
                    if data:
                        decoded = data.decode("utf-8", errors="replace")
                        sys.stdout.write(decoded)
                        sys.stdout.flush()
                        self.buffer += decoded
                        for t in texts:
                            if t in self.buffer:
                                self.buffer = self.buffer[-10000:]
                                return t
                except OSError:
                    pass
        return None

    def send(self, text, delay=0.3):
        """Send text to QEMU serial console."""
        time.sleep(delay)
        self.proc.stdin.write(text.encode())
        self.proc.stdin.flush()

    def send_enter(self, delay=0.3):
        self.send("\r", delay)

    def send_tab(self, delay=0.2):
        self.send("\t", delay)

    def send_space(self, delay=0.2):
        self.send(" ", delay)

    def send_down(self, delay=0.2):
        """Send down arrow."""
        self.send("\x1b[B", delay)

    def send_up(self, delay=0.2):
        """Send up arrow."""
        self.send("\x1b[A", delay)

    def drain(self, seconds=2):
        """Read and discard output for a few seconds."""
        start = time.time()
        while time.time() - start < seconds:
            ready, _, _ = select.select([self.proc.stdout], [], [], 0.1)
            if ready:
                try:
                    data = os.read(self.proc.stdout.fileno(), 8192)
                    if data:
                        decoded = data.decode("utf-8", errors="replace")
                        sys.stdout.write(decoded)
                        sys.stdout.flush()
                        self.buffer += decoded
                except OSError:
                    pass
        self.buffer = self.buffer[-5000:]

    def run_install(self):
        """Drive the FreeBSD installer."""
        cfg = self.config

        print("\n>>> Waiting for FreeBSD boot loader...")
        if not self.wait_for("Autoboot in", timeout=120):
            print("ERROR: Boot loader not detected")
            return False

        # Boot
        time.sleep(1)
        self.send_enter()

        print("\n>>> Waiting for installer to load...")
        # FreeBSD kernel boot + installer init takes a while
        if not self.wait_for("Install", timeout=600):
            print("ERROR: Installer did not start")
            return False

        print("\n>>> Installer loaded, starting automated install...")
        time.sleep(3)

        # === Select Install ===
        self.send_enter()
        self.drain(3)

        # === Keymap ===
        matched = self.wait_for_any(["Keymap", "keymap", "Continue with"], timeout=30)
        if matched:
            self.send_enter(delay=1)  # Accept default
            self.drain(2)

        # === Hostname ===
        if self.wait_for_any(["hostname", "Hostname", "Set the hostname"], timeout=30):
            time.sleep(1)
            # Clear any default and type our hostname
            for _ in range(20):
                self.send("\x08", 0.05)  # Backspace to clear
            self.send(cfg.get("HOSTNAME", "webbsd"), delay=0.5)
            self.send_enter()
            self.drain(2)

        # === Distribution Select ===
        if self.wait_for_any(["distribution", "components", "Choose optional"], timeout=30):
            # Accept defaults (base + kernel)
            self.send_enter(delay=1)
            self.drain(2)

        # === Partitioning ===
        if self.wait_for_any(["Partition", "partition", "How would you like"], timeout=30):
            time.sleep(1)
            # Select Auto (UFS) - should be first option
            self.send_enter()
            self.drain(3)

            # Entire Disk
            if self.wait_for_any(["Entire Disk", "entire disk", "Would you like to use"], timeout=15):
                self.send_enter()
                self.drain(2)

            # Partition scheme - select MBR
            if self.wait_for_any(["partition scheme", "Partition Scheme", "MBR", "GPT"], timeout=15):
                time.sleep(1)
                # MBR should be second option (after GPT)
                # Or it might show a dialog - try selecting MBR
                self.send_down()
                time.sleep(0.5)
                self.send_enter()
                self.drain(2)

            # Review/Finish partition layout
            if self.wait_for_any(["Finish", "finish"], timeout=15):
                self.send_enter()
                self.drain(2)

            # Commit
            if self.wait_for_any(["Commit", "commit", "Your changes"], timeout=15):
                self.send_enter()
                self.drain(2)

        # === Installation progress ===
        print("\n>>> Installing base system (this takes several minutes)...")
        # Wait for the extraction to complete
        if not self.wait_for_any(["password", "Password", "New Password", "root password"], timeout=900):
            print("WARNING: Password prompt not detected, continuing...")

        # === Root Password ===
        time.sleep(1)
        root_pw = cfg.get("ROOT_PASSWORD", "")
        if root_pw:
            self.send(root_pw)
        self.send_enter(delay=0.5)
        time.sleep(1)
        # Confirm password
        if root_pw:
            self.send(root_pw)
        self.send_enter(delay=0.5)
        self.drain(3)

        # === Network Configuration ===
        if self.wait_for_any(["network interface", "Network", "ed0", "Configure IPv4"], timeout=30):
            self.send_enter(delay=1)  # Yes to network config or select interface
            self.drain(2)

            # Select interface if prompted
            if self.wait_for_any(["ed0", "network interface"], timeout=10):
                self.send_enter()
                self.drain(2)

            # IPv4
            if self.wait_for_any(["IPv4", "DHCP"], timeout=10):
                self.send_enter()  # Yes
                self.drain(2)

            # DHCP
            if self.wait_for_any(["DHCP"], timeout=10):
                self.send_enter()  # Yes
                self.drain(5)  # Wait for DHCP

            # IPv6
            if self.wait_for_any(["IPv6"], timeout=10):
                self.send("n", delay=0.5)
                self.send_enter()
                self.drain(2)

            # Resolver/DNS
            if self.wait_for_any(["Resolver", "resolver", "DNS", "Search"], timeout=10):
                self.send_enter()  # Accept defaults
                self.drain(2)

        # === Timezone ===
        if self.wait_for_any(["time zone", "Time Zone", "region", "UTC", "Select timezone"], timeout=30):
            time.sleep(1)
            # "Is this machine's CMOS clock set to UTC?" -> Yes
            self.send_enter()
            self.drain(3)

            # If it shows continents, select UTC
            # This varies by installer version - try to navigate
            matched = self.wait_for_any(["UTC", "Confirm", "Does the abbreviation"], timeout=15)
            if matched:
                self.send_enter()
                self.drain(2)
            # Date/time confirmation
            if self.wait_for_any(["Skip", "skip"], timeout=10):
                self.send_enter()
                self.drain(2)

        # === Services ===
        if self.wait_for_any(["services", "system services", "Choose the services"], timeout=30):
            time.sleep(1)
            # Toggle services as needed
            services = cfg.get("SERVICES", "sshd").split()
            # sshd is usually in the list - just accept defaults or toggle
            self.send_enter(delay=1)  # OK with defaults
            self.drain(2)

        # === Security Hardening ===
        if self.wait_for_any(["security", "hardening", "Choose system security"], timeout=15):
            self.send_enter(delay=1)  # Accept defaults
            self.drain(2)

        # === Add Users ===
        if self.wait_for_any(["users", "Add Users", "user accounts", "Add user accounts"], timeout=15):
            user_name = cfg.get("USER_NAME", "")
            if user_name:
                self.send_enter(delay=1)  # Yes
                self.drain(2)
                # Fill in user details
                if self.wait_for_any(["Username", "Login"], timeout=10):
                    self.send(user_name)
                    self.send_enter()
                    # Full name
                    self.send_enter(delay=1)  # Accept default
                    # Uid
                    self.send_enter(delay=0.5)
                    # Login group
                    self.send_enter(delay=0.5)
                    # Additional groups
                    groups = cfg.get("USER_GROUPS", "wheel")
                    self.send(groups)
                    self.send_enter(delay=0.5)
                    # Login class
                    self.send_enter(delay=0.5)
                    # Shell
                    self.send_enter(delay=0.5)
                    # Home directory
                    self.send_enter(delay=0.5)
                    # Home mode
                    self.send_enter(delay=0.5)
                    # Use password auth
                    self.send_enter(delay=0.5)
                    # Use empty password
                    user_pw = cfg.get("USER_PASSWORD", "")
                    if user_pw:
                        self.send(user_pw)
                    self.send_enter(delay=0.5)
                    if user_pw:
                        self.send(user_pw)
                    self.send_enter(delay=0.5)
                    self.drain(2)
                    # Add another user? No
                    if self.wait_for_any(["another", "Add another"], timeout=10):
                        self.send("no")
                        self.send_enter()
            else:
                # No additional users
                self.send("n", delay=0.5)
                self.send_enter()
            self.drain(2)

        # === Final Configuration ===
        if self.wait_for_any(["Final", "configuration", "Apply your"], timeout=30):
            self.send_enter(delay=1)  # Exit
            self.drain(2)

        # === Manual Configuration ===
        # Say Yes to get a shell for custom configuration
        if self.wait_for_any(["manual", "Manual", "open a shell"], timeout=15):
            time.sleep(1)
            self.send_enter()  # Yes
            time.sleep(3)

            # We should be in a shell now - apply custom configs
            print("\n>>> Applying post-install configuration...")

            cmds = [
                # Boot loader
                f'echo \'autoboot_delay="{cfg.get("AUTOBOOT_DELAY", "2")}"\' >> /boot/loader.conf',
                f'echo \'beastie_disable="{cfg.get("DISABLE_BEASTIE", "YES")}"\' >> /boot/loader.conf',
                # Network
                f'sysrc hostname="{cfg.get("HOSTNAME", "webbsd")}"',
                f'sysrc ifconfig_{cfg.get("NET_IFACE", "ed0")}="{cfg.get("NET_CONFIG", "DHCP")}"',
                # SSH
                f'sysrc sshd_enable="YES"',
            ]

            if cfg.get("SSH_PERMIT_ROOT", "yes") == "yes":
                cmds.append('echo "PermitRootLogin yes" >> /etc/ssh/sshd_config')
            if cfg.get("SSH_PERMIT_EMPTY_PW", "yes") == "yes":
                cmds.append('echo "PermitEmptyPasswords yes" >> /etc/ssh/sshd_config')

            # Timezone
            tz = cfg.get("TIMEZONE", "UTC")
            cmds.append(f'cp /usr/share/zoneinfo/{tz} /etc/localtime')

            # Packages
            packages = cfg.get("PACKAGES", "").strip()
            if packages:
                cmds.append(f'pkg install -y {packages}')

            for cmd in cmds:
                self.send(cmd + "\r", delay=0.5)
                time.sleep(1)

            # Exit shell
            time.sleep(2)
            self.send("exit\r", delay=1)
            self.drain(3)

        # === Reboot ===
        if self.wait_for_any(["Reboot", "reboot", "Complete"], timeout=30):
            time.sleep(1)
            self.send_enter()

        print("\n>>> Waiting for QEMU to exit...")
        try:
            self.proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            self.proc.wait()

        return True

    def cleanup(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait()


def download_vm_image(config):
    """Download pre-built FreeBSD VM image (preferred over installer)."""
    version = config.get("FREEBSD_VERSION", "13.5")
    arch = config.get("FREEBSD_ARCH", "i386")
    raw_name = f"FreeBSD-{version}-RELEASE-{arch}.raw.xz"
    raw_path = os.path.join(IMAGES_DIR, raw_name)

    if os.path.exists(raw_path) and os.path.getsize(raw_path) > 1000000:
        print(f"VM image exists: {raw_path} ({os.path.getsize(raw_path) // 1048576} MB)")
        return raw_path

    url = f"https://download.freebsd.org/releases/VM-IMAGES/{version}-RELEASE/{arch}/Latest/{raw_name}"
    print(f"Downloading {raw_name}...")
    print(f"URL: {url}")
    subprocess.run(["curl", "-L", "-o", raw_path, url], check=True)
    return raw_path


def download_iso(config):
    """Download FreeBSD ISO if not present."""
    version = config.get("FREEBSD_VERSION", "12.4")
    arch = config.get("FREEBSD_ARCH", "i386")
    iso_name = f"FreeBSD-{version}-RELEASE-{arch}-disc1.iso"
    iso_path = os.path.join(IMAGES_DIR, iso_name)

    if os.path.exists(iso_path) and os.path.getsize(iso_path) > 1000000:
        print(f"ISO exists: {iso_path} ({os.path.getsize(iso_path) // 1048576} MB)")
        return iso_path

    # FreeBSD 13+ uses current release mirrors, older versions use archive
    major = int(version.split(".")[0])
    if major >= 13:
        url = f"https://download.freebsd.org/releases/{arch}/{arch}/ISO-IMAGES/{version}/{iso_name}"
    else:
        url = f"http://ftp-archive.freebsd.org/pub/FreeBSD-Archive/old-releases/ISO-IMAGES/{version}/{iso_name}"
    print(f"Downloading {iso_name}...")
    print(f"URL: {url}")
    subprocess.run(["curl", "-L", "-k", "-o", iso_path, url], check=True)
    return iso_path


def main():
    parser = argparse.ArgumentParser(description="webBSD automated image builder")
    parser.add_argument("--config", default=os.path.join(PROJECT_DIR, "webbsd.conf"))
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--use-installer", action="store_true",
                        help="Use ISO installer instead of pre-built VM image")
    args = parser.parse_args()

    print("=" * 60)
    print("webBSD Image Builder")
    print("=" * 60)

    # Load config
    config = load_config(args.config)
    version = config.get("FREEBSD_VERSION", "13.5")
    arch = config.get("FREEBSD_ARCH", "i386")
    disk_size = config.get("DISK_SIZE", "8G")

    print(f"Config: {args.config}")
    print(f"  FreeBSD {version} {arch}")
    print(f"  Disk: {disk_size}")
    print(f"  Hostname: {config.get('HOSTNAME', 'webbsd')}")
    print()

    os.makedirs(IMAGES_DIR, exist_ok=True)
    img_path = os.path.join(IMAGES_DIR, "freebsd.img")

    # Prefer pre-built VM image (faster, more reliable)
    if not args.use_installer:
        print("Using pre-built FreeBSD VM image (recommended)")
        if not args.skip_download:
            raw_xz_path = download_vm_image(config)
        else:
            raw_xz_path = os.path.join(IMAGES_DIR, f"FreeBSD-{version}-RELEASE-{arch}.raw.xz")

        if not os.path.exists(raw_xz_path):
            print(f"ERROR: VM image not found: {raw_xz_path}")
            sys.exit(1)

        # Decompress
        print(f"\nDecompressing to {img_path}...")
        if os.path.exists(img_path):
            os.remove(img_path)
        subprocess.run(["xz", "-dk", raw_xz_path], check=True)
        # xz decompresses to same name without .xz
        decompressed = raw_xz_path.rsplit(".xz", 1)[0]
        os.rename(decompressed, img_path)

        # Get current size
        current_size = os.path.getsize(img_path)
        print(f"  Decompressed: {current_size // 1048576} MB")

        # Resize to target size
        target_bytes = int(disk_size.rstrip("G")) * 1024 * 1024 * 1024
        if current_size < target_bytes:
            print(f"  Resizing to {disk_size}...")
            subprocess.run(["truncate", "-s", disk_size, img_path], check=True)
            print(f"  Image resized to {os.path.getsize(img_path) // 1048576} MB")
            print("  Note: Filesystem will be grown on first boot via fix-image.py")

        print("\n" + "=" * 60)
        print("webBSD base image ready!")
        print(f"  Image: {img_path} ({os.path.getsize(img_path) // 1048576} MB)")
        print("=" * 60)
        print("\nNext: run fix-image.py to configure hostname, root, etc.")
        return

    # Fallback: ISO installer (for older versions or custom installs)
    print("Using ISO installer")
    if not args.skip_download:
        iso_path = download_iso(config)
    else:
        iso_path = os.path.join(IMAGES_DIR, f"FreeBSD-{version}-RELEASE-{arch}-disc1.iso")

    print(f"\nCreating {disk_size} disk image: {img_path}")
    if os.path.exists(img_path):
        os.remove(img_path)
    subprocess.run(["truncate", "-s", disk_size, img_path], check=True)

    automator = QEMUAutomator(config)

    def sighandler(sig, frame):
        print("\nInterrupted!")
        automator.cleanup()
        sys.exit(1)

    signal.signal(signal.SIGINT, sighandler)
    signal.signal(signal.SIGTERM, sighandler)

    automator.start_qemu(iso_path, img_path)

    success = automator.run_install()
    automator.cleanup()

    if success:
        print("\n" + "=" * 60)
        print("webBSD image built successfully!")
        print(f"  Image: {img_path} ({os.path.getsize(img_path) // 1048576} MB)")
        print("=" * 60)
    else:
        print("\nERROR: Installation may have failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
