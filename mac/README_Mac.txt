RFI Trail 2.0.0j - Mac
================================================================
Design and on-air testing by KW4EX. No warranty. Use at your own risk.
Not made or approved by SDRplay, Apple or any radio maker.

This Mac version has been used on an Apple-silicon MacBook (ANAN and SDRplay radios).
It has not yet been tried on an Intel Mac or on a long drive. Reports are welcome: send them to KW4EX.

ABOUT RFI TRAIL
  RFI Trail is the successor to RF Noise Map (the same program, grown up). It has its own
  folder (Applications/RFI Trail), its own data folder (~/RFI Trail) and its own ports (8790 and 8775).
  If you used the earlier test version called "Noise Trail", the installer moves your drives, maps
  and settings from ~/Noise Trail into ~/RFI Trail for you.
  With thanks to Jeff Stuparits, W4DD, whose noise-mapping program and generous help inspired it.
  New: radios are plug-ins. Radios with a CAT/USB cable (Icom, Yaesu, Kenwood, Elecraft)
  can be added in Hardware setup > "Radios on a CAT cable", in Follow mode (read only) or
  Control mode (the program tunes the radio), and mixed with dongles, SDRplay and Hermes.
  FlexRadio 6000/8000 series is added the same way and connects over the
  network (the SmartSDR interface, TCP 4992): press "Find on network" or type the radio's
  address. Allow RFI Trail / Python through the Mac firewall (meter readings arrive by UDP).
  In Control mode the Flex also gives a real spectrum picture, from a panadapter that RFI Trail
  makes for itself (about 200 kHz wide, centred on the slot). In Follow mode, and for the other CAT
  radios, the slot shows the level only. Radio audio (listening, recording) and filter controls are not
  available for CAT/Flex slots yet.
  Neither the CAT radio table nor the Flex support has been checked on real radios yet.

WHAT IS NEW SINCE 2.0.0a (versions b to j)
  - The Desktop icon now starts the program in a way macOS 27 does not stop. It also checks for a
    copy that is already running (or a different version, or a stuck one) and tells you what it found.
    If the window says "Lost contact with program", read ~/Library/Logs/RFI_Trail.log.
  - When you click the icon it asks "Allow clamshell mode?". Yes keeps the Mac awake while RFI Trail
    runs, so you can close the lid while the Mac is plugged in. It ends by itself when RFI Trail closes.
  - Closing the browser window closes the program (a setting, on by default; never during a drive).
  - FlexRadio slots: zoom, drag the tuning bar to retune, a Centre button and Keep centred, and Mute radio speaker.
  - GPS wording now fits whichever phone app you use (GPS2IP, NMEA Gps...). "Hide unused" hides slots with no radio.
  - Point at anything and press ? for help. The top bar and the Compact and Car views are tidier (no wrapping or overlap).
  - Map pages: the boxes fold up to their title, and the colour bar is a two-handle slider for Min and Max.
    The full list is in docs/release-notes/v2.0.0j.md.
  - Phone and tablet access is on by default: scan the QR code on the main screen (see the user guide).
    If the Mac asks whether to allow incoming connections, choose Allow.

WHAT YOU NEED
  - A Mac, a radio (SDRplay, Hermes Lite 2, ANAN, FlexRadio, RTL-SDR or a CAT radio), and a GPS (iPhone with the GPS2IP app, or a USB GPS).
  - Internet while installing (it downloads two small helper libraries).
  - For the real radio: the SDRplay API from sdrplay.com and the SoapySDR radio
    library (the installer offers to help). Practice mode and maps need neither.

INSTALL - STEP BY STEP
  1. You need the Mac download: RFI_Trail_Mac_v2.0.0j (a folder, or the zip of the same name).
  2. If it is a zip, open Downloads and double-click it to unzip it. Keep the folders
     "mac" and "app" together.
  3. Open the "mac" folder. Right-click  Install_RFI_Trail.command  and choose Open,
     then Open again (first time only).
     If macOS says it "cannot be opened because Apple cannot check it": click Done
     (never "Move to Trash"). Then open System Settings > Privacy & Security, scroll down
     to the message about Install_RFI_Trail.command, click "Open Anyway" and enter your
     Mac password. (This only happens for the installer; it clears the warning for the
     other files in the folder, including the uninstaller.)
  4. Read each step in the window and answer y to go on. When it says DONE, an
     "RFI Trail" icon is on your Desktop and in Applications.
  5. If the file opens in a text editor: open Terminal, type  bash  and a space,
     drag Install_RFI_Trail.command into the window, press Return.

