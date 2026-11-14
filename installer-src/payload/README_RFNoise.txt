RF NOISE MAP  v1.3.0  TESTING VERSION   (Windows 10 / 11)
Design and testing: KW4EX
=====================================================================

WHAT IT IS
  A small Python program that runs on your PC with an SDRplay receiver and a
  GPS. You drive a route; it measures the radio signal level on up to four
  frequencies and records where you were. Afterwards one button draws a street
  map with colored dots (blue = quiet, red = strong) so you can find noisy
  power lines, poles, homes or businesses.

  Everything is in ONE folder. The installer makes it for you:

     C:\RadioScripts\RFNoise          (you can choose another place)
        Start_RFNoise.bat             starts the program (and opens the panel)
        Stop_RFNoise.bat              closes it
        Open_Panel.bat                opens the panel of the running program
        Uninstall_RFNoise.bat         removes the program (you choose what happens to your data)
        Make_Support_File.bat         packs the logs into ONE zip to send for help
        Open_Logs.bat                 opens the Logs folder
        README_RFNoise.txt            this file
        RFNoise_Help.html             the full guide (also inside the program)
        RFNoise_User_Guide.pdf        the same guide, to print
        install_log.txt               a copy of what the installer said (newest one)
        app\                          the program files (do not edit)
        Drives\                       one .csv file per recorded drive
        Maps\                         finished maps (.html, open in any browser)
        Exports\                      Google Earth .kml files and email .zip files
        Backups\                      zip backups
        Settings\                     your remembered choices and the logger log
        Recordings\                   audio recordings made in the panadapter
        Logs\                         install logs (newest 10 kept) and program_errors.log

---------------------------------------------------------------------
PART 1 - INSTALL
---------------------------------------------------------------------
  EASY WAY (recommended)
   1. Double-click  Install_RFNoise_Windows.bat
      If Windows says "Windows protected your PC", click More info, then
      Run anyway.
   2. Answer the short questions. Press Enter to accept the answer shown in
      [brackets]. It asks for the folder (suggested: C:\RadioScripts), makes
      the RFNoise subfolder, finds Python (and offers to install it), installs
      numpy and pyserial, copies the program, offers the shortcuts (Desktop,
      Start menu, sign-in) and runs a quick self-test with practice data.
      It first does a quick check of your PC (Windows version, free disk space,
      internet) and tells you plainly if something is wrong.
      It also adds RF Noise Map to Windows Settings > Apps, so it can be removed there.
   3. When it says "All done", double-click Start_RFNoise.bat (or the Desktop
      shortcut if you chose one).

  BY HAND
   1. Make the folder C:\RadioScripts\RFNoise and copy all the files into it.
   2. Open Command Prompt and type:   py -m pip install --user numpy pyserial
   3. Make an empty file named  rfnoise_install.flag  in the RFNoise folder
      (this tells the program to keep your data next to it).
   4. Double-click Start_RFNoise.bat.

  RUNNING IT AGAIN: if RF Noise Map is already installed, the installer offers
  1 = upgrade or repair (keeps your data), 2 = check it and make a support file
  (changes nothing), 3 = uninstall.

  SILENT INSTALL (for experts): open Command Prompt and type
      Install_RFNoise_Windows.bat /silent /dir=C:\RadioScripts
  It uses the default answers and asks nothing.   Uninstall silently:
      Install_RFNoise_Windows.bat /silent /uninstall

  UPGRADE: run the newer Install_RFNoise_Windows.bat and give it the same folder. It
  keeps your Drives, Maps, Exports, Backups and Settings. The old program is
  kept in the folder app_previous (one copy) in case you want to go back.

