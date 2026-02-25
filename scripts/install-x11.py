#!/usr/bin/env python3
"""Install X11 desktop environment into FreeBSD image.

Boots the FreeBSD image in QEMU with networking, installs packages,
configures Xorg, fluxbox, auto-login, and auto-startx.

Reads PACKAGES and X11 config from webbsd.conf.
"""

import subprocess
import time
import sys
import os
import socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")
CONF = os.path.join(BASE, "webbsd.conf")

MONITOR_PORT = 45455
SERIAL_PORT = 45456


def load_config(path):
    config = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                val = val.strip().strip('"').strip("'")
                config[key.strip()] = val
    return config


cfg = load_config(CONF)
PACKAGES = cfg.get("PACKAGES", "")
X11_RESOLUTION = cfg.get("X11_RESOLUTION", "1024x768")
X11_DEPTH = cfg.get("X11_DEPTH", "24")
X11_WM = cfg.get("X11_WM", "fluxbox")
HOSTNAME = cfg.get("HOSTNAME", "webbsd")
WALLPAPER = cfg.get("WALLPAPER", "")
DESKTOP_USER = cfg.get("USER_NAME", "") or "root"
USER_GROUPS = cfg.get("USER_GROUPS", "wheel")

# Home directory for the desktop user
HOME_DIR = f"/home/{DESKTOP_USER}" if DESKTOP_USER != "root" else "/root"

print(f"Installing X11 desktop into {IMAGE}")
print(f"  Packages: {PACKAGES}")
print(f"  Resolution: {X11_RESOLUTION}x{X11_DEPTH}")
print(f"  Window manager: {X11_WM}")
print(f"  Desktop user: {DESKTOP_USER} ({HOME_DIR})")
print()

