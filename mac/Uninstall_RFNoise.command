#!/bin/bash
# ==============================================================================
#  RF Noise Map - Mac uninstaller
#  Shows what is installed, asks before deleting anything, and keeps your recorded
#  drives, maps and recordings unless you choose otherwise.
#  A record of what it did is kept in:  ~/Library/Logs/RFNoiseMap_uninstall.log
# ==============================================================================
DEST="$HOME/Applications/RF Noise Map"
APPB="$HOME/Applications/RF Noise Map.app"
DATA="$HOME/RF Noise Map"
STAMP="$(date +%Y%m%d_%H%M%S)"
ULOG="$HOME/Library/Logs/RFNoiseMap_uninstall.log"
mkdir -p "$HOME/Library/Logs"
say() { echo "$*"; echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$ULOG"; }
sz()  { du -sh "$1" 2>/dev/null | awk '{print $1}'; }
done_exit() { echo; read -r -p "Press Return to close this window..." _; exit "${1:-0}"; }

clear
echo "============================================================"
echo "   RF NOISE MAP  -  uninstall (Mac)"
echo "============================================================"
echo "Here is what is on this Mac right now:"
echo
[ -d "$DEST" ]  && echo "  Program files   : $DEST  ($(sz "$DEST"))"   || echo "  Program files   : not found"
[ -d "$APPB" ]  && echo "  App icon        : $APPB"                    || echo "  App icon        : not found"
[ -L "$HOME/Desktop/RF Noise Map" ] && echo "  Desktop icon    : yes"
if [ -d "$DATA" ]; then
    echo "  Your data       : $DATA  ($(sz "$DATA"))"
    for d in Drives Maps Exports Backups Recordings Logs Settings; do
        [ -d "$DATA/$d" ] && echo "       $d: $(sz "$DATA/$d")"
    done
else
    echo "  Your data       : not found"
fi
echo
echo "What would you like to do?"
echo "  1)  Remove the PROGRAM only. Keep my drives, maps, recordings and logs.   [recommended]"
echo "  2)  Remove the program AND my data, after saving a backup zip in my home folder."
echo "  3)  Remove EVERYTHING including my data, with no backup."
echo "  0)  Cancel. Change nothing."
echo
read -r -p "Type 0, 1, 2 or 3 and press Return [1]: " C
C="${C:-1}"
case "$C" in 0|1|2|3) ;; *) say "Cancelled (no valid choice). Nothing was changed."; done_exit 0;; esac
[ "$C" = "0" ] && { say "Cancelled. Nothing was changed."; done_exit 0; }

if [ "$C" = "3" ]; then
    read -r -p "This permanently deletes ALL your recorded data. Type DELETE (capitals) to confirm: " T
    [ "$T" = "DELETE" ] || { say "Cancelled. Nothing was changed."; done_exit 0; }
fi

say "---- uninstall started: choice $C ----"
echo
echo "Step 1: closing the program if it is running..."
if [ -x "$DEST/venv/bin/python" ] && [ -f "$DEST/app/rfmap_app.py" ]; then
    ( cd "$DEST/app" && "$DEST/venv/bin/python" rfmap_app.py --stop >/dev/null 2>&1 )
    sleep 2
fi
pkill -f "rfmap_app.py" 2>/dev/null; pkill -f "rf_logger.py" 2>/dev/null
say "Program closed (or was not running)."

if [ "$C" = "2" ]; then
    echo
    echo "Step 2: saving a backup of your data first..."
    BK="$HOME/RFNoiseMap_backup_$STAMP.zip"
    if [ -d "$DATA" ] && ( cd "$HOME" && zip -q -r "$BK" "RF Noise Map" ) && [ -s "$BK" ]; then
        say "Backup saved: $BK ($(sz "$BK"))"
    else
        say "The backup could not be made, so I will NOT delete your data. Nothing about your data was changed."
        C=1
    fi
fi

echo
echo "Step 3: removing the program, icon and launcher log..."
rm -rf "$DEST" "$APPB" 2>/dev/null
[ -L "$HOME/Desktop/RF Noise Map" ] && rm -f "$HOME/Desktop/RF Noise Map"
rm -f "$HOME/Library/Logs/RFNoiseMap.log" 2>/dev/null
say "Program, icon and Desktop shortcut removed."

if [ "$C" = "2" ] || [ "$C" = "3" ]; then
    echo
    echo "Step 4: removing your data folder..."
    rm -rf "$DATA" 2>/dev/null
    say "Data folder removed."
else
    say "Your data was kept in: $DATA"
fi

echo
echo "------------------------------------------------------------"
say "DONE."
echo "NOT removed (other programs may use them, so I leave them alone):"
echo "  - The SDRplay API (use SDRplay's own uninstaller if you want it gone)"
echo "  - Homebrew, SoapySDR and cmake. To remove them yourself, in Terminal:   brew uninstall soapysdr cmake"
echo "  - The SDRplay driver module. To remove it:   rm \"\$(brew --prefix)/lib/SoapySDR/modules0.9/libsdrPlaySupport.so\""
echo "A record of this uninstall is in: $ULOG"
done_exit 0
