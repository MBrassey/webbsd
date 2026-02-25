#!/usr/bin/env python3
"""Complete desktop setup with networking: nerd fonts, oh-my-fish, golden ratio
layout, transparency, wallpaper, sparkline status bar.

Boots QEMU with networking to install packages and download assets.
"""

import subprocess, time, sys, os, socket, base64

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")
WALLPAPER = os.path.join(BASE, "images", "assets", "wallpaper.png")

SERIAL_PORT = 45458
MONITOR_PORT = 45457
HOME = "/home/bsduser"

# ══════════════════════════════════════════════════════════════
# Golden rectangle startup layout
# ══════════════════════════════════════════════════════════════
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

# ══════════════════════════════════════════════════════════════
# Sparkline status bar
# ══════════════════════════════════════════════════════════════
STATUS_SH = r"""#!/bin/sh
S0=$(printf '\342\226\201')
S1=$(printf '\342\226\202')
S2=$(printf '\342\226\203')
S3=$(printf '\342\226\204')
S4=$(printf '\342\226\205')
S5=$(printf '\342\226\206')
S6=$(printf '\342\226\207')
S7=$(printf '\342\226\210')
_spark=""
build_spark() {
    _spark=""
    for v in $1; do
        idx=$((v * 7 / 100))
        [ "$idx" -lt 0 ] && idx=0
        [ "$idx" -gt 7 ] && idx=7
        case $idx in
            0) _spark="${_spark}${S0}" ;; 1) _spark="${_spark}${S1}" ;;
            2) _spark="${_spark}${S2}" ;; 3) _spark="${_spark}${S3}" ;;
            4) _spark="${_spark}${S4}" ;; 5) _spark="${_spark}${S5}" ;;
            6) _spark="${_spark}${S6}" ;; *) _spark="${_spark}${S7}" ;;
        esac
    done
}
echo '{"version":1}'
echo '['
echo '[]'
cpu_hist=""; mem_hist=""; cpu_n=0; mem_n=0; prev=""
while true; do
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
    tp=$(sysctl -n vm.stats.vm.v_page_count)
    fp=$(sysctl -n vm.stats.vm.v_free_count)
    ip=$(sysctl -n vm.stats.vm.v_inactive_count)
    used=$((tp-fp-ip))
    [ "$tp" -gt 0 ] && mem=$((100*used/tp)) || mem=0
    [ "$mem" -lt 0 ] && mem=0; [ "$mem" -gt 100 ] && mem=100
    if [ -z "$cpu_hist" ]; then cpu_hist="$cpu"; else cpu_hist="$cpu_hist $cpu"; fi
    if [ -z "$mem_hist" ]; then mem_hist="$mem"; else mem_hist="$mem_hist $mem"; fi
    cpu_n=$((cpu_n+1)); mem_n=$((mem_n+1))
    [ "$cpu_n" -gt 20 ] && { cpu_hist="${cpu_hist#* }"; cpu_n=20; }
    [ "$mem_n" -gt 20 ] && { mem_hist="${mem_hist#* }"; mem_n=20; }
    build_spark "$cpu_hist"; cpu_spark="$_spark"
    build_spark "$mem_hist"; mem_spark="$_spark"
    [ $cpu -ge 85 ] && cc="#ff3333" || { [ $cpu -ge 60 ] && cc="#ccaa00" || cc="#8899aa"; }
    [ $mem -ge 90 ] && mc="#ff3333" || { [ $mem -ge 70 ] && mc="#ccaa00" || mc="#8899aa"; }
    dt=$(date '+%a %b %d  %H:%M')
    printf ',['
    printf '{"full_text":" CPU %s %d%% ","color":"%s","separator":false,"separator_block_width":18},' "$cpu_spark" "$cpu" "$cc"
    printf '{"full_text":" MEM %s %d%% ","color":"%s","separator":false,"separator_block_width":18},' "$mem_spark" "$mem" "$mc"
    printf '{"full_text":" %s ","color":"#555555","separator":false}' "$dt"
    printf ']\n'
    sleep 2
done
""".lstrip()

# ══════════════════════════════════════════════════════════════
# Fish greeting
# ══════════════════════════════════════════════════════════════
FISH_GREETING = r"""function fish_greeting
    set_color 5f87af
    printf "  Welcome to "
    set_color --bold 87afd7
    echo "webBSD"
    set_color normal
    set_color 626262
    echo "  FreeBSD 13.5-RELEASE | i3wm"
    set_color normal
end
""".lstrip()

