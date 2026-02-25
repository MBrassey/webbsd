#!/usr/bin/env python3
"""Fix desktop: copy configs from /root to /home/bsduser, fix auto-login/startx.

The first install wrote all configs to /root. The second install tried to write
to /home/bsduser but many writes failed due to serial timeouts. This script
copies configs from /root, fixes gettytab, and adds fish auto-startx.
"""

import subprocess
import time
import sys
import os
import socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")

SERIAL_PORT = 45456
MONITOR_PORT = 45455

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

def send_cmd(cmd, timeout=30):
    """Send command, wait for prompt (# ) to return."""
    global serial_buf
    serial_buf = b""
    send(cmd + "\n", 0.3)
    start = time.time()
    while time.time() - start < timeout:
        drain()
        # Look for shell prompt after command output
        if b"# " in serial_buf and serial_buf.rstrip().endswith(b"#"):
            drain()
            return True
        time.sleep(0.3)
    drain()
    return False


print("=== Fixing desktop configuration ===")
print("Waiting for boot...")

if not wait_for("login:", timeout=300):
    print("ERROR: No login prompt")
    proc.kill()
    sys.exit(1)

print("\n>>> Logging in as root...")
send("root\n", 3)
drain()

# Kill cron to stop dhclient noise immediately
send("crontab -u root -r 2>/dev/null; true\n", 2)
send("pkill -f 'dhclient ed0' 2>/dev/null; true\n", 2)
drain()

# 1. Check what exists in /root vs /home/bsduser
print("\n=== Checking existing configs ===")
send("ls /root/.xinitrc /root/.config/i3/config 2>&1\n", 2)
drain()
send("ls /home/bsduser/.xinitrc /home/bsduser/.config/i3/config 2>&1\n", 2)
drain()

# 2. Copy all configs from /root to /home/bsduser
print("\n=== Copying configs from /root to /home/bsduser ===")
send("cp -a /root/.config /home/bsduser/ 2>/dev/null\n", 2)
drain()
send("cp -a /root/.xinitrc /home/bsduser/ 2>/dev/null\n", 1)
drain()
send("cp -a /root/.Xresources /home/bsduser/ 2>/dev/null\n", 1)
drain()
send("cp -a /root/.tmux.conf /home/bsduser/ 2>/dev/null\n", 1)
drain()
send("cp -a /root/.profile /home/bsduser/ 2>/dev/null\n", 1)
drain()
send("cp -a /root/.login /home/bsduser/ 2>/dev/null\n", 1)
drain()

# 3. If /root/.xinitrc doesn't exist, create it
print("\n=== Ensuring .xinitrc exists ===")
send("test -f /home/bsduser/.xinitrc || echo 'NEED_XINITRC'\n", 2)
drain()
if b"NEED_XINITRC" in serial_buf:
    print(">>> Creating .xinitrc...")
    send("mkdir -p /home/bsduser/.config/i3\n", 1)
    send("mkdir -p /home/bsduser/.config/i3status\n", 1)
    send("mkdir -p /home/bsduser/.config/picom\n", 1)
    drain()

    # Write minimal .xinitrc
    send("cat > /home/bsduser/.xinitrc << 'EOF'\n", 0.3)
    send("#!/bin/sh\n", 0.2)
    send("xrdb -merge /home/bsduser/.Xresources 2>/dev/null\n", 0.2)
    send("exec i3\n", 0.2)
    send("EOF\n", 1)
    drain()
    send("chmod +x /home/bsduser/.xinitrc\n", 1)
    drain()

# 4. Ensure i3 config exists (minimal if needed)
print("\n=== Ensuring i3 config exists ===")
send("test -f /home/bsduser/.config/i3/config || echo 'NEED_I3'\n", 2)
drain()
if b"NEED_I3" in serial_buf:
    print(">>> Writing i3 config...")
    serial_buf = b""
    send("cat > /home/bsduser/.config/i3/config << 'I3EOF'\n", 0.3)
    i3_lines = """# webBSD i3 config
set $mod Mod1
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
exec --no-startup-id sh -c 'echo DESKTOP_READY > /tmp/x11_ready'
"""
    for line in i3_lines.strip().split("\n"):
        send(line + "\n", 0.08)
    send("I3EOF\n", 2)
    drain()

