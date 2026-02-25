#!/usr/bin/env python3
"""Install Hybrid vim color scheme, powerline/Hack Nerd fonts, syntax highlighting."""
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

print("=== Install vim theme + fonts + syntax ===")
print("Waiting for boot...")
if not wait_for("login:", timeout=300):
    print("ERROR!"); proc.kill(); sys.exit(1)

time.sleep(1)
send("root\n", 3); drain()
send("/bin/sh\n", 1); drain()
send_cmd("service cron stop", timeout=10)
send_cmd("killall dhclient 2>/dev/null; true", timeout=5)

# Get network up with real DNS
print("Getting network...")
send("dhclient em0 2>&1\n", 20)
drain()
send_cmd("echo 'nameserver 8.8.8.8' > /etc/resolv.conf")

# 1. Install Hack Nerd Font
print("\n=== Installing fonts ===")
# Check what font packages exist
serial_buf = b""
send("pkg search nerd-font 2>&1 | head -10\n", 5)
send("pkg search hack-font 2>&1 | head -5\n", 5)
send("pkg search powerline-fonts 2>&1 | head -5\n", 5)
time.sleep(15)
drain()
output = serial_buf.decode(errors="replace")
print("Font packages:")
for line in output.split("\n"):
    s = line.strip()
    if s and ("font" in s.lower() or "nerd" in s.lower() or "hack" in s.lower() or "powerline" in s.lower()) and not s.startswith("$") and not s.startswith("#") and not s.startswith("pkg"):
        print(f"  {s}")

# Install Hack Nerd Font (or Hack font + powerline)
print("\nInstalling fonts...")
serial_buf = b""
send("pkg install -y nerd-fonts 2>&1 | tail -10\n", 5)
start = time.time()
while time.time() - start < 300:
    drain()
    output = serial_buf.decode(errors="replace")
    if "installed" in output.lower() or "already installed" in output.lower() or "No packages" in output:
        break
    time.sleep(5)
wait_for("#", timeout=60)
drain()
output = serial_buf.decode(errors="replace")
if "No packages" in output or "No matching" in output:
    print("  nerd-fonts not found, trying alternatives...")
    # Try hack-font or font-hack-ttf
    for font_pkg in ["font-hack-ttf", "hack-font", "powerline-fonts"]:
        serial_buf = b""
        send(f"pkg install -y {font_pkg} 2>&1 | tail -5\n", 5)
        wait_for("#", timeout=120)
        drain()
        if "installed" in serial_buf.decode(errors="replace").lower():
            print(f"  {font_pkg} installed")
            break
else:
    print("  nerd-fonts installed")

# Also try to get Hack font specifically
serial_buf = b""
send("pkg search hack 2>&1 | grep -i font | head -5\n", 5)
time.sleep(5)
drain()
output = serial_buf.decode(errors="replace")
for line in output.split("\n"):
    s = line.strip()
    if s and "hack" in s.lower() and not s.startswith("$"):
        print(f"  Found: {s}")

# Install whatever Hack font package exists
serial_buf = b""
send("pkg install -y hack-font 2>&1 | tail -5\n", 5)
wait_for("#", timeout=120)
drain()

# Update font cache
send_cmd("fc-cache -f 2>/dev/null || true", timeout=30)

# 2. Install vim with full features
print("\n=== Setting up vim ===")
serial_buf = b""
send("pkg search '^vim' 2>&1 | head -10\n", 5)
time.sleep(10)
drain()
output = serial_buf.decode(errors="replace")
print("Vim packages:")
for line in output.split("\n"):
    s = line.strip()
    if s and "vim" in s.lower() and not s.startswith("$") and not s.startswith("#") and not s.startswith("pkg"):
        print(f"  {s}")

# Install vim (full version with syntax highlighting)
print("Installing vim...")
serial_buf = b""
send("pkg install -y vim 2>&1 | tail -10\n", 5)
wait_for("#", timeout=300)
drain()
output = serial_buf.decode(errors="replace")
for line in output.split("\n"):
    s = line.strip()
    if s and ("install" in s.lower() or "already" in s.lower()) and not s.startswith("$"):
        print(f"  {s}")

