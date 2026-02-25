#!/usr/bin/env python3
"""Transfer the missing files: wallpaper, golden-3term.sh, fix OMF.
Uses 76-char chunks with proper pacing to avoid serial garbling."""

import subprocess, time, sys, os, socket, base64

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")
WALLPAPER = os.path.join(BASE, "images", "assets", "wallpaper.png")

SERIAL_PORT = 45464
MONITOR_PORT = 45465
HOME = "/home/bsduser"

GOLDEN_3TERM = r"""#!/bin/sh
# Golden rectangle: A(left 62%) | B(top-right 62%) / C(bottom-right 38%)
TERM="${TERMINAL:-urxvt -e fish}"
sleep 2
i3-msg 'workspace 1'
sleep 0.3

# Terminal A (fills workspace)
i3-msg "exec $TERM"
sleep 1.5

# Split horizontal -> Terminal B on right
i3-msg 'split h'
sleep 0.3
i3-msg "exec $TERM"
sleep 1.5

# B focused; split vertical -> Terminal C below B
i3-msg 'split v'
sleep 0.3
i3-msg "exec $TERM"
sleep 1.5

# Resize A to 62% width
i3-msg 'focus left; resize set width 62 ppt'
sleep 0.3

# Resize B to 62% of right column height
i3-msg 'focus right; focus up; resize set height 62 ppt'
sleep 0.3

# Return focus to Terminal A
i3-msg 'focus left'
""".lstrip()

print("=== Fix missing files ===")

# Read wallpaper
with open(WALLPAPER, "rb") as f:
    wallpaper_data = f.read()
print(f"Wallpaper: {len(wallpaper_data)} bytes")

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

def transfer_b64_safe(data, dest_path, chunk_size=76):
    """Transfer binary data via base64 with small safe chunks."""
    b64 = base64.b64encode(data).decode()
    chunks = [b64[i:i+chunk_size] for i in range(0, len(b64), chunk_size)]
    print(f"  Transferring {dest_path} ({len(data)} bytes, {len(chunks)} chunks @ {chunk_size} chars)...")

    # Clear target
    send("rm -f /tmp/xfer.b64\n", 0.5)
    time.sleep(0.5)
    drain()

    for i, chunk in enumerate(chunks):
        # Use printf to avoid echo interpretation issues
        ser.send(f"printf '%s\\n' '{chunk}' >> /tmp/xfer.b64\n".encode())
        # Pace: tiny delay per chunk, longer pause every 100
        time.sleep(0.02)
        if (i + 1) % 100 == 0:
            time.sleep(0.5)
            drain()
            print(f"    {i+1}/{len(chunks)}...")
        if (i + 1) % 500 == 0:
            # Extra drain pause every 500 chunks
            time.sleep(1.0)
            drain()

    # Wait for shell to catch up
    print(f"    Waiting for shell to finish writing...")
    time.sleep(5)
    drain()

    # Verify b64 file size
    serial_buf_before = len(serial_buf)
    send(f"wc -c < /tmp/xfer.b64\n", 3)
    drain()

    # Decode
    if send_cmd(f"cat /tmp/xfer.b64 | /usr/bin/b64decode -r > {dest_path}", timeout=120):
        print(f"    Decoded OK")
    else:
        print(f"    WARN: decode may have timed out")

    # Verify output size
    send(f"wc -c < {dest_path}\n", 2)
    drain()
    decoded_text = serial_buf.decode(errors="replace")
    # Look for the size in recent output
    lines = decoded_text.split("\n")
    for line in lines[-10:]:
        stripped = line.strip()
        if stripped.isdigit():
            actual = int(stripped)
            if abs(actual - len(data)) < 100:
                print(f"    Size verified: {actual} bytes (expected {len(data)})")
            elif actual > 0:
                print(f"    Size: {actual} bytes (expected {len(data)})")

    send("rm -f /tmp/xfer.b64\n", 0.5)

