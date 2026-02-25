#!/usr/bin/env python3
"""Debug and fix the terminal layout to include tty-clock in T3."""
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

print("=== Fix layout with clock ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)

# Check what exec lines are in i3 config
print("\n=== i3 config exec lines ===")
serial_buf = b""
send(f"grep -n 'exec' {HOME}/.config/i3/config | grep -v bindsym | grep -v '#'\n", 2)
time.sleep(3); drain()
print(serial_buf.decode(errors="replace")[:500])

# Check current startup.sh
print("\n=== Current startup.sh ===")
serial_buf = b""
send(f"cat {HOME}/.config/i3/startup.sh\n", 2)
time.sleep(3); drain()
print(serial_buf.decode(errors="replace")[:800])

# Rewrite startup.sh completely with clock in T3
print("\n=== Writing new startup.sh ===")
startup = [
    '#!/bin/sh',
    '# Golden ratio layout: large left, medium top-right, clock bottom-right',
    'sleep 2',
    '',
    '# T1 - left terminal (fills workspace)',
    "i3-msg 'exec urxvt'",
    'sleep 1.5',
    '',
    '# Split horizontal, T2 on the right',
    "i3-msg 'split h'",
    'sleep 0.3',
    "i3-msg 'exec urxvt'",
    'sleep 1.5',
    '',
    '# Split T2 vertically, T3 below with clock',
    "i3-msg 'split v'",
    'sleep 0.3',
    "i3-msg 'exec urxvt -e tty-clock -c -C 1 -t'",
    'sleep 1.5',
    '',
    '# Resize: left ~62% width (golden ratio)',
    "i3-msg 'focus left; resize grow width 120 px'",
    'sleep 0.3',
    '# Top-right taller (~62% of right side)',
    "i3-msg 'focus right; focus up; resize grow height 80 px'",
    'sleep 0.3',
    '',
    '# Focus the large left terminal',
    "i3-msg 'focus left'",
]
write_lines(startup, f"{HOME}/.config/i3/startup.sh", executable=True)

# Verify
serial_buf = b""
send(f"cat {HOME}/.config/i3/startup.sh\n", 2)
time.sleep(3); drain()
print("\nNew startup.sh:")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$") and not s.startswith("cat "):
        print(f"  {s}")

# Make sure i3 config uses startup.sh and doesn't have conflicting exec urxvt
print("\n=== Cleaning i3 config exec lines ===")
send_cmd(f"sed -i '' '/^exec.*urxvt/d' {HOME}/.config/i3/config")
send_cmd(f"sed -i '' '/^exec.*tmux/d' {HOME}/.config/i3/config")
# Ensure startup.sh is there
serial_buf = b""
send(f"grep startup.sh {HOME}/.config/i3/config\n", 1)
time.sleep(2); drain()
has_startup = "startup.sh" in serial_buf.decode(errors="replace")
if not has_startup:
    print("Adding startup.sh to i3 config...")
    send_cmd(f"echo 'exec --no-startup-id {HOME}/.config/i3/startup.sh' >> {HOME}/.config/i3/config")
else:
    print("startup.sh already in i3 config")

# Verify tty-clock binary
serial_buf = b""
send("which tty-clock && tty-clock --help 2>&1 | head -3\n", 2)
time.sleep(2); drain()
print(f"\ntty-clock: {serial_buf.decode(errors='replace')[:200]}")

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
