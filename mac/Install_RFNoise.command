#!/bin/bash
# ==============================================================================
#  RF Noise Map - Mac installer
#  Double-click this file (first time: right-click it > Open > Open).
#  It tells you what it is about to do before each step. Safe to run again.
# ==============================================================================
cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"
APPSRC="$HERE/app"
[ -f "$APPSRC/rfmap_app.py" ] || APPSRC="$HERE/../app"      # the repository layout has app/ one level up
DEST="$HOME/Applications/RF Noise Map"
DATA="$HOME/RF Noise Map"      # not under Documents: macOS blocks programs from Documents/Desktop/Downloads
OLDDATA="$HOME/Documents/RF Noise Map"
APPBUNDLE="$HOME/Applications/RF Noise Map.app"

# ---- the install log: a new file every run, all kept (the newest 10) in  ~/RF Noise Map/Logs  ----------------------
STAMP="$(date +%Y%m%d_%H%M%S)"
LOGDIR="$DATA/Logs"
mkdir -p "$DATA" "$LOGDIR" "$HOME/Applications"
LOG="$LOGDIR/install_log_$STAMP.txt"
LASTLOG="$DATA/install_log.txt"          # always a copy of the newest log, easy to find
: > "$LOG"
WARNINGS=()
# Lines the installer itself writes start with "[installer]" in the log; everything else is raw output of the tools it runs.
say()  { echo "$*"; printf '%s\n' "$*" | sed 's/^/[installer] /' >> "$LOG"; }
step() { echo; echo "------------------------------------------------------------"; say "STEP $1"; shift; say "$*"; echo; }
ask()  { local a; read -r -p "$1 [y/n] " a; [[ "$a" == "y" || "$a" == "Y" ]]; }
note_warn() { WARNINGS+=("$*"); }
finish_log() {
    cp "$LOG" "$LASTLOG" 2>/dev/null
    ls -t "$LOGDIR"/install_log_*.txt 2>/dev/null | tail -n +11 | while read -r f; do rm -f "$f"; done
}
trap finish_log EXIT
trap 'say "Installer stopped with Ctrl+C."; exit 130' INT
pause_exit() { echo; read -r -p "Press Return to close this window..." _; exit "${1:-0}"; }
log_since() { tail -n +"$(( $1 + 1 ))" "$LOG" | grep -v '^\[installer\]'; }          # raw tool output written after line $1
log_mark()  { wc -l < "$LOG" | tr -d ' '; }

