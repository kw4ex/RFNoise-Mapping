# RFI Trail

Find power-line and other radio noise (RFI, radio-frequency interference) by driving a route.

RFI Trail logs the signal level on up to four frequencies you choose, together with your GPS position, and draws it as colored dots on a street map, so you can see where the noise is loudest and follow it to the source. It works with the radio you already own. RFI Trail is the successor to **RF Noise Map**.

![The RFI Trail control panel (in Practice mode, with a simulated FlexRadio)](docs/images/panel.png)

> **Status (2.0.0, a testing release):** shared as is, no warranty, use at your own risk. Tested on a Windows 11 PC and an Apple-silicon MacBook with a real **ANAN-7000DLE MkIII** and a real **FLEX-6700** (and, in the RF Noise Map versions, a real SDRplay RSP1 and Hermes Lite 2). **RTL-SDR dongles and CAT radios (Icom, Yaesu, Kenwood, Elecraft) have been tried only against simulated radios.** A full real-world noise-hunting drive is the next milestone. Reports are welcome on the [Issues](../../issues) page.

**Read the story:** [The Story of RFI Trail](docs/The-Story-of-RFI-Trail.md) ([PDF](docs/guides/The-Story-of-RFI-Trail.pdf)): the idea, the road bumps, and what it does today. **User guide:** [PDF](docs/guides/RFI_Trail_User_Guide.pdf) (it is also built into the program: press **Help & guide**).

## Download and install

Get the newest zip from the [**Releases**](../../releases) page.

**Windows 10 / 11**
1. Download `RFI_Trail_Windows_v2.0.0.zip` and unzip it.
2. Double-click `Install_RFI_Trail_Windows.bat`. It tells you what it is about to do before each step, and the usual answer is just Enter.
3. At the end, say yes to the firewall question if you use a network radio (ANAN, Hermes Lite 2, FlexRadio).

**Mac**
1. Download `RFI_Trail_Mac_v2.0.0.zip` and unzip it.
2. Open the `mac` folder and double-click `Install_RFI_Trail.command`. (If macOS objects, right-click it and choose Open.)

First try: press **Settings**, then **Try a practice drive + map**. No radio is needed.

## What it does

- Logs up to **four frequencies** at once, saved **by distance** (for example every 10 feet) **or by time**, each reading timed to the millisecond, so a map can show one dot every X feet of route whatever speed you drove.
- Draws a **street map** of colored dots (blue = weak, red = strong), exports to **Google Earth (.kml)**, and keeps backups.
- Every frequency slot is a full **panadapter** (live spectrum and waterfall) with a built-in receiver (AM, SAM, USB, LSB, CW, narrow FM): click a signal to tune it, listen, record audio, and see its S-meter.
- **Your radios, your mix.** SDRplay RSP1, Hermes Lite 2, ANAN, FlexRadio 6000/8000, RTL-SDR dongles, and CAT radios (Icom, Yaesu, Kenwood, Elecraft) in Follow (read only) or Control mode. Each slot picks its own radio; only radios that a slot uses are ever opened.
- **Hardware setup** window with a radio scan, a "Ready to drive?" check, saved setups and per-slot calibration.
- **Practice mode** with a pretend radio and GPS, and a loud banner whenever it is on.
- **Context help**: point at anything and press **?** (or F1).
- GPS from a USB puck or an iPhone (the GPS2IP app).

## Radio drivers

Hermes Lite 2, ANAN and FlexRadio need no driver (on Windows the installer offers to allow their network data through the firewall). An SDRplay needs the SDRplay API (and PothosSDR on Windows) from their own sites; see the guide. Only one program can use a radio at a time, so close Thetis, SDR Console and similar first.

## Credits and history

Designed and tested on the air by **KW4EX**.

**With thanks to Jeff Stuparits, W4DD**, whose own noise-mapping program and generous help, to the author and to many other hams, inspired this one and many of its ideas.

RFI Trail grew from **RF Noise Map** (versions 1.x), which was published in this repository. The last RF Noise Map files remain available on the branch `rfnoise-mapping-legacy`, and its release notes are in [docs/legacy](docs/legacy/). An earlier test version of RFI Trail was called "Noise Trail"; the installers move its data across for you.

## Not made or approved by

SDRplay, Apple, Microsoft, FlexRadio, Apache Labs, Icom, Yaesu, Kenwood, Elecraft, or any other radio maker.

## License

[MIT](LICENSE). Free to use and share.
