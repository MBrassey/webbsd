#!/usr/bin/env python3
"""Ensure .Xresources has transparency settings and xrdb loads them."""
import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")
SERIAL_PORT = 45494
MONITOR_PORT = 45495
HOME = "/home/bsduser"

proc = subprocess.Popen(
    ["qemu-system-i386", "-m", "1024",
     "-drive", f"file={IMAGE},format=raw,cache=writethrough",
     "-display", "none",
     "-serial", f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off",
     "-monitor", f"tcp:127.0.0.1:{MONITOR_PORT},server=on,wait=off",
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

print("=== Fix transparency ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)

# Check current .Xresources
print("\n=== Current .Xresources ===")
serial_buf = b""
send(f"cat {HOME}/.Xresources\n", 2)
time.sleep(3); drain()
xr = serial_buf.decode(errors="replace")
print(xr[:1000])

# Check if transparency lines exist
has_transparent = "transparent" in xr.lower()
has_shading = "shading" in xr.lower()
has_depth = "depth" in xr.lower()
print(f"\nHas transparent: {has_transparent}")
print(f"Has shading: {has_shading}")
print(f"Has depth: {has_depth}")

if not (has_transparent and has_shading and has_depth):
    print("\n=== Adding missing transparency settings ===")
    # Remove any existing transparency lines first
    send_cmd(f"sed -i '' '/transparent/Id' {HOME}/.Xresources")
    send_cmd(f"sed -i '' '/shading/Id' {HOME}/.Xresources")
    send_cmd(f"sed -i '' '/URxvt.depth/Id' {HOME}/.Xresources")
    # Add them
    send_cmd(f"echo 'URxvt.transparent: true' >> {HOME}/.Xresources")
    send_cmd(f"echo 'URxvt.shading: 25' >> {HOME}/.Xresources")
    send_cmd(f"echo 'URxvt.depth: 32' >> {HOME}/.Xresources")
else:
    print("Transparency settings already present.")

# Ensure .xinitrc loads xrdb BEFORE i3 and sets wallpaper
print("\n=== Checking .xinitrc ===")
serial_buf = b""
send(f"cat {HOME}/.xinitrc\n", 2)
time.sleep(3); drain()
xi = serial_buf.decode(errors="replace")
print(xi[:500])

has_xrdb = "xrdb" in xi
has_feh = "feh" in xi
print(f"\nHas xrdb: {has_xrdb}")
print(f"Has feh: {has_feh}")

if not has_xrdb:
    print("Adding xrdb to .xinitrc...")
    # Prepend xrdb before exec i3
    send_cmd(f"sed -i '' '/exec i3/i\\\nxrdb -merge $HOME/.Xresources' {HOME}/.xinitrc")

# Also ensure i3 config runs xrdb and feh on startup
print("\n=== Ensuring i3 config loads xrdb + wallpaper ===")
serial_buf = b""
send(f"grep -n 'xrdb\\|feh\\|wallpaper' {HOME}/.config/i3/config\n", 2)
time.sleep(3); drain()
i3lines = serial_buf.decode(errors="replace")
print(i3lines[:500])

if "xrdb" not in i3lines:
    print("Adding xrdb exec to i3 config...")
    send_cmd(f"echo 'exec_always --no-startup-id xrdb -merge $HOME/.Xresources' >> {HOME}/.config/i3/config")

# Verify final .Xresources
print("\n=== Final .Xresources ===")
serial_buf = b""
send(f"grep -n 'transparent\\|shading\\|depth\\|font\\|color' {HOME}/.Xresources\n", 2)
time.sleep(3); drain()
print(serial_buf.decode(errors="replace")[:500])

send_cmd(f"chown -R bsduser:bsduser {HOME}")

print("\nSyncing...")
send("sync\n", 3)
send("sync\n", 3)
send("mount -ur /\n", 2)
send("shutdown -p now\n", 5)
try: proc.wait(timeout=120)
except: proc.kill()
mon.close(); ser.close()
print("Done!")
