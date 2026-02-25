#!/usr/bin/env python3
"""Fix net-watchdog to run as root via rc.local instead of i3 (bsduser)."""
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

def write_lines(lines, dest_path, executable=False):
    send(f"rm -f {dest_path}\n", 0.3)
    for line in lines:
        escaped = line.replace("'", "'\\''")
        send(f"echo '{escaped}' >> {dest_path}\n", 0.04)
    time.sleep(1)
    drain()
    if executable:
        send_cmd(f"chmod +x {dest_path}")

print("=== Fix net-watchdog to run as root ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)

# 1. Create root-owned network watchdog
print("\n=== Creating root net-watchdog ===")
watchdog = [
    '#!/bin/sh',
    '# Network watchdog (runs as root via rc.local)',
    '# Handles DHCP renewal after v86 state restore',
    '',
    '# Wait for desktop to start',
    'sleep 5',
    '',
    '# Release old lease and get new one',
    'dhclient -r vtnet0 2>/dev/null',
    'sleep 1',
    'dhclient vtnet0 2>/dev/null',
    '',
    '# Monitor loop: re-DHCP if IP lost',
    'while true; do',
    '    ip=$(ifconfig vtnet0 2>/dev/null | grep "inet " | awk \'{print $2}\')',
    '    if [ -z "$ip" ]; then',
    '        dhclient vtnet0 2>/dev/null',
    '    fi',
    '    sleep 15',
    'done',
]
write_lines(watchdog, "/usr/local/sbin/net-watchdog.sh", executable=True)

# 2. Create rc.local to start watchdog as root
print("\n=== Creating /etc/rc.local ===")
rc_local = [
    '#!/bin/sh',
    '# Start network watchdog in background (runs as root)',
    '/usr/local/sbin/net-watchdog.sh &',
]
write_lines(rc_local, "/etc/rc.local", executable=True)

# 3. Remove old watchdog from i3 config (was running as bsduser)
print("\n=== Removing old watchdog from i3 config ===")
send_cmd(f"sed -i '' '/net-watchdog/d' {HOME}/.config/i3/config")

# Verify
serial_buf = b""
send("cat /etc/rc.local\n", 1)
send("cat /usr/local/sbin/net-watchdog.sh\n", 2)
time.sleep(3)
drain()
print("\nrc.local + watchdog:")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$"):
        print(f"  {s}")

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
