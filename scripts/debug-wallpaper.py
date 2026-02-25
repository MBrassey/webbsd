#!/usr/bin/env python3
"""Debug wallpaper: check file structure, test feh, check cycle script."""

import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")

SERIAL_PORT = 45472
MONITOR_PORT = 45473
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

def dump(label):
    global serial_buf
    time.sleep(2)
    drain()
    decoded = serial_buf.decode(errors="replace")
    vs = decoded.rfind(f"---{label}_S---")
    ve = decoded.rfind(f"---{label}_E---")
    if vs >= 0 and ve >= 0:
        content = decoded[vs+len(f"---{label}_S---"):ve]
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}")
        for line in content.strip().split("\n"):
            print(f"  {line.rstrip()}")
        return content
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

# 1. Check wallpaper directory structure
serial_buf = b""
send("echo '---DIR_S---'\n", 0.3)
send("ls -la /usr/local/share/wallpapers/freebsd-wallpapers/ 2>&1\n", 2)
send("echo '---DIR_E---'\n", 1)
dump("DIR")

# 2. Check for image files recursively
serial_buf = b""
send("echo '---FILES_S---'\n", 0.3)
send("find /usr/local/share/wallpapers/freebsd-wallpapers -type f 2>&1 | head -30\n", 3)
send("echo '---FILES_E---'\n", 1)
dump("FILES")

# 3. Check file extensions
serial_buf = b""
send("echo '---EXT_S---'\n", 0.3)
send("find /usr/local/share/wallpapers/freebsd-wallpapers -type f | sed 's/.*\\.//' | sort | uniq -c | sort -rn 2>&1\n", 3)
send("echo '---EXT_E---'\n", 1)
dump("EXT")

# 4. Check if feh is installed and works
serial_buf = b""
send("echo '---FEH_S---'\n", 0.3)
send("which feh 2>&1\n", 1)
send("feh --version 2>&1 | head -2\n", 1)
send("echo '---FEH_E---'\n", 1)
dump("FEH")

# 5. Check if sort -R works on FreeBSD
serial_buf = b""
send("echo '---SORT_S---'\n", 0.3)
send("echo -e 'a\\nb\\nc' | sort -R 2>&1 | head -3\n", 1)
send("echo '---SORT_E---'\n", 1)
dump("SORT")

# 6. Check wallpaper-cycle.sh content
serial_buf = b""
send("echo '---CYCLE_S---'\n", 0.3)
send(f"cat {HOME}/.config/i3/wallpaper-cycle.sh 2>&1\n", 2)
send("echo '---CYCLE_E---'\n", 1)
dump("CYCLE")

# 7. Try running the find command from cycle script manually
serial_buf = b""
send("echo '---FIND_S---'\n", 0.3)
send("find /usr/local/share/wallpapers/freebsd-wallpapers -type f \\( -name '*.jpg' -o -name '*.png' -o -name '*.jpeg' -o -name '*.JPG' -o -name '*.PNG' \\) 2>&1 | head -10\n", 3)
send("echo '---FIND_E---'\n", 1)
dump("FIND")

# 8. Check if imlib2 is installed (feh dependency for image loading)
serial_buf = b""
send("echo '---IMLIB_S---'\n", 0.3)
send("pkg info | grep -i imlib 2>&1\n", 2)
send("pkg info | grep -i jpeg 2>&1\n", 2)
send("pkg info | grep -i png 2>&1\n", 2)
send("echo '---IMLIB_E---'\n", 1)
dump("IMLIB")

# Shutdown
send("shutdown -p now\n", 5)
try:
    proc.wait(timeout=60)
except subprocess.TimeoutExpired:
    proc.kill()

mon.close()
ser.close()
print("\n\nDone.")
