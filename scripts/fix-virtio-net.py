#!/usr/bin/env python3
"""Switch from NE2000 (ed) to virtio-net (vtnet).
FreeBSD 13.5 removed the ed driver, but has vtnet built-in."""
import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")
SERIAL_PORT = 45494
MONITOR_PORT = 45495
HOME = "/home/bsduser"

# Network watchdog for vtnet0
NET_WATCHDOG_LINES = [
    '#!/bin/sh',
    '# Network watchdog: run dhclient vtnet0 when NIC has no IP',
    'sleep 5',
    'while true; do',
    '    if ifconfig vtnet0 > /dev/null 2>&1; then',
    '        ip=$(ifconfig vtnet0 | grep "inet " | awk \'{print $2}\')',
    '        if [ -z "$ip" ]; then',
    '            dhclient vtnet0 > /dev/null 2>&1',
    '        fi',
    '    fi',
    '    sleep 15',
    'done',
]

proc = subprocess.Popen(
    ["qemu-system-i386", "-m", "512",
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

def send_cmd(cmd, timeout=30):
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

print("=== Switch to virtio-net ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)

# 1. Update rc.conf: add vtnet0 DHCP config
print("\n=== Configuring vtnet0 in rc.conf ===")
send_cmd("grep -q 'ifconfig_vtnet0' /etc/rc.conf || echo 'ifconfig_vtnet0=\"DHCP\"' >> /etc/rc.conf")

# 2. Load vtnet module at boot (it might be built-in, but ensure it)
print("\n=== Ensuring vtnet module ===")
send_cmd("grep -q 'if_vtnet_load' /boot/loader.conf || echo 'if_vtnet_load=\"YES\"' >> /boot/loader.conf")
# Also add virtio PCI transport
send_cmd("grep -q 'virtio_pci_load' /boot/loader.conf || echo 'virtio_pci_load=\"YES\"' >> /boot/loader.conf")
send_cmd("grep -q 'virtio_load' /boot/loader.conf || echo 'virtio_load=\"YES\"' >> /boot/loader.conf")

# Same for loader.conf.local
send_cmd("grep -q 'if_vtnet_load' /boot/loader.conf.local 2>/dev/null || echo 'if_vtnet_load=\"YES\"' >> /boot/loader.conf.local")
send_cmd("grep -q 'virtio_pci_load' /boot/loader.conf.local 2>/dev/null || echo 'virtio_pci_load=\"YES\"' >> /boot/loader.conf.local")
send_cmd("grep -q 'virtio_load' /boot/loader.conf.local 2>/dev/null || echo 'virtio_load=\"YES\"' >> /boot/loader.conf.local")

# Remove the broken if_ed_load entries
send_cmd("sed -i '' '/if_ed_load/d' /boot/loader.conf")
send_cmd("sed -i '' '/if_ed_load/d' /boot/loader.conf.local")

# 3. Update network watchdog for vtnet0
print("\n=== Updating network watchdog for vtnet0 ===")
write_lines(NET_WATCHDOG_LINES, f"{HOME}/.config/i3/net-watchdog.sh", executable=True)

# 4. Update resolv.conf to have DNS servers
print("\n=== Setting DNS servers ===")
send_cmd("echo 'nameserver 8.8.8.8' > /etc/resolv.conf")
send_cmd("echo 'nameserver 8.8.4.4' >> /etc/resolv.conf")

# Ownership
send_cmd(f"chown -R bsduser:bsduser {HOME}/.config")

# Verify
print("\n=== Verifying ===")
serial_buf = b""
send("grep vtnet /etc/rc.conf\n", 1)
send("cat /boot/loader.conf\n", 2)
send("cat /etc/resolv.conf\n", 1)
send(f"cat {HOME}/.config/i3/net-watchdog.sh\n", 2)
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
