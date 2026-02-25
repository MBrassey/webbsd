#!/usr/bin/env python3
"""Fix fish prompt position: clear screen in fish_greeting (runs after OMF init),
and remove the clear from config.fish."""

import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")

SERIAL_PORT = 45476
MONITOR_PORT = 45477
HOME = "/home/bsduser"

# Greeting with clear at start — runs AFTER all init including OMF
FISH_GREETING_LINES = [
    'function fish_greeting',
    '    clear',
    '    set_color 5f87af',
    '    printf "  Welcome to "',
    '    set_color --bold 87afd7',
    '    echo "webBSD"',
    '    set_color normal',
    '    set_color 626262',
    '    echo "  FreeBSD 13.5-RELEASE | i3wm"',
    '    set_color normal',
    '    echo',
    'end',
]

# Config.fish WITHOUT the clear (greeting handles it now)
FISH_CONFIG_LINES = [
    '# Fish configuration',
    'if test -f /home/bsduser/.local/share/omf/init.fish',
    '    source /home/bsduser/.local/share/omf/init.fish',
    'end',
]

print("=== Fix prompt position ===")

proc = subprocess.Popen(
    [
        "qemu-system-i386",
        "-m", "512",
        "-drive", f"file={IMAGE},format=raw,cache=writethrough",
        "-display", "none",
        "-serial", f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off",
        "-monitor", f"tcp:127.0.0.1:{MONITOR_PORT},server=on,wait=off",
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
    global serial_buf
    marker = f"__OK_{time.time_ns()}__"
    send(cmd + f" && echo {marker}\n", 0.5)
    if not wait_for(marker, timeout):
        print(f"  WARN: No confirm for: {cmd[:70]}...")
        return False
    drain()
    return True

def write_lines(lines, dest_path):
    print(f"  Writing {dest_path}...")
    send(f"rm -f {dest_path}\n", 0.3)
    for line in lines:
        escaped = line.replace("'", "'\\''")
        send(f"echo '{escaped}' >> {dest_path}\n", 0.04)
    time.sleep(1)
    drain()

print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!")
    proc.kill()
    sys.exit(1)

time.sleep(1)
send("root\n", 3)
drain()
send("/bin/sh\n", 1)
drain()
send_cmd("service cron stop", timeout=10)
send_cmd("killall dhclient 2>/dev/null; true", timeout=5)

# Fix greeting
print("Writing fish_greeting.fish...")
send_cmd(f"mkdir -p {HOME}/.config/fish/functions")
write_lines(FISH_GREETING_LINES, f"{HOME}/.config/fish/functions/fish_greeting.fish")

# Fix config.fish
print("Writing config.fish...")
write_lines(FISH_CONFIG_LINES, f"{HOME}/.config/fish/config.fish")

# Ownership
send_cmd(f"chown -R bsduser:bsduser {HOME}/.config")

# Shutdown
print("Syncing...")
send("sync\n", 3)
send("sync\n", 3)
send("mount -ur /\n", 2)
send("shutdown -p now\n", 5)

try:
    proc.wait(timeout=120)
except subprocess.TimeoutExpired:
    proc.kill()

mon.close()
ser.close()
print("Done!")
