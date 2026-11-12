
# RF Noise Map - one-click installer (Windows PowerShell 5.1 or newer)
# This text is plain and readable on purpose: open the installer .bat in Notepad to see it.
$ErrorActionPreference = 'Stop'
$script:Test = [bool]$env:RFNOISE_TEST
$script:IsWin = ($env:OS -eq 'Windows_NT')
$script:Made = @()          # shortcuts we create
$script:PyCmd = ''
$script:PyExit = 0

function Say($t, $c = 'Gray') { Write-Host $t -ForegroundColor $c }
function Head($t) { Write-Host ''; Write-Host ('=== ' + $t + ' ===') -ForegroundColor Cyan }
function Pause-Key { if (-not $script:Test) { Read-Host 'Press Enter to continue' | Out-Null } }
function AskText($q, $d = '') {
    if ($d) { $p = "$q [$d]" } else { $p = $q }
    $r = Read-Host $p
    if ($null -eq $r -or $r.Trim() -eq '') { return $d }
    return $r.Trim()
}
function AskYN($q, [bool]$d) {
    if ($d) { $s = 'Y/n' } else { $s = 'y/N' }
    for ($i = 0; $i -lt 5; $i++) {
        $r = Read-Host "$q ($s)"
        if ($null -eq $r -or $r.Trim() -eq '') { return $d }
        $r = $r.Trim().ToLower()
        if ($r -eq 'y' -or $r -eq 'yes') { return $true }
        if ($r -eq 'n' -or $r -eq 'no') { return $false }
        Say 'Please type y or n.' 'Yellow'
    }
    return $d
}
function Test-Py($cmd, $need) {
    # returns the version text if this command is Python 3.8+ (and exactly $need, e.g. '3.9', when given)
    $ErrorActionPreference = 'Continue'
    try {
        $parts = @($cmd -split ' ')
        if (-not (Get-Command $parts[0] -ErrorAction SilentlyContinue)) { return $null }
        $pre = @(); if ($parts.Count -gt 1) { $pre = $parts[1..($parts.Count - 1)] }
        $out = (& $parts[0] @pre '--version' 2>&1 | Out-String)
        if ($out -match 'Python (\d+)\.(\d+)\.(\d+)') {
            if ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 8) {
                if ($need -and (("$($Matches[1]).$($Matches[2])") -ne $need)) { return $null }
                return $Matches[0]
            }
        }
    } catch { }
    return $null
}
function Find-Python($need) {
    # $need = the exact Python version the radio library needs (like '3.9'), or $null for "any, but prefer 3.9"
    if ($need) { $cands = @("py -$need", 'python', 'python3') }
    else { $cands = @('py -3.9', 'py -3', 'py', 'python', 'python3') }
    foreach ($c in $cands) {
        $v = Test-Py $c $need
        if ($v) { return @{ cmd = $c; ver = $v } }
    }
    return $null
}
function Get-PothosPyVersions {
    # PothosSDR keeps its Python bindings in lib\python3.X - they only work with that exact Python
    $pf = $env:ProgramFiles; if (-not $pf) { $pf = 'C:\Program Files' }
    $lib = Join-Path (Join-Path $pf 'PothosSDR') 'lib'
    $r = @()
    if (Test-Path -LiteralPath $lib) {
        foreach ($d in @(Get-ChildItem -LiteralPath $lib -Directory -ErrorAction SilentlyContinue)) {
            if ($d.Name -match '^python(3\.\d+)$') { $r += $Matches[1] }
        }
    }
    return $r
}
function Invoke-Py([string[]]$PyArgs) {
    $ErrorActionPreference = 'Continue'
    $parts = @($script:PyCmd -split ' ')
    $pre = @(); if ($parts.Count -gt 1) { $pre = $parts[1..($parts.Count - 1)] }
    $out = (& $parts[0] @pre @PyArgs 2>&1 | ForEach-Object { if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { $_ } } | Out-String)
    $script:PyExit = $LASTEXITCODE
    return $out
}
function Test-PyModule($m) {
    $o = Invoke-Py @('-c', "import $m;print('MODULE_OK')")
    return ($o -match '(?m)^\s*MODULE_OK\s*$')
}
function Ensure-Pip {
    $o = Invoke-Py @('-m', 'pip', '--version')
    if ($script:PyExit -eq 0 -and $o -match 'pip \d') { return $true }
    Say 'The Python package installer (pip) is missing or broken. Repairing it...' 'Yellow'
    $o = Invoke-Py @('-m', 'ensurepip', '--user')
    $o = Invoke-Py @('-m', 'pip', '--version')
    if ($script:PyExit -eq 0 -and $o -match 'pip \d') { Say 'pip repaired.' 'Green'; return $true }
    $o = Invoke-Py @('-m', 'ensurepip', '--upgrade')
    $o = Invoke-Py @('-m', 'pip', '--version')
    return ($script:PyExit -eq 0 -and $o -match 'pip \d')
}
function Ensure-PyModule($m, $pkg) {
    if (Test-PyModule $m) { Say "$pkg is already installed." 'Green'; return $true }
    if (-not ($script:Test -and $env:RFNOISE_TEST_NOPIP)) { $null = Ensure-Pip }
    if ($script:Test -and $env:RFNOISE_TEST_NOPIP) { Say "(test mode: $pkg install skipped)"; return $false }
    Say "Installing $pkg (small helper library, needs internet)..."
    $o = Invoke-Py @('-m', 'pip', 'install', '--user', '--quiet', '--disable-pip-version-check', $pkg)
    if (-not (Test-PyModule $m)) {   # some Python setups refuse --user: try the normal way
        $o = Invoke-Py @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', $pkg)
    }
    if (Test-PyModule $m) { Say "$pkg installed." 'Green'; return $true }
    Say "$pkg could not be installed (no internet, or pip is missing)." 'Yellow'
    $last = @($o -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 2)
    foreach ($l in $last) { Say ('  ' + $l.Trim()) }
    return $false
}
function New-Shortcut($lnk, $target, $workdir, $desc, $icon) {
    $w = New-Object -ComObject WScript.Shell
    $s = $w.CreateShortcut($lnk)
    $s.TargetPath = $target; $s.WorkingDirectory = $workdir
    $s.Description = $desc; $s.WindowStyle = 7
    if ($icon -and (Test-Path -LiteralPath $icon)) { $s.IconLocation = $icon }
    $s.Save()
}
function Get-RunningPorts {
    # the ports (8780-8789) where an RF Noise Map control panel answers
    $r = @()
    for ($p = 8780; $p -le 8789; $p++) {
        try {
            $x = Invoke-WebRequest -Uri ("http://127.0.0.1:$p/api/ping") -UseBasicParsing -TimeoutSec 1
            if ($x.Content -match '"app"\s*:\s*"rfmap"') { $r += $p }
        } catch { }
    }
    return $r
}

