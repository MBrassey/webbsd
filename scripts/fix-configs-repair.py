#!/usr/bin/env python3
"""Quick repair: verify and fix i3/urxvt configs that may have failed
during the wallpaper transfer garbling in fix-desktop-complete.py.
No networking or large file transfers needed."""

import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")

SERIAL_PORT = 45460
MONITOR_PORT = 45461
HOME = "/home/bsduser"
I3CFG = f"{HOME}/.config/i3/config"
XRES = f"{HOME}/.Xresources"

print("=== Config repair (verify & fix) ===")

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
# CHECK CURRENT STATE
# ══════════════════════════════════════════════════════════════
print("\n=== Checking current config state ===")

# Check what's in i3 config
send(f"echo '---I3CFG_START---' && cat {I3CFG} && echo '---I3CFG_END---'\n", 3)
time.sleep(2)
drain()

decoded = serial_buf.decode(errors="replace")
i3_start = decoded.find("---I3CFG_START---")
i3_end = decoded.find("---I3CFG_END---")
if i3_start >= 0 and i3_end >= 0:
    i3_content = decoded[i3_start+17:i3_end]
    print(f"  i3 config: {len(i3_content)} chars")
    has_golden = "golden-3term" in i3_content
    has_status = "status.sh" in i3_content
    has_feh = "feh" in i3_content
    has_fish_term = "urxvt -e fish" in i3_content
    has_thin_border = "default_border pixel 1" in i3_content
    print(f"  golden-3term: {'OK' if has_golden else 'MISSING'}")
    print(f"  status.sh: {'OK' if has_status else 'MISSING'}")
    print(f"  feh wallpaper: {'OK' if has_feh else 'MISSING'}")
    print(f"  urxvt -e fish: {'OK' if has_fish_term else 'MISSING'}")
    print(f"  thin border: {'OK' if has_thin_border else 'MISSING'}")
else:
    print("  Could not read i3 config!")
    has_golden = has_status = has_feh = has_fish_term = has_thin_border = False

# Check .Xresources
serial_buf = b""
send(f"echo '---XRES_START---' && cat {XRES} && echo '---XRES_END---'\n", 3)
time.sleep(2)
drain()

decoded = serial_buf.decode(errors="replace")
xr_start = decoded.find("---XRES_START---")
xr_end = decoded.find("---XRES_END---")
if xr_start >= 0 and xr_end >= 0:
    xres_content = decoded[xr_start+16:xr_end]
    print(f"  .Xresources: {len(xres_content)} chars")
    has_nerd_font = "JetBrains" in xres_content
    has_transp = "transparent" in xres_content
    has_shading = "shading" in xres_content
    has_internal_border = "internalBorder" in xres_content
    print(f"  Nerd font: {'OK' if has_nerd_font else 'MISSING'}")
    print(f"  Transparency: {'OK' if has_transp else 'MISSING'}")
    print(f"  Shading: {'OK' if has_shading else 'MISSING'}")
    print(f"  Internal border: {'OK' if has_internal_border else 'MISSING'}")
else:
    print("  Could not read .Xresources!")
    has_nerd_font = has_transp = has_shading = has_internal_border = False

# Check scripts exist
serial_buf = b""
send(f"ls -la {HOME}/.config/i3/golden-3term.sh {HOME}/.config/i3/status.sh 2>&1\n", 2)
drain()
send("wc -c < /usr/local/share/wallpapers/freebsd.png 2>/dev/null || echo 'NO_WALLPAPER'\n", 2)
drain()

# ══════════════════════════════════════════════════════════════
# REPAIR CONFIGS
# ══════════════════════════════════════════════════════════════
needs_repair = not all([has_golden, has_status, has_feh, has_fish_term, has_thin_border,
                         has_nerd_font, has_transp, has_shading, has_internal_border])