def transfer_text_safe(text, dest_path):
    """Transfer text file using echo per line (no heredocs!)."""
    lines = text.split("\n")
    print(f"  Writing {dest_path} ({len(lines)} lines)...")
    send(f"rm -f {dest_path}\n", 0.3)
    for line in lines:
        # Escape single quotes
        escaped = line.replace("'", "'\\''")
        send(f"echo '{escaped}' >> {dest_path}\n", 0.03)
    time.sleep(1)
    drain()
    send_cmd(f"chmod +x {dest_path}")
    print(f"    Written OK")


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
# 1. GOLDEN-3TERM.SH (text, use echo per line)
# ══════════════════════════════════════════════════════════════
print("\n=== 1. Writing golden-3term.sh ===")
send_cmd(f"mkdir -p {HOME}/.config/i3")
transfer_text_safe(GOLDEN_3TERM, f"{HOME}/.config/i3/golden-3term.sh")

# Verify
send(f"head -3 {HOME}/.config/i3/golden-3term.sh\n", 2)
drain()

# ══════════════════════════════════════════════════════════════
# 2. WALLPAPER (binary, use base64 with small chunks)
# ══════════════════════════════════════════════════════════════
print("\n=== 2. Transferring wallpaper ===")
send_cmd("mkdir -p /usr/local/share/wallpapers")
transfer_b64_safe(wallpaper_data, "/usr/local/share/wallpapers/freebsd.png")

# ══════════════════════════════════════════════════════════════
# 3. FIX OMF (needs fish config to source it)
# ══════════════════════════════════════════════════════════════
print("\n=== 3. Fixing Oh My Fish config ===")
# OMF needs to be sourced in config.fish
send_cmd(f"mkdir -p {HOME}/.config/fish")

# Write config.fish that sources OMF
send(f"rm -f {HOME}/.config/fish/config.fish\n", 0.3)
send(f"echo '# Fish configuration' >> {HOME}/.config/fish/config.fish\n", 0.05)
send(f"echo 'if test -f {HOME}/.local/share/omf/init.fish' >> {HOME}/.config/fish/config.fish\n", 0.05)
send(f"echo '    source {HOME}/.local/share/omf/init.fish' >> {HOME}/.config/fish/config.fish\n", 0.05)
send(f"echo 'end' >> {HOME}/.config/fish/config.fish\n", 0.05)
time.sleep(1)
drain()
print("  Wrote config.fish with OMF source")

# Verify config.fish
send(f"cat {HOME}/.config/fish/config.fish\n", 2)
drain()

# ══════════════════════════════════════════════════════════════
# OWNERSHIP
# ══════════════════════════════════════════════════════════════
print("\n=== Setting ownership ===")
send_cmd(f"chown -R bsduser:bsduser {HOME}/.config")
send_cmd(f"chown -R bsduser:bsduser {HOME}/.local")

# ══════════════════════════════════════════════════════════════
# VERIFY
# ══════════════════════════════════════════════════════════════
print("\n=== Verifying ===")
serial_buf = b""
send("echo '---V_START---'\n", 0.3)
send(f"ls -la /usr/local/share/wallpapers/freebsd.png 2>&1\n", 1)
send(f"ls -la {HOME}/.config/i3/golden-3term.sh 2>&1\n", 1)
send(f"wc -c < /usr/local/share/wallpapers/freebsd.png 2>&1\n", 1)
send(f"head -1 {HOME}/.config/i3/golden-3term.sh 2>&1\n", 1)
send(f"cat {HOME}/.config/fish/config.fish 2>&1\n", 1)
send("echo '---V_END---'\n", 2)
time.sleep(3)
drain()

decoded = serial_buf.decode(errors="replace")
vs = decoded.find("---V_START---")
ve = decoded.find("---V_END---")
if vs >= 0 and ve >= 0:
    for line in decoded[vs:ve].strip().split("\n"):
        print(f"  {line.rstrip()}")

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
print("\n=== Fix missing files done! ===")
