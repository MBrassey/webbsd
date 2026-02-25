#!/usr/bin/env python3
"""Fix DNS for fetch backend (must use 192.168.86.1, not 8.8.8.8) and
install a proper browser with JS support."""
import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")
SERIAL_PORT = 45494
MONITOR_PORT = 45495
HOME = "/home/bsduser"

# Network watchdog: more aggressive initial check, use 192.168.86.1 DNS
NET_WATCHDOG_LINES = [
    '#!/bin/sh',
    '# Network watchdog: dhclient vtnet0 when no IP',
    '# First check quickly, then slow down',
    'n=0',
    'while true; do',
    '    if ifconfig vtnet0 > /dev/null 2>&1; then',
    '        ip=$(ifconfig vtnet0 | grep "inet " | awk \'{print $2}\')',
    '        if [ -z "$ip" ]; then',
    '            dhclient vtnet0 > /dev/null 2>&1',
    '            # Ensure DNS points to virtual router',
    '            echo "nameserver 192.168.86.1" > /etc/resolv.conf',
    '        fi',
    '    fi',
    '    if [ "$n" -lt 6 ]; then',
    '        sleep 3',
    '        n=$((n+1))',
    '    else',
    '        sleep 30',
    '    fi',
    'done',
]

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

def write_lines(lines, dest_path, executable=False):
    print(f"  Writing {dest_path}...")
    send(f"rm -f {dest_path}\n", 0.3)
    for line in lines:
        escaped = line.replace("'", "'\\''")
        send(f"echo '{escaped}' >> {dest_path}\n", 0.04)
    time.sleep(1)
    drain()
    if executable:
        send_cmd(f"chmod +x {dest_path}")

print("=== Fix DNS + install browser ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)

# Get QEMU network up
print("Getting network...")
send("dhclient em0\n", 15)
drain()

# 1. Fix DNS config for fetch backend
# The fetch backend's virtual router is 192.168.86.1 — it intercepts DNS queries
# to that IP. Queries to 8.8.8.8 get dropped because fetch can't forward raw UDP.
print("\n=== Fixing DNS for fetch backend ===")
send_cmd("echo 'nameserver 192.168.86.1' > /etc/resolv.conf")

# dhclient.conf: force DNS to virtual router, don't prepend external servers
send_cmd("echo 'supersede domain-name-servers 192.168.86.1;' > /etc/dhclient.conf")

# 2. Update network watchdog
print("\n=== Updating network watchdog ===")
write_lines(NET_WATCHDOG_LINES, f"{HOME}/.config/i3/net-watchdog.sh", executable=True)

# 3. Check what browsers are available for i386
print("\n=== Checking available browsers ===")
serial_buf = b""
send("pkg search firefox 2>&1 | head -5\n", 5)
send("pkg search chromium 2>&1 | head -3\n", 5)
send("pkg search surf 2>&1 | head -3\n", 5)
send("pkg search falkon 2>&1 | head -3\n", 5)
send("pkg search epiphany 2>&1 | head -3\n", 5)
send("pkg search webkit 2>&1 | grep -i browser | head -3\n", 5)
time.sleep(10)
drain()
print("Available browsers:")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$") and not s.startswith("#") and not s.startswith("pkg"):
        print(f"  {s}")

# 4. Install Firefox ESR (best JS/React support)
print("\n=== Installing Firefox ESR ===")
send("pkg install -y firefox-esr 2>&1 | tail -10\n", 5)
print("Installing firefox-esr (this will take a while)...")
# Firefox is large, wait up to 15 minutes
start = time.time()
while time.time() - start < 900:
    drain()
    output = serial_buf.decode(errors="replace")
    if "installed" in output.lower() or "already installed" in output.lower():
        break
    if "error" in output.lower() and "pkg" in output.lower():
        print("  pkg error detected, checking...")
        break
    time.sleep(5)
drain()

# Check result
serial_buf = b""
send("which firefox 2>&1\n", 2)
send("which firefox-esr 2>&1\n", 2)
send("pkg info firefox-esr 2>/dev/null | head -2\n", 3)
time.sleep(5)
drain()
output = serial_buf.decode(errors="replace")
print("Firefox install result:")
for line in output.split("\n"):
    s = line.strip()
    if s and ("firefox" in s.lower() or "/usr" in s) and not s.startswith("$"):
        print(f"  {s}")

# If firefox not found, check what we got
if "firefox" not in output.lower() or "not found" in output.lower():
    print("  Firefox may not be available for i386, checking alternatives...")
    serial_buf = b""
    # Try surf (WebKit2GTK based, lightweight, has JS)
    send("pkg install -y surf 2>&1 | tail -5\n", 5)
    wait_for("$", timeout=300)
    send("which surf 2>&1\n", 2)
    # Try epiphany/gnome-web (WebKit based)
    send("pkg install -y epiphany 2>&1 | tail -5\n", 5)
    wait_for("$", timeout=300)
    send("which epiphany 2>&1\n", 2)
    time.sleep(5)
    drain()
    for line in serial_buf.decode(errors="replace").split("\n"):
        s = line.strip()
        if s and not s.startswith("$"):
            print(f"  {s}")

# 5. Update status.sh click handler for new browser
print("\n=== Checking final browser binary ===")
serial_buf = b""
send("ls /usr/local/bin/firefox* /usr/local/bin/surf /usr/local/bin/epiphany 2>&1\n", 3)
time.sleep(3)
drain()
browser_bin = None
output = serial_buf.decode(errors="replace")
for candidate in ["firefox-esr", "firefox", "surf", "epiphany"]:
    if f"/usr/local/bin/{candidate}" in output:
        browser_bin = candidate
        break
if browser_bin:
    print(f"  Browser: {browser_bin}")
else:
    print("  No modern browser found, keeping netsurf-gtk3")
    browser_bin = "netsurf-gtk3"

# Ownership
send_cmd(f"chown -R bsduser:bsduser {HOME}/.config")

# Verify
serial_buf = b""
send("cat /etc/resolv.conf\n", 1)
send("cat /etc/dhclient.conf\n", 1)
time.sleep(2)
drain()
print("\nDNS config:")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and ("nameserver" in s or "supersede" in s or "resolv" in s or "dhclient" in s):
        print(f"  {s}")

print(f"\nBrowser binary: {browser_bin}")

# Shutdown
print("\nSyncing...")
send("sync\n", 3)
send("sync\n", 3)
send("mount -ur /\n", 2)
send("shutdown -p now\n", 5)
try: proc.wait(timeout=120)
except: proc.kill()
mon.close(); ser.close()
print("Done!")