# --- DIAG-BEGIN  (the problem finder: it reads what went wrong and explains it in plain words)
DIAG_N=0; DIAG_URL=""; DIAG_IN=""
rule() {   # pattern | short title | what it means | what to do | web page (optional)
    if printf '%s\n' "$DIAG_IN" | grep -Eiq -- "$1"; then
        DIAG_N=$((DIAG_N + 1))
        [ "$DIAG_N" -gt 3 ] && return
        say ""
        say "  >> LIKELY CAUSE $DIAG_N: $2"
        say "     What it means: $3"
        say "     What to do:    $4"
        if [ -n "$5" ]; then say "     More help:     $5"; [ -z "$DIAG_URL" ] && DIAG_URL="$5"; fi
    fi
}
diagnose() {
    DIAG_IN="$1"; DIAG_N=0; DIAG_URL=""
    rule "cstring.*file not found|c\+\+/v1.*not found|fatal error:.*file not found" \
        "The Mac's compiler tools are incomplete (missing C++ headers)" \
        "Apple's 'Command Line Tools' did not install fully, so the radio driver module cannot be built." \
        "In Terminal paste this, press Return, wait for the install window to finish, then run this installer again:  sudo rm -rf /Library/Developer/CommandLineTools ; xcode-select --install" \
        "https://developer.apple.com/documentation/xcode/installing-the-command-line-tools/"
    rule "xcrun: error: invalid active developer path|no developer tools were found|xcode-select: error|CommandLineTools.*(missing|not found)" \
        "Apple's developer tools are not installed" \
        "The Mac needs the free Command Line Tools (for git, Python and the compiler)." \
        "In Terminal type  xcode-select --install  and click Install in the window that appears. When it finishes, run this installer again." \
        "https://developer.apple.com/documentation/xcode/installing-the-command-line-tools/"
    rule "Library not loaded.*sdrplay|libsdrplay_api.*(not found|image not found|no such file)|dlopen.*sdrplay" \
        "The radio driver module cannot find the SDRplay library" \
        "The driver module was built, but it points at a differently named SDRplay file, or the SDRplay API is not installed." \
        "Install the SDRplay API (macOS) from sdrplay.com, restart the Mac, then run this installer again and answer y to the radio driver step (it re-points the module for you)." \
        "https://www.sdrplay.com/softwarehome/"
    rule "is not writable|Permission denied.*(homebrew|/usr/local|/opt)|Error: .*not writable|cannot create .*(Cellar|Homebrew)" \
        "Homebrew does not own its folders" \
        "Homebrew (the tool that installs the radio library) cannot write to its own folders, usually because it was first set up with another account." \
        "Run this installer again and answer y when it offers to fix Homebrew permissions (it asks for your Mac password). Or in Terminal:  sudo chown -R \"\$(whoami)\" /opt/homebrew" \
        "https://docs.brew.sh/FAQ"
    rule "Could not resolve host|Network is unreachable|Connection (timed out|refused|reset)|curl: \(6\)|curl: \(7\)|curl: \(28\)|curl: \(35\)|CERTIFICATE_VERIFY_FAILED|Temporary failure in name resolution|ProxyError|Failed to establish a new connection|Read timed out|Name or service not known" \
        "The Mac could not reach the internet" \
        "The installer downloads two small helper libraries and (for the radio) the driver source. The download did not complete." \
        "Check Wi-Fi, turn off any VPN or content filter for a few minutes, then run this installer again. It is safe to run as often as you like." \
        "https://pypi.org/"
    rule "No matching distribution found|Could not find a version that satisfies|externally-managed-environment|Could not install packages due to" \
        "Python could not install numpy or pyserial" \
        "Usually no internet, or the Python found is too old (3.8 or newer is needed)." \
        "Connect to the internet and run this installer again. If it keeps failing, delete the folder  ~/Applications/RF Noise Map/venv  and run the installer again." \
        "https://www.python.org/downloads/macos/"
    rule "incompatible architecture|have .x86_64., need .arm64|mach-o.*wrong architecture|importing the numpy C-extensions failed" \
        "The program was started in Intel (Rosetta) mode on an Apple-silicon Mac" \
        "The libraries are built for the Apple chip, but something started the program through Rosetta (Intel emulation)." \
        "Start RF Noise Map from its Desktop icon (it always starts natively). If you run the installer in Terminal, make sure Terminal is not set to 'Open using Rosetta' (Finder > Applications > Utilities > Terminal > Get Info)." \
        ""
    rule "No space left on device|Not enough space|disk is full|Disk quota exceeded" \
        "The Mac's disk is full" \
        "There is no room to unpack the program or build the driver." \
        "Free up a few GB (empty the Trash, delete old downloads), then run this installer again." \
        "https://support.apple.com/guide/mac-help/free-up-storage-space-mchlp2206/mac"
    rule "Operation not permitted|not permitted to access|PermissionError.*(Documents|Desktop|Downloads)" \
        "macOS privacy protection is blocking a folder" \
        "macOS does not let programs started from icons read Documents, Desktop or Downloads unless you allow it." \
        "RF Noise Map keeps its data in the 'RF Noise Map' folder in your home folder to avoid this. If the message names another folder: System Settings > Privacy & Security > Files and Folders (or Full Disk Access), switch on Terminal, then run the installer again." \
        "https://support.apple.com/guide/mac-help/control-access-to-files-and-folders-on-mac-mchl534f1b08/mac"
    rule "Address already in use|Errno 48" \
        "Another copy of RF Noise Map is already running" \
        "Two copies cannot use the same network port." \
        "Press the Desktop icon and choose 'Close it and start fresh', or in Terminal type:  pkill -f rfmap_app.py  then try again." \
        ""
    rule "no SDRplay found|sdrplay_api_Open|sdrplay_api.*(fail|error)|SDRplay (API )?service|Failed to open sdrplay|SDRplay.*not (found|detected)" \
        "The SDRplay radio is not being found" \
        "The radio is unplugged or on a hub, the SDRplay background service is not running, or another SDR program has the radio." \
        "(1) Plug the radio straight into the Mac. (2) Quit SDRuno, SDR++, CubicSDR and similar programs. (3) Restart the SDRplay service: in Terminal  sudo killall -9 sdrplay_apiService  (it restarts by itself), or restart the Mac. (4) Check the SDRplay API is version 3.15 or newer. Then press 'Check setup' in the RF Noise Map panel." \
        "https://www.sdrplay.com/softwarehome/"
    rule "SoapySDR.*(not found|not installed|not available)|radio library.*(not available|missing)|No module named .SoapySDR" \
        "The SoapySDR radio library is not set up" \
        "The program cannot find the library that talks to the SDRplay (practice mode and maps still work)." \
        "Run this installer again and answer y at the radio-driver step. You need the SDRplay API (from sdrplay.com) installed first, then Homebrew, which the installer offers to set up." \
        "https://github.com/pothosware/SoapySDRPlay3"
    rule "CMake Error|command not found: cmake|cmake: command not found" \
        "The driver module could not be built (cmake)" \
        "The build tool cmake is missing, or the compiler tools are incomplete." \
        "Run this installer again (it installs cmake through Homebrew). If it still fails, install the Command Line Tools:  xcode-select --install" \
        "https://brew.sh/"
    rule "fatal: unable to access|git clone.*(failed|fatal)|command not found: git|xcode-select: note: no developer tools" \
        "The driver source could not be downloaded (git)" \
        "Either there is no internet, or Apple's developer tools (which include git) are not installed." \
        "Check the internet, then in Terminal type  xcode-select --install  and run this installer again." \
        ""
    rule "Homebrew did not install|brew: command not found|command not found: brew" \
        "Homebrew is not installed" \
        "Homebrew is the standard Mac tool that installs the radio library." \
        "Install it from brew.sh (the installer can do this for you: answer y when asked). It asks for your Mac password." \
        "https://brew.sh/"
    rule "cannot be opened because Apple cannot check|can.t be opened because Apple cannot check|damaged and can.t be opened|unidentified developer" \
        "macOS Gatekeeper is blocking a downloaded file" \
        "macOS blocks files from the internet until you approve them once." \
        "Click Done (never Move to Trash). Open System Settings > Privacy & Security, scroll down, click 'Open Anyway' next to the file name, and enter your Mac password." \
        "https://support.apple.com/guide/mac-help/open-a-mac-app-from-an-unidentified-developer-mh40616/mac"
    rule "python3.*(command not found|No such file)|Python 3 is not available|No module named .venv|ensurepip" \
        "Python 3 is missing or incomplete" \
        "The program's private Python environment could not be made." \
        "In Terminal type  xcode-select --install  (this provides Python 3), wait for it to finish, then run this installer again." \
        "https://www.python.org/downloads/macos/"
    rule "No module named .numpy.|No module named .serial." \
        "The helper libraries (numpy, pyserial) are not installed" \
        "The radio maths library is missing from the program's private Python." \
        "Run this installer again with the internet connected; it installs them." \
        ""
    if [ "$DIAG_N" -eq 0 ] && [ -z "$2" ]; then
        say ""
        say "  I could not match this to a known problem."
        say "  What to do: run this installer again (it is safe to repeat). If it fails the same way, make the support file below and send it to KW4EX or Claude."
        say "  More help:  https://github.com/kw4ex/RFNoise-Mapping/issues"
        DIAG_URL=""
    fi
}
# --- DIAG-END

