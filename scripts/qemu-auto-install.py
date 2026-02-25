#!/usr/bin/env python3
"""
Automated FreeBSD installation via QEMU serial console.
Sends keystrokes to the FreeBSD installer running in QEMU with -nographic.
"""

import subprocess
import sys
import time
import os
import argparse
import select
import signal

def wait_for(proc, text, timeout=300):
    """Wait for specific text to appear in process output."""
    buf = ""
    start = time.time()
    while time.time() - start < timeout:
        if proc.poll() is not None:
            print(f"\nQEMU exited with code {proc.returncode}")
            return False
        ready, _, _ = select.select([proc.stdout], [], [], 1)
        if ready:
            try:
                data = os.read(proc.stdout.fileno(), 4096)
                if data:
                    decoded = data.decode("utf-8", errors="replace")
                    sys.stdout.write(decoded)
                    sys.stdout.flush()
                    buf += decoded
                    if text in buf:
                        return True
                    # Keep buffer manageable
                    if len(buf) > 100000:
                        buf = buf[-50000:]
            except OSError:
                pass
    print(f"\nTimeout waiting for: {text}")
    return False

def send(proc, text, delay=0.5):
    """Send text to QEMU stdin."""
    time.sleep(delay)
    proc.stdin.write(text.encode())
    proc.stdin.flush()

