RF NOISE MAP  v1.1   (Windows 11)
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
        Uninstall_RFNoise.bat         removes the program (asks about your data)
        README_RFNoise.txt            this file
        RFNoise_Help.html             the full guide (also inside the program)
        RFNoise_User_Guide.pdf        the same guide, to print
        install_log.txt               a copy of what the installer said
        app\                          the program files (do not edit)
        Drives\                       one .csv file per recorded drive
        Maps\                         finished maps (.html, open in any browser)
        Exports\                      Google Earth .kml files and email .zip files
        Backups\                      zip backups
        Settings\                     your remembered choices and the logger log

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
      numpy and pyserial, copies the program, offers the shortcuts, and runs a
      quick self-test with practice data.
   3. When it says "All done", double-click Start_RFNoise.bat (or the Desktop
      shortcut if you chose one).

  BY HAND
   1. Make the folder C:\RadioScripts\RFNoise and copy all the files into it.
   2. Open Command Prompt and type:   py -m pip install --user numpy pyserial
   3. Make an empty file named  rfnoise_install.flag  in the RFNoise folder
      (this tells the program to keep your data next to it).
   4. Double-click Start_RFNoise.bat.

  UPGRADE: run the newer Install_RFNoise_Windows.bat and give it the same folder. It
  keeps your Drives, Maps, Exports, Backups and Settings. The old program is
  kept in the folder app_previous (one copy) in case you want to go back.

---------------------------------------------------------------------
PART 2 - THE RADIO (needed only for real measuring)
---------------------------------------------------------------------
  Practice mode and the map features work without any of this.
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
   - The window shows a message and stops: send install_log.txt and the
     message to Claude.
   - Panel will not open: double-click Open_Panel.bat, or go to
     http://localhost:8780/ in your browser.
   - To remove everything: Uninstall_RFNoise.bat (it asks before it deletes
     your recorded data, and keeps it unless you say yes).
