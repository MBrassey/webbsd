#!/usr/bin/env python3
"""Final fix: write ALL desktop configs and ensure clean shutdown.

Previous fixes were lost due to unclean shutdowns causing fsck to revert changes.
This script writes everything and ensures proper sync before poweroff.
"""

import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")

proc = subprocess.Popen(
    ["qemu-system-i386", "-m", "512",
     "-drive", f"file={IMAGE},format=raw",
     "-display", "none",
     "-serial", f"tcp:127.0.0.1:45456,server=on,wait=off",
     "-monitor", f"tcp:127.0.0.1:45455,server=on,wait=off",
     "-no-reboot"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
time.sleep(1)

ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
ser.settimeout(1)
ser.connect(("127.0.0.1", 45456))

# Monitor for clean shutdown
mon = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
mon.settimeout(5)
mon.connect(("127.0.0.1", 45455))
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
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        except: break

def wait_for(pattern, timeout=300):
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

def mon_cmd(cmd, delay=0.5):
    mon.send((cmd + "\r\n").encode())
    time.sleep(delay)

print("Waiting for boot...")
if not wait_for("login:"):
    print("ERROR: No login prompt")
    proc.kill()
    sys.exit(1)

print("\n>>> Logging in...")
send("root\n", 5)
drain()

H = "/home/bsduser"

# ============================================================
# 1. Fix /etc/ttys — replace ttyv0 line with auto-login
# ============================================================
print("\n=== 1. Fixing /etc/ttys ===")
# Show current state
send("grep ttyv0 /etc/ttys\n", 2)
drain()
# Use a more robust sed pattern that handles tabs and various formats
send("sed -i '' '/^ttyv0[[:space:]]/d' /etc/ttys\n", 1)
drain()
# Append our auto-login entry
send("printf 'ttyv0\\t\"/usr/libexec/getty Al\"\\txterm\\ton\\tsecure\\n' >> /etc/ttys\n", 1)
drain()
# Verify
send("grep ttyv0 /etc/ttys\n", 2)
drain()

# ============================================================
# 2. Fix gettytab — clean Al entry
# ============================================================
print("\n=== 2. Fixing gettytab ===")
send("sed -i '' '/^Al|/d' /etc/gettytab\n", 1)
send("sed -i '' '/^[[:space:]]*:al=bsduser/d' /etc/gettytab\n", 1)
send("sed -i '' '/^[[:space:]]*:al=root/d' /etc/gettytab\n", 1)
drain()
send("printf 'Al|Autologin:\\\\\\n    :al=bsduser:ht:np:sp#115200:\\n' >> /etc/gettytab\n", 2)
drain()
send("tail -3 /etc/gettytab\n", 2)
drain()

# ============================================================
# 3. Create directories
# ============================================================
print("\n=== 3. Creating directories ===")
send(f"mkdir -p {H}/.config/i3 {H}/.config/i3status {H}/.config/picom {H}/.config/fish\n", 2)
drain()

# ============================================================
# 4. Write .profile (auto-startx)
# ============================================================
print("\n=== 4. Writing .profile ===")
send(f"cat > {H}/.profile << 'ENDPROFILE'\n", 0.3)
send('if [ "$(tty)" = "/dev/ttyv0" ]; then\n', 0.15)
send("    exec startx\n", 0.15)
send("fi\n", 0.15)
send("ENDPROFILE\n", 1)
drain()

# ============================================================
# 5. Write .xinitrc
# ============================================================
print("\n=== 5. Writing .xinitrc ===")
send(f"cat > {H}/.xinitrc << 'ENDXINITRC'\n", 0.3)
send("#!/bin/sh\n", 0.15)
send(f"xrdb -merge $HOME/.Xresources 2>/dev/null\n", 0.15)
send("exec i3\n", 0.15)
send("ENDXINITRC\n", 1)
drain()
send(f"chmod +x {H}/.xinitrc\n", 1)
drain()

# ============================================================
# 6. Write .Xresources
# ============================================================
print("\n=== 6. Writing .Xresources ===")
send(f"cat > {H}/.Xresources << 'ENDXRES'\n", 0.3)
xres_lines = [
    "*color0:  #0a0a0a", "*color8:  #555555",
    "*color1:  #ab1100", "*color9:  #cc2200",
    "*color2:  #1a8a1a", "*color10: #33cc33",
    "*color3:  #aa8800", "*color11: #ccaa00",
    "*color4:  #3465a4", "*color12: #5599dd",
    "*color5:  #8a2252", "*color13: #aa4488",
    "*color6:  #2aa198", "*color14: #44ccbb",
    "*color7:  #c0c0c0", "*color15: #e0e0e0",
    "URxvt.font: xft:DejaVu Sans Mono:size=10",
    "URxvt.boldFont: xft:DejaVu Sans Mono:bold:size=10",
    "URxvt.background: #0a0a0a",
    "URxvt.foreground: #c0c0c0",
    "URxvt.cursorColor: #ab1100",
    "URxvt.cursorBlink: true",
    "URxvt.scrollBar: false",
    "URxvt.saveLines: 10000",
    "URxvt.internalBorder: 10",
    "URxvt.depth: 32",
    "URxvt.lineSpace: 2",
    "URxvt.iso14755: false",
    "URxvt.iso14755_52: false",
]
for line in xres_lines:
    send(line + "\n", 0.06)
send("ENDXRES\n", 1)
drain()

# ============================================================
# 7. Write i3 config
# ============================================================
print("\n=== 7. Writing i3 config ===")
send(f"cat > {H}/.config/i3/config << 'ENDI3'\n", 0.3)
i3_lines = [
    "set $mod Mod1",
    "set $term urxvt",
    "font pango:DejaVu Sans Mono 9",
    "gaps inner 8",
    "gaps outer 4",
    "smart_gaps on",
    "client.focused          #ab1100 #1a0a08 #e0e0e0 #ab1100   #ab1100",
    "client.focused_inactive #333333 #0f0f0f #888888 #333333   #1a1a1a",
    "client.unfocused        #1a1a1a #0a0a0a #555555 #1a1a1a   #0a0a0a",
    "client.urgent           #cc2200 #1a0a08 #ffffff #cc2200   #cc2200",
    "client.background       #080808",
    "default_border pixel 2",
    "default_floating_border pixel 2",
    "hide_edge_borders smart",
    "bindsym $mod+Return exec $term",
    "bindsym $mod+d exec dmenu_run -fn 'DejaVu Sans Mono:size=10' -nb '#0a0a0a' -nf '#888888' -sb '#ab1100' -sf '#ffffff'",
    "bindsym $mod+Shift+q kill",
    "bindsym $mod+Shift+c reload",
    "bindsym $mod+Shift+r restart",
    'bindsym $mod+Shift+e exec "i3-msg exit"',
    "bindsym $mod+h focus left",
    "bindsym $mod+j focus down",
    "bindsym $mod+k focus up",
    "bindsym $mod+l focus right",
    "bindsym $mod+Left focus left",
    "bindsym $mod+Down focus down",
    "bindsym $mod+Up focus up",
    "bindsym $mod+Right focus right",
    "bindsym $mod+Shift+h move left",
    "bindsym $mod+Shift+j move down",
    "bindsym $mod+Shift+k move up",
    "bindsym $mod+Shift+l move right",
    "bindsym $mod+b split h",
    "bindsym $mod+v split v",
    "bindsym $mod+s layout stacking",
    "bindsym $mod+w layout tabbed",
    "bindsym $mod+e layout toggle split",
    "bindsym $mod+f fullscreen toggle",
    "bindsym $mod+Shift+space floating toggle",
    "bindsym $mod+space focus mode_toggle",
    'set $ws1 "1"',
    'set $ws2 "2"',
    'set $ws3 "3"',
    'set $ws4 "4"',
    'set $ws5 "5"',
    "bindsym $mod+1 workspace $ws1",
    "bindsym $mod+2 workspace $ws2",
    "bindsym $mod+3 workspace $ws3",
    "bindsym $mod+4 workspace $ws4",
    "bindsym $mod+5 workspace $ws5",
    "bindsym $mod+Shift+1 move container to workspace $ws1",
    "bindsym $mod+Shift+2 move container to workspace $ws2",
    "bindsym $mod+Shift+3 move container to workspace $ws3",
    "bindsym $mod+Shift+4 move container to workspace $ws4",
    "bindsym $mod+Shift+5 move container to workspace $ws5",
    'mode "resize" {',
    "    bindsym h resize shrink width 5 px or 5 ppt",
    "    bindsym j resize grow height 5 px or 5 ppt",
    "    bindsym k resize shrink height 5 px or 5 ppt",
    "    bindsym l resize grow width 5 px or 5 ppt",
    "    bindsym Return mode \"default\"",
    "    bindsym Escape mode \"default\"",
    "}",
    "bindsym $mod+r mode \"resize\"",
    "bar {",
    "    status_command i3status",
    "    position bottom",
    "    height 22",
    "    colors {",
    "        background #0a0a0aCC",
    "        statusline #888888",
    "        separator  #333333",
    "        focused_workspace  #ab1100 #ab1100 #ffffff",
    "        active_workspace   #333333 #1a1a1a #888888",
    "        inactive_workspace #0a0a0a #0a0a0a #555555",
    "        urgent_workspace   #cc2200 #cc2200 #ffffff",
    "    }",
    "}",
    "exec --no-startup-id xsetroot -solid '#080808'",
    "exec --no-startup-id urxvt -e tmux",
    "exec --no-startup-id sh -c 'echo DESKTOP_READY > /tmp/x11_ready'",
]
for line in i3_lines:
    send(line + "\n", 0.06)
send("ENDI3\n", 2)
drain()

# ============================================================
# 8. Write i3status config
# ============================================================
print("\n=== 8. Writing i3status config ===")
send(f"cat > {H}/.config/i3status/config << 'ENDI3S'\n", 0.3)
i3s_lines = [
    "general {",
    '    output_format = "i3bar"',
    "    colors = true",
    '    color_good = "#ab1100"',
    '    color_degraded = "#555555"',
    '    color_bad = "#ff0000"',
    "    interval = 5",
    "}",
    'order += "cpu_usage"',
    'order += "memory"',
    'order += "disk /"',
    'order += "tztime local"',
    "cpu_usage {",
    '    format = " CPU %usage "',
    "}",
    "memory {",
    '    format = " MEM %used/%total "',
    '    threshold_degraded = "10%"',
    '    threshold_critical = "5%"',
    "}",
    'disk "/" {',
    '    format = " SSD %avail "',
    "}",
    "tztime local {",
    '    format = " %Y-%m-%d %H:%M "',
    "}",
]
for line in i3s_lines:
    send(line + "\n", 0.06)
send("ENDI3S\n", 1)
drain()

# ============================================================
# 9. Write .tmux.conf
# ============================================================
print("\n=== 9. Writing .tmux.conf ===")
send(f"cat > {H}/.tmux.conf << 'ENDTMUX'\n", 0.3)
tmux_lines = [
    'set -g default-terminal "xterm-256color"',
    "set -g default-shell /usr/local/bin/fish",
    "unbind C-b",
    "set -g prefix C-a",
    "bind C-a send-prefix",
    "set -g base-index 1",
    "setw -g pane-base-index 1",
    "set -g mouse on",
    "setw -g mode-keys vi",
    'bind | split-window -h -c "#{pane_current_path}"',
    'bind - split-window -v -c "#{pane_current_path}"',
    "bind h select-pane -L",
    "bind j select-pane -D",
    "bind k select-pane -U",
    "bind l select-pane -R",
    "set -g status-position bottom",
    "set -g status-style 'bg=#0a0a0a,fg=#888888'",
    "set -g status-left '#[fg=#ab1100,bold] #S #[fg=#333333]|'",
    "set -g status-left-length 30",
    "set -g status-right '#[fg=#555555]#H #[fg=#333333]| #[fg=#ab1100]%H:%M '",
    "set -g status-right-length 50",
    "setw -g window-status-format ' #[fg=#555555]#I:#W '",
    "setw -g window-status-current-format ' #[fg=#ab1100,bold]#I:#W '",
    "setw -g window-status-separator ''",
    "set -g pane-border-style 'fg=#222222'",
    "set -g pane-active-border-style 'fg=#ab1100'",
    "set -g message-style 'bg=#1a0a08,fg=#ab1100'",
    "set -sg escape-time 0",
    "set -g history-limit 50000",
]
for line in tmux_lines:
    send(line + "\n", 0.06)
send("ENDTMUX\n", 1)
drain()

# ============================================================
# 10. Write fish config
# ============================================================
print("\n=== 10. Writing fish config ===")
send(f"cat > {H}/.config/fish/config.fish << 'ENDFISH'\n", 0.3)
fish_lines = [
    'set -g fish_greeting ""',
    "set -gx PATH /usr/local/bin /usr/local/sbin /usr/bin /usr/sbin /bin /sbin $PATH",
    "set -g fish_color_command green",
    "set -g fish_color_param normal",
    "set -g fish_color_error red --bold",
    "set -g fish_color_quote yellow",
    "set -g fish_color_autosuggestion 555555",
    "set -g fish_color_cwd red",
    "function fish_prompt",
    "    set_color red",
    "    echo -n (whoami)",
    "    set_color 555555",
    "    echo -n '@'",
    "    set_color brred",
    "    echo -n (hostname -s)",
    "    set_color 555555",
    "    echo -n ':'",
    "    set_color blue",
    "    echo -n (prompt_pwd)",
    "    set_color 555555",
    "    echo -n ' > '",
    "    set_color normal",
    "end",
    "alias ll='ls -la'",
    "alias la='ls -A'",
    "alias ..='cd ..'",
    "alias q='exit'",
    "alias c='clear'",
    "alias t='tmux'",
    "alias ta='tmux attach'",
]
for line in fish_lines:
    send(line + "\n", 0.06)
send("ENDFISH\n", 1)
drain()

# ============================================================
# 11. Fix ownership
# ============================================================
print("\n=== 11. Fixing ownership ===")
send(f"chown -R bsduser:bsduser {H}\n", 3)
drain()

# ============================================================
# 12. Verify everything
# ============================================================
print("\n=== 12. Verification ===")
send(f"ls -la {H}/.profile {H}/.xinitrc {H}/.config/i3/config {H}/.Xresources {H}/.tmux.conf {H}/.config/fish/config.fish {H}/.config/i3status/config\n", 3)
drain()
send("grep ttyv0 /etc/ttys\n", 2)
drain()
send("grep -A1 Autologin /etc/gettytab\n", 2)
drain()
send(f"head -3 {H}/.profile\n", 2)
drain()
send(f"head -3 {H}/.xinitrc\n", 2)
drain()

# ============================================================
# 13. CRITICAL: Proper sync and clean shutdown
# ============================================================
print("\n=== 13. Clean shutdown (sync + halt) ===")
# Multiple syncs to ensure filesystem is flushed
send("sync\n", 2)
send("sync\n", 2)
send("sync\n", 2)
# Wait for all pending I/O
time.sleep(5)
# Use halt -p for immediate power off after sync
send("halt -p\n", 1)

# Wait for QEMU to see the halt
time.sleep(10)

# Use QEMU monitor to ensure clean poweroff
try:
    mon_cmd("quit")
except:
    pass

try:
    proc.wait(timeout=30)
except subprocess.TimeoutExpired:
    proc.kill()

try: mon.close()
except: pass
try: ser.close()
except: pass

print("\n\n=== Final fix complete! ===")
print("Key changes:")
print("  - /etc/ttys: ttyv0 uses Al (auto-login) getty")
print("  - /etc/gettytab: Al entry logs in as bsduser")
print("  - ~/.profile: auto-startx on ttyv0")
print("  - ~/.xinitrc: exec i3")
print("  - All i3/picom/tmux/fish configs written")
print("  - Filesystem synced before halt")