# 3. Create Hybrid color scheme
# vim-hybrid is a dark colorscheme by w0ng
print("\n=== Installing Hybrid color scheme ===")
send_cmd(f"mkdir -p {HOME}/.vim/colors")
send_cmd(f"mkdir -p {HOME}/.vim/autoload")

# Download hybrid.vim colorscheme from GitHub
serial_buf = b""
send(f"fetch -o {HOME}/.vim/colors/hybrid.vim 'https://raw.githubusercontent.com/w0ng/vim-hybrid/master/colors/hybrid.vim' 2>&1\n", 5)
wait_for("#", timeout=30)
drain()
output = serial_buf.decode(errors="replace")
print("Hybrid download:")
for line in output.split("\n"):
    s = line.strip()
    if s and not s.startswith("$") and not s.startswith("#"):
        print(f"  {s}")

# Check if it downloaded
serial_buf = b""
send(f"ls -la {HOME}/.vim/colors/hybrid.vim 2>&1\n", 2)
time.sleep(2)
drain()
if "No such file" in serial_buf.decode(errors="replace"):
    print("  Download failed, writing hybrid.vim manually...")
    # Write a simplified but accurate Hybrid color scheme
    hybrid_colors = [
        '" Hybrid color scheme (w0ng)',
        '" A dark colour scheme for Vim',
        'set background=dark',
        'hi clear',
        'if exists("syntax_on")',
        '  syntax reset',
        'endif',
        'let g:colors_name = "hybrid"',
        '',
        '" Background and text',
        'hi Normal       ctermfg=250 ctermbg=234',
        'hi NonText      ctermfg=238 ctermbg=234',
        'hi SpecialKey   ctermfg=238 ctermbg=234',
        '',
        '" Cursor and selection',
        'hi Cursor       ctermfg=234 ctermbg=145',
        'hi CursorLine   ctermbg=235 cterm=NONE',
        'hi CursorColumn ctermbg=235',
        'hi Visual       ctermbg=237',
        'hi VisualNOS    ctermbg=237',
        '',
        '" Line numbers and columns',
        'hi LineNr       ctermfg=238 ctermbg=234',
        'hi CursorLineNr ctermfg=214 ctermbg=235',
        'hi SignColumn   ctermfg=145 ctermbg=234',
        'hi ColorColumn  ctermbg=235',
        '',
        '" Status line',
        'hi StatusLine   ctermfg=145 ctermbg=236',
        'hi StatusLineNC ctermfg=238 ctermbg=236',
        'hi VertSplit    ctermfg=236 ctermbg=236',
        '',
        '" Tabs',
        'hi TabLine      ctermfg=238 ctermbg=234',
        'hi TabLineFill  ctermfg=238 ctermbg=234',
        'hi TabLineSel   ctermfg=250 ctermbg=236',
        '',
        '" Folding',
        'hi Folded       ctermfg=145 ctermbg=235',
        'hi FoldColumn   ctermfg=145 ctermbg=234',
        '',
        '" Search and matching',
        'hi Search       ctermfg=234 ctermbg=214',
        'hi IncSearch    ctermfg=234 ctermbg=214',
        'hi MatchParen   ctermfg=NONE ctermbg=237 cterm=bold',
        '',
        '" Popup menu',
        'hi Pmenu        ctermfg=250 ctermbg=236',
        'hi PmenuSel     ctermfg=234 ctermbg=109',
        'hi PmenuSbar    ctermbg=237',
        'hi PmenuThumb   ctermbg=238',
        '',
        '" Messages',
        'hi ErrorMsg     ctermfg=167 ctermbg=234',
        'hi WarningMsg   ctermfg=214',
        'hi MoreMsg      ctermfg=109',
        'hi Question     ctermfg=109',
        'hi ModeMsg      ctermfg=109 cterm=bold',
        '',
        '" Diff',
        'hi DiffAdd      ctermfg=234 ctermbg=108',
        'hi DiffChange   ctermfg=234 ctermbg=109',
        'hi DiffDelete   ctermfg=234 ctermbg=167',
        'hi DiffText     ctermfg=234 ctermbg=214 cterm=bold',
        '',
        '" Syntax highlighting',
        'hi Comment      ctermfg=243',
        'hi Constant     ctermfg=173',
        'hi String       ctermfg=108',
        'hi Character    ctermfg=108',
        'hi Number       ctermfg=173',
        'hi Boolean      ctermfg=173',
        'hi Float        ctermfg=173',
        '',
        'hi Identifier   ctermfg=167',
        'hi Function     ctermfg=214',
        '',
        'hi Statement    ctermfg=109 cterm=NONE',
        'hi Conditional  ctermfg=109',
        'hi Repeat       ctermfg=109',
        'hi Label        ctermfg=109',
        'hi Operator     ctermfg=109',
        'hi Keyword      ctermfg=109',
        'hi Exception    ctermfg=109',
        '',
        'hi PreProc      ctermfg=109',
        'hi Include      ctermfg=109',
        'hi Define       ctermfg=109',
        'hi Macro        ctermfg=109',
        'hi PreCondit    ctermfg=109',
        '',
        'hi Type         ctermfg=214 cterm=NONE',
        'hi StorageClass ctermfg=214',
        'hi Structure    ctermfg=214',
        'hi Typedef      ctermfg=214',
        '',
        'hi Special      ctermfg=173',
        'hi SpecialChar  ctermfg=173',
        'hi Tag          ctermfg=167',
        'hi Delimiter    ctermfg=250',
        'hi Debug        ctermfg=167',
        '',
        'hi Underlined   ctermfg=109 cterm=underline',
        'hi Error        ctermfg=167 ctermbg=234 cterm=bold',
        'hi Todo         ctermfg=214 ctermbg=234 cterm=bold',
        '',
        '" Spell checking',
        'hi SpellBad     ctermbg=52',
        'hi SpellCap     ctermbg=17',
        'hi SpellLocal   ctermbg=17',
        'hi SpellRare    ctermbg=53',
        '',
        '" Directory listing',
        'hi Directory    ctermfg=109',
        'hi Title        ctermfg=214 cterm=bold',
    ]
    write_lines(hybrid_colors, f"{HOME}/.vim/colors/hybrid.vim")
