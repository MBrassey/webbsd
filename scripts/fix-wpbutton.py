#!/usr/bin/env python3
"""Add wallpaper refresh button to i3bar status script + a cycle-wallpaper helper."""

import subprocess, time, sys, os, socket

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(BASE, "images", "freebsd.img")

SERIAL_PORT = 45478
MONITOR_PORT = 45479
HOME = "/home/bsduser"

# Helper script to set a random wallpaper (called by i3bar click and by cycle loop)
CYCLE_WP_LINES = [
    '#!/bin/sh',
    'WP_DIR="/usr/local/share/wallpapers/freebsd-wallpapers"',
    'wp=$(find "$WP_DIR" -maxdepth 1 -type f -iname "*.png" 2>/dev/null | sort -R | head -1)',
    'if [ -z "$wp" ]; then',
    '    wp=$(find "$WP_DIR" -maxdepth 1 -type f -iname "*.jpg" 2>/dev/null | sort -R | head -1)',
    'fi',
    'if [ -n "$wp" ]; then',
    '    feh --bg-fill "$wp"',
    'fi',
]

# Updated status.sh with click support and wallpaper button
# i3bar click events come as JSON on stdin when click_events: true
STATUS_SH_LINES = [
    '#!/bin/sh',
    "S0=$(printf '\\342\\226\\201')",
    "S1=$(printf '\\342\\226\\202')",
    "S2=$(printf '\\342\\226\\203')",
    "S3=$(printf '\\342\\226\\204')",
    "S4=$(printf '\\342\\226\\205')",
    "S5=$(printf '\\342\\226\\206')",
    "S6=$(printf '\\342\\226\\207')",
    "S7=$(printf '\\342\\226\\210')",
    '_spark=""',
    'build_spark() {',
    '    _spark=""',
    '    for v in $1; do',
    '        idx=$((v * 7 / 100))',
    '        [ "$idx" -lt 0 ] && idx=0',
    '        [ "$idx" -gt 7 ] && idx=7',
    '        case $idx in',
    '            0) _spark="${_spark}${S0}" ;; 1) _spark="${_spark}${S1}" ;;',
    '            2) _spark="${_spark}${S2}" ;; 3) _spark="${_spark}${S3}" ;;',
    '            4) _spark="${_spark}${S4}" ;; 5) _spark="${_spark}${S5}" ;;',
    '            6) _spark="${_spark}${S6}" ;; *) _spark="${_spark}${S7}" ;;',
    '        esac',
    '    done',
    '}',
    'echo \'{"version":1,"click_events":true}\'',
    'echo \'[\'',
    'echo \'[]\'',
    'cpu_hist=""; mem_hist=""; cpu_n=0; mem_n=0; prev=""',
    'while true; do',
    '    cp=$(sysctl -n kern.cp_time)',
    '    if [ -n "$prev" ]; then',
    '        set -- $prev; pu=$1; pn=$2; ps=$3; pi=$4; pid=$5',
    '        set -- $cp; cu=$1; cn=$2; cs=$3; ci=$4; cid=$5',
    '        du=$((cu-pu)); dn=$((cn-pn)); ds=$((cs-ps)); di=$((ci-pi)); did=$((cid-pid))',
    '        t=$((du+dn+ds+di+did))',
    '        [ "$t" -gt 0 ] && cpu=$((100*(t-did)/t)) || cpu=0',
    '    else',
    '        cpu=0',
    '    fi',
    '    prev="$cp"',
    '    tp=$(sysctl -n vm.stats.vm.v_page_count)',
    '    fp=$(sysctl -n vm.stats.vm.v_free_count)',
    '    ip=$(sysctl -n vm.stats.vm.v_inactive_count)',
    '    used=$((tp-fp-ip))',
    '    [ "$tp" -gt 0 ] && mem=$((100*used/tp)) || mem=0',
    '    [ "$mem" -lt 0 ] && mem=0; [ "$mem" -gt 100 ] && mem=100',
    '    if [ -z "$cpu_hist" ]; then cpu_hist="$cpu"; else cpu_hist="$cpu_hist $cpu"; fi',
    '    if [ -z "$mem_hist" ]; then mem_hist="$mem"; else mem_hist="$mem_hist $mem"; fi',
    '    cpu_n=$((cpu_n+1)); mem_n=$((mem_n+1))',
    '    [ "$cpu_n" -gt 20 ] && { cpu_hist="${cpu_hist#* }"; cpu_n=20; }',
    '    [ "$mem_n" -gt 20 ] && { mem_hist="${mem_hist#* }"; mem_n=20; }',
    '    build_spark "$cpu_hist"; cpu_spark="$_spark"',
    '    build_spark "$mem_hist"; mem_spark="$_spark"',
    '    [ $cpu -ge 85 ] && cc="#ff3333" || { [ $cpu -ge 60 ] && cc="#ccaa00" || cc="#8899aa"; }',
    '    [ $mem -ge 90 ] && mc="#ff3333" || { [ $mem -ge 70 ] && mc="#ccaa00" || mc="#8899aa"; }',
    '    dt=$(date \'+%a %b %d  %H:%M\')',
    "    printf ','",
    "    printf '[{\"name\":\"wallpaper\",\"full_text\":\" \\u21bb WP \",\"color\":\"#5f87af\",\"separator\":false,\"separator_block_width\":12},'",
    '    printf \'{"full_text":" CPU %s %d%% ","color":"%s","separator":false,"separator_block_width":18},\' "$cpu_spark" "$cpu" "$cc"',
    '    printf \'{"full_text":" MEM %s %d%% ","color":"%s","separator":false,"separator_block_width":18},\' "$mem_spark" "$mem" "$mc"',
    "    printf '{\"full_text\":\" %s \",\"color\":\"#555555\",\"separator\":false}' \"$dt\"",
    "    printf ']\\n'",
    '    sleep 2',
    'done &',
    '',
    '# Read click events from i3bar',
    'while read line; do',
    '    case "$line" in',
    '        *wallpaper*)',
    '            /home/bsduser/.config/i3/cycle-wp.sh &',
    '            ;;',
    '    esac',
    'done',
]