# 5. Fix gettytab — clean and rewrite
print("\n=== Fixing gettytab ===")
send("sed -i '' '/^Al|Autologin/d' /etc/gettytab\n", 1)
send("sed -i '' '/^[[:space:]]*:al=/d' /etc/gettytab\n", 1)
drain()
# Use printf for proper backslash handling
send("printf 'Al|Autologin:\\\\\\n    :al=bsduser:ht:np:sp#115200:\\n' >> /etc/gettytab\n", 2)
drain()
# Verify
send("grep -A1 'Autologin' /etc/gettytab\n", 2)
drain()

# 6. Ensure ttys has correct auto-login entry
print("\n=== Fixing ttys ===")
send("sed -i '' '/^ttyv0/d' /etc/ttys\n", 1)
send("printf 'ttyv0\\t\"/usr/libexec/getty Al\"\\txterm\\ton\\tsecure\\n' >> /etc/ttys\n", 2)
drain()
send("grep ttyv0 /etc/ttys\n", 2)
drain()

# 7. Add auto-startx to fish config
print("\n=== Adding auto-startx to fish config ===")
send("mkdir -p /home/bsduser/.config/fish\n", 1)
drain()
# Check if already has startx
send("grep -q startx /home/bsduser/.config/fish/config.fish 2>/dev/null || echo 'NEED_STARTX'\n", 2)
drain()
if b"NEED_STARTX" in serial_buf:
    serial_buf = b""
    send("cat >> /home/bsduser/.config/fish/config.fish << 'FISHEOF'\n", 0.3)
    send("\n", 0.1)
    send("# Auto-start X if on console ttyv0\n", 0.2)
    send("if status is-login; and test (tty) = /dev/ttyv0\n", 0.2)
    send("    exec startx\n", 0.2)
    send("end\n", 0.2)
    send("FISHEOF\n", 1)
    drain()
    print(">>> Added startx to fish config")

# 8. Also ensure .profile has startx (fallback for sh)
send("test -f /home/bsduser/.profile || echo 'NEED_PROFILE'\n", 2)
drain()
if b"NEED_PROFILE" in serial_buf:
    serial_buf = b""
    send("cat > /home/bsduser/.profile << 'PEOF'\n", 0.3)
    send('if [ "$(tty)" = "/dev/ttyv0" ]; then\n', 0.2)
    send("    exec startx\n", 0.2)
    send("fi\n", 0.2)
    send("PEOF\n", 1)
    drain()

# 9. Ensure .Xresources exists (minimal)
send("test -f /home/bsduser/.Xresources || echo 'NEED_XRES'\n", 2)
drain()
if b"NEED_XRES" in serial_buf:
    serial_buf = b""
    send("cat > /home/bsduser/.Xresources << 'XEOF'\n", 0.3)
    send("URxvt.background: #0a0a0a\n", 0.1)
    send("URxvt.foreground: #c0c0c0\n", 0.1)
    send("URxvt.cursorColor: #ab1100\n", 0.1)
    send("URxvt.scrollBar: false\n", 0.1)
    send("URxvt.font: xft:DejaVu Sans Mono:size=10\n", 0.1)
    send("URxvt.internalBorder: 8\n", 0.1)
    send("URxvt.saveLines: 10000\n", 0.1)
    send("XEOF\n", 1)
    drain()

# 10. Fix ownership
print("\n=== Fixing ownership ===")
send("chown -R bsduser:bsduser /home/bsduser\n", 3)
drain()

# 11. Fix bsduser password — ensure empty (no password required)
print("\n=== Fixing password ===")
send("pw mod user bsduser -w none\n", 2)
drain()
# Verify
send("grep bsduser /etc/master.passwd | head -1\n", 2)
drain()

# 12. Verify everything
print("\n=== Final verification ===")
send("echo '--- .xinitrc ---' && cat /home/bsduser/.xinitrc\n", 2)
drain()
send("echo '--- i3 config head ---' && head -3 /home/bsduser/.config/i3/config\n", 2)
drain()
send("echo '--- fish startx ---' && grep startx /home/bsduser/.config/fish/config.fish\n", 2)
drain()
send("echo '--- gettytab ---' && grep -A1 Autologin /etc/gettytab\n", 2)
drain()
send("echo '--- ttys ---' && grep ttyv0 /etc/ttys\n", 2)
drain()
send("df -h /\n", 2)
drain()

# Shutdown
print("\n=== Shutting down ===")
send("sync\n", 1)
send("/sbin/shutdown -p now\n", 5)

try:
    proc.wait(timeout=60)
except subprocess.TimeoutExpired:
    proc.kill()

ser.close()
print("\n\n=== Desktop fix complete! ===")
