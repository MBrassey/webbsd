#!/usr/bin/env python3
"""Fix pkg mirror config, install JS browser, set DNS for v86 fetch backend.

Key insight: During QEMU session, DNS must use 8.8.8.8 (QEMU NAT forwards it).
The v86 fetch backend DNS (192.168.86.1) only exists at runtime in the browser.
So we install packages with real DNS, then set 192.168.86.1 at the very end.
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

print("=== Fix pkg + install browser ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)
send_cmd("killall dhclient 2>/dev/null; true", timeout=5)

# Get QEMU network up
print("Getting network...")
send("dhclient em0 2>&1\n", 20)
drain()

# Use REAL DNS during QEMU session (QEMU NAT forwards to host)
print("Setting DNS for QEMU session (8.8.8.8)...")
send_cmd("echo 'nameserver 8.8.8.8' > /etc/resolv.conf")
send_cmd("echo 'nameserver 8.8.4.4' >> /etc/resolv.conf")

# Test DNS
serial_buf = b""
send_cmd("ping -c 1 8.8.8.8", timeout=15)
print("Ping OK" if b"1 packets received" in serial_buf else "Ping failed")

serial_buf = b""
send("host pkg.FreeBSD.org 2>&1 || nslookup pkg.FreeBSD.org 2>&1 | head -5\n", 10)
time.sleep(10)
drain()
output = serial_buf.decode(errors="replace")
print("DNS test:")
for line in output.split("\n"):
    s = line.strip()
    if s and ("address" in s.lower() or "name" in s.lower() or "server" in s.lower()) and not s.startswith("$"):
        print(f"  {s}")

# Fix pkg repo config: use HTTP mirror instead of SRV
# SRV records don't work through some NAT setups
print("\n=== Fixing pkg repo config ===")
send_cmd("mkdir -p /usr/local/etc/pkg/repos")
# Disable the default SRV-based repo
send_cmd("echo 'FreeBSD: { enabled: no }' > /usr/local/etc/pkg/repos/FreeBSD.conf")
# Add direct HTTP repo
send("rm -f /usr/local/etc/pkg/repos/direct.conf\n", 0.3)
send("echo 'direct: {' >> /usr/local/etc/pkg/repos/direct.conf\n", 0.1)
send("echo '  url: \"http://pkg.FreeBSD.org/FreeBSD:13:i386/quarterly\",' >> /usr/local/etc/pkg/repos/direct.conf\n", 0.1)
send("echo '  mirror_type: \"http\",' >> /usr/local/etc/pkg/repos/direct.conf\n", 0.1)
send("echo '  enabled: yes' >> /usr/local/etc/pkg/repos/direct.conf\n", 0.1)
send("echo '}' >> /usr/local/etc/pkg/repos/direct.conf\n", 0.3)
time.sleep(1)
drain()

# Update pkg catalog
print("Updating pkg catalog...")
serial_buf = b""
send("pkg update -f 2>&1\n", 5)
if not wait_for("Fetching meta", timeout=60):
    # Try waiting for any completion
    wait_for("#", timeout=60)
drain()
# Wait for it to fully finish
time.sleep(5)
wait_for("#", timeout=120)
drain()
output = serial_buf.decode(errors="replace")
print("pkg update result:")
for line in output.split("\n"):
    s = line.strip()
    if s and not s.startswith("$") and ("updat" in s.lower() or "error" in s.lower() or "fetch" in s.lower() or "process" in s.lower() or "catalog" in s.lower()):
        print(f"  {s}")

# Search for available browsers
print("\n=== Searching for browsers ===")
serial_buf = b""
send("pkg search firefox 2>&1 | head -10\n", 5)
time.sleep(15)
drain()
output = serial_buf.decode(errors="replace")
print("Firefox search:")
for line in output.split("\n"):
    s = line.strip()
    if s and "firefox" in s.lower() and not s.startswith("$") and not s.startswith("#"):
        print(f"  {s}")

serial_buf = b""
send("pkg search surf 2>&1 | head -5\n", 5)
time.sleep(10)
drain()
output = serial_buf.decode(errors="replace")
print("Surf search:")
for line in output.split("\n"):
    s = line.strip()
    if s and "surf" in s.lower() and not s.startswith("$") and not s.startswith("#"):
        print(f"  {s}")

serial_buf = b""
send("pkg search midori 2>&1 | head -5\n", 5)
send("pkg search falkon 2>&1 | head -5\n", 5)
send("pkg search epiphany 2>&1 | head -5\n", 5)
time.sleep(20)
drain()
output = serial_buf.decode(errors="replace")
print("Other browser search:")
for line in output.split("\n"):
    s = line.strip()
    if s and ("midori" in s.lower() or "falkon" in s.lower() or "epiphany" in s.lower()) and not s.startswith("$") and not s.startswith("#"):
        print(f"  {s}")

# Try installing browsers in order of preference
# firefox-esr > firefox > surf > falkon > midori
browser_installed = None
for browser_pkg in ["firefox-esr", "firefox", "surf", "falkon", "midori"]:
    print(f"\n=== Trying to install {browser_pkg} ===")
    serial_buf = b""
    send(f"pkg install -y {browser_pkg} 2>&1 | tail -30\n", 5)
    print(f"  Installing {browser_pkg} (waiting up to 15min)...")

    start = time.time()
    while time.time() - start < 900:
        drain()
        output = serial_buf.decode(errors="replace")
        if "Number of packages" in output or "already installed" in output:
            # Package is being installed, wait for completion
            print("  Package found, installing...")
            wait_for("#", timeout=600)
            break
        if "No packages available" in output or "No matching" in output:
            print(f"  {browser_pkg} not available")
            break
        if "error" in output.lower() and "updating" in output.lower():
            print(f"  Repository error")
            wait_for("#", timeout=30)
            break
        time.sleep(3)

    drain()

    # Check if it actually installed
    serial_buf = b""
    send(f"which {browser_pkg} 2>&1\n", 3)
    time.sleep(3)
    drain()
    check = serial_buf.decode(errors="replace")
    if f"/usr/local/bin/{browser_pkg}" in check:
        browser_installed = browser_pkg
        print(f"  SUCCESS: {browser_pkg} installed!")
        break

    # Also check without -esr suffix for firefox-esr
    if browser_pkg == "firefox-esr":
        serial_buf = b""
        send("which firefox 2>&1\n", 3)
        time.sleep(3)
        drain()
        check2 = serial_buf.decode(errors="replace")
        if "/usr/local/bin/firefox" in check2:
            browser_installed = "firefox"
            print(f"  SUCCESS: firefox installed (from firefox-esr package)!")
            break

    print(f"  {browser_pkg} not found after install attempt")

if not browser_installed:
    print("\nNo JS-capable browser could be installed.")
    print("Keeping netsurf-gtk3 as fallback.")
    browser_installed = "netsurf-gtk3"
else:
    print(f"\nBrowser to use: {browser_installed}")

# Fix status.sh click handler - the previous script may have incorrectly set it to "firefox"
print("\n=== Updating status.sh browser command ===")
# First, check current state
serial_buf = b""
send(f"grep 'exec.*web' {HOME}/.config/i3/status.sh\n", 2)
time.sleep(2)
drain()
current = serial_buf.decode(errors="replace")
print(f"Current click handler: {[l.strip() for l in current.split(chr(10)) if 'exec' in l and 'web' in l]}")

# Set the correct browser
if browser_installed != "netsurf-gtk3":
    # Replace any browser reference in the web click handler
    send_cmd(f"sed -i '' 's|exec [a-z_-]*-gtk3|exec {browser_installed}|' {HOME}/.config/i3/status.sh")
    send_cmd(f"sed -i '' 's|exec netsurf[a-z_-]*|exec {browser_installed}|' {HOME}/.config/i3/status.sh")
    send_cmd(f"sed -i '' 's|exec firefox[a-z_-]*|exec {browser_installed}|' {HOME}/.config/i3/status.sh")
    # Also fix i3 config bindings
    send_cmd(f"sed -i '' 's|exec netsurf[a-z_-]*|exec {browser_installed}|' {HOME}/.config/i3/config")
else:
    # Revert to netsurf-gtk3 if that's all we have
    send_cmd(f"sed -i '' 's|exec firefox[a-z_-]*|exec netsurf-gtk3|' {HOME}/.config/i3/status.sh")
    send_cmd(f"sed -i '' 's|exec firefox|exec netsurf-gtk3|' {HOME}/.config/i3/status.sh")
    send_cmd(f"sed -i '' 's|exec firefox|exec netsurf-gtk3|' {HOME}/.config/i3/config")

# Verify the fix
serial_buf = b""
send(f"grep 'exec.*web' {HOME}/.config/i3/status.sh\n", 2)
time.sleep(2)
drain()
current = serial_buf.decode(errors="replace")
print(f"Updated click handler: {[l.strip() for l in current.split(chr(10)) if 'exec' in l and 'web' in l]}")

send_cmd(f"chown -R bsduser:bsduser {HOME}/.config")

# NOW set DNS for v86 fetch backend (192.168.86.1) - MUST be last
print("\n=== Setting DNS for v86 fetch backend ===")
send_cmd("echo 'nameserver 192.168.86.1' > /etc/resolv.conf")
send_cmd("echo 'supersede domain-name-servers 192.168.86.1;' > /etc/dhclient.conf")

# Final verification
print("\n=== Final verification ===")
serial_buf = b""
send("cat /etc/resolv.conf\n", 1)
send("cat /etc/dhclient.conf\n", 1)
send("cat /usr/local/etc/pkg/repos/direct.conf\n", 1)
send(f"head -3 {HOME}/.config/i3/net-watchdog.sh\n", 1)
time.sleep(5)
drain()
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$") and not s.startswith("#"):
        print(f"  {s}")

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