snapshot() {
    echo "---- system snapshot ----"
    echo "Date: $(date)"
    echo "macOS: $(sw_vers -productName 2>/dev/null) $(sw_vers -productVersion 2>/dev/null) ($(sw_vers -buildVersion 2>/dev/null))"
    echo "Chip: $(uname -m)   running through Rosetta: $(sysctl -n sysctl.proc_translated 2>/dev/null || echo n/a)"
    echo "Free disk in home folder: $(df -h "$HOME" 2>/dev/null | awk 'NR==2{print $4}')"
    if xcode-select -p >/dev/null 2>&1; then
        echo "Command Line Tools: $(xcode-select -p)   SDK: $(xcrun --show-sdk-path 2>/dev/null)"
        echo "python3: $(command -v python3) $(python3 --version 2>&1)"
    else
        echo "Command Line Tools: NOT INSTALLED"
        echo "python3: $(command -v python3) (Apple's placeholder only, no developer tools)"
    fi
    echo "Homebrew: $(ls -d /opt/homebrew/bin/brew /usr/local/bin/brew 2>/dev/null | tr '\n' ' ')"
    echo "SDRplay API installed: $([ -f /usr/local/include/sdrplay_api.h ] && echo yes || echo no)   service running: $(pgrep -f sdrplay_apiService >/dev/null 2>&1 && echo yes || echo no)"
    echo "Installer folder: $HERE"
    echo "Installed program: $([ -f "$DEST/app/rfmap_app.py" ] && echo "yes ($DEST)" || echo no)"
    echo "-------------------------"
}
make_support_zip() {
    local z="$LOGDIR/RFNoise_install_support_$STAMP.zip" tmpd; tmpd="$(mktemp -d)"
    snapshot > "$tmpd/system_snapshot.txt" 2>&1
    cp "$LOG" "$tmpd/" 2>/dev/null
    [ -f "$LOGDIR/program_errors.log" ] && cp "$LOGDIR/program_errors.log" "$tmpd/"
    [ -f "$DATA/Settings/logger.log" ] && cp "$DATA/Settings/logger.log" "$tmpd/"
    [ -f "$HOME/Library/Logs/RFNoiseMap.log" ] && tail -n 600 "$HOME/Library/Logs/RFNoiseMap.log" > "$tmpd/RFNoiseMap_launcher_log_last_600_lines.txt"
    ( cd "$tmpd" && zip -q -r "$z" . ) 2>/dev/null
    rm -rf "$tmpd"
    if [ -f "$z" ]; then
        say "Support file made: $z"
        say "It holds logs and system details only (no drives, no passwords). Send it to KW4EX or Claude."
        open -R "$z" 2>/dev/null
    else
        say "Could not make the zip file. Please send the log instead: $LASTLOG"
    fi
}
offer_support() {
    echo
    say "I can put everything needed to diagnose this into ONE small zip file (logs only; nothing is sent anywhere)."
    if ask "Make that support file now?"; then make_support_zip; fi
}
fail() {
    echo; say "PROBLEM: $*"
    diagnose "$(tail -n 120 "$LOG" | grep -v '^\[installer\]')
$*"
    say ""
    say "(Everything shown here is saved in: $LOG)"
    if [ -n "$DIAG_URL" ] && ask "Open the help page now?"; then open "$DIAG_URL" 2>/dev/null; fi
    offer_support
    pause_exit 1
}

say "RF Noise Map installer - $(date)"
snapshot | while IFS= read -r l; do printf '[installer] %s\n' "$l" >> "$LOG"; done