# =========================================================================
$log = Join-Path ([IO.Path]::GetTempPath()) 'rfnoise_install_log.txt'
try { Start-Transcript -Path $log -Force | Out-Null } catch { }
$tmp = $null
try {

Clear-Host
Say '==========================================================' 'Cyan'
Say '   RF Noise Map - one-click installer' 'Cyan'
Say '==========================================================' 'Cyan'
Say ''
Say 'This sets up RF Noise Map: it drives a route with an SDRplay radio and'
Say 'a GPS, then draws a street map of where the radio noise is strongest.'
Say 'It asks a few short questions. Press Enter to accept the'
Say 'answer shown in [brackets]. Nothing is changed until you'
Say 'confirm the install folder.'

# ---- unpack the files that travel inside this installer -------------------
$tmp = Join-Path ([IO.Path]::GetTempPath()) ('rfnoise_pkg_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$all = [IO.File]::ReadAllText($env:RFNOISE_INSTALLER)
$b0 = $all.IndexOf("`n#PAYLOAD-BEGIN")
$b1 = $all.IndexOf("`n#PAYLOAD-END")
if ($b0 -lt 0 -or $b1 -lt 0) { throw 'This installer file looks damaged (no payload). Please download it again.' }
$b64 = $all.Substring($b0 + 15, $b1 - $b0 - 15) -replace '\s', ''
$zip = Join-Path $tmp 'pkg.zip'
[IO.File]::WriteAllBytes($zip, [Convert]::FromBase64String($b64))
Add-Type -AssemblyName System.IO.Compression.FileSystem
$pk = Join-Path $tmp 'files'
[IO.Compression.ZipFile]::ExtractToDirectory($zip, $pk)
$newApp = Join-Path (Join-Path $pk 'app') 'rfmap_app.py'
$newCommon = Join-Path (Join-Path $pk 'app') 'rfmap_common.py'
$newVer = ([regex]::Match([IO.File]::ReadAllText($newCommon), '(?m)^VERSION = "([\d.]+)"')).Groups[1].Value
Say ("This installer contains RF Noise Map version $newVer.") 'Gray'

# ---- 1. Python ---------------------------------------------------------------
Head 'Step 1 of 7: Python'
$pothVers = @(Get-PothosPyVersions)
$need = $null
if ($pothVers.Count -ge 1) {
    $need = $pothVers[0]
    Say "The radio library on this PC (PothosSDR) only works with Python $need, so Python $need will be used." 'Gray'
}
$script:RadioPyMismatch = $false
$py = Find-Python $need
if (-not $py) {
    $want = $need; if (-not $want) { $want = '3.9' }
    if ($need) { Say "Python $need was not found on this computer. It is needed for the SDRplay radio library." 'Yellow' }
    else { Say 'Python was not found on this computer. The program needs it (Python 3.9 is installed because the radio library needs that version).' 'Yellow' }
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget -and $script:IsWin -and -not $script:Test) {
        if (AskYN "Install Python $want now with Windows (winget)? About 100 MB. It does not change your other Python versions." $true) {
            try {
                & winget install -e --id ("Python.Python." + $want) --accept-package-agreements --accept-source-agreements
                $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
                $py = Find-Python $need
            } catch { Say "The automatic install did not finish: $($_.Exception.Message)" 'Yellow' }
        }
    }
    if (-not $py -and $need) {
        Say ''
        Say "Python $need could not be set up automatically." 'Yellow'
        Say "  1. Go to https://www.python.org/downloads/windows/ and download 'Python $need' (the newest $need.x installer, 64-bit)."
        Say '  2. Run it (you can leave "Add python.exe to PATH" ticked or not - this installer finds it either way).'
        Say '  3. Double-click this installer again.'
        if (AskYN 'Continue anyway with another Python (practice mode and maps work; the real radio will NOT)?' $false) {
            $py = Find-Python $null
            $script:RadioPyMismatch = $true
        }
    }
    if (-not $py) {
        Say ''
        Say 'Please install Python yourself, then run this installer again:' 'Yellow'
        Say '  1. Go to https://www.python.org/downloads/windows/ and download Python 3.9 (64-bit).'
        Say '  2. Run it and TICK "Add python.exe to PATH" on the first screen.'
        Say '  3. Double-click this installer again.'
        if (-not $script:Test -and $script:IsWin) { if (AskYN 'Open the download page now?' $true) { Start-Process 'https://www.python.org/downloads/windows/' } }
        Pause-Key
        try { Stop-Transcript | Out-Null } catch { }
        exit 2
    }
}
$script:PyCmd = $py.cmd
Say ("Using $($py.ver)  (command: $($py.cmd))") 'Green'
if ($script:RadioPyMismatch) { Say "NOTE: this Python does not match the radio library (needs $need). Fix this later by installing Python $need and running this installer again." 'Yellow' }

# numpy does the radio maths; pyserial talks to a USB GPS
$haveNumpy = Ensure-PyModule 'numpy' 'numpy'
$null = Ensure-PyModule 'serial' 'pyserial'
if (-not $haveNumpy) {
    Say ''
    Say 'numpy is required and could not be installed. Connect to the internet and run this installer again.' 'Yellow'
    Say 'Or, in Command Prompt, type:   py -m pip install numpy pyserial' 'Yellow'
    Pause-Key
    try { Stop-Transcript | Out-Null } catch { }
    exit 2
}

# ---- 2. Where to install ------------------------------------------------------
Head 'Step 2 of 7: Install folder'
$SUB = 'RFNoise'
$def = 'C:\RadioScripts'
if ($env:RFNOISE_TEST_DIR) { $def = $env:RFNOISE_TEST_DIR }
Say 'Choose the folder for your radio programs. RF Noise Map gets its OWN subfolder in it,'
Say "named $SUB, so its files never mix with your other programs."
Say 'Your recorded drives and maps are kept in that same subfolder.'
Say 'Do not use "Program Files" (Windows blocks the log and settings there).'
$dir = ''; $base = ''
while (-not $dir) {
    $d = AskText 'Folder' $def
    $d = $d.Trim('"').TrimEnd('\')
    if ($d -match '(?i)\\Program Files') { Say 'Please choose another folder (not Program Files).' 'Yellow'; continue }
    if ((Split-Path $d -Leaf) -ieq $SUB) { $b = Split-Path $d -Parent; $sd = $d } else { $b = $d; $sd = Join-Path $d $SUB }
    if (-not (Test-Path $b)) {
        if (-not (AskYN "The folder $b does not exist. Create it?" $true)) { continue }
        try { New-Item -ItemType Directory -Path $b -Force | Out-Null } catch { Say "Could not create it: $($_.Exception.Message)" 'Yellow'; continue }
    }
    try {
        if (-not (Test-Path $sd)) { New-Item -ItemType Directory -Path $sd -Force | Out-Null }
        $t = Join-Path $sd '.write_test'; [IO.File]::WriteAllText($t, 'x'); Remove-Item $t -Force
    } catch { Say 'That folder is not writable. Choose another.' 'Yellow'; continue }
    $dir = $sd; $base = $b
}
Say "RF Noise Map goes into:  $dir" 'Green'
$appDir = Join-Path $dir 'app'
$prevDir = Join-Path $dir 'app_previous'
$launcher = Join-Path $dir 'Start_RFNoise.bat'
$oldCommon = Join-Path $appDir 'rfmap_common.py'

# ---- 3. Copy the program -------------------------------------------------------
Head 'Step 3 of 7: Copying the program'
$upgrade = Test-Path -LiteralPath $oldCommon
if ($upgrade) {
    $oldVer = ([regex]::Match([IO.File]::ReadAllText($oldCommon), '(?m)^VERSION = "([\d.]+)"')).Groups[1].Value
    Say ("An earlier install (version $oldVer) is in this folder. It will be upgraded to $newVer.") 'Yellow'
    Say 'Your drives, maps, exports, backups and settings are kept. The old program is saved in the folder app_previous.'
    if (-not (AskYN 'Continue?' $true)) { Say 'Cancelled. Nothing was changed.'; Pause-Key; exit 0 }
}
$ports = @(Get-RunningPorts)
if ($ports.Count -gt 0) {
    Say ''
    Say 'RF Noise Map is running right now. It has to be closed so the files can be replaced.' 'Yellow'
    Say 'If it is recording a drive, the recording is stopped and saved.'
    if (AskYN 'Close it now?' $true) {
        $o = Invoke-Py @($newApp, '--stop')
        Start-Sleep -Seconds 2
        if (@(Get-RunningPorts).Count -gt 0) { throw 'RF Noise Map is still running. Close it (press Quit in its panel) and run this installer again.' }
        Say 'Closed.' 'Green'
    } else {
        throw 'Please close RF Noise Map first (press Quit in its panel), then run this installer again.'
    }
}
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
if ($upgrade) {
    if (Test-Path -LiteralPath $prevDir) { Remove-Item -LiteralPath $prevDir -Recurse -Force }
    Move-Item -LiteralPath $appDir -Destination $prevDir -Force
    if (Test-Path -LiteralPath $launcher) { Copy-Item -LiteralPath $launcher -Destination ($launcher + '.' + $stamp + '.bak') -Force }
} elseif (Test-Path -LiteralPath $appDir) {
    Remove-Item -LiteralPath $appDir -Recurse -Force
}
Copy-Item -LiteralPath (Join-Path $pk 'app') -Destination $appDir -Recurse -Force
foreach ($f in @('Open_Panel.bat', 'README_RFNoise.txt', 'RFNoise_Help.html', 'RFNoise_User_Guide.pdf')) {
    Copy-Item -LiteralPath (Join-Path $pk $f) -Destination (Join-Path $dir $f) -Force
}
# the start, stop, uninstall, test and GPS-finder files carry the Python command found in step 1
foreach ($nm in @('Start_RFNoise', 'Stop_RFNoise', 'Uninstall_RFNoise', 'Test_Everything', 'Find_GPS')) {
    $bt = [IO.File]::ReadAllText((Join-Path $pk ($nm + '.template.bat'))).Replace('@@PYCMD@@', $script:PyCmd)
    [IO.File]::WriteAllText((Join-Path $dir ($nm + '.bat')), $bt)
}
# the marker file tells the program to keep your data in this folder
[IO.File]::WriteAllText((Join-Path $dir 'rfnoise_install.flag'), "RF Noise Map install marker. Do not delete: it makes the program keep your data in this folder.`r`n")
foreach ($d in @('Drives', 'Maps', 'Exports', 'Backups', 'Settings')) { New-Item -ItemType Directory -Force -Path (Join-Path $dir $d) | Out-Null }
if (-not (Test-Path -LiteralPath (Join-Path $appDir 'rfmap_app.py'))) { throw "Could not copy the program files into $dir." }
Say "Program files copied to $dir" 'Green'
Say 'Data folders ready: Drives, Maps, Exports, Backups, Settings' 'Green'

# ---- 4. The radio -----------------------------------------------------------------
Head 'Step 4 of 7: The radio (SDRplay)'
Say 'The SDRplay driver is not included (it comes from sdrplay.com). Practice mode and the'
Say 'map features work without it. Looking for it on this computer (changes nothing):'
$pf = $env:ProgramFiles; if (-not $pf) { $pf = 'C:\Program Files' }
$sdrFound = Test-Path -LiteralPath (Join-Path $pf 'SDRplay')
$pothFound = Test-Path -LiteralPath (Join-Path $pf 'PothosSDR')
if ($sdrFound) { Say '  SDRplay driver (API):  found' 'Green' } else { Say '  SDRplay driver (API):  not found' 'Yellow' }
if ($pothFound) { Say '  PothosSDR radio library:  found' 'Green' } else { Say '  PothosSDR radio library:  not found' 'Yellow' }
$o = Invoke-Py @((Join-Path $appDir 'check_setup.py'))
foreach ($l in ($o -split "`r?`n" | Where-Object { $_.Trim() })) { Say ('  ' + $l) }
if (-not $sdrFound -or -not $pothFound) {
    Say ''
    Say 'To measure with the radio you need both of these (see Part 2 of README_RFNoise.txt):'
    Say '  1. SDRplay API, version 3.15 or newer:  https://www.sdrplay.com/softwarehome/'
    Say '  2. PothosSDR (free):  https://github.com/pothosware/PothosSDR/wiki'
    if ($script:IsWin -and -not $script:Test) {
        if (-not $sdrFound -and (AskYN 'Open the SDRplay download page now?' $false)) { Start-Process 'https://www.sdrplay.com/softwarehome/' }
        if (-not $pothFound -and (AskYN 'Open the PothosSDR page now?' $false)) { Start-Process 'https://github.com/pothosware/PothosSDR/wiki' }
    }
}

# programs that may be holding the radio or a GPS port
$blk = Invoke-Py @((Join-Path $appDir 'device_guard.py'), '--list')
$blkLines = @($blk -split "`r?`n" | Where-Object { $_ -match '^PROGRAM:' })
if ($blkLines.Count -gt 0) {
    Say ''
    Say 'These programs are open and may be using the radio or a GPS port (only one program can at a time):' 'Yellow'
    foreach ($l in $blkLines) { Say ('  ' + ($l -replace '^PROGRAM:\d+:', '')) }
    if (AskYN 'Close them now? (they are asked politely to close; save your work first)' $false) {
        $o = Invoke-Py @((Join-Path $appDir 'device_guard.py'), '--close')
        foreach ($l in ($o -split "`r?`n" | Where-Object { $_.Trim() })) { Say ('  ' + $l) }
    }
}
if ($script:RadioPyMismatch) { Say 'REMINDER: the radio will not work until Python and the radio library match (see Step 1).' 'Yellow' }

# ---- 5. GPS ------------------------------------------------------------------------
Head 'Step 5 of 7: GPS'
$script:UsbGps = $false
Say 'RF Noise Map can take its position from an iPhone (GPS2IP app) or from a USB GPS puck.'
if (AskYN 'Do you use a USB GPS puck plugged into this PC? (say no if you use the iPhone)' $false) {
    $script:UsbGps = $true
    Say 'Plug the puck in now. A window or the outdoors is best, but it is not needed just to find it.'
    if (-not $script:Test) { Read-Host 'Press Enter when it is plugged in' | Out-Null }
    Say 'Looking for it on the COM ports and speeds. This can take up to a minute...'
    $o = Invoke-Py @((Join-Path $appDir 'gps_detect.py'), '--save')
    foreach ($l in ($o -split "`r?`n" | Where-Object { $_.Trim() })) { Say ('  ' + $l) }
    if ($o -match 'Found a GPS') { Say 'GPS found and saved. The panel is already set to it.' 'Green' }
    else { Say 'No GPS found yet. You can try again any time with Find_GPS.bat (in the install folder).' 'Yellow' }
} else {
    Say 'OK - iPhone. Turn on its Personal Hotspot, join this PC to it and run GPS2IP when you drive (see the guide).'
}

# ---- 5. Shortcuts -----------------------------------------------------------------
Head 'Step 6 of 7: Shortcuts'
if ($script:IsWin -and -not $script:Test) {
    $icon = Join-Path $appDir 'icon.ico'
    $lnkD = Join-Path ([Environment]::GetFolderPath('Desktop')) 'RF Noise Map.lnk'
    $lnkS = Join-Path ([Environment]::GetFolderPath('Startup')) 'RF Noise Map.lnk'
    foreach ($l in @($lnkD, $lnkS)) {
        if (Test-Path -LiteralPath $l) {
            try { New-Shortcut $l $launcher $dir 'Start RF Noise Map' $icon; $script:Made += $l; Say "Shortcut updated: $l" 'Green' } catch { }
        }
    }
    if ((Test-Path -LiteralPath $lnkD) -and ($script:Made -contains $lnkD)) { }
    elseif (AskYN 'Put a "RF Noise Map" shortcut on the Desktop?' $true) {
        try { New-Shortcut $lnkD $launcher $dir 'Start RF Noise Map' $icon; $script:Made += $lnkD; Say 'Desktop shortcut created.' 'Green' }
        catch { Say "Could not create the shortcut: $($_.Exception.Message)" 'Yellow' }
    }
    if ((Test-Path -LiteralPath $lnkS) -and ($script:Made -contains $lnkS)) { }
    elseif (AskYN 'Start RF Noise Map automatically when you sign in to Windows?' $false) {
        try { New-Shortcut $lnkS $launcher $dir 'Start RF Noise Map at sign-in' $icon; $script:Made += $lnkS; Say 'Auto-start set up. (To undo: delete that shortcut from the Startup folder.)' 'Green' }
        catch { Say "Could not create the auto-start shortcut: $($_.Exception.Message)" 'Yellow' }
    }
} else { Say '(test mode: shortcuts skipped)' }

# ---- 6. Self-test -----------------------------------------------------------------
Head 'Step 7 of 7: Tests'
if (AskYN 'Run a quick self-test with practice data now (about 20 seconds; your real data is not touched)?' $true) {
    Say 'Testing...'
    $tdir = Join-Path ([IO.Path]::GetTempPath()) ('rfnoise_test_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    $tdrv = Join-Path $tdir 'Drives'
    New-Item -ItemType Directory -Path $tdrv -Force | Out-Null
    $env:RFMAP_DATA = $tdir
    $ok = $false
    try {
        $o1 = Invoke-Py @((Join-Path $appDir 'rf_logger.py'), '--gps', 'sim', '--sdr', 'sim', '--outdir', $tdrv, '--settings', (Join-Path $tdir 's.json'), '--port', '8799', '--local-only')
        $csv = Get-ChildItem -LiteralPath $tdrv -Filter *.csv -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($csv) {
            $tmap = Join-Path $tdir 'test_map.html'
            $o2 = Invoke-Py @((Join-Path $appDir 'make_map.py'), $csv.FullName, '-o', $tmap)
            if ((Test-Path -LiteralPath $tmap) -and ((Get-Item -LiteralPath $tmap).Length -gt 1000)) { $ok = $true }
        }
    } finally { Remove-Item Env:\RFMAP_DATA -ErrorAction SilentlyContinue }
    try { Remove-Item -LiteralPath $tdir -Recurse -Force } catch { }
    if ($ok) { Say 'SELF-TEST PASSED: the logger and the map builder both work.' 'Green' }
    else {
        Say 'The self-test did not pass. The details are in install_log.txt in the install folder.' 'Yellow'
        Say 'Please send that file to Claude.' 'Yellow'
        $bad = @(($o1 + $o2) -split "`r?`n" | Where-Object { $_ -match 'Traceback|Error' } | Select-Object -First 6)
        foreach ($l in $bad) { Say ('  ' + $l.Trim()) }
    }
}

if ($pothFound -and $sdrFound -and -not $script:RadioPyMismatch -and -not $script:Test) {
    Say ''
    Say 'The FULL TEST checks the real radio, the GPS and a pretend drive in about a minute.'
    Say 'Have the radio (with antenna) and the GPS puck plugged in.'
    if (AskYN 'Run the full test now?' $true) {
        $fa = @((Join-Path $appDir 'full_test.py'), '--report', (Join-Path $dir 'full_test_report.txt'))
        if (-not $script:UsbGps) { $fa += '--iphone' }
        $o = Invoke-Py $fa
        foreach ($l in ($o -split "`r?`n" | Where-Object { $_.Trim() })) {
            if ($l -match '\[FIX') { Say ('  ' + $l) 'Yellow' } elseif ($l -match '\[WARN') { Say ('  ' + $l) 'Yellow' } else { Say ('  ' + $l) }
        }
        Say 'You can repeat this any time: double-click Test_Everything.bat. (Report: full_test_report.txt)'
    }
} elseif (-not $script:Test) {
    Say ''
    Say 'Later, when the radio driver and GPS are set up, double-click Test_Everything.bat to test everything automatically.'
}

# ---- done -----------------------------------------------------------------------
Head 'All done'
Say "Installed in:   $dir" 'Green'
Say ("Start it with: " + $launcher + $(if ($script:Made.Count) { '   (or the Desktop shortcut)' } else { '' })) 'Green'
Say 'Control panel: http://localhost:8780  (it opens in your browser by itself)'
Say 'Your data:     the folders Drives, Maps, Exports, Backups and Settings in the install folder.'
Say 'Stop it:       press Quit in the panel, or double-click Stop_RFNoise.bat.'
Say 'Test it:       Test_Everything.bat checks the radio, GPS and a pretend drive. Find_GPS.bat finds your GPS puck.'
Say 'Help file:     RFNoise_Help.html (also the Help button in the panel). A printable PDF guide is there too.'
Say 'To remove:     run Uninstall_RFNoise.bat in the install folder (it asks before it deletes your data).'
try { Stop-Transcript | Out-Null; Copy-Item $log (Join-Path $dir 'install_log.txt') -Force } catch { }
if ($script:IsWin -and -not $script:Test) {
    Say ''
    $goApp = AskYN 'Start RF Noise Map now?' $true
    $goHelp = AskYN 'Open the help file now?' $false
    if ($goApp) { Start-Process -FilePath $launcher -WorkingDirectory $dir; Start-Sleep -Seconds 1 }
    if ($goHelp) { Start-Process (Join-Path $dir 'RFNoise_Help.html') }
}

} catch {
    Say ''
    Say ('PROBLEM: ' + $_.Exception.Message) 'Red'
    Say 'Nothing was damaged. Please send a screenshot of this window (or the file install_log.txt) to Claude.' 'Yellow'
    try { Stop-Transcript | Out-Null } catch { }
    Pause-Key
    exit 1
} finally {
    if ($tmp) { try { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue } catch { } }
}
