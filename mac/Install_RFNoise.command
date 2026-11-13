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
LOG="$DATA/install_log.txt"
APPBUNDLE="$HOME/Applications/RF Noise Map.app"

mkdir -p "$DATA" "$HOME/Applications"
say()  { echo "$*"; echo "$*" >> "$LOG"; }
step() { echo; echo "------------------------------------------------------------"; say "STEP $1"; shift; say "$*"; echo; }
ask()  { local a; read -r -p "$1 [y/n] " a; [[ "$a" == "y" || "$a" == "Y" ]]; }
pause_exit() { echo; read -r -p "Press Return to close this window..." _; exit "${1:-0}"; }
fail() { echo; say "PROBLEM: $*"; say "(A copy of everything shown here is saved in: $LOG)"; say "Send that file to Claude and we will fix it together."; pause_exit 1; }

: > "$LOG"
say "RF Noise Map installer - $(date)"
say "Mac: $(sw_vers -productVersion 2>/dev/null)  chip: $(uname -m)"

clear
cat <<'EOF'
============================================================
   RF NOISE MAP  -  installer for Mac
============================================================
This will:
  1. Copy the program into  Applications/RF Noise Map
  2. Set up its private Python environment (no changes to your system Python)
  3. Create a folder  RF Noise Map  in your home folder for your data
  4. Put an "RF Noise Map" icon on your Desktop and in Applications
  5. (Optional) help you install the SDRplay radio driver
  6. Run a quick self-test with practice data

Nothing is sent anywhere. You can run this installer again at any time.
EOF
echo
ask "Ready to start?" || pause_exit 0

# ------------------------------------------------------------------------------
step 1 "I am about to check the program files in this folder."
[ -f "$APPSRC/rfmap_app.py" ] || fail "I can't find the 'app' folder. Download the Mac zip from the Releases page (or the whole repository) and keep the folders together; don't move this file out by itself."
say "Found the program files."

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
step 3 "RADIO DRIVER (optional but needed to use the SDRplay receiver).
The SDRplay driver is not mine to include; it comes from sdrplay.com. I can
walk you through it now. If you only want to try Practice mode and make maps,
answer n - you can run this installer again later."
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
        "$BREW" install cmake soapysdr python 2>&1 | tee -a "$LOG"
        if ! "$BREW" list --versions cmake soapysdr >/dev/null 2>&1; then
            say "Homebrew could not install cmake or SoapySDR (see the log). Skipping the driver module."
            BREW_FAILED=1
        fi
        TMP="$(mktemp -d)"
        if [ -n "${BREW_FAILED:-}" ]; then
            :
        else
        say "I am about to build the SDRplay driver module (SoapySDRPlay3)."
        if git clone --depth 1 https://github.com/pothosware/SoapySDRPlay3.git "$TMP/src" >>"$LOG" 2>&1 \
           && cmake -S "$TMP/src" -B "$TMP/build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$("$BREW" --prefix)" >>"$LOG" 2>&1 \
           && cmake --build "$TMP/build" -j4 >>"$LOG" 2>&1 \
           && cmake --install "$TMP/build" >>"$LOG" 2>&1; then
            say "SDRplay driver module built and installed."
            RADIO_OK=1
        else
            say "The driver module did not build. Details are in the log. The rest of the install will continue."
            say "(Newer driver modules need SDRplay API 3.15 or later; if yours is older, update the API from sdrplay.com.)"
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
rm -rf "$DEST/venv"
"$PY" -m venv "$DEST/venv" || fail "Could not create the Python environment."
"$DEST/venv/bin/python" -m pip install --upgrade pip >>"$LOG" 2>&1
"$DEST/venv/bin/python" -m pip install numpy pyserial 2>&1 | tee -a "$LOG" | tail -3
"$DEST/venv/bin/python" -c "import numpy, serial" 2>>"$LOG" || fail "The helper libraries (numpy, pyserial) did not install. Are you connected to the internet?"
say "Python environment ready."

# ------------------------------------------------------------------------------
step 6 "I am about to create your data folders in: $DATA"
for d in Drives Maps Exports Backups Settings; do mkdir -p "$DATA/$d"; done
say "Created: Drives, Maps, Exports, Backups, Settings"
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
</dict></plist>
PLIST
cat > "$APPBUNDLE/Contents/MacOS/launcher" <<LAUNCH
#!/bin/bash
cd "$DEST/app" || exit 1
mkdir -p "\$HOME/Library/Logs"
exec "$DEST/venv/bin/python" rfmap_app.py >> "\$HOME/Library/Logs/RFNoiseMap.log" 2>&1
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
TESTDIR="$(mktemp -d)"
if ( cd "$DEST/app" && RFMAP_DATA="$TESTDIR" "$DEST/venv/bin/python" rf_logger.py --gps sim --sdr sim \
        --outdir "$TESTDIR/Drives" --settings "$TESTDIR/s.json" --port 8799 --local-only >>"$LOG" 2>&1 ) \
   && ( cd "$DEST/app" && "$DEST/venv/bin/python" make_map.py "$TESTDIR"/Drives/*.csv -o "$TESTDIR/test_map.html" >>"$LOG" 2>&1 ) \
   && [ -s "$TESTDIR/test_map.html" ]; then
    say "SELF-TEST PASSED: the logger and the map builder both work."
else
    say "SELF-TEST FAILED. Details are in the log."
fi
rm -rf "$TESTDIR"

echo
say "I am about to check that the control panel starts and answers (this finds 'connection' problems)."
PCHK="$(mktemp -d)"; PPORT=8795; PANEL_OK=0
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
fi
kill $PPID_CHK 2>/dev/null; pkill -f "rfmap_app.py --no-browser --port $PPORT" 2>/dev/null
rm -rf "$PCHK"

echo
say "Checking the radio (this is informational):"
( cd "$DEST/app" && "$DEST/venv/bin/python" check_setup.py 2>&1 | tee -a "$LOG" )

echo
echo "============================================================"
say "DONE."
say "  Open it:      double-click 'RF Noise Map' on your Desktop (or in Applications)."
say "  Your data:    $DATA"
say "  The guide:    in the program window, press 'Help & guide'."
if [ "$RADIO_OK" = "0" ]; then
  say "  Radio driver: not set up yet. Run this installer again and answer y at STEP 3 when you are ready."
fi
echo "============================================================"
if ask "Open RF Noise Map now?"; then open "$APPBUNDLE"; fi
pause_exit 0