# ══════════════════════════════════════════════════════════════
# Fish setup script (run after OMF install)
# ══════════════════════════════════════════════════════════════
FISH_SETUP = r"""#!/usr/local/bin/fish
# Configure bobthefish theme
set -U theme_color_scheme dark
set -U theme_nerd_fonts yes
set -U theme_display_date no
set -U theme_display_cmd_duration yes
set -U theme_powerline_fonts yes
set -U theme_title_display_process yes
set -U theme_title_use_abbreviated_path yes

# FreeBSD-cool syntax highlighting (cool blues, neutral grays)
set -U fish_color_command 5f87af
set -U fish_color_param 87afd7
set -U fish_color_error ff5f5f
set -U fish_color_quote 87af5f
set -U fish_color_autosuggestion 4e4e4e
set -U fish_color_comment 626262
set -U fish_color_operator 5fafaf
set -U fish_color_end 5faf5f
set -U fish_color_escape 87afaf
set -U fish_color_redirection 5fafaf
set -U fish_color_cwd 5f87af
set -U fish_color_user 5f87af
set -U fish_color_host 87afd7
set -U fish_color_status ff5f5f
set -U fish_color_selection white --bold --background=303030
set -U fish_color_search_match bryellow --background=303030
set -U fish_color_valid_path --underline
set -U fish_pager_color_completion normal
set -U fish_pager_color_description 626262
set -U fish_pager_color_prefix 5f87af --bold --underline
set -U fish_pager_color_progress brwhite --background=303030
""".lstrip()


print("=== Complete desktop setup (with networking) ===")

# Read wallpaper
with open(WALLPAPER, "rb") as f:
    wallpaper_data = f.read()
wallpaper_b64 = base64.b64encode(wallpaper_data).decode()
print(f"Wallpaper: {len(wallpaper_data)} bytes")

# Boot QEMU WITH NETWORKING
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


def transfer_file(content, dest_path, chunk_size=256):
    """Transfer a file via base64 over serial."""
    if isinstance(content, str):
        data = content.encode()
    else:
        data = content
    b64 = base64.b64encode(data).decode()
    chunks = [b64[i:i+chunk_size] for i in range(0, len(b64), chunk_size)]
    print(f"  Transferring {dest_path} ({len(data)} bytes, {len(chunks)} chunks)...")
    send("rm -f /tmp/xfer.b64\n", 0.3)
    for i, chunk in enumerate(chunks):
        send(f"echo '{chunk}' >> /tmp/xfer.b64\n", 0.03)
        if i % 200 == 0 and i > 0:
            print(f"    {i}/{len(chunks)}...")
            time.sleep(0.3)
    time.sleep(1)
    send_cmd(f"cat /tmp/xfer.b64 | /usr/bin/b64decode -r > {dest_path}", timeout=60)
    send("rm -f /tmp/xfer.b64\n", 0.3)


# ══════════════════════════════════════════════════════════════
# BOOT & LOGIN
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

# Kill noise
send_cmd("service cron stop", timeout=10)
send_cmd("killall dhclient 2>/dev/null; true", timeout=5)

# ══════════════════════════════════════════════════════════════
# NETWORKING
# ══════════════════════════════════════════════════════════════
print("\n=== Setting up networking ===")
send_cmd("dhclient em0", timeout=30)
time.sleep(3)
drain()

# Verify network
if send_cmd("host pkg.FreeBSD.org", timeout=15):
    print("  DNS works!")
else:
    print("  DNS check failed, trying manual resolv.conf...")
    send_cmd("echo 'nameserver 10.0.2.3' > /etc/resolv.conf", timeout=5)

# ══════════════════════════════════════════════════════════════
# INSTALL PACKAGES
# ══════════════════════════════════════════════════════════════
print("\n=== Installing git ===")
send_cmd("env ASSUME_ALWAYS_YES=yes pkg install -y git", timeout=600)
print("  git installed")

# ══════════════════════════════════════════════════════════════
# NERD FONTS
# ══════════════════════════════════════════════════════════════
print("\n=== Installing JetBrainsMono Nerd Font ===")
send_cmd("mkdir -p /usr/local/share/fonts/nerd")
nerd_url = "https://github.com/ryanoasis/nerd-fonts/releases/download/v3.3.0/JetBrainsMono.zip"
if send_cmd(f"fetch -o /tmp/nerd.zip '{nerd_url}'", timeout=300):
    print("  Downloaded nerd font zip")
    send_cmd("cd /usr/local/share/fonts/nerd && tar xf /tmp/nerd.zip", timeout=120)
    send_cmd("fc-cache -f", timeout=120)
    send_cmd("rm -f /tmp/nerd.zip")
    print("  Nerd font installed")
else:
    print("  WARN: Nerd font download failed, will use DejaVu")