preflight() {
    local maj avail
    maj="$(sw_vers -productVersion 2>/dev/null | cut -d. -f1)"
    [ -n "$maj" ] && [ "$maj" -lt 11 ] 2>/dev/null && { say "NOTE: this Mac runs an older macOS ($maj). The program may still work, but macOS 11 or newer is recommended."; note_warn "old macOS"; }
    if [ "$(sysctl -n sysctl.proc_translated 2>/dev/null)" = "1" ]; then
        say "WARNING: this Terminal window is running through Rosetta (Intel mode) on an Apple-silicon Mac."
        say "         That can break the radio maths library. Fix: Finder > Applications > Utilities > Terminal > Get Info > untick 'Open using Rosetta', then run this installer again."
        note_warn "Terminal is in Rosetta mode"
    fi
    avail="$(df -m "$HOME" 2>/dev/null | awk 'NR==2{print $4}')"
    if [ -n "$avail" ] && [ "$avail" -lt 300 ] 2>/dev/null; then
        say "PROBLEM: only $avail MB of disk space is free. I need at least 300 MB."
        diagnose "No space left on device"
        offer_support; pause_exit 1
    elif [ -n "$avail" ] && [ "$avail" -lt 1500 ] 2>/dev/null; then
        say "NOTE: only $avail MB is free. The program needs little, but the optional radio driver build needs about 1.5 GB (including Homebrew)."
    fi
    case "$HERE" in *AppTranslocation*)
        say "WARNING: macOS is running this installer from a temporary protected copy (App Translocation), so it cannot see the 'app' folder next to it."
        say "         Fix: move the unzipped folder out of Downloads into your home folder, then open the installer again."
        note_warn "installer was translocated";;
    esac
    if ! curl -sI -m 8 https://pypi.org >/dev/null 2>&1; then
        say "WARNING: I could not reach the internet (pypi.org). The step that downloads two helper libraries will fail without it."
        note_warn "no internet at start"
    fi
}

health_check() {
    echo; echo "------------------------------------------------------------"
    say "CHECKING YOUR SETUP (nothing is changed)"
    local PYV="$DEST/venv/bin/python" bad=0 out txt=""
    chk() { if [ "$1" = ok ]; then say "  [ OK  ] $2"; else say "  [FIX  ] $2"; bad=$((bad+1)); fi; }
    [ -f "$DEST/app/rfmap_app.py" ] && chk ok "Program installed in $DEST" || chk bad "Program is not installed (run option 1 of this installer)"
    if [ -x "$PYV" ] && "$PYV" --version >/dev/null 2>&1; then chk ok "Private Python works ($("$PYV" --version 2>&1))"; else chk bad "Private Python environment is missing or broken (run option 1 to rebuild it)"; fi
    out="$("$PYV" -c "import numpy, serial; print('numpy', numpy.__version__)" 2>&1)"
    if [ $? -eq 0 ]; then chk ok "Helper libraries present ($out)"; else chk bad "Helper libraries (numpy, pyserial) are not working"; txt="$txt
$out"; fi
    [ -x "$APPBUNDLE/Contents/MacOS/launcher" ] && chk ok "Desktop/Applications icon is present" || chk bad "The app icon is missing (run option 1)"
    [ -w "$DATA/Logs" ] && chk ok "Data folder is writable ($DATA)" || chk bad "Cannot write to the data folder $DATA"
    if [ -f /usr/local/include/sdrplay_api.h ]; then chk ok "SDRplay API installed"; else say "  [info ] SDRplay API not installed (only needed for the real radio; practice mode works without it)"; fi
    if pgrep -f sdrplay_apiService >/dev/null 2>&1; then chk ok "SDRplay service is running"; else say "  [info ] SDRplay service is not running (it starts after the API is installed and the Mac restarted)"; fi
    if [ -x "$PYV" ] && [ -f "$DEST/app/check_setup.py" ]; then
        out="$(cd "$DEST/app" && "$PYV" check_setup.py 2>&1 | grep -v "SoapyVOLKConverters")"; printf '%s\n' "$out" >> "$LOG"
        say "  Radio and setup check:"; printf '%s\n' "$out" | sed 's/^/        /'
        txt="$txt
$out"
    fi
    if curl -s -m 2 http://127.0.0.1:8780/api/ping 2>/dev/null | grep -q rfmap; then say "  [info ] RF Noise Map is running right now (port 8780)"; fi
    if [ -f "$LOGDIR/program_errors.log" ]; then
        local errs; errs="$(grep -c ' ERROR ' "$LOGDIR/program_errors.log" 2>/dev/null)"
        say "  Program error log: $errs error(s) recorded. The newest:"
        grep ' ERROR ' "$LOGDIR/program_errors.log" | tail -n 5 | sed 's/^/        /'
        txt="$txt
$(tail -n 60 "$LOGDIR/program_errors.log")"
    else
        say "  Program error log: empty so far (no problems recorded)."
    fi
    echo
    if [ "$bad" -eq 0 ]; then say "Everything that can be checked here looks fine."
    else say "$bad item(s) marked [FIX] above need attention. Choose 1 (Install or update) in this installer to repair them."; fi
    diagnose "$txt" quiet
    offer_support
}

preflight

clear
cat <<'EOF'
============================================================
   RF NOISE MAP  -  installer for Mac
============================================================
What would you like to do?

  1)  Install or update RF Noise Map  (this also repairs a broken install)
  2)  Check my setup and make a support file  (changes nothing)
  3)  Uninstall RF Noise Map

EOF
read -r -p "Type 1, 2 or 3 and press Return [1]: " CHOICE
case "$CHOICE" in
    2) health_check; pause_exit 0 ;;
    3) if [ -f "$HERE/Uninstall_RFNoise.command" ]; then bash "$HERE/Uninstall_RFNoise.command"; else bash "$HERE/mac/Uninstall_RFNoise.command"; fi; pause_exit 0 ;;
