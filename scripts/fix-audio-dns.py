#!/usr/bin/env python3
"""Install audio support (SB16 driver + playback tools) and fix DNS config."""
import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")
SERIAL_PORT = 45494
MONITOR_PORT = 45495

# QEMU with networking for pkg install
proc = subprocess.Popen(
    ["qemu-system-i386", "-m", "1024",
     "-drive", f"file={IMAGE},format=raw,cache=writethrough",
     "-display", "none",
     "-serial", f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off",
     "-monitor", f"tcp:127.0.0.1:{MONITOR_PORT},server=on,wait=off",
     "-nic", "user,model=e1000",
     "-no-reboot"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

time.sleep(2)
ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
ser.settimeout(1)
ser.connect(("127.0.0.1", SERIAL_PORT))
mon = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
mon.settimeout(5)
mon.connect(("127.0.0.1", MONITOR_PORT))
time.sleep(0.5)
try: mon.recv(4096)
except: pass

serial_buf = b""
def drain():
    global serial_buf
    while True:
        try:
            data = ser.recv(4096)
            if not data: break
            serial_buf += data
        except (socket.timeout, BlockingIOError): break

def wait_for(pattern, timeout=180):
    global serial_buf
    start = time.time()
    while time.time() - start < timeout:
        drain()
        if pattern.encode() in serial_buf: return True
        time.sleep(0.3)
    return False

def send(text, delay=0.5):
    ser.send(text.encode()); time.sleep(delay)

def send_cmd(cmd, timeout=60):
    global serial_buf
    marker = f"__OK_{time.time_ns()}__"
    send(cmd + f" && echo {marker}\n", 0.5)
    if not wait_for(marker, timeout):
        print(f"  WARN: No confirm for: {cmd[:70]}...")
        return False
    drain(); return True

print("=== Install audio + fix DNS ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)

# Get network up
print("Getting network...")
send("dhclient em0\n", 15)
drain()

# 1. Audio: load SB16 driver
print("\n=== Configuring SB16 audio driver ===")
# Check what sound modules exist
serial_buf = b""
send("ls /boot/kernel/snd_sb*.ko /boot/kernel/snd_driver.ko 2>&1\n", 2)
time.sleep(2)
drain()
print("Sound modules:")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and "snd" in s and not s.startswith("$"):
        print(f"  {s}")

# Load snd_sbc (Sound Blaster) at boot
# snd_sbc handles SB16 compatible cards
send_cmd("grep -q 'snd_sbc_load' /boot/loader.conf || echo 'snd_sbc_load=\"YES\"' >> /boot/loader.conf")
send_cmd("grep -q 'snd_sb16_load' /boot/loader.conf || echo 'snd_sb16_load=\"YES\"' >> /boot/loader.conf")
send_cmd("grep -q 'snd_sbc_load' /boot/loader.conf.local 2>/dev/null || echo 'snd_sbc_load=\"YES\"' >> /boot/loader.conf.local")
send_cmd("grep -q 'snd_sb16_load' /boot/loader.conf.local 2>/dev/null || echo 'snd_sb16_load=\"YES\"' >> /boot/loader.conf.local")

# 2. Install audio playback software
print("\n=== Installing audio packages ===")
send("pkg install -y mpv ffmpeg 2>&1 | tail -5\n", 5)
print("Installing mpv + ffmpeg (this takes a while)...")
# mpv + ffmpeg are large, wait up to 10 minutes
if not wait_for("installed", timeout=600):
    # Check if it timed out or just slow
    drain()
    output = serial_buf.decode(errors="replace")
    if "already installed" in output:
        print("  Already installed")
    else:
        print("  Install may still be running, waiting more...")
        wait_for("$", timeout=300)
drain()

# Check what got installed
serial_buf = b""
send("which mpv 2>&1\n", 2)
send("which ffplay 2>&1\n", 2)
send("pkg info mpv 2>/dev/null | head -1\n", 2)
time.sleep(3)
drain()
print("Installed:")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and ("mpv" in s or "ffplay" in s or "/usr" in s) and not s.startswith("$"):
        print(f"  {s}")

# 3. Fix DNS config
print("\n=== Fixing DNS config ===")
# The fetch backend provides DHCP with DNS at 192.168.86.1
# But also set static DNS as fallback
send_cmd("echo 'nameserver 8.8.8.8' > /etc/resolv.conf")
send_cmd("echo 'nameserver 8.8.4.4' >> /etc/resolv.conf")

# Configure dhclient to always prepend our DNS servers
send_cmd("echo 'prepend domain-name-servers 8.8.8.8, 8.8.4.4;' > /etc/dhclient.conf")

# 4. Verify loader.conf
serial_buf = b""
send("cat /boot/loader.conf\n", 2)
time.sleep(2)
drain()
print("\nloader.conf:")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$") and not s.startswith("#"):
        print(f"  {s}")

# Shutdown
print("\nSyncing...")
send("sync\n", 3)
send("sync\n", 3)
send("mount -ur /\n", 2)
send("shutdown -p now\n", 5)
try: proc.wait(timeout=120)
except: proc.kill()
mon.close(); ser.close()
print("Done!")
