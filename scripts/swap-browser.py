#!/usr/bin/env python3
"""Remove Firefox ESR and install a lighter FreeBSD-native browser.
Candidates: midori, epiphany, surf (WebKit-based, much lighter than Firefox).
"""
import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")
SERIAL_PORT = 45494
MONITOR_PORT = 45495
HOME = "/home/bsduser"

proc = subprocess.Popen(
    ["qemu-system-i386", "-m", "1024",
     "-drive", f"file={IMAGE},format=raw,cache=writethrough",
     "-display", "none",
     "-serial", f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off",
     "-monitor", f"tcp:127.0.0.1:{MONITOR_PORT},server=on,wait=off",
     "-nic", "user,model=e1000",
     "-no-reboot"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

time.sleep(2)
ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
ser.settimeout(1)
ser.connect(("127.0.0.1", SERIAL_PORT))
mon = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
mon.settimeout(5)
mon.connect(("127.0.0.1", MONITOR_PORT))
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
        except (socket.timeout, BlockingIOError): break

def wait_for(pattern, timeout=180):
    global serial_buf
    start = time.time()
    while time.time() - start < timeout:
        drain()
        if pattern.encode() in serial_buf: return True
        time.sleep(0.3)
    return False

def send(text, delay=0.5):
    ser.send(text.encode()); time.sleep(delay)

def send_cmd(cmd, timeout=60):
    global serial_buf
    marker = f"__OK_{time.time_ns()}__"
    send(cmd + f" && echo {marker}\n", 0.5)
    if not wait_for(marker, timeout):
        print(f"  WARN: No confirm for: {cmd[:70]}...")
        return False
    drain(); return True

print("=== Swap Firefox for lighter browser ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)

# Set DNS for QEMU session
send_cmd("echo 'nameserver 8.8.8.8' > /etc/resolv.conf")

# Check disk space before
print("\n=== Disk space before ===")
serial_buf = b""
send("df -h /\n", 2)
time.sleep(2); drain()
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and ("/" in s or "Avail" in s):
        print(f"  {s}")

# Remove Firefox ESR (huge package)
print("\n=== Removing Firefox ESR ===")
send_cmd("pkg delete -fy firefox-esr", timeout=120)
# Clean up orphaned deps
send_cmd("pkg autoremove -y", timeout=120)
send_cmd("pkg clean -ay", timeout=60)

# Check what lighter browsers are available
print("\n=== Searching for lighter browsers ===")
serial_buf = b""
send("pkg search -o midori epiphany falkon surf netsurf dillo pale 2>&1 | head -30\n", 3)
time.sleep(5); drain()
search_text = serial_buf.decode(errors="replace")
print("Search results:")
for line in search_text.split("\n"):
    s = line.strip()
    if s and not s.startswith("$") and not s.startswith("#"):
        print(f"  {s}")

# Try to install in order of preference: midori, epiphany, falkon
browsers = [
    ("midori", "/usr/local/bin/midori", "midori"),
    ("epiphany", "/usr/local/bin/epiphany", "epiphany"),
    ("falkon", "/usr/local/bin/falkon", "falkon"),
    ("surf", "/usr/local/bin/surf", "surf"),
]

installed_browser = None
installed_cmd = None

for pkg_name, binary_path, cmd_name in browsers:
    print(f"\n=== Trying to install {pkg_name} ===")
    serial_buf = b""
    marker = f"__OK_{time.time_ns()}__"
    send(f"pkg install -y {pkg_name} && echo {marker}\n", 0.5)
    if wait_for(marker, timeout=300):
        print(f"  {pkg_name} installed successfully!")
        installed_browser = pkg_name
        installed_cmd = cmd_name
        break
    else:
        drain()
        output = serial_buf.decode(errors="replace")
        if "No packages" in output or "not found" in output:
            print(f"  {pkg_name} not available, trying next...")
        else:
            print(f"  {pkg_name} install may have failed, trying next...")
        # Try to clean up partial install
        send_cmd(f"pkg delete -fy {pkg_name} 2>/dev/null", timeout=30)

if not installed_browser:
    print("\nWARN: No lightweight browser found, keeping system without browser")
else:
    # Update i3 config to use new browser
    print(f"\n=== Updating i3 config for {installed_browser} ===")
    send_cmd(f"sed -i '' 's/firefox/{installed_cmd}/g' {HOME}/.config/i3/config")

# Check disk space after
print("\n=== Disk space after ===")
serial_buf = b""
send("df -h /\n", 2)
time.sleep(2); drain()
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and ("/" in s or "Avail" in s):
        print(f"  {s}")

# Verify installed browser
if installed_browser:
    serial_buf = b""
    send(f"which {installed_cmd}\n", 1)
    send(f"pkg info {installed_browser} | head -5\n", 2)
    time.sleep(3); drain()
    print(f"\nBrowser info:")
    for line in serial_buf.decode(errors="replace").split("\n"):
        s = line.strip()
        if s and not s.startswith("$"):
            print(f"  {s}")

# Set DNS back for relay
send_cmd("echo 'nameserver 8.8.8.8' > /etc/resolv.conf")

send_cmd(f"chown -R bsduser:bsduser {HOME}")

print("\nSyncing...")
send("sync\n", 3)
send("sync\n", 3)
send("mount -ur /\n", 2)
send("shutdown -p now\n", 5)
try: proc.wait(timeout=120)
except: proc.kill()
mon.close(); ser.close()
print(f"\nDone! Browser: {installed_browser or 'none'}")