esac
cat <<'EOF'

This will:
  1. Copy the program into  Applications/RF Noise Map
  2. Set up its private Python environment (no changes to your system Python)
  3. Create a folder  RF Noise Map  in your home folder for your data
  4. Put an "RF Noise Map" icon on your Desktop and in Applications
  5. (Optional) help you install the SDRplay radio driver
     (a Hermes Lite 2 needs NO driver - if that is your radio, say n at that step)
  6. Run a quick self-test with practice data

Nothing is sent anywhere. Everything it does is written to a log that is kept:
   ~/RF Noise Map/Logs/   (if anything goes wrong it explains the likely cause)
You can run this installer again at any time.
EOF
echo
ask "Ready to start?" || pause_exit 0

# ------------------------------------------------------------------------------
step 1 "I am about to check the program files in this folder."
[ -f "$APPSRC/rfmap_app.py" ] || fail "I can't find the 'app' folder. Download the Mac zip from the Releases page (or the whole repository) and keep the folders together; don't move this file out by itself."
say "Found the program files."
# macOS marks downloaded files "from the internet" and then refuses to run each one. Clear that mark for this whole
# unzipped folder so the other files here (like the uninstaller) open normally. Local, harmless.
xattr -dr com.apple.quarantine "$HERE" 2>/dev/null
[ -d "$HERE/../app" ] && xattr -dr com.apple.quarantine "$HERE/../app" 2>/dev/null

# ------------------------------------------------------------------------------
step 2 "I am about to look for Homebrew (a standard Mac tool installer, only needed for the radio driver)."
BREW=""; WRONGBREW=""
ARCH="$(uname -m)"
if [ "$ARCH" = "arm64" ]; then
    # Apple-silicon Mac: the right Homebrew lives in /opt/homebrew. One in /usr/local is the old Intel kind
    # (it cannot be written to without extra steps and mixes up the radio driver), so do not use it.
    [ -x /opt/homebrew/bin/brew ] && BREW=/opt/homebrew/bin/brew
    [ -z "$BREW" ] && [ -x /usr/local/bin/brew ] && WRONGBREW=/usr/local/bin/brew
else
    for b in /usr/local/bin/brew /opt/homebrew/bin/brew; do [ -x "$b" ] && BREW="$b" && break; done
fi
if [ -n "$BREW" ]; then
    eval "$($BREW shellenv)"; say "Homebrew found at $BREW"
elif [ -n "$WRONGBREW" ]; then
    say "I found an older Intel-type Homebrew ($WRONGBREW) on this Apple-silicon Mac. I will not use it."
    say "If you set up the radio driver, I can install the correct Apple-silicon Homebrew next to it (your old one is left alone)."
else
    say "Homebrew not installed (only needed for the SDRplay radio driver)."
fi

