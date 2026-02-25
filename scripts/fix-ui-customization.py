#!/usr/bin/env python3
"""Customize desktop UI: sparkline status bar, golden rectangle layout,
fish shell with FreeBSD-themed prompt/colors, transparent terminals,
subtle borders, wallpaper.

Boots multi-user, transfers all configs via base64, updates i3/urxvt/fish, shuts down.
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

HOME = "/home/bsduser"

# ══════════════════════════════════════════════════════════════
# Scripts & configs to install
# ══════════════════════════════════════════════════════════════

STATUS_SH = r"""#!/bin/sh
# i3bar sparkline status - CPU/MEM history charts
# Outputs i3bar JSON protocol

# Sparkline block characters (1/8 to 8/8 height)
S0=$(printf '\342\226\201')
S1=$(printf '\342\226\202')
S2=$(printf '\342\226\203')
S3=$(printf '\342\226\204')
S4=$(printf '\342\226\205')
S5=$(printf '\342\226\206')
S6=$(printf '\342\226\207')
S7=$(printf '\342\226\210')

# Build sparkline from space-separated values (uses global _spark)
_spark=""
build_spark() {
    _spark=""
    for v in $1; do
        idx=$((v * 7 / 100))
        [ "$idx" -lt 0 ] && idx=0
        [ "$idx" -gt 7 ] && idx=7
        case $idx in
            0) _spark="${_spark}${S0}" ;;
            1) _spark="${_spark}${S1}" ;;
            2) _spark="${_spark}${S2}" ;;
            3) _spark="${_spark}${S3}" ;;
            4) _spark="${_spark}${S4}" ;;
            5) _spark="${_spark}${S5}" ;;
            6) _spark="${_spark}${S6}" ;;
            *) _spark="${_spark}${S7}" ;;
        esac
    done
}

echo '{"version":1}'
echo '['
echo '[]'

cpu_hist=""
mem_hist=""
cpu_n=0
mem_n=0
prev=""

while true; do
    # CPU
    cp=$(sysctl -n kern.cp_time)
    if [ -n "$prev" ]; then
        set -- $prev; pu=$1; pn=$2; ps=$3; pi=$4; pid=$5
        set -- $cp; cu=$1; cn=$2; cs=$3; ci=$4; cid=$5
        du=$((cu-pu)); dn=$((cn-pn)); ds=$((cs-ps)); di=$((ci-pi)); did=$((cid-pid))
        t=$((du+dn+ds+di+did))
        [ "$t" -gt 0 ] && cpu=$((100*(t-did)/t)) || cpu=0
    else
        cpu=0
    fi
    prev="$cp"

    # Memory
    tp=$(sysctl -n vm.stats.vm.v_page_count)
    fp=$(sysctl -n vm.stats.vm.v_free_count)
    ip=$(sysctl -n vm.stats.vm.v_inactive_count)
    used=$((tp-fp-ip))
    [ "$tp" -gt 0 ] && mem=$((100*used/tp)) || mem=0
    [ "$mem" -lt 0 ] && mem=0
    [ "$mem" -gt 100 ] && mem=100

    # Update history (keep last 20)
    if [ -z "$cpu_hist" ]; then cpu_hist="$cpu"; else cpu_hist="$cpu_hist $cpu"; fi
    if [ -z "$mem_hist" ]; then mem_hist="$mem"; else mem_hist="$mem_hist $mem"; fi
    cpu_n=$((cpu_n+1)); mem_n=$((mem_n+1))
    [ "$cpu_n" -gt 20 ] && { cpu_hist="${cpu_hist#* }"; cpu_n=20; }
    [ "$mem_n" -gt 20 ] && { mem_hist="${mem_hist#* }"; mem_n=20; }

    # Build sparklines
    build_spark "$cpu_hist"; cpu_spark="$_spark"
    build_spark "$mem_hist"; mem_spark="$_spark"

    # Colors (adaptive)
    [ $cpu -ge 85 ] && cc="#ff3333" || { [ $cpu -ge 60 ] && cc="#ccaa00" || cc="#993322"; }
    [ $mem -ge 90 ] && mc="#ff3333" || { [ $mem -ge 70 ] && mc="#ccaa00" || mc="#993322"; }

    dt=$(date '+%a %b %d  %H:%M')

    printf ',['
    printf '{"full_text":" CPU %s %d%% ","color":"%s","separator":false,"separator_block_width":18},' "$cpu_spark" "$cpu" "$cc"
    printf '{"full_text":" MEM %s %d%% ","color":"%s","separator":false,"separator_block_width":18},' "$mem_spark" "$mem" "$mc"
    printf '{"full_text":" %s ","color":"#555555","separator":false}' "$dt"
    printf ']\n'

    sleep 2