if needs_repair:
    print("\n=== Repairing configs ===")

    # --- I3 CONFIG ---
    if not has_status:
        send_cmd(f"sed -i '' 's|status_command.*|status_command {HOME}/.config/i3/status.sh|' {I3CFG}")
        print("  Fixed: status_command")

    if not has_fish_term:
        send_cmd(f"sed -i '' 's|exec urxvt$|exec urxvt -e fish|' {I3CFG}")
        send_cmd(f"sed -i '' 's|exec i3-sensible-terminal|exec urxvt -e fish|' {I3CFG}")
        send_cmd(f"sed -i '' 's|exec urxvt -e tmux$|exec urxvt -e fish|' {I3CFG}")
        # Also fix bindsym lines
        send_cmd(f"sed -i '' '/bindsym.*Return.*exec/s|exec.*|exec urxvt -e fish|' {I3CFG}")
        print("  Fixed: terminal command")

    if not has_thin_border:
        send_cmd(f"sed -i '' 's|default_border pixel [0-9]*|default_border pixel 1|' {I3CFG}")
        send_cmd(f"grep -q 'default_border' {I3CFG} || echo 'default_border pixel 1' >> {I3CFG}")
        print("  Fixed: border width")

    # Border colors
    send_cmd(f"sed -i '' 's|^client\\.focused .*|client.focused          #2a3a4a #1a2a3a #cccccc #2a3a4a   #2a3a4a|' {I3CFG}")
    send_cmd(f"sed -i '' 's|^client\\.unfocused .*|client.unfocused        #1a1a1a #0a0a0a #666666 #1a1a1a   #1a1a1a|' {I3CFG}")
    send_cmd(f"sed -i '' 's|^client\\.focused_inactive .*|client.focused_inactive  #222222 #111111 #888888 #222222   #222222|' {I3CFG}")
    # Add if missing
    send_cmd(f"grep -q 'client.focused ' {I3CFG} || echo 'client.focused          #2a3a4a #1a2a3a #cccccc #2a3a4a   #2a3a4a' >> {I3CFG}")
    send_cmd(f"grep -q 'client.unfocused' {I3CFG} || echo 'client.unfocused        #1a1a1a #0a0a0a #666666 #1a1a1a   #1a1a1a' >> {I3CFG}")
    send_cmd(f"grep -q 'client.focused_inactive' {I3CFG} || echo 'client.focused_inactive  #222222 #111111 #888888 #222222   #222222' >> {I3CFG}")
    print("  Fixed: border colors")

    # Remove old startup exec lines, add golden-3term
    if not has_golden:
        send_cmd(f"sed -i '' '/^exec.*urxvt/d' {I3CFG}")
        send_cmd(f"sed -i '' '/^exec.*startup\\.sh/d' {I3CFG}")
        send_cmd(f"grep -q 'golden-3term' {I3CFG} || echo 'exec --no-startup-id {HOME}/.config/i3/golden-3term.sh' >> {I3CFG}")
        print("  Fixed: golden-3term startup")

    # Wallpaper exec
    if not has_feh:
        send_cmd(f"sed -i '' '/feh.*wallpaper/d' {I3CFG}")
        send_cmd(f"echo 'exec --no-startup-id feh --bg-fill /usr/local/share/wallpapers/freebsd.png' >> {I3CFG}")
        print("  Fixed: feh wallpaper")

    # Bar colors
    send_cmd(f"sed -i '' 's|background .*#[0-9a-fA-F]*|background #0a0a0a|' {I3CFG}")
    send_cmd(f"sed -i '' 's|statusline .*#[0-9a-fA-F]*|statusline #888888|' {I3CFG}")
    print("  Fixed: bar colors")

    # --- XRESOURCES ---
    if not has_nerd_font:
        send_cmd(f"sed -i '' '/URxvt\\.font/d' {XRES}")
        send_cmd(f"sed -i '' '/URxvt\\.boldFont/d' {XRES}")
        send_cmd(f"echo 'URxvt.font: xft:JetBrainsMono Nerd Font Mono:size=10:antialias=true, xft:DejaVu Sans Mono:size=10' >> {XRES}")
        send_cmd(f"echo 'URxvt.boldFont: xft:JetBrainsMono Nerd Font Mono:bold:size=10:antialias=true, xft:DejaVu Sans Mono:bold:size=10' >> {XRES}")
        print("  Fixed: nerd font")

    if not has_transp:
        send_cmd(f"sed -i '' '/URxvt\\.transparent/d' {XRES}")
        send_cmd(f"echo 'URxvt.transparent: true' >> {XRES}")
        print("  Fixed: transparency")

    if not has_shading:
        send_cmd(f"sed -i '' '/URxvt\\.shading/d' {XRES}")
        send_cmd(f"echo 'URxvt.shading: 25' >> {XRES}")
        print("  Fixed: shading")

    if not has_internal_border:
        send_cmd(f"sed -i '' '/URxvt\\.internalBorder/d' {XRES}")
        send_cmd(f"sed -i '' '/URxvt\\.letterSpace/d' {XRES}")
        send_cmd(f"echo 'URxvt.internalBorder: 10' >> {XRES}")
        send_cmd(f"echo 'URxvt.letterSpace: 0' >> {XRES}")
        print("  Fixed: internal border")

    # Ownership
    send_cmd(f"chown -R bsduser:bsduser {HOME}/.config")
    send_cmd(f"chown -R bsduser:bsduser {HOME}/.local")
    print("  Fixed: ownership")

    # Verify final state
    print("\n=== Verifying repairs ===")
    serial_buf = b""
    send(f"grep 'golden-3term' {I3CFG} && echo 'GOLDEN: OK'\n", 1)
    send(f"grep 'status.sh' {I3CFG} && echo 'STATUS: OK'\n", 1)
    send(f"grep 'urxvt -e fish' {I3CFG} && echo 'FISH_TERM: OK'\n", 1)
    send(f"grep 'feh' {I3CFG} && echo 'FEH: OK'\n", 1)
    send(f"grep 'transparent' {XRES} && echo 'TRANSP: OK'\n", 1)
    send(f"grep 'JetBrains' {XRES} && echo 'FONT: OK'\n", 1)
    time.sleep(2)
    drain()
    for line in serial_buf.decode(errors="replace").split("\n"):
        if "OK" in line:
            print(f"  {line.strip()}")
else:
    print("\n=== All configs OK, no repair needed ===")

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
print("\n=== Config repair done! ===")
