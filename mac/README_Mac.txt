RF Noise Map - Mac (TESTING VERSION)
================================================================
Design and on-air testing by KW4EX. No warranty. Use at your own risk.
Not made or approved by SDRplay, Apple or any radio maker.

This Mac version has been installed and used on one Apple-silicon MacBook with an SDRplay RSP1.
It has not yet been tried on an Intel Mac or on a long drive. Reports are welcome (open an issue).

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

WHAT THE INSTALLER MENU OFFERS (you can run it as often as you like)
  1) Install or update. This also repairs a broken install.
  2) Check my setup and make a support file. Changes nothing. It lists what is
     working, what needs fixing, explains the likely cause in plain words and
     offers a zip file to send for help.
  3) Uninstall.

IF SOMETHING GOES WRONG
  * The installer keeps a log of every run in  ~/RF Noise Map/Logs  (the newest
    copy is also  ~/RF Noise Map/install_log.txt). When a step fails it says what
    the likely cause is, what to do, and gives a web page for more help. It then
    offers to make ONE zip "support file" (logs only, nothing is sent anywhere).
  * While the program runs, any error is written to
    ~/RF Noise Map/Logs/program_errors.log. In the program window go to
    Tools > "Show recent problems" or "Make a support file (zip)".
  * Common causes it recognises: missing Apple developer tools, incomplete compiler
    headers, Homebrew permissions, no internet, Rosetta (Intel) mode, a full disk,
    macOS privacy blocks, another copy already running, SDRplay not found.
  * Send the support file to KW4EX or Claude, or open an issue:
    https://github.com/kw4ex/RFNoise-Mapping/issues

REMOVE IT LATER
  Right-click  Uninstall_RFNoise.command  > Open (or choose 3 in the installer).
  It shows what is installed and lets you choose: program only (recommended; your
  drives, maps, recordings and logs are kept), program plus data after saving a
  backup zip in your home folder, or everything with no backup. A record is kept
  in ~/Library/Logs/RFNoiseMap_uninstall.log.

The full guide is in the app (Help & guide button) and docs/guides in the repository.
