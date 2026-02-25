#!/usr/bin/env python3
"""Fix DNS + install browser. More verbose/robust version."""
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

def write_lines(lines, dest_path, executable=False):
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
send_cmd("killall dhclient 2>/dev/null; true", timeout=5)

# Get QEMU network up
print("Getting network...")
send("dhclient em0 2>&1\n", 20)
drain()

# Test connectivity
serial_buf = b""
send_cmd("ping -c 1 8.8.8.8", timeout=15)
print("Network OK" if b"1 packets received" in serial_buf else "Network issue")

# 1. Fix DNS for fetch backend
print("\n=== Fixing DNS ===")
send_cmd("echo 'nameserver 192.168.86.1' > /etc/resolv.conf")
send_cmd("echo 'supersede domain-name-servers 192.168.86.1;' > /etc/dhclient.conf")

# 2. Update watchdog
print("Writing watchdog...")
watchdog = [
    '#!/bin/sh',
    'n=0',
    'while true; do',
    '    if ifconfig vtnet0 > /dev/null 2>&1; then',
    '        ip=$(ifconfig vtnet0 | grep "inet " | awk \'{print $2}\')',
    '        if [ -z "$ip" ]; then',
    '            dhclient vtnet0 > /dev/null 2>&1',
    '            echo "nameserver 192.168.86.1" > /etc/resolv.conf',
    '        fi',
    '    fi',
    '    [ "$n" -lt 6 ] && sleep 3 && n=$((n+1)) || sleep 30',
    'done',
]
write_lines(watchdog, f"{HOME}/.config/i3/net-watchdog.sh", executable=True)

# 3. Check pkg and available browsers
print("\n=== Updating pkg catalog ===")
send("pkg update -f 2>&1 | tail -3\n", 5)
wait_for("$", timeout=120)
drain()

print("\n=== Searching for browsers ===")
serial_buf = b""
send("pkg search -Q comment firefox | head -5\n", 10)
time.sleep(10)
drain()
output = serial_buf.decode(errors="replace")
print("Firefox packages:")
for line in output.split("\n"):
    s = line.strip()
    if s and "firefox" in s.lower() and not s.startswith("$"):
        print(f"  {s}")

serial_buf = b""
send("pkg search -Q comment '^www/' 2>/dev/null | grep -i 'browser\\|webkit\\|web kit' | head -10\n", 15)
time.sleep(15)
drain()
output = serial_buf.decode(errors="replace")
print("\nOther browsers:")
for line in output.split("\n"):
    s = line.strip()
    if s and not s.startswith("$") and not s.startswith("#"):
        print(f"  {s}")

# 4. Try installing firefox
print("\n=== Installing Firefox ===")
serial_buf = b""
send("pkg install -y firefox 2>&1 | tail -20\n", 5)
print("Waiting for Firefox install...")
# Wait up to 15 minutes
start = time.time()
found = False
while time.time() - start < 900:
    drain()
    output = serial_buf.decode(errors="replace")
    if "Number of packages" in output or "already installed" in output:
        found = True
        # Wait for it to finish
        wait_for("$", timeout=600)
        break
    if "No packages available" in output or "No matching" in output:
        print("  Firefox not available!")
        break
    time.sleep(5)

drain()
output = serial_buf.decode(errors="replace")
# Show last 15 lines
lines = [l.strip() for l in output.split("\n") if l.strip() and not l.strip().startswith("$")]
for l in lines[-15:]:
    print(f"  {l}")

# 5. Check what we got
serial_buf = b""
send("which firefox firefox-esr 2>&1\n", 2)
send("ls /usr/local/bin/firefox* 2>&1\n", 2)
send("ls /usr/local/lib/firefox*/firefox 2>&1\n", 2)
time.sleep(3)
drain()
output = serial_buf.decode(errors="replace")
print("\nFirefox binaries:")
for line in output.split("\n"):
    s = line.strip()
    if s and ("firefox" in s or "/usr" in s) and not s.startswith("$"):
        print(f"  {s}")

# Determine browser binary
browser = "netsurf-gtk3"  # fallback
for candidate in ["/usr/local/bin/firefox", "/usr/local/bin/firefox-esr"]:
    serial_buf = b""
    send(f"test -x {candidate} && echo FOUND_{candidate}\n", 2)
    time.sleep(2)
    drain()
    if f"FOUND_{candidate}" in serial_buf.decode(errors="replace"):
        browser = os.path.basename(candidate)
        break

print(f"\nUsing browser: {browser}")

# 6. Update status.sh click handler if browser changed
if browser != "netsurf-gtk3":
    print(f"Updating status.sh to use {browser}...")
    send_cmd(f"sed -i '' 's|exec netsurf-gtk3|exec {browser}|' {HOME}/.config/i3/status.sh")
    # Also update i3 config keybinding if any
    send_cmd(f"sed -i '' 's|exec netsurf|exec {browser}|' {HOME}/.config/i3/config")

send_cmd(f"chown -R bsduser:bsduser {HOME}/.config")

# Final verify
print("\n=== Final verification ===")
serial_buf = b""
send("cat /etc/resolv.conf\n", 1)
send("cat /etc/dhclient.conf\n", 1)
send(f"grep 'web' {HOME}/.config/i3/status.sh | head -2\n", 1)
time.sleep(3)
drain()
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$"):
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