WHAT THE INSTALLER MENU OFFERS (you can run it as often as you like)
  1) Install or update. This also repairs a broken install.
  2) Check my setup and make a support file. Changes nothing. It lists what is
     working, what needs fixing, explains the likely cause in plain words and
     offers a zip file to send for help.
  3) Uninstall.

HERMES LITE 2 ON A MAC (NETWORK SETUP)
  The Mac needs no driver for the Hermes Lite 2, but it needs a network port:
    1. Plug a USB-to-Ethernet adapter (or a dock with an Ethernet socket) into the
       Mac. Plug the radio's network cable into it, then power the radio.
    2. LEAVE WI-FI ON. The Mac may have Wi-Fi and the adapter connected at once.
       The program searches for the radio out of every
       network port, so the order of the connections does not matter.
    3. Wait about 30 seconds. Open System Settings > Network. The adapter is
       listed with a green dot. With the radio connected directly (no router) the
       Mac gives itself an address starting 169.254. That is normal: keep
       "Configure IPv4: Using DHCP" and do NOT type an address by hand.
    4. If macOS asks to allow "devices on your local network", press Allow. If
       you refused: System Settings > Privacy & Security > Local Network, switch
       the program (or Terminal / Python) on.
    5. If the Mac firewall is on (System Settings > Network > Firewall), allow
       incoming connections for the program or Python.
    6. In the program tick Hermes Lite 2 and press "Find my radio". It names the
       port where it found the radio. If not, wait 30 seconds and try again, or
       type the radio's address in the box.
  Only one program at a time can use the radio: close Thetis / SDR Console first.

RTL-SDR DONGLES (NOT YET TRIED ON REAL DONGLES)
  Up to four USB dongles (for example the RTL-SDR Blog V3), any dongle in any slot.
  The installer offers to add these drivers for you (step 3b). To add them later, open RFI Trail > Hardware setup > RTL-SDR and press 'Install the RTL-SDR drivers', or run the installer again. Then press 'Check my dongle': it looks at the USB ports, the drivers and the Python match and tells you what to do. (By hand it is:  brew install soapysdr soapyrtlsdr librtlsdr.)
  In the program tick "RTL-SDR dongles" under Your radios and press "Find my
  dongles". Give each dongle its own serial number first, one dongle plugged in at
  a time:  rtl_eeprom -s 00000001   then unplug and replug. Use a powered USB hub.

PRACTICE MODE: a red striped banner at the top (and [PRACTICE] in the browser tab) means the radios, GPS and sound are
  pretend. The tick is remembered between runs: press "Turn practice off" before a real drive.

BROWSER: the program opens in Google Chrome (Safari holds the sound back until the
  page gets a click). To use your normal browser choose it under "Open the program
  in" in the radio settings.

IF SOMETHING GOES WRONG
  * The installer keeps a log of every run in  ~/RFI Trail/Logs  (the newest
    copy is also  ~/RFI Trail/install_log.txt). When a step fails it says what
    the likely cause is, what to do, and gives a web page for more help. It then
    offers to make ONE zip "support file" (logs only, nothing is sent anywhere).
  * While the program runs, any error is written to
    ~/RFI Trail/Logs/program_errors.log. In the program window go to
    Settings > "Show recent problems" or "Make a support file (zip)".
  * Common causes it recognises: missing Apple developer tools, incomplete compiler
    headers, Homebrew permissions, no internet, Rosetta (Intel) mode, a full disk,
    macOS privacy blocks, another copy already running, SDRplay not found.
  * Send the support file to KW4EX or Claude.

REMOVE IT LATER
  Right-click  Uninstall_RFI_Trail.command  > Open (or choose 3 in the installer).
  It shows what is installed and lets you choose: program only (recommended; your
  drives, maps, recordings and logs are kept), program plus data after saving a
  backup zip in your home folder, or everything with no backup. A record is kept
  in ~/Library/Logs/RFI_Trail_uninstall.log.

The full guide is in the app (Guide button) and, to print, RFI_Trail_User_Guide.pdf next to the mac folder. In the program, point at anything and press the ? key (or F1)
for a short explanation of it.