done
""".lstrip()

STARTUP_SH = r"""#!/bin/sh
# Golden rectangle terminal layout
# ┌──────────┬─────────────────┐
# │  T1 60%  │                 │
# │  height  │   T2 (large)    │
# ├──────────┤   ~62% width    │
# │  T3 40%  │                 │
# │  height  │                 │
# └──────────┴─────────────────┘

sleep 2

# T1 - first terminal (fills workspace)
i3-msg 'exec urxvt -e fish'
sleep 1.5

# Split horizontal, open T2 on the right
i3-msg 'split h'
sleep 0.3
i3-msg 'exec urxvt -e fish'
sleep 1.5

# Go back to T1 (left), split vertical, open T3 below
i3-msg 'focus left; split v'
sleep 0.3
i3-msg 'exec urxvt -e fish'
sleep 1.5

# Make T2 (right) larger - golden ratio ~62% width
i3-msg 'focus right; resize grow width 200 px'
sleep 0.3

# Make T1 (top-left) taller - ~60% of left side height
i3-msg 'focus left; focus up; resize grow height 80 px'
sleep 0.3

# Focus the large right terminal as primary
i3-msg 'focus right'
""".lstrip()

FISH_PROMPT = r"""function fish_prompt
    set -l last_status $status
    if test $last_status -ne 0
        set_color ff3333
        printf '[%d] ' $last_status
    end
    set_color ab1100
    printf '%s' (whoami)
    set_color 666
    printf '@'
    set_color cc3300
    printf '%s' (hostname -s)
    set_color 666
    printf ':'
    set_color 4488cc
    printf '%s' (prompt_pwd)
    set_color 666
    printf ' > '
    set_color normal
end
""".lstrip()

FISH_RIGHT_PROMPT = r"""function fish_right_prompt
    set_color 444
    printf '%s' (date '+%H:%M')
    set_color normal
end
""".lstrip()

FISH_GREETING = r"""function fish_greeting
    set_color ab1100
    printf "  Welcome to "
    set_color brred
    echo "webBSD"
    set_color 666
    echo "  FreeBSD 13.5-RELEASE | i3wm"
    set_color normal
