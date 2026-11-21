RFI Trail - Windows
================================================================
Design and on-air testing by KW4EX. No warranty. Use at your own risk.
Not made or approved by SDRplay, Microsoft or any radio maker.

Find where radio noise (power lines, poles, noisy buildings) is strongest: drive a route with a radio
and a GPS and the program draws the readings as coloured dots on a street map.

WHAT YOU NEED
  - A Windows 10 or 11 computer (a laptop for the car).
  - A GPS: an iPhone with the GPS2IP app, or a USB GPS puck.
  - A radio: Hermes Lite 2, ANAN or FlexRadio (network cable, no driver), or practice mode with no radio.
  - Internet while installing (two small helper libraries are downloaded) and for street backgrounds on maps.

INSTALL - STEP BY STEP
  1. Right-click the zip you downloaded and choose Extract All. Keep  Install_RFI_Trail_Windows.bat
     and the  app  folder together, side by side.
  2. Double-click  Install_RFI_Trail_Windows.bat.
     If Windows says "Windows protected your PC": click More info, then Run anyway.
  3. Answer the questions (Y or n; Enter alone means yes). No administrator password is needed.
     - Step 1 asks for a folder. Press Enter for C:\RadioScripts (the program goes in C:\RadioScripts\RFI_Trail).
     - Step 3 finds Python 3, or installs it for you with Windows' own winget tool.
  4. When it says DONE, double-click the "RFI Trail" icon on your Desktop
     (or Start_RFI_Trail.bat in the install folder). It opens in your web browser; Google Chrome is best for sound.
  5. First try: press Settings, then "Try a practice drive + map". No radio is needed.
     A red PRACTICE MODE banner means the radios, GPS and sound are pretend; press "Turn practice off" for real use.

UPDATING: run the newer download's installer the same way. It replaces the program, keeps the old one in
  app_previous, and never touches your Drives, Maps, Exports, Backups, Settings or Recordings folders.

REAL RADIOS
  - Hermes Lite 2, ANAN, FlexRadio: no driver. Plug in the network cable (or join the same network),
    switch the radio on, open Hardware setup and press "Scan and set up for me".
    Run  Tools\Allow_ANAN_Firewall.bat  once (it asks for permission) so Windows lets the radio's data through.
    Close Thetis / SmartSDR-controlled programs that use the same receiver first where the radio allows one program only.
  - Icom, Yaesu, Kenwood, Elecraft on a USB (CAT) cable: Hardware setup > "Add a CAT radio".
  - SDRplay and RTL-SDR dongles on Windows need extra software that THIS installer does not set up yet:
    the SDRplay API (sdrplay.com) and the PothosSDR bundle (github.com/pothosware/PothosSDR/wiki), and a Python
    version that matches PothosSDR. Practice mode, maps and all network radios work without it.

HELP
  - Point at any button, box or number in the program and press the ? key (or F1): a short explanation opens.
  - The full guide: the "Help & guide" button at the top of the program, or RFI_Trail_User_Guide.pdf (to print)
    and RFI_Trail_Help.html in the install folder.
  - Problems: the install log is  Logs\install_log.txt ; while the program runs, errors go to
    Logs\program_errors.log. In the program: Settings > "Show recent problems" or "Make a support file".
    Send the support file to KW4EX or Claude. Nothing is ever sent automatically.

STOP / REMOVE
  - Stop_RFI_Trail.bat closes a running program. In the program, "Close program" does the same.
  - The installer also keeps a copy of this download in KW4EX_Downloads\RFI_Trail_Windows_vX next to the RFI_Trail folder.
  - Uninstall_RFI_Trail.bat (in the install folder): remove the program only (your data is kept), or everything.

THIS WINDOWS INSTALLER IS NEW AND HAS NOT YET BEEN TRIED ON A REAL WINDOWS PC. If a step fails, the message
says what happened; please send Logs\install_log.txt to KW4EX.

ABOUT
  RFI Trail is the successor to RF Noise Map, designed and tested on the air by KW4EX.
  With thanks to Jeff Stuparits, W4DD, whose noise-mapping program and generous help inspired it.