print("=== Add wallpaper button to i3bar ===")

proc = subprocess.Popen(
    [
        "qemu-system-i386",
        "-m", "512",
        "-drive", f"file={IMAGE},format=raw,cache=writethrough",
        "-display", "none",
        "-serial", f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off",
        "-monitor", f"tcp:127.0.0.1:{MONITOR_PORT},server=on,wait=off",
        "-no-reboot",
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

time.sleep(2)

ser = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
ser.settimeout(1)
ser.connect(("127.0.0.1", SERIAL_PORT))

mon = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
mon.settimeout(5)
mon.connect(("127.0.0.1", MONITOR_PORT))
time.sleep(0.5)
try:
    mon.recv(4096)
except:
    pass

serial_buf = b""

def drain():
    global serial_buf
    while True:
        try:
            data = ser.recv(4096)
            if not data:
                break
            serial_buf += data
        except (socket.timeout, BlockingIOError):
            break

def wait_for(pattern, timeout=180):
    global serial_buf
    start = time.time()
    while time.time() - start < timeout:
        drain()
        if pattern.encode() in serial_buf:
            return True
        time.sleep(0.3)
    return False

def send(text, delay=0.5):
    ser.send(text.encode())
    time.sleep(delay)

def send_cmd(cmd, timeout=30):
    global serial_buf
    marker = f"__OK_{time.time_ns()}__"
    send(cmd + f" && echo {marker}\n", 0.5)
    if not wait_for(marker, timeout):
        print(f"  WARN: No confirm for: {cmd[:70]}...")
        return False
    drain()
    return True

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

print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!")
    proc.kill()
    sys.exit(1)

time.sleep(1)
send("root\n", 3)
drain()
send("/bin/sh\n", 1)
drain()
send_cmd("service cron stop", timeout=10)
send_cmd("killall dhclient 2>/dev/null; true", timeout=5)

# Write cycle-wp.sh helper
print("\n1. Writing cycle-wp.sh...")
write_lines(CYCLE_WP_LINES, f"{HOME}/.config/i3/cycle-wp.sh", executable=True)

# Write updated status.sh with click events
print("2. Writing status.sh with WP button...")
write_lines(STATUS_SH_LINES, f"{HOME}/.config/i3/status.sh", executable=True)

# Ownership
send_cmd(f"chown -R bsduser:bsduser {HOME}/.config")

# Shutdown
print("Syncing...")
send("sync\n", 3)
send("sync\n", 3)
send("mount -ur /\n", 2)
send("shutdown -p now\n", 5)

try:
    proc.wait(timeout=120)
except subprocess.TimeoutExpired:
    proc.kill()

mon.close()
ser.close()
print("Done!")
