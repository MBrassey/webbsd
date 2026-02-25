#!/usr/bin/env python3
"""Fix .Xresources font, clean up nerd-fonts temp dir, verify everything."""
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

print("=== Fix fonts + cleanup ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)

# 1. Clean up nerd-fonts temp directory
print("\n=== Cleaning up nerd-fonts temp ===")
serial_buf = b""
send("du -sh /usr/local/share/fonts/.pkgtemp.nerd-fonts* 2>&1\n", 3)
time.sleep(3)
drain()
output = serial_buf.decode(errors="replace")
for line in output.split("\n"):
    s = line.strip()
    if s and "pkgtemp" in s and not s.startswith("$"):
        print(f"  {s}")

send_cmd("rm -rf /usr/local/share/fonts/.pkgtemp.nerd-fonts*")
send_cmd("fc-cache -f 2>/dev/null || true", timeout=30)

# 2. Fix .Xresources - replace JetBrainsMono Nerd Font with Hack
print("\n=== Fixing .Xresources font ===")
# Read current content
serial_buf = b""
send(f"cat {HOME}/.Xresources\n", 2)
time.sleep(3)
drain()
output = serial_buf.decode(errors="replace")
print("Current .Xresources:")
xresources_lines = []
in_content = False
for line in output.split("\n"):
    s = line.strip()
    if "URxvt" in s or "Xft" in s or "!" in s or s == "":
        in_content = True
    if in_content and s and not s.startswith("$") and not s.startswith("#") and not s.startswith("cat "):
        print(f"  {s}")
        xresources_lines.append(s)

# Write new .Xresources with Hack font
xresources = [
    '! URxvt terminal config',
    'URxvt.font: xft:Hack:size=11:antialias=true, xft:DejaVu Sans Mono:size=11',
    'URxvt.boldFont: xft:Hack:bold:size=11:antialias=true, xft:DejaVu Sans Mono:bold:size=11',
    'URxvt.italicFont: xft:Hack:italic:size=11:antialias=true',
    'URxvt.boldItalicFont: xft:Hack:bold:italic:size=11:antialias=true',
    '',
    '! Colors - dark theme matching Hybrid',
    'URxvt.background: #1d1f21',
    'URxvt.foreground: #c5c8c6',
    'URxvt.cursorColor: #c5c8c6',
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
    'URxvt.internalBorder: 4',
    'URxvt.saveLines: 4096',
    'URxvt.urgentOnBell: true',
    '',
    '! URL handling',
    'URxvt.perl-ext-common: default,matcher',
    'URxvt.url-launcher: firefox',
    'URxvt.matcher.button: 1',
    '',
    '! Font rendering',
    'Xft.dpi: 96',
    'Xft.antialias: true',
    'Xft.hinting: true',
    'Xft.hintstyle: hintslight',
    'Xft.rgba: rgb',
]
write_lines(xresources, f"{HOME}/.Xresources")

# 3. Verify .vimrc and hybrid.vim
print("\n=== Verifying vim setup ===")
serial_buf = b""
send(f"wc -l {HOME}/.vimrc {HOME}/.vim/colors/hybrid.vim 2>&1\n", 2)
send(f"head -5 {HOME}/.vimrc\n", 2)
time.sleep(3)
drain()
output = serial_buf.decode(errors="replace")
for line in output.split("\n"):
    s = line.strip()
    if s and not s.startswith("$"):
        print(f"  {s}")

# 4. Verify fish colors
serial_buf = b""
send(f"wc -l {HOME}/.config/fish/conf.d/colors.fish 2>&1\n", 2)
send(f"head -3 {HOME}/.config/fish/conf.d/colors.fish\n", 2)
time.sleep(3)
drain()
output = serial_buf.decode(errors="replace")
print("\nFish colors:")
for line in output.split("\n"):
    s = line.strip()
    if s and not s.startswith("$"):
        print(f"  {s}")

# 5. Fix PulseAudio to not auto-start in QEMU (only in v86 with SB16)
# Remove the i3 autostart for pulseaudio, instead start it in the net-watchdog
# after checking for /dev/dsp0
print("\n=== Fixing PulseAudio autostart ===")
send_cmd(f"sed -i '' '/pulseaudio/d' {HOME}/.config/i3/config")

# Add pulseaudio start to .xinitrc or a startup script that checks for sound device
# Actually, let's just add it to the golden-3term.sh startup
send_cmd(f"grep -q 'pulseaudio' {HOME}/.config/i3/golden-3term.sh 2>/dev/null || sed -i '' '2i\\'$'\\n''test -c /dev/dsp0 && pulseaudio --start 2>/dev/null' {HOME}/.config/i3/golden-3term.sh")

# Fix ownership
send_cmd(f"chown -R bsduser:bsduser {HOME}")

# Set DNS for v86
send_cmd("echo 'nameserver 192.168.86.1' > /etc/resolv.conf")

# Final disk check
serial_buf = b""
send("df -h /\n", 2)
time.sleep(2)
drain()
print("\nDisk usage:")
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