# Start QEMU with networking
proc = subprocess.Popen(
    [
        "qemu-system-i386", "-m", "512",
        "-drive", f"file={IMAGE},format=raw",
        "-display", "none",
        "-serial", f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off",
        "-monitor", f"tcp:127.0.0.1:{MONITOR_PORT},server=on,wait=off",
        "-net", "nic,model=e1000",
        "-net", "user",
        "-no-reboot",
    ],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
time.sleep(1)

# Connect to QEMU monitor
mon = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
mon.settimeout(5)
mon.connect(("127.0.0.1", MONITOR_PORT))
time.sleep(0.5)
try:
    mon.recv(4096)
except:
    pass


def mon_cmd(cmd, delay=0.3):
    mon.send((cmd + "\r\n").encode())
    time.sleep(delay)
    try:
        return mon.recv(8192).decode(errors='replace')
    except:
        return ""


def sendkey(key, delay=0.1):
    mon_cmd(f"sendkey {key}", delay)


# Connect to serial
ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
ser.settimeout(1)
ser.connect(("127.0.0.1", SERIAL_PORT))

serial_buf = b""


def drain():
    global serial_buf
    while True:
        try:
            data = ser.recv(4096)
            if not data:
                break
            serial_buf += data
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
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


def send_cmd(cmd, timeout=60):
    """Send a command and wait for completion using sentinel.

    The sentinel appears twice in serial output:
    1. In the shell's echo of the command line
    2. In the actual output of 'echo SENTINEL'
    We wait for the second occurrence to ensure the command finished.
    """
    global serial_buf
    import random
    sentinel = f"__DONE_{random.randint(10000,99999)}__"
    serial_buf = b""
    send(cmd + f" ; echo {sentinel}\n", 0.3)
    # Wait for sentinel to appear twice (echo + output)
    start = time.time()
    while time.time() - start < timeout:
        drain()
        if serial_buf.count(sentinel.encode()) >= 2:
            drain()
            return
        time.sleep(0.3)
    print(f"WARNING: Timeout ({timeout}s) waiting for: {cmd[:80]}...")
    drain()


# Boot to multi-user — just wait for login prompt
print("Waiting for FreeBSD to boot...")
if not wait_for("login:", timeout=300):
    print("ERROR: No login prompt detected")
    drain()
    proc.kill()
    sys.exit(1)

print(">>> Login prompt detected, logging in as root...")
send("root\n", 3)
drain()

# Filesystem is already mounted rw in multi-user mode
# Kill noisy cron/dhclient that pollutes serial output
print("\n=== Silencing dhclient noise ===")
send("crontab -r 2>/dev/null; pkill -f 'dhclient ed0' 2>/dev/null\n", 2)
drain()

# Ensure networking is up on em0 (QEMU e1000)
print("\n=== Starting networking ===")
send_cmd("/sbin/ifconfig em0 up", timeout=5)
send_cmd("/sbin/dhclient em0", timeout=30)
time.sleep(3)
drain()

# Verify network
send("ping -c 1 8.8.8.8\n", 0.3)
if wait_for("1 packets received", timeout=15):
    print(">>> Network is up!")
else:
    print("WARNING: Network may not be working, trying anyway...")
    drain()

# Set DNS
send_cmd("echo 'nameserver 8.8.8.8' > /etc/resolv.conf")

# Bootstrap pkg
print("\n=== Bootstrapping pkg ===")
send_cmd("env ASSUME_ALWAYS_YES=yes pkg bootstrap", timeout=120)

# Install packages
print(f"\n=== Installing packages: {PACKAGES} ===")
print("This may take 10-30 minutes depending on download speed...")
send_cmd(f"pkg install -y {PACKAGES}", timeout=1800)

# Verify key packages (use full paths — PATH is limited in single-user mode)
print("\n=== Verifying installation ===")
send_cmd("test -x /usr/local/bin/Xorg && echo XORG_OK || echo XORG_FAIL")
send_cmd(f"test -x /usr/local/bin/{X11_WM} && echo WM_OK || echo WM_FAIL")

# ============================================================
# Create desktop user
# ============================================================
if DESKTOP_USER != "root":
    print(f"\n=== Creating user: {DESKTOP_USER} ===")
    send_cmd(f"pw useradd -n {DESKTOP_USER} -d {HOME_DIR} -m -G {USER_GROUPS} -s /usr/local/bin/fish", timeout=10)
    # Set empty password (allow passwordless login)
    send_cmd(f"pw mod user {DESKTOP_USER} -w none", timeout=10)
    # Also allow console login without password
    send_cmd(f"sed -i '' 's/^{DESKTOP_USER}:\\*:/{DESKTOP_USER}::/' /etc/master.passwd && pwd_mkdb -p /etc/master.passwd", timeout=10)
    print(f">>> User {DESKTOP_USER} created with no password")

# ============================================================
# Configure Xorg
# ============================================================
print("\n=== Configuring Xorg ===")
send_cmd("mkdir -p /usr/local/etc/X11/xorg.conf.d")

# VESA driver config
print(">>> Writing Xorg VESA config...")
send("cat > /usr/local/etc/X11/xorg.conf.d/10-vesa.conf << 'XEOF'\n", 0.3)
send('Section "Device"\n', 0.2)
send('    Identifier "Card0"\n', 0.2)
send('    Driver "vesa"\n', 0.2)
send('EndSection\n', 0.2)
send('\n', 0.1)
send('Section "Screen"\n', 0.2)
send('    Identifier "Screen0"\n', 0.2)
send('    Device "Card0"\n', 0.2)
send(f'    DefaultDepth {X11_DEPTH}\n', 0.2)
send(f'    SubSection "Display"\n', 0.2)
send(f'        Depth {X11_DEPTH}\n', 0.2)
send(f'        Modes "{X11_RESOLUTION}"\n', 0.2)
send('    EndSubSection\n', 0.2)
send('EndSection\n', 0.2)
send("XEOF\n", 1)
drain()

# Input config
print(">>> Writing Xorg input config...")
send("cat > /usr/local/etc/X11/xorg.conf.d/20-input.conf << 'XEOF'\n", 0.3)
send('Section "ServerLayout"\n', 0.2)
send('    Identifier "Layout0"\n', 0.2)
send('    Screen "Screen0"\n', 0.2)
send('    InputDevice "Keyboard0" "CoreKeyboard"\n', 0.2)
send('    InputDevice "Mouse0" "CorePointer"\n', 0.2)
send('EndSection\n', 0.2)
send('\n', 0.1)
send('Section "InputDevice"\n', 0.2)
send('    Identifier "Keyboard0"\n', 0.2)
send('    Driver "kbd"\n', 0.2)
send('    Option "XkbLayout" "us"\n', 0.2)
send('EndSection\n', 0.2)
send('\n', 0.1)
send('Section "InputDevice"\n', 0.2)
send('    Identifier "Mouse0"\n', 0.2)
send('    Driver "mouse"\n', 0.2)
send('    Option "Protocol" "auto"\n', 0.2)
send('    Option "Device" "/dev/sysmouse"\n', 0.2)
send('    Option "ZAxisMapping" "4 5"\n', 0.2)
send('EndSection\n', 0.2)
send("XEOF\n", 1)
drain()

# Enable moused
print(">>> Enabling moused...")
send_cmd("sysrc moused_enable=YES")
send_cmd("sysrc moused_port=/dev/psm0")

# ============================================================
# Configure i3 window manager
# ============================================================
print("\n=== Configuring i3 ===")
send_cmd(f"mkdir -p {HOME_DIR}/.config/i3")
send_cmd(f"mkdir -p {HOME_DIR}/.config/i3status")

# i3 config — full rice with gaps, picom, rofi, urxvt
# Mod1 = Alt (v86 PS/2 keyboard has no Super key)
print(">>> Writing i3 config...")
i3_config = r"""# webBSD i3 config — dark hacker rice
set $mod Mod1
set $term urxvt

# Font (Nerd Font if available, fallback to DejaVu)
font pango:JetBrainsMono Nerd Font 9, DejaVu Sans Mono 9

# Gaps
gaps inner 8
gaps outer 4
smart_gaps on

# Colors — base16 dark with #ab1100 red accent
# class                 border  bg      text    indicator child_border
client.focused          #ab1100 #1a0a08 #e0e0e0 #ab1100   #ab1100
client.focused_inactive #333333 #0f0f0f #888888 #333333   #1a1a1a
client.unfocused        #1a1a1a #0a0a0a #555555 #1a1a1a   #0a0a0a
client.urgent           #cc2200 #1a0a08 #ffffff #cc2200   #cc2200
client.placeholder      #000000 #080808 #555555 #000000   #000000
client.background       #080808

# Window borders
default_border pixel 2
default_floating_border pixel 2
hide_edge_borders smart

# Keybindings
bindsym $mod+Return exec $term
bindsym $mod+d exec dmenu_run -fn 'DejaVu Sans Mono:size=10' -nb '#0a0a0a' -nf '#888888' -sb '#ab1100' -sf '#ffffff'
bindsym $mod+Tab exec --no-startup-id i3-msg focus next
bindsym $mod+Shift+q kill
bindsym $mod+Shift+c reload
bindsym $mod+Shift+r restart
bindsym $mod+Shift+e exec "i3-msg exit"

# Focus (vim keys)
bindsym $mod+h focus left
bindsym $mod+j focus down
bindsym $mod+k focus up
bindsym $mod+l focus right
bindsym $mod+Left focus left
bindsym $mod+Down focus down
bindsym $mod+Up focus up
bindsym $mod+Right focus right

# Move windows
bindsym $mod+Shift+h move left
bindsym $mod+Shift+j move down
bindsym $mod+Shift+k move up
bindsym $mod+Shift+l move right
bindsym $mod+Shift+Left move left
bindsym $mod+Shift+Down move down
bindsym $mod+Shift+Up move up
bindsym $mod+Shift+Right move right

# Split
bindsym $mod+b split h
bindsym $mod+v split v

# Layout
bindsym $mod+s layout stacking
bindsym $mod+w layout tabbed
bindsym $mod+e layout toggle split
bindsym $mod+f fullscreen toggle
bindsym $mod+Shift+space floating toggle
bindsym $mod+space focus mode_toggle

# Workspaces
set $ws1 "1"
set $ws2 "2"
set $ws3 "3"
set $ws4 "4"
set $ws5 "5"
bindsym $mod+1 workspace $ws1
bindsym $mod+2 workspace $ws2
bindsym $mod+3 workspace $ws3
bindsym $mod+4 workspace $ws4
bindsym $mod+5 workspace $ws5
bindsym $mod+Shift+1 move container to workspace $ws1
bindsym $mod+Shift+2 move container to workspace $ws2
bindsym $mod+Shift+3 move container to workspace $ws3
bindsym $mod+Shift+4 move container to workspace $ws4
bindsym $mod+Shift+5 move container to workspace $ws5

# Resize mode
mode "resize" {
    bindsym h resize shrink width 5 px or 5 ppt
    bindsym j resize grow height 5 px or 5 ppt
    bindsym k resize shrink height 5 px or 5 ppt
    bindsym l resize grow width 5 px or 5 ppt
    bindsym Left resize shrink width 5 px or 5 ppt
    bindsym Down resize grow height 5 px or 5 ppt
    bindsym Up resize shrink height 5 px or 5 ppt
    bindsym Right resize grow width 5 px or 5 ppt
    bindsym Return mode "default"
    bindsym Escape mode "default"
    bindsym $mod+r mode "default"
}
bindsym $mod+r mode "resize"

# Floating rules

# Status bar
bar {
    status_command i3status
    position bottom
    height 22
    colors {
        background #0a0a0aCC
        statusline #888888
        separator  #333333
        focused_workspace  #ab1100 #ab1100 #ffffff
        active_workspace   #333333 #1a1a1a #888888
        inactive_workspace #0a0a0a #0a0a0a #555555
        urgent_workspace   #cc2200 #cc2200 #ffffff
    }
}

# Startup applications
exec --no-startup-id picom --config HOME_DIR_PLACEHOLDER/.config/picom/picom.conf &
exec --no-startup-id xsetroot -solid '#080808'
exec --no-startup-id urxvt -e tmux
exec --no-startup-id sh -c 'echo DESKTOP_READY > /tmp/x11_ready'
"""
i3_config = i3_config.replace("HOME_DIR_PLACEHOLDER", HOME_DIR)
send(f"cat > {HOME_DIR}/.config/i3/config << 'I3EOF'\n", 0.3)
for line in i3_config.strip().split("\n"):
    send(line + "\n", 0.12)
send("I3EOF\n", 1)
drain()

# i3status config
print(">>> Writing i3status config...")
send(f"cat > {HOME_DIR}/.config/i3status/config << 'I3SEOF'\n", 0.3)
i3status_lines = r"""general {
    output_format = "i3bar"
    colors = true
    color_good = "#ab1100"
    color_degraded = "#555555"
    color_bad = "#ff0000"
    interval = 5
}

order += "cpu_usage"
order += "memory"
order += "disk /"
order += "tztime local"

cpu_usage {
    format = " CPU %usage "
}

memory {
    format = " MEM %used/%total "
    threshold_degraded = "10%"
    threshold_critical = "5%"
}

disk "/" {
    format = " SSD %avail "
}

tztime local {
    format = " %Y-%m-%d %H:%M "
}"""
for line in i3status_lines.strip().split("\n"):
    send(line + "\n", 0.12)
send("I3SEOF\n", 1)
drain()

# ============================================================
# picom compositor — xrender backend for VESA compatibility
# ============================================================
print(">>> Writing picom config...")
send_cmd(f"mkdir -p {HOME_DIR}/.config/picom")
send(f"cat > {HOME_DIR}/.config/picom/picom.conf << 'PCEOF'\n", 0.3)
picom_lines = """# picom — xrender backend (no GPU needed)
backend = "xrender";

# Opacity
active-opacity = 1.0;
inactive-opacity = 0.90;
frame-opacity = 0.85;

# Fade
fading = true;
fade-in-step = 0.06;
fade-out-step = 0.06;
fade-delta = 8;

# Shadows
shadow = true;
shadow-radius = 12;
shadow-offset-x = -7;
shadow-offset-y = -7;
shadow-opacity = 0.6;
shadow-color = "#000000";
shadow-exclude = [
    "class_g = 'i3-frame'",
    "_NET_WM_STATE@:32a *= '_NET_WM_STATE_HIDDEN'"
];

# Opacity rules
opacity-rule = [
    "90:class_g = 'URxvt' && focused",
    "80:class_g = 'URxvt' && !focused"
];

# Performance
vsync = false;
use-damage = true;
unredir-if-possible = true;"""
for line in picom_lines.strip().split("\n"):
    send(line + "\n", 0.12)
send("PCEOF\n", 1)
drain()

# ============================================================
# urxvt config — semi-transparent, Nerd Font, dark theme
# ============================================================
print(">>> Writing urxvt/Xresources config...")

# ============================================================
# Xresources — urxvt dark rice + xterm fallback
# ============================================================
print("\n=== Configuring terminal (urxvt + xterm) ===")
send(f"cat > {HOME_DIR}/.Xresources << 'XEOF'\n", 0.3)
xres_lines = """! === Base16 Dark Color Scheme ===
! Black
*color0:  #0a0a0a
*color8:  #555555
! Red
*color1:  #ab1100
*color9:  #cc2200
! Green
*color2:  #1a8a1a
*color10: #33cc33
! Yellow
*color3:  #aa8800
*color11: #ccaa00
! Blue
*color4:  #3465a4
*color12: #5599dd
! Magenta
*color5:  #8a2252
*color13: #aa4488
! Cyan
*color6:  #2aa198
*color14: #44ccbb
! White
*color7:  #c0c0c0
*color15: #e0e0e0

! === URxvt config ===
URxvt.font: xft:JetBrainsMono Nerd Font:size=10, xft:DejaVu Sans Mono:size=10
URxvt.boldFont: xft:JetBrainsMono Nerd Font:bold:size=10, xft:DejaVu Sans Mono:bold:size=10
URxvt.background: [85]#0a0a0a
URxvt.foreground: #c0c0c0
URxvt.cursorColor: #ab1100
URxvt.cursorBlink: true
URxvt.scrollBar: false
URxvt.saveLines: 10000
URxvt.internalBorder: 12
URxvt.externalBorder: 0
URxvt.depth: 32
URxvt.letterSpace: 0
URxvt.lineSpace: 2
URxvt.geometry: 100x35
URxvt.urgentOnBell: true
URxvt.iso14755: false
URxvt.iso14755_52: false
! Clickable URLs
URxvt.perl-ext-common: default,matcher
URxvt.url-launcher: /usr/bin/xdg-open
URxvt.matcher.button: 1

! === XTerm fallback ===
XTerm*background: #0a0a0a
XTerm*foreground: #c0c0c0
XTerm*cursorColor: #ab1100
XTerm*faceName: DejaVu Sans Mono
XTerm*faceSize: 11
XTerm*scrollBar: false
XTerm*saveLines: 2000
XTerm*selectToClipboard: true
XTerm*metaSendsEscape: true
XTerm*termName: xterm-256color"""
for line in xres_lines.strip().split("\n"):
    send(line + "\n", 0.12)
send("XEOF\n", 1)
drain()

# ============================================================
# Nerd Font — download JetBrainsMono
# ============================================================
print("\n=== Installing Nerd Font ===")
send_cmd("mkdir -p /usr/local/share/fonts/nerd")
# Download just the JetBrainsMono Nerd Font (single zip, ~30MB)
print(">>> Downloading JetBrainsMono Nerd Font...")
send_cmd(
    "fetch -o /tmp/jbmono.tar.xz 'https://github.com/ryanoasis/nerd-fonts/releases/latest/download/JetBrainsMono.tar.xz' "
    "2>&1 && echo FONT_DL_OK || echo FONT_DL_FAIL",
    timeout=120
)
send_cmd(
    "cd /usr/local/share/fonts/nerd && tar xf /tmp/jbmono.tar.xz 2>/dev/null; rm -f /tmp/jbmono.tar.xz; echo FONT_EXTRACT_OK",
    timeout=60
)
send_cmd("fc-cache -f /usr/local/share/fonts/nerd 2>/dev/null", timeout=30)

# ============================================================
# tmux — powerline-style dark config
# ============================================================
print("\n=== Configuring tmux ===")
send(f"cat > {HOME_DIR}/.tmux.conf << 'TMEOF'\n", 0.3)
tmux_lines = r"""# Terminal
set -g default-terminal "xterm-256color"
set -g default-shell /usr/local/bin/fish

# Prefix: Ctrl-a (more ergonomic than Ctrl-b)
unbind C-b
set -g prefix C-a
bind C-a send-prefix

# Start windows/panes at 1
set -g base-index 1
setw -g pane-base-index 1

# Mouse support
set -g mouse on

# Vi mode
setw -g mode-keys vi

# Split with | and -
bind | split-window -h -c "#{pane_current_path}"
bind - split-window -v -c "#{pane_current_path}"

# Vim-like pane navigation
bind h select-pane -L
bind j select-pane -D
bind k select-pane -U
bind l select-pane -R

# Resize panes
bind -r H resize-pane -L 5
bind -r J resize-pane -D 5
bind -r K resize-pane -U 5
bind -r L resize-pane -R 5

# Status bar
set -g status-position bottom
set -g status-style 'bg=#0a0a0a,fg=#888888'
set -g status-left '#[fg=#ab1100,bold] #S #[fg=#333333]|'
set -g status-left-length 30
set -g status-right '#[fg=#555555]#H #[fg=#333333]| #[fg=#ab1100]%H:%M '
set -g status-right-length 50

# Window status
setw -g window-status-format ' #[fg=#555555]#I:#W '
setw -g window-status-current-format ' #[fg=#ab1100,bold]#I:#W '
setw -g window-status-separator ''

# Pane borders
set -g pane-border-style 'fg=#222222'
set -g pane-active-border-style 'fg=#ab1100'

# Message style
set -g message-style 'bg=#1a0a08,fg=#ab1100'

# No delay on escape
set -sg escape-time 0

# History
set -g history-limit 50000"""
for line in tmux_lines.strip().split("\n"):
    send(line + "\n", 0.12)
send("TMEOF\n", 1)
drain()

# ============================================================
# fish shell config
# ============================================================
print("\n=== Configuring fish shell ===")
send_cmd(f"mkdir -p {HOME_DIR}/.config/fish/functions")

# Set fish as default shell for desktop user
send_cmd(f"chsh -s /usr/local/bin/fish {DESKTOP_USER}")

# fish config
send(f"cat > {HOME_DIR}/.config/fish/config.fish << 'FISHEOF'\n", 0.3)
fish_lines = r"""# webBSD fish config
set -g fish_greeting ""

# Path
set -gx PATH /usr/local/bin /usr/local/sbin /usr/bin /usr/sbin /bin /sbin $PATH

# Colors — base16 dark
set -g fish_color_command green
set -g fish_color_param normal
set -g fish_color_error red --bold
set -g fish_color_quote yellow
set -g fish_color_autosuggestion 555555
set -g fish_color_valid_path --underline
set -g fish_color_cwd red

# Custom prompt
function fish_prompt
    set_color red
    echo -n (whoami)
    set_color 555555
    echo -n '@'
    set_color brred
    echo -n (hostname -s)
    set_color 555555
    echo -n ':'
    set_color blue
    echo -n (prompt_pwd)
    set_color 555555
    echo -n ' > '
    set_color normal
end

# Aliases
alias ll='ls -la'
alias la='ls -A'
alias ..='cd ..'
alias ...='cd ../..'
alias q='exit'
alias c='clear'
alias t='tmux'
alias ta='tmux attach'"""
for line in fish_lines.strip().split("\n"):
    send(line + "\n", 0.12)
send("FISHEOF\n", 1)
drain()

# ============================================================
# Auto-login + auto-startx
# ============================================================
print("\n=== Configuring auto-login ===")

# Add autologin getty entry — single backslash for line continuation
send("cat >> /etc/gettytab << 'GEOF'\n", 0.3)
send(f"Al|Autologin:\\\n", 0.2)
send(f"    :al={DESKTOP_USER}:ht:np:sp#115200:\n", 0.2)
send("GEOF\n", 1)
drain()

# Update ttyv0 to use autologin
print(f">>> Updating ttys for auto-login as {DESKTOP_USER} on ttyv0...")
send_cmd("sed -i '' '/^ttyv0/d' /etc/ttys")
send("printf 'ttyv0\\t\"/usr/libexec/getty Al\"\\txterm\\ton\\tsecure\\n' >> /etc/ttys\n", 1)
drain()

# .xinitrc
print(">>> Writing .xinitrc...")
send(f"cat > {HOME_DIR}/.xinitrc << 'XEOF'\n", 0.3)
send("#!/bin/sh\n", 0.2)
send(f"xrdb -merge {HOME_DIR}/.Xresources\n", 0.2)
send("exec i3\n", 0.2)
send("XEOF\n", 1)
drain()
send_cmd(f"chmod +x {HOME_DIR}/.xinitrc")

# Auto-startx on login
print(">>> Configuring auto-startx...")
send(f"cat > {HOME_DIR}/.profile << 'PEOF'\n", 0.3)
send("# Auto-start X if on console ttyv0\n", 0.2)
send('if [ "$(tty)" = "/dev/ttyv0" ]; then\n', 0.2)
send("    exec startx\n", 0.2)
send("fi\n", 0.2)
send("PEOF\n", 1)
drain()

# Also handle csh (FreeBSD default shell)
send(f"cat > {HOME_DIR}/.login << 'PEOF'\n", 0.3)
send("# Auto-start X if on console ttyv0\n", 0.2)
send("if ( `tty` == /dev/ttyv0 ) then\n", 0.2)
send("    exec startx\n", 0.2)
send("endif\n", 0.2)
send("PEOF\n", 1)
drain()

# ============================================================
# DNS + DHCP auto-config (for v86 state restore)
# ============================================================
print("\n=== Configuring DNS + auto-DHCP ===")
send_cmd("echo 'nameserver 8.8.8.8' > /etc/resolv.conf")
send_cmd("echo 'nameserver 8.8.4.4' >> /etc/resolv.conf")

send_cmd("mkdir -p /usr/local/bin")
send("cat > /usr/local/bin/auto-dhcp.sh << 'DEOF'\n", 0.3)
send("#!/bin/sh\n", 0.2)
send("IP=$(ifconfig ed0 2>/dev/null | grep 'inet ' | awk '{print $2}')\n", 0.2)
send('if [ -z "$IP" ]; then\n', 0.2)
send("    /sbin/dhclient ed0 > /dev/null 2>&1 &\n", 0.2)
send("fi\n", 0.2)
send("grep -q nameserver /etc/resolv.conf 2>/dev/null || echo 'nameserver 8.8.8.8' > /etc/resolv.conf\n", 0.2)
send("DEOF\n", 1)
drain()
send_cmd("chmod +x /usr/local/bin/auto-dhcp.sh")

send("cat > /etc/rc.local << 'REOF'\n", 0.3)
send("#!/bin/sh\n", 0.2)
send("sleep 2 && /usr/local/bin/auto-dhcp.sh &\n", 0.2)
send("REOF\n", 1)
drain()
send_cmd("chmod +x /etc/rc.local")
send_cmd("echo '* * * * * /usr/local/bin/auto-dhcp.sh' | crontab -")

# dhclient.conf to preserve DNS
send_cmd("grep -q 'supersede domain-name-servers' /etc/dhclient.conf || echo 'supersede domain-name-servers 8.8.8.8, 8.8.4.4;' >> /etc/dhclient.conf")

# DHCP delay
send_cmd("sysrc defaultroute_delay=5")

# ============================================================
# Final verification
# ============================================================
print("\n=== Final verification ===")
send("echo '--- Xorg ---' && ls -la /usr/local/bin/Xorg\n", 1)
drain()
send(f"echo '--- {X11_WM} ---' && ls -la /usr/local/bin/{X11_WM}\n", 1)
drain()
send("echo '--- dmenu ---' && ls -la /usr/local/bin/dmenu_run\n", 1)
drain()
send("echo '--- i3status ---' && ls -la /usr/local/bin/i3status\n", 1)
drain()
send(f"echo '--- .xinitrc ---' && cat {HOME_DIR}/.xinitrc\n", 1)
drain()
send(f"echo '--- i3 config ---' && head -5 {HOME_DIR}/.config/i3/config\n", 1)
drain()
send("echo '--- ttys ttyv0 ---' && grep ttyv0 /etc/ttys\n", 1)
drain()
send("echo '--- disk usage ---' && df -h /\n", 1)
drain()

# Fix ownership of all config files
if DESKTOP_USER != "root":
    print(f"\n=== Fixing ownership for {DESKTOP_USER} ===")
    send_cmd(f"chown -R {DESKTOP_USER}:{DESKTOP_USER} {HOME_DIR}")

# ============================================================
# Firewall — PF: allow out, block in
# ============================================================
print("\n=== Configuring PF firewall ===")
send("cat > /etc/pf.conf << 'PFEOF'\n", 0.3)
pf_lines = """# webBSD PF firewall — allow out, block in
set skip on lo0

# Default: block all incoming
block in all

# Allow all outgoing + keep state for replies
# (stateful: return traffic is automatically allowed)
pass out all keep state

# Allow ICMP (ping)
pass in inet proto icmp all
"""
for line in pf_lines.strip().split("\n"):
    send(line + "\n", 0.12)
send("PFEOF\n", 1)
drain()

# Enable PF
send_cmd("sysrc pf_enable=YES")
send_cmd("sysrc pflog_enable=YES")

# Clean shutdown
print("\n=== Shutting down ===")
send("sync\n", 1)
send("/sbin/shutdown -p now\n", 5)

try:
    proc.wait(timeout=60)
except subprocess.TimeoutExpired:
    proc.kill()

mon.close()
ser.close()
print("\n\n=== X11 desktop installation complete! ===")
print(f"Installed: {PACKAGES}")
print(f"Resolution: {X11_RESOLUTION}")
print(f"Window manager: {X11_WM} with dark theme")
print(f"Auto-login: {DESKTOP_USER} on ttyv0")
print("Auto-startx: enabled")
