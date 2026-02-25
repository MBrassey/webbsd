#!/usr/bin/env python3
"""Comprehensive fix:
1. Clone freebsd-wallpapers repo + cycle wallpapers every 5 min
2. Fix golden-3term.sh layout (robust, long sleeps for v86)
3. Fix fish OMF __original_fish_user_key_bindings error
4. Fix i3 config for proper layout + wallpaper cycling
"""

import subprocess, time, sys, os, socket, base64

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")

SERIAL_PORT = 45470
MONITOR_PORT = 45471
HOME = "/home/bsduser"
I3CFG = f"{HOME}/.config/i3/config"

# ══════════════════════════════════════════════════════════════
# Golden-3term with generous sleeps for v86 speed
# ══════════════════════════════════════════════════════════════
GOLDEN_3TERM = r"""#!/bin/sh
# Golden ratio layout: A(left 62%) | B(top-right 62%) / C(bottom-right 38%)
# Launches terminals directly (not via i3-msg exec) for reliability.
TERM_CMD="${TERMINAL:-urxvt}"

sleep 4
i3-msg 'workspace 1'
sleep 1

# Terminal A — fills workspace
$TERM_CMD -e fish &
sleep 4

# Split container horizontally so next window goes RIGHT
i3-msg 'split horizontal'
sleep 0.5

# Terminal B — right of A
$TERM_CMD -e fish &
sleep 4

# B is focused. Split vertically so next window goes BELOW
i3-msg 'split vertical'
sleep 0.5

# Terminal C — below B
$TERM_CMD -e fish &
sleep 4

# Resize A to 62% width
i3-msg 'focus left'
sleep 0.5
i3-msg 'resize set width 62 ppt'
sleep 0.5

# Resize B to 62% of right column height
i3-msg 'focus right'
sleep 0.3
i3-msg 'focus up'
sleep 0.3
i3-msg 'resize set height 62 ppt'
sleep 0.5

# Return focus to Terminal A
i3-msg 'focus left'
""".lstrip()

# ══════════════════════════════════════════════════════════════
# Wallpaper cycling script
# ══════════════════════════════════════════════════════════════
WALLPAPER_CYCLE = r"""#!/bin/sh
# Cycle through FreeBSD wallpapers every 5 minutes
WP_DIR="/usr/local/share/wallpapers/freebsd-wallpapers"

# Wait for X and wallpapers dir
sleep 5

set_random_wp() {
    wp=$(find "$WP_DIR" -type f \( -name '*.jpg' -o -name '*.png' -o -name '*.jpeg' -o -name '*.JPG' -o -name '*.PNG' \) 2>/dev/null | sort -R | head -1)
    if [ -n "$wp" ]; then
        feh --bg-fill "$wp" 2>/dev/null
    fi
}

# Set initial wallpaper
set_random_wp

# Cycle every 5 minutes
while true; do
    sleep 300
    set_random_wp
done
""".lstrip()

# ══════════════════════════════════════════════════════════════
# Fish key bindings stub (fixes OMF __original_fish_user_key_bindings error)
# ══════════════════════════════════════════════════════════════
FISH_KEY_BINDINGS = """function fish_user_key_bindings
end
""".lstrip()

print("=== Comprehensive fix ===")