# ------------------------------------------------------------------------------
step 3 "RADIO DRIVER (optional - needed ONLY for the SDRplay receiver).
A Hermes Lite 2 connects by network cable and needs NO driver: if that is your
radio, answer n here and you are done with this step. The SDRplay driver is not
mine to include; it comes from sdrplay.com. I can walk you through it now. If
you only want Practice mode and maps, answer n - you can run this again later."
RADIO_OK=0
if ask "Set up the SDRplay radio driver now?"; then
    if [ ! -f /usr/local/include/sdrplay_api.h ]; then
        say "The SDRplay API is not installed yet."
        echo "I am about to open the SDRplay download page in your browser."
        echo "  1) Choose macOS, download the API installer, and run it."
        echo "  2) When it finishes, RESTART the Mac (the SDRplay service needs it)."
        echo "  3) After restarting, double-click this installer again."
        open "https://www.sdrplay.com/softwarehome/" 2>/dev/null
        say "Stopped here on purpose: install the SDRplay API, restart, then run this installer again."
        pause_exit 0
    fi
    say "SDRplay API found."
    if [ -z "$BREW" ]; then
        echo "Homebrew (a standard Mac tool installer) is needed for the next part."
        [ -n "$WRONGBREW" ] && echo "(This installs the Apple-silicon version into /opt/homebrew; your older one is not touched.)"
        if ask "Install Homebrew now? (official installer from brew.sh; it will ask for your Mac password)"; then
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || fail "Homebrew did not install. See https://brew.sh"
            for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && BREW="$b" && break; done
            [ -n "$BREW" ] && eval "$($BREW shellenv)"
        fi
    fi
    if [ -n "$BREW" ]; then
        PFX="$("$BREW" --prefix)"
        if [ ! -w "$PFX/bin" ] || [ ! -w "$PFX/share" ]; then
            say "Homebrew cannot write to its own folders ($PFX). This is why installs fail with 'not writable'."
            echo "I can fix it with one standard command (it asks for your Mac password):"
            echo "    sudo chown -R \"\$(whoami)\" the Homebrew folders inside $PFX"
            if ask "Run that now?"; then
                for d in bin etc include lib sbin share var opt Cellar Frameworks Homebrew; do
                    [ -e "$PFX/$d" ] && sudo chown -R "$(whoami)" "$PFX/$d"
                done
                chmod u+w "$PFX/bin" "$PFX/share" "$PFX/share/man" "$PFX/share/man/man8" 2>/dev/null
            fi
        fi
        if [ ! -w "$PFX/bin" ]; then
            say "Homebrew is still not writable, so I will skip the radio driver. Practice mode and maps will work."
            say "To fix later: run this installer again and answer y to the question above."
            BREW=""
        fi
    fi
    if [ -n "$BREW" ]; then
        say "I am about to install SoapySDR, cmake and Python with Homebrew (a few minutes)."
        M1="$(log_mark)"
        "$BREW" install cmake soapysdr python 2>&1 | tee -a "$LOG"
        if ! "$BREW" list --versions cmake soapysdr >/dev/null 2>&1; then
            say "Homebrew could not install cmake or SoapySDR. Skipping the driver module (everything else still installs)."
            diagnose "$(log_since "$M1")"
            note_warn "Homebrew could not install cmake/SoapySDR"
            BREW_FAILED=1
        fi
        TMP="$(mktemp -d)"
        if [ -n "${BREW_FAILED:-}" ]; then
            :
        else
        say "I am about to build the SDRplay driver module (SoapySDRPlay3)."
        # Some Command Line Tools installs lack the C++ headers folder the compiler expects
        # (error "'cstring' file not found"). The same headers exist inside the SDK, so point at them.
        SDKP="$(xcrun --show-sdk-path 2>/dev/null)"
        CXXEXTRA=""
        CLTH="/Library/Developer/CommandLineTools/usr/include/c++/v1/cstring"
        if [ -n "$SDKP" ] && [ -f "$SDKP/usr/include/c++/v1/cstring" ]; then
            export SDKROOT="$SDKP"
            if [ ! -f "$CLTH" ]; then
                CXXEXTRA="-isystem $SDKP/usr/include/c++/v1"
                echo "Compiler headers missing from Command Line Tools; using SDK copy: $SDKP" >>"$LOG"
            fi
        else
            say "The Mac's compiler tools look incomplete (the C++ headers are missing)."
            say "Fix: in Terminal run   sudo rm -rf /Library/Developer/CommandLineTools ; xcode-select --install"
            say "Then run this installer again. Everything else will still work meanwhile."
        fi
        M2="$(log_mark)"
        if git clone --depth 1 https://github.com/pothosware/SoapySDRPlay3.git "$TMP/src" >>"$LOG" 2>&1 \
           && cmake -S "$TMP/src" -B "$TMP/build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$("$BREW" --prefix)" ${SDKP:+-DCMAKE_OSX_SYSROOT="$SDKP"} ${CXXEXTRA:+-DCMAKE_CXX_FLAGS="$CXXEXTRA"} >>"$LOG" 2>&1 \
           && cmake --build "$TMP/build" -j4 >>"$LOG" 2>&1 \
           && cmake --install "$TMP/build" >>"$LOG" 2>&1; then
            say "SDRplay driver module built and installed."
            RADIO_OK=1
            # The module may look for the SDRplay library under a different file name than the Mac one.
            MOD="$("$BREW" --prefix)/lib/SoapySDR/modules0.9/libsdrPlaySupport.so"
            APILIB=""
            for C in /usr/local/lib/libsdrplay_api.dylib /usr/local/lib/libsdrplay_api.so.3 /usr/local/lib/libsdrplay_api.3.dylib; do
                [ -f "$C" ] && APILIB="$C" && break
            done
            if [ -f "$MOD" ] && [ -n "$APILIB" ]; then
                OLDREF="$(otool -L "$MOD" 2>/dev/null | awk '/libsdrplay_api/ {print $1; exit}')"
                if [ -n "$OLDREF" ] && [ "$OLDREF" != "$APILIB" ]; then
                    install_name_tool -change "$OLDREF" "$APILIB" "$MOD" >>"$LOG" 2>&1
                    codesign --force -s - "$MOD" >>"$LOG" 2>&1
                    echo "Re-pointed driver module from $OLDREF to $APILIB" >>"$LOG"
                fi
            fi
        else
            say "The driver module did not build. Details are in the log. The rest of the install will continue."
            say "(Newer driver modules need SDRplay API 3.15 or later; if yours is older, update the API from sdrplay.com.)"
            diagnose "$(log_since "$M2")"
            note_warn "The SDRplay driver module did not build"
        fi
        fi
        rm -rf "$TMP"
    else
        say "Skipping the driver module (no Homebrew)."
    fi
else
    say "Skipped the radio driver. Practice mode and maps will still work."
fi

# ------------------------------------------------------------------------------
step 4 "I am about to copy the program into: $DEST"
pkill -f "rfmap_app.py" 2>/dev/null && say "Closed a running copy of RF Noise Map so it can be replaced."
mkdir -p "$DEST" || fail "Could not create $DEST"
rm -rf "$DEST/app"
cp -R "$APPSRC" "$DEST/app" || fail "Could not copy the program files."
say "Copied."

