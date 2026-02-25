#!/usr/bin/env python3
"""Write essential desktop config files to /home/bsduser.
No conditional checks - just write everything unconditionally.
"""

import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")

proc = subprocess.Popen(
    ["qemu-system-i386", "-m", "512",
     "-drive", f"file={IMAGE},format=raw",
     "-display", "none",
     "-serial", "tcp:127.0.0.1:45456,server=on,wait=off",
     "-no-reboot"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
time.sleep(1)

ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
ser.settimeout(1)
ser.connect(("127.0.0.1", 45456))

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

print("Waiting for boot...")
if not wait_for("login:"):
    print("ERROR: No login prompt")
    proc.kill()
    sys.exit(1)

print("\n>>> Logging in...")
send("root\n", 3)
drain()

H = "/home/bsduser"

# Create directories
print("\n=== Creating directories ===")
send(f"mkdir -p {H}/.config/i3 {H}/.config/i3status {H}/.config/picom\n", 2)
drain()

# Write .profile with auto-startx
print(">>> Writing .profile (auto-startx)...")
send(f"cat > {H}/.profile << 'EOF'\n", 0.3)
send('if [ "$(tty)" = "/dev/ttyv0" ]; then\n', 0.2)
send("    exec startx\n", 0.2)
send("fi\n", 0.2)
send("EOF\n", 1)
drain()

# Write .xinitrc
print(">>> Writing .xinitrc...")
send(f"cat > {H}/.xinitrc << 'EOF'\n", 0.3)
send("#!/bin/sh\n", 0.2)
send(f"xrdb -merge {H}/.Xresources 2>/dev/null\n", 0.2)
send("exec i3\n", 0.2)
send("EOF\n", 1)
drain()
send(f"chmod +x {H}/.xinitrc\n", 1)
drain()

# Write .Xresources
print(">>> Writing .Xresources...")
send(f"cat > {H}/.Xresources << 'EOF'\n", 0.3)
xres = """*color0:  #0a0a0a
*color8:  #555555
*color1:  #ab1100
*color9:  #cc2200
*color2:  #1a8a1a
*color10: #33cc33
*color3:  #aa8800
*color11: #ccaa00
*color4:  #3465a4
*color12: #5599dd
*color5:  #8a2252
*color13: #aa4488
*color6:  #2aa198
*color14: #44ccbb
*color7:  #c0c0c0
*color15: #e0e0e0
URxvt.font: xft:DejaVu Sans Mono:size=10
URxvt.boldFont: xft:DejaVu Sans Mono:bold:size=10
URxvt.background: #0a0a0a
URxvt.foreground: #c0c0c0
URxvt.cursorColor: #ab1100
URxvt.cursorBlink: true
URxvt.scrollBar: false
URxvt.saveLines: 10000
URxvt.internalBorder: 10
URxvt.depth: 32
URxvt.lineSpace: 2
URxvt.iso14755: false
URxvt.iso14755_52: false"""
for line in xres.strip().split("\n"):
    send(line + "\n", 0.08)
send("EOF\n", 1)
drain()

# Write i3 config
print(">>> Writing i3 config...")
send(f"cat > {H}/.config/i3/config << 'I3EOF'\n", 0.3)
i3 = """set $mod Mod1
set $term urxvt
font pango:DejaVu Sans Mono 9
gaps inner 8
gaps outer 4
smart_gaps on
client.focused          #ab1100 #1a0a08 #e0e0e0 #ab1100   #ab1100
client.focused_inactive #333333 #0f0f0f #888888 #333333   #1a1a1a
client.unfocused        #1a1a1a #0a0a0a #555555 #1a1a1a   #0a0a0a
client.urgent           #cc2200 #1a0a08 #ffffff #cc2200   #cc2200
client.background       #080808
default_border pixel 2
default_floating_border pixel 2
hide_edge_borders smart
bindsym $mod+Return exec $term
bindsym $mod+d exec dmenu_run -fn 'DejaVu Sans Mono:size=10' -nb '#0a0a0a' -nf '#888888' -sb '#ab1100' -sf '#ffffff'
bindsym $mod+Shift+q kill
bindsym $mod+Shift+c reload
bindsym $mod+Shift+r restart
bindsym $mod+Shift+e exec "i3-msg exit"
bindsym $mod+h focus left
bindsym $mod+j focus down
bindsym $mod+k focus up
bindsym $mod+l focus right
bindsym $mod+Left focus left
bindsym $mod+Down focus down
bindsym $mod+Up focus up
bindsym $mod+Right focus right
bindsym $mod+Shift+h move left
bindsym $mod+Shift+j move down
bindsym $mod+Shift+k move up
bindsym $mod+Shift+l move right
bindsym $mod+b split h
bindsym $mod+v split v
bindsym $mod+s layout stacking
bindsym $mod+w layout tabbed
bindsym $mod+e layout toggle split
bindsym $mod+f fullscreen toggle
bindsym $mod+Shift+space floating toggle
bindsym $mod+space focus mode_toggle
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
mode "resize" {
    bindsym h resize shrink width 5 px or 5 ppt
    bindsym j resize grow height 5 px or 5 ppt
    bindsym k resize shrink height 5 px or 5 ppt
    bindsym l resize grow width 5 px or 5 ppt
    bindsym Return mode "default"
    bindsym Escape mode "default"
}
bindsym $mod+r mode "resize"
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
exec --no-startup-id xsetroot -solid '#080808'
exec --no-startup-id urxvt -e tmux
exec --no-startup-id sh -c 'echo DESKTOP_READY > /tmp/x11_ready'"""
for line in i3.strip().split("\n"):
    send(line + "\n", 0.08)
send("I3EOF\n", 2)
drain()

# Write i3status config
print(">>> Writing i3status config...")
send(f"cat > {H}/.config/i3status/config << 'EOF'\n", 0.3)
i3s = """general {
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
for line in i3s.strip().split("\n"):
    send(line + "\n", 0.08)
send("EOF\n", 1)
drain()

# Write .tmux.conf
print(">>> Writing .tmux.conf...")
send(f"cat > {H}/.tmux.conf << 'EOF'\n", 0.3)
tmux = """set -g default-terminal "xterm-256color"
set -g default-shell /usr/local/bin/fish
unbind C-b
set -g prefix C-a
bind C-a send-prefix
set -g base-index 1
setw -g pane-base-index 1
set -g mouse on
setw -g mode-keys vi
bind | split-window -h -c "#{pane_current_path}"
bind - split-window -v -c "#{pane_current_path}"
bind h select-pane -L
bind j select-pane -D
bind k select-pane -U
bind l select-pane -R
set -g status-position bottom
set -g status-style 'bg=#0a0a0a,fg=#888888'
set -g status-left '#[fg=#ab1100,bold] #S #[fg=#333333]|'
set -g status-left-length 30
set -g status-right '#[fg=#555555]#H #[fg=#333333]| #[fg=#ab1100]%H:%M '
set -g status-right-length 50
setw -g window-status-format ' #[fg=#555555]#I:#W '
setw -g window-status-current-format ' #[fg=#ab1100,bold]#I:#W '
setw -g window-status-separator ''
set -g pane-border-style 'fg=#222222'
set -g pane-active-border-style 'fg=#ab1100'
set -g message-style 'bg=#1a0a08,fg=#ab1100'
set -sg escape-time 0
set -g history-limit 50000"""
for line in tmux.strip().split("\n"):
    send(line + "\n", 0.08)
send("EOF\n", 1)
drain()

# Fix ownership
print(">>> Fixing ownership...")
send(f"chown -R bsduser:bsduser {H}\n", 3)
drain()

# Verify
print("\n=== Verification ===")
send(f"echo '=== .profile ===' && cat {H}/.profile\n", 2)
drain()
send(f"echo '=== .xinitrc ===' && cat {H}/.xinitrc\n", 2)
drain()
send(f"echo '=== i3 head ===' && head -5 {H}/.config/i3/config\n", 2)
drain()
send(f"ls -la {H}/.profile {H}/.xinitrc {H}/.config/i3/config {H}/.Xresources {H}/.tmux.conf\n", 2)
drain()

# Shutdown
print("\n=== Shutting down ===")
send("sync\n", 1)
send("shutdown -p now\n", 5)

try:
    proc.wait(timeout=60)
except subprocess.TimeoutExpired:
    proc.kill()

ser.close()
print("\n=== Config fix complete! ===")
