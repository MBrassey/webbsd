#!/usr/bin/env python3
"""Add FreeBSD wallpaper and set timezone in the disk image via QEMU.

Boots multi-user, transfers wallpaper via base64 over serial,
updates i3 config to use feh, sets timezone, shuts down.
"""

import subprocess
import time
import sys
import os
import socket
import base64

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")
WALLPAPER = os.path.join(BASE, "images", "assets", "wallpaper.png")

SERIAL_PORT = 45458
MONITOR_PORT = 45457

print(f"=== Adding wallpaper and setting timezone ===")

# Read wallpaper and encode as base64
with open(WALLPAPER, "rb") as f:
    wallpaper_data = f.read()
wallpaper_b64 = base64.b64encode(wallpaper_data).decode()
print(f"Wallpaper: {len(wallpaper_data)} bytes, {len(wallpaper_b64)} base64 chars")

proc = subprocess.Popen(
    [
        "qemu-system-i386",
        "-m", "512",
        "-drive", f"file={IMAGE},format=raw,cache=writethrough",
        "-display", "none",
        "-serial", f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off",
        "-monitor", f"tcp:127.0.0.1:{MONITOR_PORT},server=on,wait=off",
        "-net", "none",
        "-no-reboot",
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

time.sleep(2)

ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
ser.settimeout(1)
ser.connect(("127.0.0.1", SERIAL_PORT))

mon = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
mon.settimeout(5)
mon.connect(("127.0.0.1", MONITOR_PORT))
time.sleep(0.5)
try:
    mon.recv(4096)
except:
    pass

serial_buf = b""


def drain():
    global serial_buf
    while True:
        try:
            data = ser.recv(4096)
            if not data:
                break
            serial_buf += data
        except (socket.timeout, BlockingIOError):
            break


def wait_for(pattern, timeout=180):
    global serial_buf
    start = time.time()
    while time.time() - start < timeout:
        drain()
        if pattern.encode() in serial_buf:
            return True
        time.sleep(0.3)
    return False


def send(text, delay=0.5):
    ser.send(text.encode())
    time.sleep(delay)


def send_cmd(cmd, timeout=30):
    marker = f"__OK_{time.time_ns()}__"
    send(cmd + f" && echo {marker}\n", 0.5)
    if not wait_for(marker, timeout):
        print(f"  WARNING: No confirmation for: {cmd[:60]}...")
    drain()


# Wait for boot
print("Waiting for FreeBSD to boot...")
if not wait_for("login:", timeout=300):
    print("ERROR: No login prompt!")
    proc.kill()
    sys.exit(1)

print(">>> Logging in...")
time.sleep(1)
send("root\n", 3)
drain()
send("/bin/sh\n", 1)
drain()

# === Transfer wallpaper via base64 ===
print("\n=== Transferring wallpaper ===")
send_cmd("mkdir -p /usr/local/share/wallpapers")

# Send base64 in chunks (serial has line length limits)
CHUNK_SIZE = 76  # standard base64 line width
chunks = [wallpaper_b64[i:i+CHUNK_SIZE] for i in range(0, len(wallpaper_b64), CHUNK_SIZE)]
print(f"Sending {len(chunks)} chunks...")

# Start the base64 decode pipe
send("rm -f /tmp/wp.b64\n", 0.3)

for i, chunk in enumerate(chunks):
    send(f"echo '{chunk}' >> /tmp/wp.b64\n", 0.05)
    if i % 100 == 0 and i > 0:
        print(f"  {i}/{len(chunks)} chunks sent...")
        time.sleep(0.5)  # let serial catch up

time.sleep(2)
print(f"  All {len(chunks)} chunks sent. Decoding...")

send_cmd("cat /tmp/wp.b64 | /usr/bin/b64decode -r > /usr/local/share/wallpapers/freebsd.png", timeout=30)

# Verify
send("ls -la /usr/local/share/wallpapers/freebsd.png\n", 2)
drain()
decoded = serial_buf.decode(errors="replace")
if "freebsd.png" in decoded:
    print(">>> Wallpaper transferred successfully!")
else:
    print(">>> WARNING: Wallpaper may not have transferred correctly")

# === Update i3 config to use feh for wallpaper ===
print("\n=== Updating i3 config for wallpaper ===")
HOME = "/home/bsduser"
I3CFG = f"{HOME}/.config/i3/config"

# Replace xsetroot line with feh wallpaper
send_cmd(f"sed -i '' 's|xsetroot -solid.*|feh --bg-fill /usr/local/share/wallpapers/freebsd.png|' {I3CFG}")

# Verify the change
send(f"grep -n 'feh\\|xsetroot' {I3CFG}\n", 2)
drain()

# === Set timezone ===
print("\n=== Setting timezone to America/Boise ===")
send_cmd("cp /usr/share/zoneinfo/America/Boise /etc/localtime")
send_cmd("echo 'America/Boise' > /var/db/zoneinfo")

# Verify
send("date\n", 2)
drain()

# === Clean up and shutdown ===
print("\n=== Syncing and shutting down ===")
send("rm -f /tmp/wp.b64\n", 1)
send("sync\n", 3)
send("sync\n", 3)
send("shutdown -p now\n", 5)

try:
    proc.wait(timeout=60)
except subprocess.TimeoutExpired:
    proc.kill()

mon.close()
ser.close()
print("\n\n=== Wallpaper and timezone configured! ===")