# ------------------------------------------------------------------------------
step 5 "I am about to create the program's private Python environment (a few minutes the first time)."
PY=""
[ -n "$BREW" ] && [ -x "$("$BREW" --prefix)/bin/python3" ] && PY="$("$BREW" --prefix)/bin/python3"
[ -z "$PY" ] && command -v python3 >/dev/null 2>&1 && PY="$(command -v python3)"
if [ -z "$PY" ] || ! "$PY" --version >/dev/null 2>&1; then
    say "Python 3 is not available. A window may have appeared offering to install the Apple developer tools: click Install, wait for it to finish, then run this installer again."
    xcode-select --install 2>/dev/null
    pause_exit 1
fi
say "Using Python: $PY ($("$PY" --version 2>&1))"
if ! "$PY" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>>"$LOG"; then
    fail "The Python found ($("$PY" --version 2>&1)) is too old. Python 3.8 or newer is needed. In Terminal type: xcode-select --install   (or install Python from python.org), then run this installer again."
fi
rm -rf "$DEST/venv"
"$PY" -m venv "$DEST/venv" >>"$LOG" 2>&1 || fail "Could not create the Python environment (python3 venv / ensurepip failed)."
"$DEST/venv/bin/python" -m pip install --upgrade pip >>"$LOG" 2>&1
"$DEST/venv/bin/python" -m pip install numpy pyserial 2>&1 | tee -a "$LOG" | tail -3
"$DEST/venv/bin/python" -c "import numpy, serial" 2>>"$LOG" || fail "The helper libraries (numpy, pyserial) did not install. Are you connected to the internet?"
say "Python environment ready."

# ------------------------------------------------------------------------------
step 6 "I am about to create your data folders in: $DATA"
for d in Drives Maps Exports Backups Settings Recordings Logs; do mkdir -p "$DATA/$d"; done
say "Created: Drives, Maps, Exports, Backups, Settings, Recordings, Logs"
# An earlier version kept data in Documents; macOS blocks the program from reading it there. Copy it over (the old one is left alone).
if [ -d "$OLDDATA/Drives" ] && [ -z "$(ls -A "$DATA/Drives" 2>/dev/null)" ]; then
    cp -R "$OLDDATA/." "$DATA/" 2>/dev/null && say "Copied your earlier data from $OLDDATA into $DATA (the old folder was left alone; delete it when you like)."
fi

# ------------------------------------------------------------------------------
step 7 "I am about to create the 'RF Noise Map' app icon (Applications folder and Desktop)."
rm -rf "$APPBUNDLE"
mkdir -p "$APPBUNDLE/Contents/MacOS" "$APPBUNDLE/Contents/Resources"
cat > "$APPBUNDLE/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>RF Noise Map</string>
<key>CFBundleDisplayName</key><string>RF Noise Map</string>
<key>CFBundleExecutable</key><string>launcher</string>
<key>CFBundleIdentifier</key><string>local.rfnoisemap</string>
<key>CFBundleIconFile</key><string>icon</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1.0</string>
<key>LSArchitecturePriority</key><array><string>arm64</string><string>x86_64</string></array>
</dict></plist>
PLIST
cat > "$APPBUNDLE/Contents/MacOS/launcher" <<LAUNCH
#!/bin/bash
# RF Noise Map starter. It starts the program in the background and then finishes straight away, so macOS
# never thinks the icon is "not responding". If a copy is already running it asks what you want to do.
cd "$DEST/app" || exit 1
mkdir -p "\$HOME/Library/Logs"
LOG="\$HOME/Library/Logs/RFNoiseMap.log"
PY="$DEST/venv/bin/python"

running_port() {
    for p in 8780 8781 8782 8783 8784 8785 8786 8787 8788 8789; do
        if curl -s -m 1 "http://127.0.0.1:\$p/api/ping" 2>/dev/null | grep -q '"app": "rfmap"'; then echo "\$p"; return 0; fi
    done
    return 1
}

start_app() {
    # Apple-silicon Mac: always start natively. An icon with no declared processor type can be started under
    # Rosetta (Intel emulation), which cannot load the arm64 libraries (numpy then fails to import).
    if [ "\$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ]; then
        nohup arch -arm64 "\$PY" rfmap_app.py >> "\$LOG" 2>&1 &
    else
        nohup "\$PY" rfmap_app.py >> "\$LOG" 2>&1 &
    fi
    disown 2>/dev/null
}

RP="\$(running_port)"
if [ -n "\$RP" ]; then
    ANS="\$(osascript -e 'button returned of (display dialog "RF Noise Map is already running.\n\nWhat would you like to do?\n\n(Closing it stops any recording in progress. Data already saved is kept.)" buttons {"Cancel", "Open the running one", "Close it and start fresh"} default button "Open the running one" cancel button "Cancel" with title "RF Noise Map" with icon note)' 2>/dev/null)"
    case "\$ANS" in
        "Open the running one")
            open "http://localhost:\$RP/"
            exit 0 ;;
        "Close it and start fresh")
            "\$PY" rfmap_app.py --stop >> "\$LOG" 2>&1
            for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
                sleep 0.5
                [ -z "\$(running_port)" ] && break
            done
            if [ -n "\$(running_port)" ]; then      # did not close politely: force it
                pkill -f "rfmap_app.py" 2>/dev/null
                pkill -f "rf_logger.py" 2>/dev/null
                sleep 1.5
            fi
            ;;
        *)
            exit 0 ;;
    esac
fi
start_app
exit 0
LAUNCH
chmod +x "$APPBUNDLE/Contents/MacOS/launcher"
if command -v sips >/dev/null 2>&1 && sips -s format icns "$DEST/app/icon.png" --out "$APPBUNDLE/Contents/Resources/icon.icns" >/dev/null 2>&1; then
    say "Icon created."
