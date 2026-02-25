#!/usr/bin/env python3
"""Fix terminal transparency (lost in .Xresources rewrite) and DNS
by switching vtnet0 to static IP (no DHCP needed from fetch backend)."""
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

print("=== Fix transparency + DNS ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)

# 1. Fix .Xresources - add transparency back + keep Hack font + Hybrid colors
print("\n=== Fixing .Xresources (restoring transparency) ===")
xresources = [
    '! URxvt terminal config - Hack font + Hybrid colors + transparency',
    'URxvt.font: xft:Hack:size=11:antialias=true, xft:DejaVu Sans Mono:size=11',
    'URxvt.boldFont: xft:Hack:bold:size=11:antialias=true, xft:DejaVu Sans Mono:bold:size=11',
    'URxvt.italicFont: xft:Hack:italic:size=11:antialias=true',
    'URxvt.boldItalicFont: xft:Hack:bold:italic:size=11:antialias=true',
    '',
    '! Transparency',
    'URxvt.depth: 32',
    'URxvt.transparent: true',
    'URxvt.shading: 25',
    '',
    '! Colors - Hybrid dark theme',
    'URxvt.background: #0a0a0a',
    'URxvt.foreground: #c5c8c6',
    'URxvt.cursorColor: #ab1100',
    'URxvt.cursorBlink: true',
    '',
    '! Black',
    'URxvt.color0: #282a2e',
    'URxvt.color8: #373b41',
    '! Red',
    'URxvt.color1: #a54242',
    'URxvt.color9: #cc6666',
    '! Green',
    'URxvt.color2: #8c9440',
    'URxvt.color10: #b5bd68',
    '! Yellow',
    'URxvt.color3: #de935f',
    'URxvt.color11: #f0c674',
    '! Blue',
    'URxvt.color4: #5f819d',
    'URxvt.color12: #81a2be',
    '! Magenta',
    'URxvt.color5: #85678f',
    'URxvt.color13: #b294bb',
    '! Cyan',
    'URxvt.color6: #5e8d87',
    'URxvt.color14: #8abeb7',
    '! White',
    'URxvt.color7: #707880',
    'URxvt.color15: #c5c8c6',
    '',
    '! UI',
    'URxvt.scrollBar: false',
    'URxvt.internalBorder: 10',
    'URxvt.saveLines: 10000',
    'URxvt.lineSpace: 2',
    'URxvt.iso14755: false',
    'URxvt.iso14755_52: false',
    'URxvt.urgentOnBell: true',
    '',
    '! URL handling',
    'URxvt.perl-ext-common: default,matcher',
    'URxvt.url-launcher: firefox',
    'URxvt.matcher.button: 1',
    '',
    '! XTerm fallback',
    'XTerm*background: #0a0a0a',
    'XTerm*foreground: #c5c8c6',
    'XTerm*cursorColor: #ab1100',
    'XTerm*faceName: Hack',
    'XTerm*faceSize: 11',
    'XTerm*scrollBar: false',
    '',
    '! Font rendering',
    'Xft.dpi: 96',
    'Xft.antialias: true',
    'Xft.hinting: true',
    'Xft.hintstyle: hintslight',
    'Xft.rgba: rgb',
]
write_lines(xresources, f"{HOME}/.Xresources")

# 2. Fix DNS: switch from DHCP to static IP for v86 fetch backend
# The fetch backend provides:
#   - Virtual network: 192.168.86.0/24
#   - Gateway/DNS: 192.168.86.1
#   - DHCP assigns: 192.168.86.100
# Using static IP means networking works instantly on state restore
# without waiting for DHCP (which fails during headless save-state).
print("\n=== Fixing network config (static IP for fetch backend) ===")

# Read current rc.conf
serial_buf = b""
send("cat /etc/rc.conf\n", 2)
time.sleep(3)
drain()
print("Current rc.conf:")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$") and not s.startswith("#") and not s.startswith("cat"):
        print(f"  {s}")

# Remove DHCP line for vtnet0, add static config
send_cmd("sed -i '' '/ifconfig_vtnet0/d' /etc/rc.conf")
send_cmd("sed -i '' '/defaultrouter/d' /etc/rc.conf")
# Add static IP config
send_cmd("echo 'ifconfig_vtnet0=\"inet 192.168.86.100 netmask 255.255.255.0\"' >> /etc/rc.conf")
send_cmd("echo 'defaultrouter=\"192.168.86.1\"' >> /etc/rc.conf")

# Set resolv.conf
send_cmd("echo 'nameserver 192.168.86.1' > /etc/resolv.conf")

# Set dhclient.conf (in case dhclient ever runs)
send_cmd("echo 'supersede domain-name-servers 192.168.86.1;' > /etc/dhclient.conf")

# Update net-watchdog to handle static config too
print("\n=== Updating net-watchdog ===")
watchdog = [
    '#!/bin/sh',
    '# Network watchdog for v86 fetch backend',
    '# Ensures vtnet0 has IP and DNS points to virtual router',
    'n=0',
    'while true; do',
    '    if ifconfig vtnet0 > /dev/null 2>&1; then',
    '        ip=$(ifconfig vtnet0 | grep "inet " | awk \'{print $2}\')',
    '        if [ -z "$ip" ]; then',
    '            # Try static config first',
    '            ifconfig vtnet0 inet 192.168.86.100 netmask 255.255.255.0 up',
    '            route add default 192.168.86.1 2>/dev/null',
    '        fi',
    '        # Always ensure DNS is correct',
    '        grep -q "192.168.86.1" /etc/resolv.conf 2>/dev/null || echo "nameserver 192.168.86.1" > /etc/resolv.conf',
    '    fi',
    '    [ "$n" -lt 6 ] && sleep 3 && n=$((n+1)) || sleep 30',
    'done',
]
write_lines(watchdog, f"{HOME}/.config/i3/net-watchdog.sh", executable=True)

# Verify rc.conf
serial_buf = b""
send("cat /etc/rc.conf\n", 2)
time.sleep(3)
drain()
print("\nUpdated rc.conf:")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$") and not s.startswith("#") and not s.startswith("cat"):
        print(f"  {s}")

# Verify resolv.conf
serial_buf = b""
send("cat /etc/resolv.conf\n", 1)
time.sleep(2)
drain()
print("\nresolv.conf:")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and "nameserver" in s:
        print(f"  {s}")

# Fix ownership
send_cmd(f"chown -R bsduser:bsduser {HOME}")

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
