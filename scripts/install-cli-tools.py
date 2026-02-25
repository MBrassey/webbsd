#!/usr/bin/env python3
"""Install gtop, tty-clock, cava + configure audio loopback for cava."""
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

print("=== Install CLI tools + audio config ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)
send_cmd("killall dhclient 2>/dev/null; true", timeout=5)

# Get network up with real DNS for QEMU
print("Getting network...")
send("dhclient em0 2>&1\n", 20)
drain()
send_cmd("echo 'nameserver 8.8.8.8' > /etc/resolv.conf")

# Verify network
serial_buf = b""
send_cmd("ping -c 1 8.8.8.8", timeout=15)
print("Ping OK" if b"1 packets received" in serial_buf else "Ping issue")

# Search for available packages
print("\n=== Searching for packages ===")
serial_buf = b""
send("pkg search gtop 2>&1 | head -5\n", 5)
send("pkg search gotop 2>&1 | head -5\n", 5)
send("pkg search tty-clock 2>&1 | head -5\n", 5)
send("pkg search cava 2>&1 | head -5\n", 5)
send("pkg search bashtop 2>&1 | head -3\n", 5)
send("pkg search htop 2>&1 | head -3\n", 5)
send("pkg search virtual_oss 2>&1 | head -3\n", 5)
send("pkg search pulseaudio 2>&1 | head -5\n", 5)
time.sleep(30)
drain()
output = serial_buf.decode(errors="replace")
print("Available packages:")
for line in output.split("\n"):
    s = line.strip()
    if s and not s.startswith("$") and not s.startswith("#") and not s.startswith("pkg"):
        if any(k in s.lower() for k in ["gtop", "gotop", "tty-clock", "cava", "bashtop", "htop", "virtual_oss", "pulseaudio"]):
            print(f"  {s}")

# Install packages
# gtop: might be gotop or bashtop on FreeBSD
# tty-clock: terminal clock
# cava: console audio visualizer
# pulseaudio: needed for cava to monitor playback audio
# virtual_oss: OSS audio loopback (alternative to pulseaudio for monitoring)

print("\n=== Installing packages ===")

# Try gtop first, then gotop, then bashtop as fallback for system monitor
for pkg in ["gtop", "gotop", "bashtop", "bpytop"]:
    serial_buf = b""
    send(f"pkg search -e {pkg} 2>&1\n", 5)
    time.sleep(5)
    drain()
    if pkg in serial_buf.decode(errors="replace").lower():
        print(f"Installing {pkg}...")
        serial_buf = b""
        send(f"pkg install -y {pkg} 2>&1 | tail -10\n", 5)
        wait_for("#", timeout=300)
        drain()
        output = serial_buf.decode(errors="replace")
        if "installed" in output.lower():
            print(f"  {pkg} installed")
            break
        else:
            print(f"  {pkg} install attempt done")
    else:
        print(f"  {pkg} not found")

# tty-clock
print("\nInstalling tty-clock...")
serial_buf = b""
send("pkg install -y tty-clock 2>&1 | tail -10\n", 5)
wait_for("#", timeout=300)
drain()
output = serial_buf.decode(errors="replace")
for line in output.split("\n"):
    s = line.strip()
    if s and ("install" in s.lower() or "error" in s.lower() or "not found" in s.lower()) and not s.startswith("$"):
        print(f"  {s}")

# cava
print("\nInstalling cava...")
serial_buf = b""
send("pkg install -y cava 2>&1 | tail -10\n", 5)
wait_for("#", timeout=300)
drain()
output = serial_buf.decode(errors="replace")
for line in output.split("\n"):
    s = line.strip()
    if s and ("install" in s.lower() or "error" in s.lower() or "number" in s.lower()) and not s.startswith("$"):
        print(f"  {s}")

# PulseAudio for audio monitoring (cava reads from pulseaudio monitor source)
print("\nInstalling PulseAudio...")
serial_buf = b""
send("pkg install -y pulseaudio 2>&1 | tail -15\n", 5)
print("  Waiting for PulseAudio install...")
wait_for("#", timeout=600)
drain()
output = serial_buf.decode(errors="replace")
for line in output.split("\n"):
    s = line.strip()
    if s and ("install" in s.lower() or "error" in s.lower() or "number" in s.lower()) and not s.startswith("$"):
        print(f"  {s}")

# Also install virtual_oss as backup for OSS loopback
print("\nInstalling virtual_oss...")
serial_buf = b""
send("pkg install -y virtual_oss 2>&1 | tail -5\n", 5)
wait_for("#", timeout=120)
drain()

# Check what we got installed
print("\n=== Verifying installations ===")
serial_buf = b""
for cmd in ["which gtop gotop bashtop bpytop 2>&1",
            "which tty-clock 2>&1",
            "which cava 2>&1",
            "which pulseaudio pactl 2>&1",
            "which virtual_oss 2>&1"]:
    send(f"{cmd}\n", 2)
time.sleep(5)
drain()
output = serial_buf.decode(errors="replace")
print("Installed binaries:")
for line in output.split("\n"):
    s = line.strip()
    if s and "/usr" in s and not s.startswith("$") and not s.startswith("which"):
        print(f"  {s}")

# Determine the system monitor binary
sysmon = None
for candidate in ["gtop", "gotop", "bashtop", "bpytop", "htop"]:
    serial_buf = b""
    send(f"which {candidate} 2>&1\n", 2)
    time.sleep(2)
    drain()
    if f"/usr/local/bin/{candidate}" in serial_buf.decode(errors="replace"):
        sysmon = candidate
        break
if sysmon:
    print(f"\nSystem monitor: {sysmon}")
else:
    print("\nNo system monitor found, installing htop as fallback...")
    send("pkg install -y htop 2>&1 | tail -5\n", 5)
    wait_for("#", timeout=120)
    sysmon = "htop"

# Configure PulseAudio to start with user session
print("\n=== Configuring PulseAudio ===")
# Enable PulseAudio for bsduser
send_cmd("pw groupmod pulse-access -m bsduser 2>/dev/null || true")
send_cmd("pw groupmod audio -m bsduser 2>/dev/null || true")

# Create PulseAudio config for bsduser to auto-start and load OSS module
send_cmd(f"mkdir -p {HOME}/.config/pulse")

# default.pa - load OSS module for SB16
pa_config = [
    '#!/usr/bin/pulseaudio -nF',
    '.include /usr/local/etc/pulse/default.pa',
    '# Load OSS output for SB16',
    'load-module module-oss device=/dev/dsp0',
    '# Create a monitor source so cava can read playback audio',
    'load-module module-null-sink sink_name=monitor_sink sink_properties=device.description="Monitor"',
    'load-module module-loopback source=monitor_sink.monitor sink=0',
    '# Set default sink to OSS',
    'set-default-sink 0',
]
write_lines(pa_config, f"{HOME}/.config/pulse/default.pa")

# client.conf - auto-start pulseaudio
pa_client = [
    'autospawn = yes',
    'daemon-binary = /usr/local/bin/pulseaudio',
]
write_lines(pa_client, f"{HOME}/.config/pulse/client.conf")

# Configure cava
print("\n=== Configuring cava ===")
send_cmd(f"mkdir -p {HOME}/.config/cava")

# cava config - use PulseAudio as input method
cava_config = [
    '[general]',
    'framerate = 30',
    'bars = 40',
    '',
    '[input]',
    'method = pulse',
    'source = auto',
    '',
    '[output]',
    'method = ncurses',
    '',
    '[color]',
    'gradient = 1',
    'gradient_count = 4',
    'gradient_color_1 = \'#ab1100\'',
    'gradient_color_2 = \'#ff3300\'',
    'gradient_color_3 = \'#ff6600\'',
    'gradient_color_4 = \'#ffaa00\'',
    '',
    '[smoothing]',
    'noise_reduction = 77',
]
write_lines(cava_config, f"{HOME}/.config/cava/config")

# Add PulseAudio autostart to i3 config (before any audio apps)
print("\n=== Updating i3 config ===")
send_cmd(f"grep -q 'pulseaudio' {HOME}/.config/i3/config || sed -i '' '/exec --no-startup-id.*watchdog/a\\'$'\\n''exec --no-startup-id pulseaudio --start' {HOME}/.config/i3/config")

# Fix ownership
send_cmd(f"chown -R bsduser:bsduser {HOME}/.config")

# Set DNS back for v86 fetch backend
print("\n=== Setting DNS for v86 ===")
send_cmd("echo 'nameserver 192.168.86.1' > /etc/resolv.conf")

# Final verification
print("\n=== Final verification ===")
serial_buf = b""
send("pkg info -a 2>&1 | grep -E 'gtop|gotop|bashtop|bpytop|htop|tty-clock|cava|pulseaudio|virtual_oss' | head -10\n", 5)
time.sleep(5)
drain()
print("Installed packages:")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$") and not s.startswith("#"):
        print(f"  {s}")

serial_buf = b""
send(f"cat {HOME}/.config/cava/config\n", 2)
time.sleep(2)
drain()
print("\nCava config:")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$") and not s.startswith("#") and not s.startswith("cat"):
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
