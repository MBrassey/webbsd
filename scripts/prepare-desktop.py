#!/usr/bin/env python3
"""Prepare FreeBSD image for X11 desktop.

Uses echo-per-line file writing (NOT heredocs) to avoid serial issues.
Heredocs over serial are unreliable because end markers can be missed.
"""

import subprocess, time, sys, os, socket, random

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")

SERIAL_PORT = 45456
MONITOR_PORT = 45455
H = "/home/bsduser"
U = "bsduser"


class QEMU:
    def __init__(self):
        self.proc = subprocess.Popen([
            "qemu-system-i386", "-m", "512",
            "-drive", f"file={IMAGE},format=raw,cache=writethrough",
            "-display", "none",
            "-serial", f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off",
            "-monitor", f"tcp:127.0.0.1:{MONITOR_PORT},server=on,wait=off",
            "-no-reboot",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        self.ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ser.settimeout(1)
        self.ser.connect(("127.0.0.1", SERIAL_PORT))
        self.mon = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.mon.settimeout(5)
        self.mon.connect(("127.0.0.1", MONITOR_PORT))
        time.sleep(0.5)
        try: self.mon.recv(4096)
        except: pass
        self.buf = b""

    def drain(self):
        while True:
            try:
                data = self.ser.recv(4096)
                if not data: break
                self.buf += data
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            except: break

    def wait_for(self, pattern, timeout=300):
        start = time.time()
        while time.time() - start < timeout:
            self.drain()
            if pattern.encode() in self.buf:
                return True
            time.sleep(0.3)
        return False

    def send(self, text, delay=0.5):
        self.ser.send(text.encode())
        time.sleep(delay)

    def cmd(self, text, delay=1.5):
        """Send a single-line command and wait."""
        self.ser.send((text + "\n").encode())
        time.sleep(delay)
        self.drain()

    def write_file_echo(self, path, content):
        """Write file using echo commands — ONE LINE AT A TIME.

        This is much more reliable than heredocs over serial.
        Each echo is a complete, self-contained command.
        """
        lines = content.rstrip("\n").split("\n")

        # First line: overwrite (>)
        first = lines[0].replace("'", "'\\''")  # Escape single quotes
        self.cmd(f"echo '{first}' > {path}", 0.3)

        # Remaining lines: append (>>)
        for line in lines[1:]:
            escaped = line.replace("'", "'\\''")
            self.cmd(f"echo '{escaped}' >> {path}", 0.3)

        # Small delay for filesystem
        time.sleep(0.5)
        self.drain()

    def verify_file(self, path, expected_substr):
        """Check that a file contains expected content."""
        self.buf = b""
        self.cmd(f"cat {path}", 2)
        output = self.buf.decode(errors='replace')
        if expected_substr in output:
            return True
        return False

    def mon_cmd(self, cmd, delay=0.5):
        self.mon.send((cmd + "\r\n").encode())
        time.sleep(delay)
        try: return self.mon.recv(8192).decode(errors='replace')
        except: return ""

    def shutdown(self):
        """Clean shutdown: sync, remount ro, halt, QEMU quit."""
        print("\n=== Shutdown ===")
        self.cmd("sync", 2)
        self.cmd("sync", 2)
        self.cmd("sync", 2)
        time.sleep(10)
        self.cmd("/sbin/mount -f -u -o ro / 2>/dev/null", 3)
        self.send("/sbin/halt -p\n", 1)
        time.sleep(15)
        try: self.mon_cmd("quit")
        except: pass
        try: self.proc.wait(timeout=30)
        except: self.proc.kill()
        try: self.ser.close()
        except: pass
        try: self.mon.close()
        except: pass


# ══════════════════════════════════════════════════════════════════
# PHASE 1: Write all configs
# ══════════════════════════════════════════════════════════════════
print("=" * 60)
print("PHASE 1: Writing configs (echo-per-line method)")
print("=" * 60)

q = QEMU()

print("Waiting for boot...")
if not q.wait_for("login:", timeout=300):
    print("ERROR: No login prompt")
    q.proc.kill()
    sys.exit(1)

print(">>> Logging in...")
q.send("root\n", 5)
q.drain()

# Kill background noise
q.cmd("service cron stop 2>/dev/null")
q.cmd("pkill -9 dhclient 2>/dev/null")
q.cmd("rm -f /var/cron/tabs/root 2>/dev/null")

# Remount with sync for metadata safety
q.cmd("/sbin/mount -u -o sync / 2>/dev/null")

# ── 1. Fix bsduser shell ──
print("\n>>> 1. Shell → /bin/sh")
q.cmd("chsh -s /bin/sh bsduser")

# ── 2. Empty password ──
print(">>> 2. Empty password")
q.cmd("pw mod user bsduser -w none")
q.cmd("sed -i '' 's/^bsduser:\\*:/bsduser::/' /etc/master.passwd")
q.cmd("pwd_mkdb -p /etc/master.passwd", 3)

# ── 3. Gettytab ──
print(">>> 3. Gettytab Al")
q.cmd("sed -i '' '/^Al|/d' /etc/gettytab")
q.cmd("sed -i '' '/^[[:space:]]*:al=bsduser/d' /etc/gettytab")
q.cmd("sed -i '' '/^Autologin/d' /etc/gettytab")
q.cmd(r"printf 'Al|Autologin:\\\n    :al=bsduser:ht:np:sp#115200:\n' >> /etc/gettytab", 2)

# ── 4. ttys ──
print(">>> 4. ttys ttyv0 Al")
q.cmd("sed -i '' '/^ttyv0/d' /etc/ttys")
q.cmd(r"printf 'ttyv0\t\"/usr/libexec/getty Al\"\txterm\ton\tsecure\n' >> /etc/ttys", 2)

# ── 5. Directories ──
print(">>> 5. Directories")
q.cmd(f"mkdir -p {H}/.config/i3 {H}/.config/i3status {H}/.config/picom {H}/.config/fish/functions")

# ── 6. Config files (echo method) ──
print(">>> 6. Writing config files...")

# .profile
print("  .profile")
q.write_file_echo(f"{H}/.profile", """# Auto-start X if on console ttyv0
if [ "$(tty)" = "/dev/ttyv0" ]; then
    exec startx
fi""")

# .login (csh backup)
print("  .login")
q.write_file_echo(f"{H}/.login", """# Auto-start X if on console ttyv0
if ( `tty` == /dev/ttyv0 ) then
    exec startx
endif""")

# .xinitrc
print("  .xinitrc")
q.write_file_echo(f"{H}/.xinitrc", """#!/bin/sh
xrdb -merge $HOME/.Xresources 2>/dev/null
exec i3""")
q.cmd(f"chmod +x {H}/.xinitrc")

# i3 config
print("  i3/config")
q.write_file_echo(f"{H}/.config/i3/config", """set $mod Mod1
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
    status_command ~/.config/i3/status.sh
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
exec --no-startup-id sh -c 'echo DESKTOP_READY > /tmp/x11_ready'""")

# i3status config
print("  i3status/config")
q.write_file_echo(f"{H}/.config/i3status/config", """general {
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
}""")

# i3 status bar script (FreeBSD-native, outputs i3bar JSON with Unicode bar charts)
print("  i3/status.sh")
q.write_file_echo(f"{H}/.config/i3/status.sh", """#!/bin/sh
# i3bar status script for FreeBSD - uses sysctl, no /proc
# Outputs i3bar JSON protocol

# Build a Unicode block bar: filled blocks + empty blocks
# $1 = percent (0-100), $2 = width in chars (default 8)
bar() {
    pct=$1
    width=${2:-8}
    filled=$(( pct * width / 100 ))
    empty=$(( width - filled ))
    result=""
    i=0
    while [ $i -lt $filled ]; do
        result="${result}\u2588"
        i=$(( i + 1 ))
    done
    i=0
    while [ $i -lt $empty ]; do
        result="${result}\u2591"
        i=$(( i + 1 ))
    done
    printf '%b' "$result"
}

# CPU usage: diff kern.cp_time over 0.8s sample
# Fields from sysctl: user nice sys intr idle
cpu_percent() {
    r1=$(sysctl -n kern.cp_time)
    sleep 0.8
    r2=$(sysctl -n kern.cp_time)
    u1=$(echo $r1 | awk '{print $1}')
    s1=$(echo $r1 | awk '{print $3}')
    i1=$(echo $r1 | awk '{print $4}')
    d1=$(echo $r1 | awk '{print $5}')
    u2=$(echo $r2 | awk '{print $1}')
    s2=$(echo $r2 | awk '{print $3}')
    i2=$(echo $r2 | awk '{print $4}')
    d2=$(echo $r2 | awk '{print $5}')
    n1=$(echo $r1 | awk '{print $2}')
    n2=$(echo $r2 | awk '{print $2}')
    tot=$(( (u2-u1)+(n2-n1)+(s2-s1)+(i2-i1)+(d2-d1) ))
    idle=$(( d2 - d1 ))
    if [ "$tot" -eq 0 ]; then echo 0; return; fi
    echo $(( (tot - idle) * 100 / tot ))
}

# Memory usage percent: (total - avail) / total * 100
# avail = free + inactive + cache pages
mem_percent() {
    total=$(sysctl -n vm.stats.vm.v_page_count)
    free=$(sysctl -n vm.stats.vm.v_free_count)
    inactive=$(sysctl -n vm.stats.vm.v_inactive_count)
    cache=$(sysctl -n vm.stats.vm.v_cache_count)
    avail=$(( free + inactive + cache ))
    used=$(( total - avail ))
    echo $(( used * 100 / total ))
}

# Escape text for JSON string value
json_esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

# i3bar protocol header
printf '{"version":1}\n[\n'

SEP='{"full_text":"  ","color":"#333333","separator":false,"separator_block_width":0}'

while true; do
    cpu=$(cpu_percent)
    mem=$(mem_percent)
    dt=$(date '+%Y-%m-%d %H:%M')

    cpu_bar=$(bar "$cpu" 8)
    mem_bar=$(bar "$mem" 8)

    if [ "$cpu" -ge 85 ]; then cc="#ff3333"
    elif [ "$cpu" -ge 60 ]; then cc="#ccaa00"
    else cc="#ab1100"; fi

    if [ "$mem" -ge 90 ]; then mc="#ff3333"
    elif [ "$mem" -ge 70 ]; then mc="#ccaa00"
    else mc="#ab1100"; fi

    cpu_text=$(json_esc " CPU $cpu_bar ${cpu}%")
    mem_text=$(json_esc " MEM $mem_bar ${mem}%")
    dt_text=$(json_esc "  $dt ")

    printf '[{"full_text":"%s","color":"%s","separator":false},%s,{"full_text":"%s","color":"%s","separator":false},%s,{"full_text":"%s","color":"#555555"}],\n' \
        "$cpu_text" "$cc" \
        "$SEP" \
        "$mem_text" "$mc" \
        "$SEP" \
        "$dt_text"

    sleep 1
done""")
q.cmd(f"chmod +x {H}/.config/i3/status.sh")

# .Xresources
print("  .Xresources")
q.write_file_echo(f"{H}/.Xresources", """*color0:  #0a0a0a
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
URxvt.iso14755_52: false
XTerm*background: #0a0a0a
XTerm*foreground: #c0c0c0
XTerm*cursorColor: #ab1100
XTerm*faceName: DejaVu Sans Mono
XTerm*faceSize: 11
XTerm*scrollBar: false""")

# picom config
print("  picom.conf")
q.write_file_echo(f"{H}/.config/picom/picom.conf", """backend = "xrender";
active-opacity = 1.0;
inactive-opacity = 0.90;
frame-opacity = 0.85;
fading = true;
fade-in-step = 0.06;
fade-out-step = 0.06;
shadow = true;
shadow-radius = 12;
shadow-offset-x = -7;
shadow-offset-y = -7;
shadow-opacity = 0.6;
shadow-color = "#000000";
vsync = false;
use-damage = true;""")

# .tmux.conf
print("  .tmux.conf")
q.write_file_echo(f"{H}/.tmux.conf", """set -g default-terminal "xterm-256color"
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
set -g history-limit 50000""")

# fish config
print("  fish/config.fish")
q.write_file_echo(f"{H}/.config/fish/config.fish", """set -g fish_greeting ""
set -gx PATH /usr/local/bin /usr/local/sbin /usr/bin /usr/sbin /bin /sbin $PATH
set -g fish_color_command green
set -g fish_color_param normal
set -g fish_color_error red --bold
set -g fish_color_quote yellow
set -g fish_color_autosuggestion 555555
set -g fish_color_cwd red
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
alias ll='ls -la'
alias la='ls -A'
alias ..='cd ..'
alias q='exit'
alias c='clear'
alias t='tmux'
alias ta='tmux attach'""")

# ── 7. Fix ownership ──
print("\n>>> 7. Ownership")
q.cmd(f"chown -R {U}:{U} {H}", 3)

# ── 8. Verify key files ──
print("\n>>> 8. Verification")
for path, check in [
    (f"{H}/.profile", "exec startx"),
    (f"{H}/.xinitrc", "exec i3"),
    (f"{H}/.config/i3/config", "set $mod"),
    (f"{H}/.Xresources", "color0"),
    (f"{H}/.tmux.conf", "default-terminal"),
]:
    if q.verify_file(path, check):
        print(f"  OK: {path}")
    else:
        print(f"  BAD: {path}")

# ── 9. Shutdown ──
q.shutdown()
print(">>> Phase 1 complete")

# ══════════════════════════════════════════════════════════════════
# PHASE 2: Verification boot
# ══════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("PHASE 2: Verification boot")
print("=" * 60)

q2 = QEMU()
print("Waiting for boot...")
if not q2.wait_for("login:", timeout=300):
    print("ERROR: No login prompt")
    q2.proc.kill()
    sys.exit(1)

print(">>> Logging in...")
q2.send("root\n", 8)
q2.drain()

# Kill noise
q2.cmd("pkill -9 dhclient 2>/dev/null")

ok = True
def check(name, cmd, expected):
    global ok
    q2.buf = b""
    q2.cmd(cmd, 3)
    output = q2.buf.decode(errors='replace')
    if expected in output:
        print(f"  PASS: {name}")
    else:
        print(f"  FAIL: {name}")
        ok = False

print("\nPersistence checks:")
check("shell", f"awk -F: '/{U}/{{print $7}}' /etc/passwd", "/bin/sh")
check(".profile", f"grep startx {H}/.profile", "exec startx")
check(".xinitrc", f"grep i3 {H}/.xinitrc", "exec i3")
check("i3 config", f"head -1 {H}/.config/i3/config", "set $mod")
check("ttys", "grep ttyv0 /etc/ttys", "Al")
check("gettytab", "grep Autologin /etc/gettytab", "Autologin")
check("Xorg VESA", "ls /usr/local/etc/X11/xorg.conf.d/10-vesa.conf", "10-vesa")
check("i3status", f"head -1 {H}/.config/i3status/config", "general")
check(".Xresources", f"head -1 {H}/.Xresources", "color0")
check(".tmux.conf", f"head -1 {H}/.tmux.conf", "default-terminal")

if ok:
    print("\n>>> ALL CHECKS PASSED!")
else:
    print("\n>>> SOME CHECKS FAILED")

q2.shutdown()
print("\n=== prepare-desktop.py complete ===")
sys.exit(0 if ok else 1)