else:
    print("  Hybrid colorscheme downloaded")

# 4. Create .vimrc with Hybrid theme and syntax highlighting
print("\n=== Writing .vimrc ===")
vimrc = [
    '" Hybrid color scheme',
    'set background=dark',
    'set t_Co=256',
    'colorscheme hybrid',
    '',
    '" Syntax highlighting',
    'syntax enable',
    'filetype plugin indent on',
    '',
    '" UI settings',
    'set number',
    'set relativenumber',
    'set cursorline',
    'set showmatch',
    'set laststatus=2',
    'set ruler',
    'set showcmd',
    'set wildmenu',
    'set wildmode=list:longest',
    '',
    '" Search',
    'set hlsearch',
    'set incsearch',
    'set ignorecase',
    'set smartcase',
    '',
    '" Indentation',
    'set tabstop=4',
    'set shiftwidth=4',
    'set expandtab',
    'set autoindent',
    'set smartindent',
    '',
    '" Performance',
    'set lazyredraw',
    'set ttyfast',
    '',
    '" Encoding',
    'set encoding=utf-8',
    'set fileencoding=utf-8',
    '',
    '" Backspace behavior',
    'set backspace=indent,eol,start',
    '',
    '" Status line',
    'set statusline=%f\\ %m%r%h%w\\ [%{&ff}/%Y]\\ [%l,%c]\\ [%p%%]',
    '',
    '" No swap files',
    'set noswapfile',
    'set nobackup',
    '',
    '" Mouse support',
    'set mouse=a',
    '',
    '" Split behavior',
    'set splitbelow',
    'set splitright',
]
write_lines(vimrc, f"{HOME}/.vimrc")

# Also write for root
write_lines(vimrc, "/root/.vimrc")

# 5. Update urxvt font to Hack (Nerd Font if available)
print("\n=== Updating terminal font ===")
# Check what Hack fonts are available
serial_buf = b""
send("fc-list 2>/dev/null | grep -i hack | head -10\n", 3)
time.sleep(3)
drain()
output = serial_buf.decode(errors="replace")
print("Hack fonts available:")
has_nerd = False
has_hack = False
for line in output.split("\n"):
    s = line.strip()
    if s and "hack" in s.lower() and not s.startswith("$"):
        print(f"  {s}")
        if "nerd" in s.lower():
            has_nerd = True
        elif "hack" in s.lower():
            has_hack = True