# ══════════════════════════════════════════════════════════════
# OH-MY-FISH
# ══════════════════════════════════════════════════════════════
print("\n=== Installing Oh My Fish ===")
omf_url = "https://raw.githubusercontent.com/oh-my-fish/oh-my-fish/master/bin/install"
send_cmd(f"fetch -o /tmp/install_omf '{omf_url}'", timeout=60)
# Run OMF installer as bsduser
send_cmd(
    f"su -l bsduser -c 'fish /tmp/install_omf --noninteractive --path={HOME}/.local/share/omf --config={HOME}/.config/omf'",
    timeout=180
)
print("  OMF installed")

# Install bobthefish theme
print("  Installing bobthefish theme...")
send_cmd(
    f"su -l bsduser -c 'fish -c \"omf install bobthefish\"'",
    timeout=120
)
print("  bobthefish installed")

# ══════════════════════════════════════════════════════════════
# FISH CONFIGURATION
# ══════════════════════════════════════════════════════════════
print("\n=== Configuring fish shell ===")
send_cmd(f"mkdir -p {HOME}/.config/fish/functions")
send_cmd(f"mkdir -p {HOME}/.local/share/fish")

# Transfer and run setup script (sets universal variables)
transfer_file(FISH_SETUP, "/tmp/fish_setup.fish")
send_cmd(f"su -l bsduser -c 'fish /tmp/fish_setup.fish'", timeout=30)
send("rm -f /tmp/fish_setup.fish\n", 0.3)

# Transfer greeting (overrides default)
transfer_file(FISH_GREETING, f"{HOME}/.config/fish/functions/fish_greeting.fish")

# ══════════════════════════════════════════════════════════════
# WALLPAPER
# ══════════════════════════════════════════════════════════════
print("\n=== Transferring wallpaper ===")
send_cmd("mkdir -p /usr/local/share/wallpapers")
chunks = [wallpaper_b64[i:i+256] for i in range(0, len(wallpaper_b64), 256)]
print(f"  Sending {len(chunks)} chunks...")
send("rm -f /tmp/wp.b64\n", 0.3)
for i, chunk in enumerate(chunks):
    send(f"echo '{chunk}' >> /tmp/wp.b64\n", 0.03)
    if i % 200 == 0 and i > 0:
        print(f"    {i}/{len(chunks)}...")
        time.sleep(0.3)
time.sleep(2)
send_cmd("cat /tmp/wp.b64 | /usr/bin/b64decode -r > /usr/local/share/wallpapers/freebsd.png", timeout=60)
send("rm -f /tmp/wp.b64\n", 0.3)

# Verify wallpaper
send(f"wc -c < /usr/local/share/wallpapers/freebsd.png\n", 2)
drain()

# ══════════════════════════════════════════════════════════════
# I3 SCRIPTS
# ══════════════════════════════════════════════════════════════
print("\n=== Installing i3 scripts ===")
send_cmd(f"mkdir -p {HOME}/.config/i3")
transfer_file(GOLDEN_3TERM, f"{HOME}/.config/i3/golden-3term.sh")
send_cmd(f"chmod +x {HOME}/.config/i3/golden-3term.sh")

transfer_file(STATUS_SH, f"{HOME}/.config/i3/status.sh")
send_cmd(f"chmod +x {HOME}/.config/i3/status.sh")

# ══════════════════════════════════════════════════════════════
# I3 CONFIG UPDATES
# ══════════════════════════════════════════════════════════════
print("\n=== Updating i3 config ===")
I3CFG = f"{HOME}/.config/i3/config"

# Status bar -> sparkline script
send_cmd(f"sed -i '' 's|status_command.*|status_command {HOME}/.config/i3/status.sh|' {I3CFG}")

# Terminal keybinding -> urxvt -e fish
send_cmd(f"sed -i '' 's|exec urxvt.*|exec urxvt -e fish|' {I3CFG}")
send_cmd(f"sed -i '' 's|exec i3-sensible-terminal|exec urxvt -e fish|' {I3CFG}")

# Thin subtle borders
send_cmd(f"sed -i '' 's|default_border pixel [0-9]*|default_border pixel 1|' {I3CFG}")
send_cmd(f"grep -q 'default_border' {I3CFG} || echo 'default_border pixel 1' >> {I3CFG}")

# Subtle border colors
send_cmd(f"sed -i '' 's|^client\\.focused .*|client.focused          #2a3a4a #1a2a3a #cccccc #2a3a4a   #2a3a4a|' {I3CFG}")
send_cmd(f"sed -i '' 's|^client\\.unfocused .*|client.unfocused        #1a1a1a #0a0a0a #666666 #1a1a1a   #1a1a1a|' {I3CFG}")
send_cmd(f"sed -i '' 's|^client\\.focused_inactive .*|client.focused_inactive  #222222 #111111 #888888 #222222   #222222|' {I3CFG}")

