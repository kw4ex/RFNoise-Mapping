RF Noise Map - Mac (EXPERIMENTAL, NOT YET TESTED ON A REAL MAC)
================================================================
Design and on-air testing by KW4EX. No warranty. Use at your own risk.
Not made or approved by SDRplay, Apple or any radio maker.

The Windows version is the main one. This Mac version passed the program's
self-test with practice data on Linux, but has not been tried on a real Mac,
with a real SDRplay, or on a drive. Reports are welcome (open an issue).

WHAT YOU NEED
  - A Mac, an SDRplay receiver, and a GPS (iPhone with the GPS2IP app, or a USB GPS).
  - Internet while installing (it downloads two small helper libraries).
  - For the real radio: the SDRplay API from sdrplay.com and the SoapySDR radio
    library (the installer offers to help). Practice mode and maps need neither.

INSTALL - STEP BY STEP
  1. Download the Mac zip (RFNoise_Mac_....zip) from the Releases page, Assets list.
  2. Open Downloads and double-click the zip to unzip it. Keep the folders
     "mac" and "app" together.
  3. Open the "mac" folder. Right-click  Install_RFNoise.command  and choose Open,
     then Open again (first time only).
     If macOS says it "cannot be opened because Apple cannot check it": click Done
     (never "Move to Trash"). Then open System Settings > Privacy & Security, scroll down
     to the message about Install_RFNoise.command, click "Open Anyway" and enter your
     Mac password. (This only happens for the installer; it clears the warning for the
     other files in the folder, including the uninstaller.)
  4. Read each step in the window and answer y to go on. When it says DONE, an
     "RF Noise Map" icon is on your Desktop and in Applications.
  5. If the file opens in a text editor: open Terminal, type  bash  and a space,
     drag Install_RFNoise.command into the window, press Return.

REMOVE IT LATER
  Right-click  Uninstall_RFNoise.command  > Open. Your drives and maps in
  the "RF Noise Map" folder in your home folder are kept.

The full guide is in the app (Help & guide button) and docs/guides in the repository.