else
    say "(Icon could not be made; the app will have a plain icon. That is cosmetic only.)"
fi
rm -f "$HOME/Desktop/RF Noise Map" 2>/dev/null
ln -s "$APPBUNDLE" "$HOME/Desktop/RF Noise Map" 2>/dev/null && say "Desktop icon created." || say "(Could not put an icon on the Desktop; use Applications.)"
touch "$APPBUNDLE"

# ------------------------------------------------------------------------------
step 8 "I am about to run a quick self-test using practice data (nothing touches your real data)."
TESTDIR="$(mktemp -d)"; M3="$(log_mark)"
if ( cd "$DEST/app" && RFMAP_DATA="$TESTDIR" "$DEST/venv/bin/python" rf_logger.py --gps sim --sdr sim \
        --outdir "$TESTDIR/Drives" --settings "$TESTDIR/s.json" --port 8799 --local-only >>"$LOG" 2>&1 ) \
   && ( cd "$DEST/app" && "$DEST/venv/bin/python" make_map.py "$TESTDIR"/Drives/*.csv -o "$TESTDIR/test_map.html" >>"$LOG" 2>&1 ) \
   && [ -s "$TESTDIR/test_map.html" ]; then
    say "SELF-TEST PASSED: the logger and the map builder both work."
else
    say "SELF-TEST FAILED. Details are in the log."
    diagnose "$(log_since "$M3")"
    note_warn "The self-test did not pass"
fi
rm -rf "$TESTDIR"

echo
say "I am about to check that the control panel starts and answers (this finds 'connection' problems)."
PCHK="$(mktemp -d)"; PPORT=8795; PANEL_OK=0; M4="$(log_mark)"
( cd "$DEST/app" && RFMAP_DATA="$DATA" RFMAP_NO_CLEANUP=1 "$DEST/venv/bin/python" rfmap_app.py --no-browser --port $PPORT >>"$LOG" 2>&1 ) &
PPID_CHK=$!
for i in 1 2 3 4 5 6 7 8 9 10; do
    sleep 1
    if curl -s --max-time 3 -H "X-RFMap: 1" "http://localhost:$PPORT/api/state" -o "$PCHK/state.json" 2>/dev/null && [ -s "$PCHK/state.json" ]; then PANEL_OK=1; break; fi
done
if [ "$PANEL_OK" = "1" ]; then
    WARN="$("$DEST/venv/bin/python" -c "import json,sys;d=json.load(open(sys.argv[1]));print('; '.join(d.get('warnings',[])) if 'data_dir' in d else 'NOSTATE')" "$PCHK/state.json" 2>>"$LOG")"
    if [ -z "$WARN" ]; then say "CONTROL PANEL CHECK PASSED: the program answers and can read your data folder."
    elif [ "$WARN" = "NOSTATE" ]; then say "CONTROL PANEL CHECK FAILED: the program answered but not correctly. See $LOG"
    else say "CONTROL PANEL WARNING: $WARN"; fi
else
    say "CONTROL PANEL CHECK FAILED: the program did not answer on this Mac. See $LOG (and ~/Library/Logs/RFNoiseMap.log)."
    diagnose "$(log_since "$M4")
$(tail -n 40 "$HOME/Library/Logs/RFNoiseMap.log" 2>/dev/null)"
    note_warn "The control panel did not answer in the check"
fi
kill $PPID_CHK 2>/dev/null; pkill -f "rfmap_app.py --no-browser --port $PPORT" 2>/dev/null
rm -rf "$PCHK"

echo
say "Checking the radio (this is informational):"
M5="$(log_mark)"
( cd "$DEST/app" && "$DEST/venv/bin/python" check_setup.py 2>&1 | grep -v "SoapyVOLKConverters" | tee -a "$LOG" )
if log_since "$M5" | grep -Eiq "no sdrplay|not (found|available)|FIX"; then
    diagnose "$(log_since "$M5")"
    [ "$RADIO_OK" = "0" ] && note_warn "The radio is not set up yet (fine for practice mode)"
fi

echo
echo "============================================================"
if [ "${#WARNINGS[@]}" -gt 0 ]; then
    say "FINISHED, with ${#WARNINGS[@]} thing(s) to look at:"
    for w in "${WARNINGS[@]}"; do say "   - $w"; done
    say "(Details and suggested fixes are above and in the log.)"
else
    say "FINISHED with no problems found."
fi
say "DONE."
say "  Open it:      double-click 'RF Noise Map' on your Desktop (or in Applications)."
say "  Your data:    $DATA"
say "  Install log:  $LASTLOG   (all runs are kept in $LOGDIR)"
say "  Problems:     the program writes errors to $LOGDIR/program_errors.log"
say "                 (in the panel: Tools > Make a support file). Run this installer and choose 2 to check everything."
say "  The guide:    in the program window, press 'Help & guide'."
if [ "$RADIO_OK" = "0" ]; then
  say "  Radio driver: not set up yet. Run this installer again and answer y at STEP 3 when you are ready."
fi
echo "============================================================"
if ask "Open RF Noise Map now?"; then open "$APPBUNDLE"; fi
pause_exit 0