end
""".lstrip()

# Fish universal variables file - FreeBSD-themed syntax colors
FISH_VARIABLES = """SETUVAR fish_color_autosuggestion:555
SETUVAR fish_color_cancel:\\x2dr
SETUVAR fish_color_command:cc4400
SETUVAR fish_color_comment:666
SETUVAR fish_color_cwd:4488cc
SETUVAR fish_color_cwd_root:cc0000
SETUVAR fish_color_end:cc6600
SETUVAR fish_color_error:ff3333
SETUVAR fish_color_escape:cc8833
SETUVAR fish_color_history_current:\\x2d\\x2dbold
SETUVAR fish_color_host:cc3300
SETUVAR fish_color_host_remote:yellow
SETUVAR fish_color_keyword:cc4400
SETUVAR fish_color_normal:normal
SETUVAR fish_color_operator:cc6600
SETUVAR fish_color_option:aa6633
SETUVAR fish_color_param:cccccc
SETUVAR fish_color_quote:cc8833
SETUVAR fish_color_redirection:cc6600\\x1e\\x2d\\x2dbold
SETUVAR fish_color_search_match:bryellow\\x1e\\x2d\\x2dbackground\\x3d2a0800
SETUVAR fish_color_selection:white\\x1e\\x2d\\x2dbold\\x1e\\x2d\\x2dbackground\\x3d2a0800
SETUVAR fish_color_status:ff3333
SETUVAR fish_color_user:ab1100
SETUVAR fish_color_valid_path:\\x2d\\x2dunderline
SETUVAR fish_pager_color_completion:normal
SETUVAR fish_pager_color_description:555\\x1eyellow
SETUVAR fish_pager_color_prefix:normal\\x1e\\x2d\\x2dbold\\x1e\\x2d\\x2dunderline
SETUVAR fish_pager_color_progress:brwhite\\x1e\\x2d\\x2dbackground\\x3d2a0800
SETUVAR fish_pager_color_selected_background:\\x2d\\x2dbackground\\x3d2a0800
""".lstrip()


print(f"=== Comprehensive desktop UI customization ===")

# Read wallpaper and encode
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


def transfer_file(content, dest_path):
    """Transfer a text file via base64 over serial."""
    if isinstance(content, str):
        data = content.encode()
    else:
        data = content
    b64 = base64.b64encode(data).decode()
    chunks = [b64[i:i+76] for i in range(0, len(b64), 76)]
    print(f"  Transferring {dest_path} ({len(data)} bytes, {len(chunks)} chunks)...")

    send("rm -f /tmp/xfer.b64\n", 0.3)
    for i, chunk in enumerate(chunks):
        send(f"echo '{chunk}' >> /tmp/xfer.b64\n", 0.05)
        if i % 100 == 0 and i > 0:
            print(f"    {i}/{len(chunks)} chunks...")
            time.sleep(0.5)

    time.sleep(1)
    send_cmd(f"cat /tmp/xfer.b64 | /usr/bin/b64decode -r > {dest_path}", timeout=60)
    send("rm -f /tmp/xfer.b64\n", 0.3)


def transfer_wallpaper():
    """Transfer wallpaper using pre-encoded data."""
    dest = "/usr/local/share/wallpapers/freebsd.png"
    chunks = [wallpaper_b64[i:i+76] for i in range(0, len(wallpaper_b64), 76)]
    print(f"  Transferring wallpaper ({len(wallpaper_data)} bytes, {len(chunks)} chunks)...")

    send("rm -f /tmp/wp.b64\n", 0.3)
    for i, chunk in enumerate(chunks):
        send(f"echo '{chunk}' >> /tmp/wp.b64\n", 0.05)
        if i % 200 == 0 and i > 0:
            print(f"    {i}/{len(chunks)} chunks...")
            time.sleep(0.5)

    time.sleep(2)
    send_cmd(f"cat /tmp/wp.b64 | /usr/bin/b64decode -r > {dest}", timeout=60)
    send("rm -f /tmp/wp.b64\n", 0.3)

    # Verify
    send(f"ls -la {dest}\n", 2)
    drain()
    decoded = serial_buf.decode(errors="replace")
    if "freebsd.png" in decoded:
        print("  >>> Wallpaper transferred OK!")
    else:
        print("  >>> WARNING: Wallpaper may not have transferred!")


# ══════════════════════════════════════════════════════════════
# Boot and configure
# ══════════════════════════════════════════════════════════════

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

# ── Wallpaper ──
print("\n=== Transferring wallpaper ===")
send_cmd("mkdir -p /usr/local/share/wallpapers")
transfer_wallpaper()

# ── Status bar script ──
print("\n=== Installing sparkline status bar ===")
send_cmd(f"mkdir -p {HOME}/.config/i3")
transfer_file(STATUS_SH, f"{HOME}/.config/i3/status.sh")
send_cmd(f"chmod +x {HOME}/.config/i3/status.sh")

# ── Startup layout script ──
print("\n=== Installing golden rectangle layout ===")
transfer_file(STARTUP_SH, f"{HOME}/.config/i3/startup.sh")
send_cmd(f"chmod +x {HOME}/.config/i3/startup.sh")

# ── Fish prompt, greeting, right prompt ──
print("\n=== Installing fish shell configs ===")
send_cmd(f"mkdir -p {HOME}/.config/fish/functions")
send_cmd(f"mkdir -p {HOME}/.config/fish/conf.d")
send_cmd(f"mkdir -p {HOME}/.local/share/fish")
transfer_file(FISH_PROMPT, f"{HOME}/.config/fish/functions/fish_prompt.fish")
transfer_file(FISH_RIGHT_PROMPT, f"{HOME}/.config/fish/functions/fish_right_prompt.fish")
transfer_file(FISH_GREETING, f"{HOME}/.config/fish/functions/fish_greeting.fish")
transfer_file(FISH_VARIABLES, f"{HOME}/.local/share/fish/fish_variables")

# ── Update i3 config ──
print("\n=== Updating i3 config ===")
I3CFG = f"{HOME}/.config/i3/config"

# Status command → sparkline script
send_cmd(f"sed -i '' 's|status_command.*|status_command {HOME}/.config/i3/status.sh|' {I3CFG}")

# Terminal keybinding → urxvt -e fish
send_cmd(f"sed -i '' 's|exec urxvt$|exec urxvt -e fish|' {I3CFG}")
send_cmd(f"sed -i '' 's|exec i3-sensible-terminal|exec urxvt -e fish|' {I3CFG}")

# Thinner borders (pixel 1 instead of 2-3)
send_cmd(f"sed -i '' 's|default_border pixel [0-9]*|default_border pixel 1|' {I3CFG}")
# If no default_border line exists, add it
send_cmd(f"grep -q 'default_border' {I3CFG} || echo 'default_border pixel 1' >> {I3CFG}")

# Subtle border colors (dark muted red instead of bright)
send_cmd(f"sed -i '' 's|^client\\.focused .*|client.focused          #3a0800 #1a0000 #cccccc #3a0800   #3a0800|' {I3CFG}")
send_cmd(f"sed -i '' 's|^client\\.unfocused .*|client.unfocused        #1a1a1a #0a0a0a #666666 #1a1a1a   #1a1a1a|' {I3CFG}")
send_cmd(f"sed -i '' 's|^client\\.focused_inactive .*|client.focused_inactive  #222222 #111111 #888888 #222222   #222222|' {I3CFG}")

# Remove any existing exec urxvt startup lines (replaced by startup.sh)
send_cmd(f"sed -i '' '/^exec.*urxvt/d' {I3CFG}")

# Ensure startup script is registered (only if not already there)
send_cmd(f"grep -q 'startup.sh' {I3CFG} || echo 'exec --no-startup-id {HOME}/.config/i3/startup.sh' >> {I3CFG}")

# Ensure wallpaper exec is there
send_cmd(f"grep -q 'feh.*wallpapers' {I3CFG} || echo 'exec --no-startup-id feh --bg-fill /usr/local/share/wallpapers/freebsd.png' >> {I3CFG}")

# ── URxvt transparency + styling ──
print("\n=== Configuring terminal transparency & style ===")
XRES = f"{HOME}/.Xresources"

# Add pseudo-transparency
send_cmd(f"grep -q 'URxvt.transparent' {XRES} || echo 'URxvt.transparent: true' >> {XRES}")
send_cmd(f"grep -q 'URxvt.shading' {XRES} || echo 'URxvt.shading: 30' >> {XRES}")

# Ensure internal border is small for elegance
send_cmd(f"grep -q 'URxvt.internalBorder' {XRES} || echo 'URxvt.internalBorder: 8' >> {XRES}")

# ── i3bar styling ──
print("\n=== Updating i3bar colors ===")
# Make status bar background match theme
send_cmd(f"sed -i '' 's|background .*#[0-9a-fA-F]*|background #0a0a0a|' {I3CFG}")
send_cmd(f"sed -i '' 's|statusline .*#[0-9a-fA-F]*|statusline #888888|' {I3CFG}")

# ── Timezone ──
print("\n=== Setting timezone ===")
send_cmd("cp /usr/share/zoneinfo/America/Boise /etc/localtime")
send_cmd("echo 'America/Boise' > /var/db/zoneinfo")

# ── Set ownership ──
print("\n=== Setting file ownership ===")
send_cmd(f"chown -R bsduser:bsduser {HOME}/.config")
send_cmd(f"chown -R bsduser:bsduser {HOME}/.local")

# ── Verify ──
print("\n=== Verifying ===")
send(f"echo '===WALLPAPER===' && ls -la /usr/local/share/wallpapers/freebsd.png\n", 1)
drain()
send(f"echo '===STATUS===' && head -3 {HOME}/.config/i3/status.sh\n", 1)
drain()
send(f"echo '===STARTUP===' && head -3 {HOME}/.config/i3/startup.sh\n", 1)
drain()
send(f"echo '===FISH===' && ls {HOME}/.config/fish/functions/\n", 1)
drain()
send(f"echo '===COLORS===' && head -5 {HOME}/.local/share/fish/fish_variables\n", 1)
drain()
send(f"echo '===I3CFG===' && grep -E 'status_command|startup|urxvt|default_border|client\\.focused|transparent|feh' {I3CFG}\n", 2)
drain()
send(f"echo '===XRES===' && grep -E 'transparent|shading|internalBorder' {XRES}\n", 1)
drain()

# ── Shutdown ──
print("\n=== Syncing and shutting down ===")
send("sync\n", 3)
send("sync\n", 3)
send("shutdown -p now\n", 5)

try:
    proc.wait(timeout=60)
except subprocess.TimeoutExpired:
    proc.kill()

mon.close()
ser.close()
print("\n\n=== Desktop UI customization complete! ===")
