#!/usr/bin/env python3
"""Fix disk full: remove huge nerd-fonts, install just hack-font, rewrite configs."""
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

print("=== Fix disk space ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)
send_cmd("killall dhclient 2>/dev/null; true", timeout=5)

# Check current disk usage
print("\n=== Current disk usage ===")
serial_buf = b""
send("df -h /\n", 2)
time.sleep(2)
drain()
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$"):
        print(f"  {s}")

# Remove massive nerd-fonts package (contains ALL nerd font families)
print("\n=== Removing nerd-fonts (too large) ===")
serial_buf = b""
send("pkg info -s nerd-fonts 2>&1\n", 3)
time.sleep(3)
drain()
output = serial_buf.decode(errors="replace")
for line in output.split("\n"):
    s = line.strip()
    if s and ("size" in s.lower() or "nerd" in s.lower()) and not s.startswith("$"):
        print(f"  {s}")

send("pkg delete -y nerd-fonts 2>&1 | tail -5\n", 5)
wait_for("#", timeout=120)
drain()

# Clean up pkg cache
send_cmd("pkg clean -y 2>/dev/null || true", timeout=30)
send_cmd("rm -rf /var/cache/pkg/* 2>/dev/null || true", timeout=10)

# Check free space now
serial_buf = b""
send("df -h /\n", 2)
time.sleep(2)
drain()
print("\nDisk after cleanup:")
for line in serial_buf.decode(errors="replace").split("\n"):
    s = line.strip()
    if s and not s.startswith("$"):
        print(f"  {s}")

# Get network for installing hack-font
print("\n=== Getting network ===")
send("dhclient em0 2>&1\n", 20)
drain()
send_cmd("echo 'nameserver 8.8.8.8' > /etc/resolv.conf")

# Install just hack-font (much smaller than all nerd-fonts)
print("\n=== Installing hack-font ===")
serial_buf = b""
send("pkg install -y hack-font 2>&1 | tail -10\n", 5)
wait_for("#", timeout=120)
drain()
output = serial_buf.decode(errors="replace")
for line in output.split("\n"):
    s = line.strip()
    if s and ("install" in s.lower() or "already" in s.lower()) and not s.startswith("$"):
        print(f"  {s}")

# Update font cache
send_cmd("fc-cache -f 2>/dev/null || true", timeout=30)

# Check what Hack fonts we have
serial_buf = b""
send("fc-list 2>/dev/null | grep -i hack | head -10\n", 3)
time.sleep(3)
drain()
output = serial_buf.decode(errors="replace")
print("\nHack fonts:")
for line in output.split("\n"):
    s = line.strip()
    if s and "hack" in s.lower() and not s.startswith("$"):
        print(f"  {s}")

# Update .Xresources with Hack font
print("\n=== Updating terminal font ===")
send_cmd(f"sed -i '' 's/Hack Nerd Font Mono/Hack/g' {HOME}/.Xresources 2>/dev/null || true")
# Make sure font line is correct
serial_buf = b""
send(f"grep -i font {HOME}/.Xresources 2>&1\n", 2)
time.sleep(2)
drain()
output = serial_buf.decode(errors="replace")
print("Current font in .Xresources:")
for line in output.split("\n"):
    s = line.strip()
    if s and "font" in s.lower() and not s.startswith("$") and not s.startswith("grep"):
        print(f"  {s}")

# Re-download hybrid.vim (may have been corrupted by disk full)
print("\n=== Re-downloading Hybrid colorscheme ===")
send_cmd(f"rm -f {HOME}/.vim/colors/hybrid.vim")
serial_buf = b""
send(f"fetch -o {HOME}/.vim/colors/hybrid.vim 'https://raw.githubusercontent.com/w0ng/vim-hybrid/master/colors/hybrid.vim' 2>&1\n", 5)
wait_for("#", timeout=30)
drain()
output = serial_buf.decode(errors="replace")
if "write failed" in output or "No such file" in output:
    print("  Download failed, writing manually...")
    hybrid_colors = [
        '" Hybrid color scheme (w0ng)',
        'set background=dark',
        'hi clear',
        'if exists("syntax_on")',
        '  syntax reset',
        'endif',
        'let g:colors_name = "hybrid"',
        '',
        'hi Normal       ctermfg=250 ctermbg=234',
        'hi NonText      ctermfg=238 ctermbg=234',
        'hi Cursor       ctermfg=234 ctermbg=145',
        'hi CursorLine   ctermbg=235 cterm=NONE',
        'hi Visual       ctermbg=237',
        'hi LineNr       ctermfg=238 ctermbg=234',
        'hi CursorLineNr ctermfg=214 ctermbg=235',
        'hi SignColumn   ctermfg=145 ctermbg=234',
        'hi StatusLine   ctermfg=145 ctermbg=236',
        'hi StatusLineNC ctermfg=238 ctermbg=236',
        'hi VertSplit    ctermfg=236 ctermbg=236',
        'hi Folded       ctermfg=145 ctermbg=235',
        'hi Search       ctermfg=234 ctermbg=214',
        'hi IncSearch    ctermfg=234 ctermbg=214',
        'hi MatchParen   ctermfg=NONE ctermbg=237 cterm=bold',
        'hi Pmenu        ctermfg=250 ctermbg=236',
        'hi PmenuSel     ctermfg=234 ctermbg=109',
        'hi ErrorMsg     ctermfg=167 ctermbg=234',
        'hi WarningMsg   ctermfg=214',
        'hi MoreMsg      ctermfg=109',
        'hi DiffAdd      ctermfg=234 ctermbg=108',
        'hi DiffChange   ctermfg=234 ctermbg=109',
        'hi DiffDelete   ctermfg=234 ctermbg=167',
        'hi DiffText     ctermfg=234 ctermbg=214 cterm=bold',
        'hi Comment      ctermfg=243',
        'hi Constant     ctermfg=173',
        'hi String       ctermfg=108',
        'hi Number       ctermfg=173',
        'hi Boolean      ctermfg=173',
        'hi Identifier   ctermfg=167',
        'hi Function     ctermfg=214',
        'hi Statement    ctermfg=109 cterm=NONE',
        'hi Conditional  ctermfg=109',
        'hi Repeat       ctermfg=109',
        'hi Operator     ctermfg=109',
        'hi Keyword      ctermfg=109',
        'hi PreProc      ctermfg=109',
        'hi Type         ctermfg=214 cterm=NONE',
        'hi StorageClass ctermfg=214',
        'hi Special      ctermfg=173',
        'hi Tag          ctermfg=167',
        'hi Delimiter    ctermfg=250',
        'hi Underlined   ctermfg=109 cterm=underline',
        'hi Error        ctermfg=167 ctermbg=234 cterm=bold',
        'hi Todo         ctermfg=214 ctermbg=234 cterm=bold',
        'hi Directory    ctermfg=109',
        'hi Title        ctermfg=214 cterm=bold',
        'hi SpecialKey   ctermfg=238',
        'hi ColorColumn  ctermbg=235',
        'hi SpellBad     ctermbg=52',
    ]
    write_lines(hybrid_colors, f"{HOME}/.vim/colors/hybrid.vim")
else:
    # Check file size
    serial_buf = b""
    send(f"wc -c {HOME}/.vim/colors/hybrid.vim 2>&1\n", 2)
    time.sleep(2)
    drain()
    output = serial_buf.decode(errors="replace")
    print(f"  Downloaded: {output.strip()}")

# Re-write fish color config (may have failed due to disk full)
print("\n=== Rewriting fish colors ===")
fish_colors = [
    '# Hybrid-inspired fish syntax highlighting colors',
    'set -g fish_color_normal normal',
    'set -g fish_color_command 5fafaf',
    'set -g fish_color_param d7af87',
    'set -g fish_color_keyword 5fafaf',
    'set -g fish_color_quote 87af87',
    'set -g fish_color_redirection d7af87',
    'set -g fish_color_end 5fafaf',
    'set -g fish_color_error d75f5f',
    'set -g fish_color_comment 767676',
    'set -g fish_color_selection --background=3a3a3a',
    'set -g fish_color_search_match --background=3a3a3a',
    'set -g fish_color_operator d7af87',
    'set -g fish_color_escape d7af87',
    'set -g fish_color_autosuggestion 585858',
    'set -g fish_color_valid_path --underline',
    'set -g fish_pager_color_prefix d7af5f --bold',
    'set -g fish_pager_color_completion bcbcbc',
    'set -g fish_pager_color_description 767676',
    'set -g fish_pager_color_progress 5fafaf',
]
write_lines(fish_colors, f"{HOME}/.config/fish/conf.d/colors.fish")

# Fix ownership
send_cmd(f"chown -R bsduser:bsduser {HOME}")

# Set DNS for v86
send_cmd("echo 'nameserver 192.168.86.1' > /etc/resolv.conf")

# Final disk check
serial_buf = b""
send("df -h /\n", 2)
time.sleep(2)
drain()
print("\nFinal disk usage:")
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