# Remove ALL old exec urxvt / startup.sh lines
send_cmd(f"sed -i '' '/^exec.*urxvt/d' {I3CFG}")
send_cmd(f"sed -i '' '/^exec.*startup\\.sh/d' {I3CFG}")

# Add golden-3term startup
send_cmd(f"grep -q 'golden-3term' {I3CFG} || echo 'exec --no-startup-id {HOME}/.config/i3/golden-3term.sh' >> {I3CFG}")

# Ensure wallpaper exec
send_cmd(f"sed -i '' '/feh.*wallpaper/d' {I3CFG}")
send_cmd(f"echo 'exec --no-startup-id feh --bg-fill /usr/local/share/wallpapers/freebsd.png' >> {I3CFG}")

# Bar styling
send_cmd(f"sed -i '' 's|background .*#[0-9a-fA-F]*|background #0a0a0a|' {I3CFG}")
send_cmd(f"sed -i '' 's|statusline .*#[0-9a-fA-F]*|statusline #888888|' {I3CFG}")

# ══════════════════════════════════════════════════════════════
# URXVT / XRESOURCES
# ══════════════════════════════════════════════════════════════
print("\n=== Configuring URxvt (font, transparency, style) ===")
XRES = f"{HOME}/.Xresources"

# Remove old font/transparency lines to avoid duplicates
send_cmd(f"sed -i '' '/URxvt\\.font/d' {XRES}")
send_cmd(f"sed -i '' '/URxvt\\.boldFont/d' {XRES}")
send_cmd(f"sed -i '' '/URxvt\\.transparent/d' {XRES}")
send_cmd(f"sed -i '' '/URxvt\\.shading/d' {XRES}")
send_cmd(f"sed -i '' '/URxvt\\.internalBorder/d' {XRES}")
send_cmd(f"sed -i '' '/URxvt\\.letterSpace/d' {XRES}")

# Nerd font with DejaVu fallback
send_cmd(f"echo 'URxvt.font: xft:JetBrainsMono Nerd Font Mono:size=10:antialias=true, xft:DejaVu Sans Mono:size=10' >> {XRES}")
send_cmd(f"echo 'URxvt.boldFont: xft:JetBrainsMono Nerd Font Mono:bold:size=10:antialias=true, xft:DejaVu Sans Mono:bold:size=10' >> {XRES}")

# Pseudo-transparency (shows wallpaper through terminal)
send_cmd(f"echo 'URxvt.transparent: true' >> {XRES}")
send_cmd(f"echo 'URxvt.shading: 25' >> {XRES}")

# Elegant spacing
send_cmd(f"echo 'URxvt.internalBorder: 10' >> {XRES}")
send_cmd(f"echo 'URxvt.letterSpace: 0' >> {XRES}")

# ══════════════════════════════════════════════════════════════
# TIMEZONE
# ══════════════════════════════════════════════════════════════
print("\n=== Setting timezone ===")
send_cmd("cp /usr/share/zoneinfo/America/Boise /etc/localtime")
send_cmd("echo 'America/Boise' > /var/db/zoneinfo")

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
send("fc-list | grep -i jetbrains | head -3\n", 2)
drain()
send(f"ls {HOME}/.local/share/omf/init.fish 2>/dev/null && echo 'OMF: OK' || echo 'OMF: MISSING'\n", 1)
drain()
send(f"ls /usr/local/share/wallpapers/freebsd.png && echo 'WP: OK' || echo 'WP: MISSING'\n", 1)
drain()
send(f"grep 'golden-3term' {I3CFG} && echo 'LAYOUT: OK'\n", 1)
drain()
send(f"grep 'transparent' {XRES} && echo 'TRANSP: OK'\n", 1)
drain()
send(f"grep 'JetBrains' {XRES} && echo 'FONT: OK'\n", 1)
drain()

# Print verification output
decoded = serial_buf.decode(errors="replace")
for line in decoded.split("\n"):
    if any(k in line for k in ["OK", "MISSING", "JetBrains"]):
        print(f"  {line.strip()}")

# ══════════════════════════════════════════════════════════════
# SHUTDOWN
# ══════════════════════════════════════════════════════════════
print("\n=== Syncing and shutting down ===")
send("sync\n", 3)
send("sync\n", 3)
send("shutdown -p now\n", 5)

try:
    proc.wait(timeout=120)
except subprocess.TimeoutExpired:
    proc.kill()

mon.close()
ser.close()
print("\n\n=== Complete desktop setup done! ===")