# Update .Xresources with the best available font
# Prefer: Hack Nerd Font > Hack > DejaVu Sans Mono
if has_nerd:
    font_name = "Hack Nerd Font Mono"
    print(f"  Using: {font_name}")
elif has_hack:
    font_name = "Hack"
    print(f"  Using: {font_name}")
else:
    font_name = "DejaVu Sans Mono"
    print(f"  Using: {font_name} (Hack not available)")

# Update .Xresources font
send_cmd(f"sed -i '' 's/DejaVu Sans Mono/{font_name}/g' {HOME}/.Xresources 2>/dev/null || true")
# Also set font size
send_cmd(f"sed -i '' 's/font:.*$/font: xft:{font_name}:size=11/' {HOME}/.Xresources 2>/dev/null || true")

# 6. Fish shell syntax highlighting
print("\n=== Installing fish syntax highlighting ===")
# fish has built-in syntax highlighting, but let's enhance it
# Install fish-shell if not already present (should be)
serial_buf = b""
send("which fish 2>&1\n", 2)
time.sleep(2)
drain()
if "/usr/local/bin/fish" in serial_buf.decode(errors="replace"):
    print("  fish is installed")
else:
    print("  Installing fish...")
    send("pkg install -y fish 2>&1 | tail -5\n", 5)
    wait_for("#", timeout=300)

# Configure fish syntax highlighting colors (dark theme matching Hybrid)
send_cmd(f"mkdir -p {HOME}/.config/fish/conf.d")
fish_colors = [
    '# Hybrid-inspired fish syntax highlighting colors',
    'set -g fish_color_normal normal',
    'set -g fish_color_command 5fafaf',       # blue-green (like Statement)',
    'set -g fish_color_param d7af87',          # tan (like Constant)',
    'set -g fish_color_keyword 5fafaf',        # blue-green',
    'set -g fish_color_quote 87af87',          # green (like String)',
    'set -g fish_color_redirection d7af87',    # tan',
    'set -g fish_color_end 5fafaf',            # blue-green',
    'set -g fish_color_error d75f5f',          # red (like Error)',
    'set -g fish_color_comment 767676',        # gray (like Comment)',
    'set -g fish_color_selection --background=3a3a3a',
    'set -g fish_color_search_match --background=3a3a3a',
    'set -g fish_color_operator d7af87',       # tan',
    'set -g fish_color_escape d7af87',         # tan',
    'set -g fish_color_autosuggestion 585858',
    'set -g fish_color_valid_path --underline',
    'set -g fish_pager_color_prefix d7af5f --bold',
    'set -g fish_pager_color_completion bcbcbc',
    'set -g fish_pager_color_description 767676',
    'set -g fish_pager_color_progress 5fafaf',
]
write_lines(fish_colors, f"{HOME}/.config/fish/conf.d/colors.fish")

# 7. Make vim the default editor
send_cmd(f"grep -q 'EDITOR' {HOME}/.config/fish/config.fish 2>/dev/null || echo 'set -gx EDITOR vim' >> {HOME}/.config/fish/config.fish")
send_cmd(f"grep -q 'VISUAL' {HOME}/.config/fish/config.fish 2>/dev/null || echo 'set -gx VISUAL vim' >> {HOME}/.config/fish/config.fish")

# Fix ownership
send_cmd(f"chown -R bsduser:bsduser {HOME}")

# Set DNS back for v86
send_cmd("echo 'nameserver 192.168.86.1' > /etc/resolv.conf")

# Final verification
print("\n=== Final verification ===")
serial_buf = b""
send(f"ls {HOME}/.vim/colors/\n", 2)
send(f"head -5 {HOME}/.vimrc\n", 2)
send(f"fc-list 2>/dev/null | grep -ci hack\n", 2)
send(f"head -3 {HOME}/.config/fish/conf.d/colors.fish\n", 2)
time.sleep(5)
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
