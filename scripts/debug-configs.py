#!/usr/bin/env python3
"""Debug: dump actual i3 config, .xinitrc, .Xresources, and check files."""

import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")

SERIAL_PORT = 45462
MONITOR_PORT = 45463
HOME = "/home/bsduser"

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

def dump_between(label, start_marker, end_marker):
    global serial_buf
    decoded = serial_buf.decode(errors="replace")
    s = decoded.find(start_marker)
    e = decoded.find(end_marker)
    if s >= 0 and e >= 0:
        content = decoded[s+len(start_marker):e]
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}")
        for line in content.strip().split("\n"):
            print(f"  {line.rstrip()}")
        return content
    else:
        print(f"\n  {label}: COULD NOT READ")
        return ""

print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR: No login prompt!")
    proc.kill()
    sys.exit(1)

time.sleep(1)
send("root\n", 3)
drain()
send("/bin/sh\n", 1)
drain()
send("service cron stop >/dev/null 2>&1\n", 1)
send("killall dhclient 2>/dev/null\n", 1)

# Dump i3 config
serial_buf = b""
send(f"echo '---I3_START---' && cat {HOME}/.config/i3/config && echo '---I3_END---'\n", 5)
time.sleep(3)
drain()
dump_between("I3 CONFIG", "---I3_START---", "---I3_END---")

# Dump .xinitrc
serial_buf = b""
send(f"echo '---XINITRC_START---' && cat {HOME}/.xinitrc && echo '---XINITRC_END---'\n", 3)
time.sleep(2)
drain()
dump_between(".xinitrc", "---XINITRC_START---", "---XINITRC_END---")

# Dump .Xresources
serial_buf = b""
send(f"echo '---XRES_START---' && cat {HOME}/.Xresources && echo '---XRES_END---'\n", 3)
time.sleep(2)
drain()
dump_between(".Xresources", "---XRES_START---", "---XRES_END---")

# Check golden-3term.sh
serial_buf = b""
send(f"echo '---G3_START---' && cat {HOME}/.config/i3/golden-3term.sh && echo '---G3_END---'\n", 3)
time.sleep(2)
drain()
dump_between("golden-3term.sh", "---G3_START---", "---G3_END---")

# Check status.sh
serial_buf = b""
send(f"echo '---ST_START---' && cat {HOME}/.config/i3/status.sh 2>&1 | head -5 && echo '---ST_END---'\n", 3)
time.sleep(2)
drain()
dump_between("status.sh (first 5 lines)", "---ST_START---", "---ST_END---")

# Check wallpaper file
serial_buf = b""
send("echo '---CHK_START---'\n", 0.3)
send("ls -la /usr/local/share/wallpapers/ 2>&1\n", 1)
send(f"ls -la {HOME}/.config/i3/golden-3term.sh 2>&1\n", 1)
send(f"ls -la {HOME}/.config/i3/status.sh 2>&1\n", 1)
send("fc-list | grep -i jetbrains | head -2 2>&1\n", 2)
send(f"ls -la {HOME}/.local/share/omf/init.fish 2>&1\n", 1)
send(f"fish -c 'omf list' 2>&1\n", 2)
send("echo '---CHK_END---'\n", 2)
time.sleep(3)
drain()
dump_between("FILE CHECKS", "---CHK_START---", "---CHK_END---")

# Check X11 xorg configs
serial_buf = b""
send("echo '---X11_START---'\n", 0.3)
send("cat /usr/local/etc/X11/xorg.conf.d/10-vesa.conf 2>&1\n", 2)
send("echo '---X11_END---'\n", 2)
time.sleep(2)
drain()
dump_between("10-vesa.conf", "---X11_START---", "---X11_END---")

# Xorg log for resolution
serial_buf = b""
send("echo '---XLOG_START---'\n", 0.3)
send("grep -E '(Virtual size|Setting mode|modeline|---)' /var/log/Xorg.0.log 2>&1 | tail -20\n", 2)
send("echo '---XLOG_END---'\n", 2)
time.sleep(2)
drain()
dump_between("Xorg.log resolution info", "---XLOG_START---", "---XLOG_END---")

# Shutdown
send("sync\n", 2)
send("shutdown -p now\n", 5)
try:
    proc.wait(timeout=60)
except subprocess.TimeoutExpired:
    proc.kill()

mon.close()
ser.close()
print("\n\nDone.")
