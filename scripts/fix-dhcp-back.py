#!/usr/bin/env python3
"""Switch vtnet0 back to DHCP and ensure resolv.conf gets set by watchdog."""
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

print("=== Switch to DHCP + fix watchdog ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)

# Switch rc.conf back to DHCP
print("\n=== Switching to DHCP ===")
send_cmd("sed -i '' '/ifconfig_vtnet0/d' /etc/rc.conf")
send_cmd("sed -i '' '/defaultrouter/d' /etc/rc.conf")
send_cmd("echo 'ifconfig_vtnet0=\"DHCP\"' >> /etc/rc.conf")

# dhclient.conf: ensure DNS always points to virtual router
send_cmd("echo 'supersede domain-name-servers 192.168.86.1;' > /etc/dhclient.conf")

# resolv.conf: set to virtual router (both fetch and wisp use this)
send_cmd("echo 'nameserver 192.168.86.1' > /etc/resolv.conf")

# Aggressive net-watchdog that handles both fetch and wisp backends
print("\n=== Writing net-watchdog ===")
watchdog = [
    '#!/bin/sh',
    '# Network watchdog for v86 (fetch/wisp backends)',
    '# Both backends provide DHCP at 192.168.86.x, DNS at 192.168.86.1',
    'n=0',
    'while true; do',
    '    if ifconfig vtnet0 > /dev/null 2>&1; then',
    '        ip=$(ifconfig vtnet0 | grep "inet " | awk \'{print $2}\')',
    '        if [ -z "$ip" ]; then',
    '            dhclient vtnet0 > /dev/null 2>&1',
    '        fi',
    '        # Always ensure DNS points to virtual router',
    '        grep -q "192.168.86.1" /etc/resolv.conf 2>/dev/null || echo "nameserver 192.168.86.1" > /etc/resolv.conf',
    '    fi',
    '    [ "$n" -lt 10 ] && sleep 2 && n=$((n+1)) || sleep 20',
    'done',
]
write_lines(watchdog, f"{HOME}/.config/i3/net-watchdog.sh", executable=True)

# Verify
serial_buf = b""
send("cat /etc/rc.conf\n", 2)
time.sleep(2)
drain()
print("\nrc.conf:")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$") and not s.startswith("#") and not s.startswith("cat"):
        print(f"  {s}")

send_cmd(f"chown -R bsduser:bsduser {HOME}")

print("\nSyncing...")
send("sync\n", 3)
send("sync\n", 3)
send("mount -ur /\n", 2)
send("shutdown -p now\n", 5)
try: proc.wait(timeout=120)
except: proc.kill()
mon.close(); ser.close()
print("Done!")