---------------------------------------------------------------------
PART 2 - THE RADIO (needed only for real measuring)
---------------------------------------------------------------------
  Practice mode and the map features work without any of this.

  TWO RADIOS ARE SUPPORTED, alone or together (each frequency slot on the
  control panel picks its radio):

  HERMES LITE 2 (network cable) - NOTHING TO INSTALL. Plug in its network
  cable and 12 V power, wait 20 seconds, close Thetis / SDR Console, then
  press "Find my radio" on the control panel. HL2_Test.bat tests it.
  It covers HF only (about 0.1 to 38 MHz).

  SDRPLAY (USB) - needs these two free pieces of software:
   1. SDRplay driver:  https://www.sdrplay.com/softwarehome/
      Choose Windows and install the API (version 3.15 or newer). Restart if asked.
   2. PothosSDR (free radio library bundle): link on
      https://github.com/pothosware/PothosSDR/wiki   Install with the defaults.
   3. Plug in the SDRplay, start RF Noise Map and press "Check setup".
  NOTE: PothosSDR's Python part is made for ONE Python version (Python 3.9).
  The installer notices this and uses (or installs) Python 3.9 by itself. If you
  install PothosSDR AFTER this program, run Install_RFNoise_Windows.bat again.
  Close other SDR programs (SDRuno, SDRconnect, SDR Console, HDSDR) first: only
  one program can use the radio at a time. RF Noise Map offers to close them.
  AUTOMATIC TESTS:  Test_Everything.bat checks the radio, the GPS and a pretend
  drive in about a minute.  Find_GPS.bat finds a USB GPS puck and its speed.

---------------------------------------------------------------------
PART 3 - USING IT (short version; the full guide has pictures)
---------------------------------------------------------------------
   1. Start_RFNoise.bat. The panel opens in your browser.
   2. Choose the GPS (iPhone with the GPS2IP app, or a USB GPS puck) and the
      frequencies (up to four; you can change them while driving).
   3. Press Start. Drive. Press Stop.
   4. Press "Make map". View it, print it, save it, or email it.

  Safety: have a passenger run the computer, or set it up while parked.

---------------------------------------------------------------------
PART 4 - PROBLEMS
---------------------------------------------------------------------
  THE LOGS (kept for you, nothing is sent anywhere)
   - Install log: the installer writes one every time. They are kept in the
     Logs folder (newest 10) and a copy of the newest is install_log.txt.
     Also at %LOCALAPPDATA%\RFNoiseMap\Logs  (survives even a failed install).
   - Program error log: Logs\program_errors.log records every problem the
     program meets while running (the panel, the logger, the panadapter).
   - In the panel: Tools > "Show recent problems" shows the last entries.
   - To ask for help: double-click Make_Support_File.bat (or Tools > "Make a
     support file" in the panel). It makes ONE zip file in your user folder.
     Attach it to your message to Claude. Your GPS key and passwords are left out.

  THE INSTALLER'S PROBLEM FINDER
   If the installer meets a problem it prints WHAT WENT WRONG, WHY, WHAT TO DO
   and a web page to read. It knows about: no internet, pip/SSL/proxy blocks,
   Python missing or the wrong version, access denied (antivirus, Controlled
   folder access, OneDrive), a file in use, a full disk, the Microsoft Visual
   C++ runtime (DLL load failed), the SDRplay driver, PothosSDR/Python mismatch,
   a damaged download, restricted PowerShell, a busy port, and winget trouble.
   Then it offers to make the support zip.

  COMMON ANSWERS
   - Windows says "Windows protected your PC": More info > Run anyway.
   - Panel will not open: double-click Open_Panel.bat, or go to
     http://localhost:8780/ in your browser.
   - "DLL load failed": install https://aka.ms/vs/17/release/vc_redist.x64.exe
   - Radio not found: close SDRuno/SDRconnect/SDR Console/HDSDR, replug the
     radio, install the SDRplay API, then press "Check setup".
   - A different Python than 3.9 and PothosSDR installed: run the installer again.

---------------------------------------------------------------------
PART 5 - UNINSTALL
---------------------------------------------------------------------
   Windows Settings > Apps > RF Noise Map > Uninstall, or Start menu >
   RF Noise Map > Uninstall, or double-click Uninstall_RFNoise.bat.
   It shows what is installed and how big your data is, then you choose:
     1  Remove the program only. KEEP your drives, maps and recordings.
     2  Remove the program AND your data (a backup zip is made first, in your
        user folder; if the backup fails nothing of yours is deleted).
     3  Remove everything, no backup (you must type DELETE).
     0  Cancel.
   It also removes the shortcuts, the Start menu folder and the Apps entry.
   It does NOT remove Python, numpy, pyserial, the SDRplay driver or PothosSDR.
   A record of the uninstall is kept at %LOCALAPPDATA%\RFNoiseMap\Logs.
