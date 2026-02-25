#!/usr/bin/env python3
"""Add auto-DHCP to FreeBSD image for state restore networking."""

import subprocess
import time
import sys
import os
import socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")

MONITOR_PORT = 45455
SERIAL_PORT = 45456

print(f"Fixing network in {IMAGE}...")

proc = subprocess.Popen(
    [
        "qemu-system-i386", "-m", "512",
        "-drive", f"file={IMAGE},format=raw",
        "-display", "none",
        "-serial", f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off",
        "-monitor", f"tcp:127.0.0.1:{MONITOR_PORT},server=on,wait=off",
        "-net", "none", "-no-reboot",
    ],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
time.sleep(1)

mon = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
mon.settimeout(5)
mon.connect(("127.0.0.1", MONITOR_PORT))
time.sleep(0.5)
try: mon.recv(4096)
except: pass

def mon_cmd(cmd, delay=0.3):
    mon.send((cmd + "\r\n").encode())
    time.sleep(delay)
    try: return mon.recv(8192).decode(errors='replace')
    except: return ""

def sendkey(key, delay=0.1):
    mon_cmd(f"sendkey {key}", delay)

def type_text(text, delay=0.08):
    key_map = {
        ' ': 'spc', '\n': 'ret', '-': 'minus', '.': 'dot',
        '/': 'slash', '=': 'equal', '"': 'shift-apostrophe',
        "'": 'apostrophe', '\\': 'backslash', ',': 'comma',
        ';': 'semicolon', ':': 'shift-semicolon', '_': 'shift-minus',
    }
    for ch in text:
        if ch in key_map: k = key_map[ch]
        elif ch.isalpha(): k = f"shift-{ch.lower()}" if ch.isupper() else ch
        elif ch.isdigit(): k = ch
        else: continue
        sendkey(k, delay)

ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
ser.settimeout(1)
ser.connect(("127.0.0.1", SERIAL_PORT))

serial_buf = b""
def drain():
    global serial_buf
    while True:
        try:
            data = ser.recv(4096)
            if not data: break
            serial_buf += data
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
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
    ser.send(text.encode())
    time.sleep(delay)

# Boot single-user
# loader.conf already has console="comconsole vidconsole" and autoboot_delay="2"
# beastie is disabled, so we get "Hit [Enter] to boot..." prompt
# We need to interrupt autoboot quickly via serial, then boot -s
print("Waiting for boot loader...")
time.sleep(1)
# Send space via serial to interrupt autoboot (loader listens on serial now)
send(" ", 1)
# Also try sendkey as fallback
sendkey("spc", 0.5)
time.sleep(1)
# We should now be at the "OK" loader prompt
send("boot -s\n", 1)

print("\nWaiting for shell...")
if wait_for("Enter full pathname of shell", timeout=300):
    send("\n", 3)
elif not wait_for("#", timeout=30):
    print("ERROR: No shell"); proc.kill(); sys.exit(1)

time.sleep(2); drain()

# fsck + mount rw
send("/sbin/fsck -y /dev/ada0p4\n", 2)
wait_for("#", timeout=120)
send("/sbin/mount -u -o rw /\n", 3); drain()
send("/sbin/mount -a 2>/dev/null\n", 3); drain()

# Create /usr/local/bin if it doesn't exist
send("mkdir -p /usr/local/bin\n", 1); drain()

# Write resolv.conf with public DNS
print(">>> Writing resolv.conf...")
send("cat > /etc/resolv.conf << 'EOF'\n", 0.3)
send("nameserver 8.8.8.8\n", 0.2)
send("nameserver 8.8.4.4\n", 0.2)
send("EOF\n", 1); drain()

# Prevent dhclient from overwriting resolv.conf
send("echo 'supersede domain-name-servers 8.8.8.8, 8.8.4.4;' >> /etc/dhclient.conf\n", 1); drain()

# Write auto-dhcp script
print(">>> Writing auto-dhcp script...")
send("cat > /usr/local/bin/auto-dhcp.sh << 'EOF'\n", 0.3)
send("#!/bin/sh\n", 0.2)
send("# Check if ed0 has an IP, if not run dhclient\n", 0.2)
send("IP=$(ifconfig ed0 2>/dev/null | grep 'inet ' | awk '{print $2}')\n", 0.2)
send("if [ -z \"$IP\" ]; then\n", 0.2)
send("    /sbin/dhclient ed0 > /dev/null 2>&1 &\n", 0.2)
send("fi\n", 0.2)
send("# Ensure DNS is set\n", 0.2)
send("grep -q nameserver /etc/resolv.conf 2>/dev/null || echo 'nameserver 8.8.8.8' > /etc/resolv.conf\n", 0.2)
send("EOF\n", 1); drain()
send("chmod +x /usr/local/bin/auto-dhcp.sh\n", 1); drain()

# Write rc.local
print(">>> Writing rc.local...")
send("cat > /etc/rc.local << 'EOF'\n", 0.3)
send("#!/bin/sh\n", 0.2)
send("# Auto-DHCP for v86 saved state restore\n", 0.2)
send("sleep 2 && /usr/local/bin/auto-dhcp.sh &\n", 0.2)
send("EOF\n", 1); drain()
send("chmod +x /etc/rc.local\n", 1); drain()

# Cron job for periodic check
print(">>> Setting up cron...")
send("echo '* * * * * /usr/local/bin/auto-dhcp.sh' | crontab -\n", 2); drain()

# Reduce DHCP wait from 30s to 5s
send("grep -q defaultroute_delay /etc/rc.conf || echo 'defaultroute_delay=\"5\"' >> /etc/rc.conf\n", 1); drain()

# Verify
print("\n>>> Verifying...")
send("cat /usr/local/bin/auto-dhcp.sh && echo OK_SCRIPT\n", 2); drain()
send("cat /etc/rc.local && echo OK_RCLOCAL\n", 2); drain()
send("crontab -l && echo OK_CRON\n", 2); drain()
send("cat /etc/resolv.conf && echo OK_DNS\n", 2); drain()
send("cat /etc/dhclient.conf && echo OK_DHCLIENT\n", 2); drain()

# Shutdown cleanly
print("\n>>> Shutting down...")
send("sync\n", 1)
send("/sbin/shutdown -p now\n", 5)
try: proc.wait(timeout=60)
except subprocess.TimeoutExpired: proc.kill()
mon.close(); ser.close()
print("\n\n=== Done! Network auto-DHCP configured. ===")