proc = subprocess.Popen(
    [
        "qemu-system-i386",
        "-m", "512",
        "-drive", f"file={IMAGE},format=raw,cache=writethrough",
        "-display", "none",
        "-serial", f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off",
        "-monitor", f"tcp:127.0.0.1:{MONITOR_PORT},server=on,wait=off",
        "-nic", "user,model=e1000",
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

def write_text_file(text, dest_path, executable=False):
    """Write text file using echo per line (safe over serial)."""
    lines = text.split("\n")
    print(f"  Writing {dest_path} ({len(lines)} lines)...")
    send(f"rm -f {dest_path}\n", 0.3)
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("'", "'\\''")
        send(f"echo '{escaped}' >> {dest_path}\n", 0.03)
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

# ══════════════════════════════════════════════════════════════
# NETWORKING (for git clone)
# ══════════════════════════════════════════════════════════════
print("\n=== Setting up networking ===")
send_cmd("dhclient em0", timeout=30)
time.sleep(3)
drain()

if send_cmd("host github.com", timeout=15):
    print("  DNS works!")
else:
    print("  DNS check failed, trying manual resolv.conf...")
    send_cmd("echo 'nameserver 10.0.2.3' > /etc/resolv.conf", timeout=5)

# ══════════════════════════════════════════════════════════════
# 1. CLONE FREEBSD WALLPAPERS
# ══════════════════════════════════════════════════════════════
print("\n=== Cloning FreeBSD wallpapers repo ===")
send_cmd("rm -rf /usr/local/share/wallpapers/freebsd-wallpapers", timeout=10)
if send_cmd("git clone --depth 1 https://github.com/fuzzy/freebsd-wallpapers /usr/local/share/wallpapers/freebsd-wallpapers", timeout=300):
    print("  Wallpapers cloned!")
else:
    print("  WARN: Git clone may have timed out, checking...")

# Check what we got
send("ls /usr/local/share/wallpapers/freebsd-wallpapers/ | head -20\n", 3)
drain()
send("find /usr/local/share/wallpapers/freebsd-wallpapers -type f \\( -name '*.jpg' -o -name '*.png' \\) | wc -l\n", 3)
drain()
decoded = serial_buf.decode(errors="replace")
for line in decoded.split("\n")[-15:]:
    stripped = line.strip()
    if stripped and not stripped.startswith("#") and not stripped.startswith("$"):
        print(f"  {stripped}")

# ══════════════════════════════════════════════════════════════
# 2. GOLDEN-3TERM LAYOUT SCRIPT
# ══════════════════════════════════════════════════════════════
print("\n=== Writing golden-3term.sh ===")
send_cmd(f"mkdir -p {HOME}/.config/i3")
write_text_file(GOLDEN_3TERM, f"{HOME}/.config/i3/golden-3term.sh", executable=True)

# ══════════════════════════════════════════════════════════════
# 3. WALLPAPER CYCLING SCRIPT
# ══════════════════════════════════════════════════════════════
print("\n=== Writing wallpaper-cycle.sh ===")
write_text_file(WALLPAPER_CYCLE, f"{HOME}/.config/i3/wallpaper-cycle.sh", executable=True)

# ══════════════════════════════════════════════════════════════
# 4. FIX FISH OMF KEY BINDINGS ERROR
# ══════════════════════════════════════════════════════════════
print("\n=== Fixing fish key bindings error ===")
send_cmd(f"mkdir -p {HOME}/.config/fish/functions")
write_text_file(FISH_KEY_BINDINGS, f"{HOME}/.config/fish/functions/fish_user_key_bindings.fish")

# ══════════════════════════════════════════════════════════════
# 5. UPDATE I3 CONFIG
# ══════════════════════════════════════════════════════════════
print("\n=== Updating i3 config ===")

# Remove old feh/wallpaper lines
send_cmd(f"sed -i '' '/feh.*wallpaper/d' {I3CFG}")
send_cmd(f"sed -i '' '/feh.*bg-fill/d' {I3CFG}")
send_cmd(f"sed -i '' '/wallpaper-cycle/d' {I3CFG}")

# Remove old golden-3term lines (avoid duplicates)
send_cmd(f"sed -i '' '/golden-3term/d' {I3CFG}")

# Remove old startup.sh lines
send_cmd(f"sed -i '' '/startup\\.sh/d' {I3CFG}")

# Add wallpaper cycling and golden layout
send_cmd(f"echo 'exec --no-startup-id {HOME}/.config/i3/wallpaper-cycle.sh' >> {I3CFG}")
send_cmd(f"echo 'exec --no-startup-id {HOME}/.config/i3/golden-3term.sh' >> {I3CFG}")

# Verify key i3 config lines
print("\n  Verifying i3 config...")
serial_buf = b""
send(f"echo '---VERIFY---'\n", 0.3)
send(f"grep -n 'golden-3term\\|wallpaper-cycle\\|status.sh\\|urxvt.*fish\\|default_border' {I3CFG}\n", 2)
send(f"echo '---END---'\n", 1)
time.sleep(2)
drain()
decoded = serial_buf.decode(errors="replace")
vs = decoded.find("---VERIFY---")
ve = decoded.find("---END---")
if vs >= 0 and ve >= 0:
    for line in decoded[vs+12:ve].strip().split("\n"):
        if line.strip() and not line.strip().startswith("#"):
            print(f"    {line.strip()}")

# ══════════════════════════════════════════════════════════════
# 6. OWNERSHIP
# ══════════════════════════════════════════════════════════════
print("\n=== Setting ownership ===")
send_cmd(f"chown -R bsduser:bsduser {HOME}/.config")
send_cmd(f"chown -R bsduser:bsduser {HOME}/.local")

# ══════════════════════════════════════════════════════════════
# 7. FINAL VERIFICATION
# ══════════════════════════════════════════════════════════════
print("\n=== Final verification ===")
serial_buf = b""
send("echo '---FINAL---'\n", 0.3)
send(f"ls -la {HOME}/.config/i3/golden-3term.sh && echo 'GOLDEN: OK'\n", 1)
send(f"ls -la {HOME}/.config/i3/wallpaper-cycle.sh && echo 'CYCLE: OK'\n", 1)
send(f"ls {HOME}/.config/fish/functions/fish_user_key_bindings.fish && echo 'KEYBIND: OK'\n", 1)
send("find /usr/local/share/wallpapers/freebsd-wallpapers -type f \\( -name '*.jpg' -o -name '*.png' \\) | wc -l\n", 2)
send(f"head -5 {HOME}/.config/i3/golden-3term.sh\n", 1)
send("echo '---FEND---'\n", 2)
time.sleep(3)
drain()
decoded = serial_buf.decode(errors="replace")
vs = decoded.find("---FINAL---")
ve = decoded.find("---FEND---")
if vs >= 0 and ve >= 0:
    for line in decoded[vs+11:ve].strip().split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("$"):
            print(f"  {stripped}")

# ══════════════════════════════════════════════════════════════
# SHUTDOWN
# ══════════════════════════════════════════════════════════════
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
print("\n=== Comprehensive fix done! ===")
