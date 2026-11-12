#!/bin/bash
# Removes the RF Noise Map program. Your data (Documents/RF Noise Map) is NOT touched.
echo "This removes the RF Noise Map program and its icons."
echo "Your drives and maps in  Documents/RF Noise Map  are kept."
read -r -p "Continue? [y/n] " a
if [[ "$a" == "y" || "$a" == "Y" ]]; then
  pkill -f rfmap_app.py 2>/dev/null
  rm -rf "$HOME/Applications/RF Noise Map" "$HOME/Applications/RF Noise Map.app"
  rm -f "$HOME/Desktop/RF Noise Map"
  echo "Removed."
fi
read -r -p "Press Return to close..." _