def send_key(proc, key, delay=0.3):
    """Send a single key."""
    time.sleep(delay)
    proc.stdin.write(key.encode())
    proc.stdin.flush()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iso", required=True)
    parser.add_argument("--img", required=True)
    parser.add_argument("--mem", type=int, default=256)
    args = parser.parse_args()

    print(f"Starting QEMU with FreeBSD installer...")
    print(f"  ISO: {args.iso}")
    print(f"  Image: {args.img}")
    print(f"  Memory: {args.mem}MB")
    print()

    # Boot FreeBSD ISO in QEMU with serial console
    # -nographic redirects VGA to serial console
    # The FreeBSD installer works over serial when comconsole is selected
    cmd = [
        "qemu-system-i386",
        "-m", str(args.mem),
        "-cdrom", args.iso,
        "-hda", args.img,
        "-boot", "d",
        "-net", "nic,model=ne2k_pci",
        "-net", "user",
        "-display", "none",
        "-serial", "stdio",
        "-no-reboot",
    ]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    def cleanup(sig=None, frame=None):
        proc.terminate()
        proc.wait()
        sys.exit(1)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        # Wait for FreeBSD boot loader
        print("Waiting for FreeBSD boot loader...")
        if not wait_for(proc, "Autoboot in", timeout=120):
            # Try pressing Enter anyway
            send(proc, "\r")

        # Press Enter to boot with defaults
        send(proc, "\r", delay=1)

        # Wait for kernel to load and installer to start
        # The FreeBSD installer won't show on serial unless we configure it
        # Since -nographic sends VGA to serial, we should see the installer
        print("\nWaiting for installer to load (this takes a few minutes)...")

        # Wait for the installer menu
        if wait_for(proc, "Install", timeout=300):
            print("\nInstaller loaded!")

            # The installer is a dialog-based TUI
            # Select "Install"
            time.sleep(2)
            send(proc, "\r")  # Enter on Install

            # Keymap selection - select default
            time.sleep(3)
            if wait_for(proc, "Keymap", timeout=30):
                send(proc, "\r")  # Accept default keymap

            # Hostname
            if wait_for(proc, "hostname", timeout=30):
                send(proc, "freebsd")
                send(proc, "\r")

            # Distribution select - uncheck optional components
            # Tab to OK, Enter
            if wait_for(proc, "distribution", timeout=30):
                # Just accept defaults (base + kernel)
                send(proc, "\r")

            # Partitioning - Auto (UFS)
            if wait_for(proc, "Partition", timeout=30):
                send(proc, "\r")  # Auto (UFS)

                time.sleep(1)
                # "Entire Disk" or partition editor
                if wait_for(proc, "Entire Disk", timeout=10):
                    send(proc, "\r")

                # Partition scheme - MBR for BIOS booting
                if wait_for(proc, "partition scheme", timeout=10):
                    # Select MBR
                    # Navigate to MBR option
                    send(proc, "\x1b[B")  # Down arrow
                    send(proc, "\r")

                # Confirm
                if wait_for(proc, "Finish", timeout=10):
                    send(proc, "\r")

                # Commit changes
                if wait_for(proc, "Commit", timeout=10):
                    send(proc, "\r")

            # Wait for installation to complete
            print("\nInstalling FreeBSD (this takes several minutes)...")
            if wait_for(proc, "password", timeout=600):
                # Root password - set empty
                send(proc, "\r")
                time.sleep(1)
                send(proc, "\r")

            # Network configuration
            if wait_for(proc, "network", timeout=60):
                send(proc, "\r")  # Yes to configure network
                time.sleep(2)

                # Select ed0 interface
                if wait_for(proc, "ed0", timeout=10):
                    send(proc, "\r")

                # IPv4 - Yes
                if wait_for(proc, "IPv4", timeout=10):
                    send(proc, "\r")

                # DHCP - Yes
                if wait_for(proc, "DHCP", timeout=10):
                    send(proc, "\r")

                # IPv6 - No
                if wait_for(proc, "IPv6", timeout=10):
                    send(proc, "n\r")

                # DNS
                if wait_for(proc, "DNS", timeout=10):
                    send(proc, "\r")

            # Timezone
            if wait_for(proc, "time zone", timeout=30):
                # Select UTC
                send(proc, "\r")  # Yes to UTC
                time.sleep(1)
                send(proc, "\r")  # Confirm

            # Services
            if wait_for(proc, "services", timeout=30):
                # Enable sshd (should be highlighted)
                send(proc, " ")  # Toggle sshd
                send(proc, "\r")  # OK

            # Security
            if wait_for(proc, "security", timeout=30):
                send(proc, "\r")  # OK defaults

            # Add users - No
            if wait_for(proc, "users", timeout=30):
                send(proc, "\r")  # No

            # Final config
            if wait_for(proc, "Final", timeout=30):
                send(proc, "\r")  # Exit

            # Manual config - Yes to enter shell
            if wait_for(proc, "manual", timeout=30):
                # Select Yes for manual config to set up loader.conf
                send(proc, "\r")  # Yes

                time.sleep(2)
                # We should be in a shell now
                send(proc, 'echo \'autoboot_delay="2"\' >> /boot/loader.conf\r')
                time.sleep(1)
                send(proc, 'echo \'beastie_disable="YES"\' >> /boot/loader.conf\r')
                time.sleep(1)
                # Configure ed0 for DHCP in rc.conf
                send(proc, 'echo \'ifconfig_ed0="DHCP"\' >> /etc/rc.conf\r')
                time.sleep(1)
                send(proc, 'echo \'sshd_enable="YES"\' >> /etc/rc.conf\r')
                time.sleep(1)
                send(proc, 'echo \'hostname="freebsd"\' >> /etc/rc.conf\r')
                time.sleep(1)
                # Allow root SSH login for demo purposes
                send(proc, 'echo "PermitRootLogin yes" >> /etc/ssh/sshd_config\r')
                time.sleep(1)
                send(proc, 'echo "PermitEmptyPasswords yes" >> /etc/ssh/sshd_config\r')
                time.sleep(1)
                send(proc, "exit\r")

            # Reboot
            if wait_for(proc, "Reboot", timeout=30):
                # Select Reboot
                send(proc, "\r")

            print("\n\n=== Installation complete! Waiting for QEMU to exit... ===")
            proc.wait(timeout=60)

        else:
            print("\nInstaller did not load via serial. Trying alternative approach...")
            proc.terminate()
            proc.wait()
            sys.exit(1)

    except Exception as e:
        print(f"\nError: {e}")
        proc.terminate()
        proc.wait()
        sys.exit(1)

    print(f"\n=== FreeBSD installed to {args.img} ===")

if __name__ == "__main__":
    main()
