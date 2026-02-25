#!/usr/bin/env python3
"""Add network watchdog: background script that runs dhclient ed0 when needed.

The watchdog runs forever, checking every 15s if ed0 has no IP and running
dhclient. It's started from i3 config, so it's captured in the saved state.
When state is restored in the browser, it resumes and kicks dhclient.
"""
import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")
SERIAL_PORT = 45494
MONITOR_PORT = 45495
HOME = "/home/bsduser"
I3CFG = f"{HOME}/.config/i3/config"

# Network watchdog: checks ed0 every 15s, runs dhclient if no IP
NET_WATCHDOG_LINES = [
    '#!/bin/sh',
    '# Network watchdog: run dhclient ed0 when NIC has no IP',
    'sleep 5',
    'while true; do',
    '    if ifconfig ed0 > /dev/null 2>&1; then',
    '        ip=$(ifconfig ed0 | grep "inet " | awk \'{print $2}\')',
    '        if [ -z "$ip" ]; then',
    '            dhclient ed0 > /dev/null 2>&1',
    '        fi',
    '    fi',
    '    sleep 15',
    'done',
]

print("=== Add network watchdog ===")

proc = subprocess.Popen(
    ["qemu-system-i386", "-m", "512",
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

def send_cmd(cmd, timeout=30):
    global serial_buf
    marker = f"__OK_{time.time_ns()}__"
    send(cmd + f" && echo {marker}\n", 0.5)
    if not wait_for(marker, timeout):
        print(f"  WARN: No confirm for: {cmd[:70]}...")
        return False
    drain(); return True

def write_lines(lines, dest_path, executable=False):
    print(f"  Writing {dest_path}...")
    send(f"rm -f {dest_path}\n", 0.3)
    for line in lines:
        escaped = line.replace("'", "'\\''")
        send(f"echo '{escaped}' >> {dest_path}\n", 0.04)
    time.sleep(1)
    drain()
    if executable:
        send_cmd(f"chmod +x {dest_path}")

print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)
send_cmd("killall dhclient 2>/dev/null; true", timeout=5)

# 1. Write net-watchdog.sh
print("\n=== Writing net-watchdog.sh ===")
write_lines(NET_WATCHDOG_LINES, f"{HOME}/.config/i3/net-watchdog.sh", executable=True)

# 2. Add to i3 config (if not already there)
print("\n=== Adding watchdog to i3 config ===")
send_cmd(f"grep -q 'net-watchdog' {I3CFG} || echo 'exec --no-startup-id {HOME}/.config/i3/net-watchdog.sh' >> {I3CFG}")

# Ownership
send_cmd(f"chown -R bsduser:bsduser {HOME}/.config")

# Verify
print("\n=== Verifying ===")
serial_buf = b""
send(f"cat {HOME}/.config/i3/net-watchdog.sh\n", 2)
send(f"grep 'net-watchdog' {I3CFG}\n", 1)
time.sleep(2)
drain()
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$"):
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
