#!/usr/bin/env python3
"""Fix: 1) wallpaper-cycle.sh double-escaped backslashes
       2) fish prompt starting halfway down terminal"""

import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")

SERIAL_PORT = 45474
MONITOR_PORT = 45475
HOME = "/home/bsduser"

# Fixed wallpaper cycle script — no double-escaped backslashes
WALLPAPER_CYCLE_LINES = [
    '#!/bin/sh',
    '# Cycle through FreeBSD wallpapers every 5 minutes',
    'WP_DIR="/usr/local/share/wallpapers/freebsd-wallpapers"',
    '',
    '# Wait for X to be ready',
    'sleep 5',
    '',
    'set_random_wp() {',
    # Use -iname instead of escaped parens to avoid escaping issues entirely
    '    wp=$(find "$WP_DIR" -maxdepth 1 -type f -iname "*.png" 2>/dev/null | sort -R | head -1)',
    '    if [ -z "$wp" ]; then',
    '        wp=$(find "$WP_DIR" -maxdepth 1 -type f -iname "*.jpg" 2>/dev/null | sort -R | head -1)',
    '    fi',
    '    if [ -n "$wp" ]; then',
    '        feh --bg-fill "$wp"',
    '    fi',
    '}',
    '',
    '# Set initial wallpaper immediately',
    'set_random_wp',
    '',
    '# Cycle every 5 minutes',
    'while true; do',
    '    sleep 300',
    '    set_random_wp',
    'done',
]

# Fish config with clear screen at start
FISH_CONFIG_LINES = [
    '# Fish configuration',
    'if test -f /home/bsduser/.local/share/omf/init.fish',
    '    source /home/bsduser/.local/share/omf/init.fish',
    'end',
    '',
    '# Clear screen on new interactive terminal so prompt starts at top',
    'if status is-interactive',
    '    printf "\\033[H\\033[2J"',
    'end',
]

print("=== Fix wallpaper + prompt ===")

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

def write_lines(lines, dest_path, executable=False):
    """Write file line by line using echo. No backslash escaping needed
    since single quotes protect everything except single quotes themselves."""
    print(f"  Writing {dest_path} ({len(lines)} lines)...")
    send(f"rm -f {dest_path}\n", 0.3)
    for line in lines:
        # Only need to escape single quotes inside single-quoted strings
        escaped = line.replace("'", "'\\''")
        send(f"echo '{escaped}' >> {dest_path}\n", 0.04)
    time.sleep(1)
    drain()
    if executable:
        send_cmd(f"chmod +x {dest_path}")
    print(f"    Done")

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

send_cmd("service cron stop", timeout=10)
send_cmd("killall dhclient 2>/dev/null; true", timeout=5)

# 1. Fix wallpaper-cycle.sh
print("\n=== Fixing wallpaper-cycle.sh ===")
write_lines(WALLPAPER_CYCLE_LINES, f"{HOME}/.config/i3/wallpaper-cycle.sh", executable=True)

# 2. Fix fish config (clear screen on startup)
print("\n=== Fixing fish config.fish ===")
send_cmd(f"mkdir -p {HOME}/.config/fish")
write_lines(FISH_CONFIG_LINES, f"{HOME}/.config/fish/config.fish")

# 3. Ownership
send_cmd(f"chown -R bsduser:bsduser {HOME}/.config")

# 4. Verify
print("\n=== Verifying ===")
serial_buf = b""
send("echo '---V_S---'\n", 0.3)
send(f"cat {HOME}/.config/i3/wallpaper-cycle.sh\n", 3)
send(f"echo '---SEP---'\n", 0.3)
send(f"cat {HOME}/.config/fish/config.fish\n", 2)
send("echo '---V_E---'\n", 2)
time.sleep(3)
drain()

decoded = serial_buf.decode(errors="replace")
vs = decoded.find("---V_S---")
ve = decoded.find("---V_E---")
if vs >= 0 and ve >= 0:
    content = decoded[vs+9:ve]
    # Check for double backslashes (the bug)
    if '\\\\(' in content:
        print("  ERROR: Still has double-escaped backslashes!")
    elif 'find' in content:
        print("  wallpaper-cycle.sh: OK (no double-escaping)")
    if 'printf' in content:
        print("  config.fish: OK (has clear-screen)")

# 5. Quick test: run the find command as it appears in the script
serial_buf = b""
send("echo '---TEST_S---'\n", 0.3)
send('find /usr/local/share/wallpapers/freebsd-wallpapers -maxdepth 1 -type f -iname "*.png" 2>/dev/null | wc -l\n', 3)
send('find /usr/local/share/wallpapers/freebsd-wallpapers -maxdepth 1 -type f -iname "*.jpg" 2>/dev/null | wc -l\n', 3)
send("echo '---TEST_E---'\n", 2)
time.sleep(3)
drain()
decoded = serial_buf.decode(errors="replace")
vs = decoded.find("---TEST_S---")
ve = decoded.find("---TEST_E---")
if vs >= 0 and ve >= 0:
    for line in decoded[vs+12:ve].strip().split("\n"):
        stripped = line.strip()
        if stripped.isdigit():
            print(f"  Found {stripped} wallpapers")

# Shutdown
print("\n=== Syncing and shutting down ===")
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
print("\n=== Fix done! ===")
