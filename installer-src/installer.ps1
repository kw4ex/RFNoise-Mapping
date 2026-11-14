
# RF Noise Map - one-click installer (Windows PowerShell 5.1 or newer)
# This text is plain and readable on purpose: open the installer .bat in Notepad to see it.
$ErrorActionPreference = 'Stop'
$script:Test = [bool]$env:RFNOISE_TEST
$script:IsWin = ($env:OS -eq 'Windows_NT')
$script:Made = @()          # shortcuts we create
$script:PyCmd = ''
$script:PyExit = 0
$script:Raw = ''            # raw output of the tools we run (used to find the cause of a problem)
$script:Warns = @()         # things worth telling you about at the end
$script:LogDir = ''         # install folder's Logs folder (known after step 2)
# options typed after the installer name:  /silent  /dir=C:\RadioScripts  /uninstall  /repair
$script:Silent = $false; $script:OptDir = ''; $script:OptUninst = $false
$ra = [string]$env:RFNOISE_ARGS
if ($ra -match '(?i)/silent') { $script:Silent = $true }
if ($ra -match '(?i)/uninstall') { $script:OptUninst = $true }
if ($ra -match '(?i)/dir=("([^"]+)"|(\S+))') { $script:OptDir = ($Matches[2] + $Matches[3]) }

function Say($t, $c = 'Gray') { Write-Host $t -ForegroundColor $c }
function Note-Warn($t) { $script:Warns += $t }
function Head($t) { Write-Host ''; Write-Host ('=== ' + $t + ' ===') -ForegroundColor Cyan }
function Pause-Key { if (-not $script:Test -and -not $script:Silent) { Read-Host 'Press Enter to continue' | Out-Null } }
function AskText($q, $d = '') {
    if ($script:Silent) { return $d }
    if ($d) { $p = "$q [$d]" } else { $p = $q }
    $r = Read-Host $p
    if ($null -eq $r -or $r.Trim() -eq '') { return $d }
    return $r.Trim()
}
function AskYN($q, [bool]$d) {
    if ($script:Silent) { return $d }
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
    $script:Raw += "`n" + $out
    if ($script:Raw.Length -gt 60000) { $script:Raw = $script:Raw.Substring($script:Raw.Length - 40000) }
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
    # the ports (8780-8789) where an RF Noise Map control panel answers.
    # A quick connection test first (0.3 s per port), so closed ports do not slow the installer down.
    $r = @()
    for ($p = 8780; $p -le 8789; $p++) {
        $open = $false
        $c = $null
        try {
            $c = New-Object System.Net.Sockets.TcpClient
            $iar = $c.BeginConnect('127.0.0.1', $p, $null, $null)
            if ($iar.AsyncWaitHandle.WaitOne(300)) { try { $c.EndConnect($iar); $open = $c.Connected } catch { } }
        } catch { }
        if ($c) { try { $c.Close() } catch { } }
        if (-not $open) { continue }
        try {
            $x = Invoke-WebRequest -Uri ("http://127.0.0.1:$p/api/ping") -UseBasicParsing -TimeoutSec 2
            if ($x.Content -match '"app"\s*:\s*"rfmap"') { $r += $p }
        } catch { }
    }
    return $r
}

# ---- problem finder: turns a raw error into plain words, a fix and a web page -------
function Rule($pat, $title, $meaning, $fix, $url) { return @{ pat = $pat; title = $title; meaning = $meaning; fix = $fix; url = $url } }
function Get-Rules {
    @(
    (Rule 'SSLError|CERTIFICATE_VERIFY_FAILED|ProxyError|Could not fetch URL' 'The download was blocked (security certificate or proxy)' 'A firewall, antivirus web shield, company proxy or a wrong PC clock stops Python from downloading numpy/pyserial.' 'Check the PC date and time. Turn off "web protection" in your antivirus for a few minutes, or try another network (a phone hotspot works). Then run this installer again.' 'https://pip.pypa.io/en/stable/topics/https-certificates/'),
    (Rule 'Failed to establish a new connection|getaddrinfo|Name or service not known|Temporary failure in name|Connection aborted|Max retries exceeded|timed out|No connection could be made' 'No internet connection' 'The installer could not reach the download site (pypi.org).' 'Connect to the internet (open any web page to test), then run this installer again.' 'https://pypi.org/'),
    (Rule 'No matching distribution|Could not find a version that satisfies' 'No matching download for this Python' 'This Python version or 32-bit Python has no ready-made numpy.' 'Install the 64-bit Python 3.9 from python.org, tick Add python.exe to PATH, and run this installer again.' 'https://www.python.org/downloads/windows/'),
    (Rule 'Access to the path|Access is denied|UnauthorizedAccess|PermissionError|WinError 5' 'Windows refused to write there (access denied)' 'The folder is protected, or an antivirus / "Controlled folder access" / OneDrive is blocking the write.' 'Choose a folder you own such as C:\RadioScripts (not Program Files, not a OneDrive or Desktop folder). Or allow the installer in Windows Security > Ransomware protection.' 'https://support.microsoft.com/windows/allow-an-app-through-controlled-folder-access'),
    (Rule 'used by another process|being used by another|sharing violation' 'A file is in use' 'RF Noise Map, a browser tab, a folder window, or an antivirus scan is holding a file.' 'Press Quit in the RF Noise Map panel, close folder windows showing it, wait a minute, then run this installer again.' ''),
    (Rule 'not enough space|No space left|disk is full|There is not enough space' 'The disk is full' 'There is not enough free space to copy the program.' 'Free up at least 500 MB (empty the Recycle Bin, run Disk Cleanup) and run this installer again.' 'https://support.microsoft.com/windows/free-up-drive-space-in-windows-85529ccb-c365-490d-b548-831022bc9b32'),
    (Rule 'DLL load failed|VCRUNTIME140|MSVCP140|api-ms-win-crt|0xc000007b' 'A Microsoft runtime library is missing' 'numpy and the radio library need the Microsoft Visual C++ runtime.' 'Install it (free, 1 minute): https://aka.ms/vs/17/release/vc_redist.x64.exe  then run this installer again.' 'https://aka.ms/vs/17/release/vc_redist.x64.exe'),
    (Rule 'sdrplay_api|SDRplay API|sdrplay_apiService' 'The SDRplay driver is missing or not running' 'The radio program needs the SDRplay API service from sdrplay.com.' 'Install the SDRplay API for Windows (3.15 or newer), restart the PC, plug in the radio, then press Check setup in RF Noise Map.' 'https://www.sdrplay.com/softwarehome/'),
    (Rule "No module named '?SoapySDR|SoapySDR" 'The radio library (PothosSDR) is missing or does not match Python' 'PothosSDR only works with the one Python version it was built for (3.9).' 'Install PothosSDR with the defaults, then run this installer again so it picks the matching Python.' 'https://github.com/pothosware/PothosSDR/wiki/Tutorial'),
    (Rule "No module named '?numpy|numpy.*Importing the numpy C-extensions failed" 'numpy is missing or broken' 'The math library is not installed for this Python.' 'In Command Prompt type:  py -m pip install --upgrade --force-reinstall numpy  then run this installer again.' 'https://numpy.org/install/'),
    (Rule "No module named '?serial" 'pyserial is missing' 'Only a USB GPS puck needs it.' 'In Command Prompt type:  py -m pip install pyserial' 'https://pypi.org/project/pyserial/'),
    (Rule "Python was not found|is not recognized as the name|No suitable Python|py is not recognized" 'Python is not installed (or not found)' 'The program is written in Python.' 'Install Python 3.9 (64-bit) from python.org, tick Add python.exe to PATH, then run this installer again.' 'https://www.python.org/downloads/windows/'),
    (Rule 'looks damaged|FromBase64String|Invalid length for a Base-64|payload' 'The installer file is damaged' 'It was cut short while downloading, or a security program changed it.' 'Download Install_RFNoise_Windows.bat again, right-click it > Properties > tick Unblock if shown, and run it again.' 'https://github.com/kw4ex/RFNoise-Mapping/releases'),
    (Rule 'running scripts is disabled|ConstrainedLanguage|cannot be loaded because running scripts' 'PowerShell is restricted on this PC' 'A company policy limits PowerShell scripts.' 'Ask the PC administrator, or use the BY HAND steps in README_RFNoise.txt.' 'https://learn.microsoft.com/powershell/module/microsoft.powershell.core/about/about_execution_policies'),
    (Rule 'Address already in use|WinError 10048|only one usage of each socket' 'The panel port is busy' 'Another copy of the program (or another program) uses port 8780.' 'Run Stop_RFNoise.bat, or restart the PC, then start it again.' ''),
    (Rule 'winget' 'Windows could not install Python by itself' 'winget (the Windows app installer) is missing or was refused.' 'Install Python 3.9 yourself from python.org (tick Add python.exe to PATH) and run this installer again.' 'https://www.python.org/downloads/windows/'),
    (Rule 'PathTooLong|path.*too long|filename or extension is too long' 'The folder name is too long' 'Windows limits path length.' 'Install in a short folder such as C:\RadioScripts.' ''),
    (Rule 'still running|Close it \(press Quit' 'RF Noise Map is still running' 'The files cannot be replaced while it runs.' 'Press Quit in its panel (or run Stop_RFNoise.bat) and run this installer again.' '')
    )
}
function Explain-Problem([string]$text, [bool]$quiet = $false) {
    $n = 0
    foreach ($r in (Get-Rules)) {
        if ($text -match $r.pat) {
            $n++
            if ($n -gt 3) { break }
            Say ''
            Say ('  WHAT WENT WRONG: ' + $r.title) 'Yellow'
            Say ('  WHY:             ' + $r.meaning)
            Say ('  WHAT TO DO:      ' + $r.fix) 'Green'
            if ($r.url) { Say ('  MORE HELP:       ' + $r.url) 'Cyan' }
        }
    }
    if ($n -eq 0 -and -not $quiet) {
        Say ''
        Say '  I could not match this to a known cause.' 'Yellow'
        Say '  WHAT TO DO: press Y below to make a support file, and send that zip to Claude.' 'Green'
        Say '  GENERAL HELP: https://github.com/kw4ex/RFNoise-Mapping/releases  (see README_RFNoise.txt, Part 4)' 'Cyan'
    }
    return $n
}
# ---- the install log is kept: first in %LOCALAPPDATA%\RFNoiseMap\Logs, then in <install folder>\Logs ----
function Save-Log {
    try { Stop-Transcript | Out-Null } catch { }
    if (-not (Test-Path -LiteralPath $script:LogFile)) { return }
    try {
        if ($script:Dir2) {
            $ld = Join-Path $script:Dir2 'Logs'
            New-Item -ItemType Directory -Force -Path $ld | Out-Null
            Copy-Item -LiteralPath $script:LogFile -Destination (Join-Path $ld ('install_log_' + $script:Stamp0 + '.txt')) -Force
            Copy-Item -LiteralPath $script:LogFile -Destination (Join-Path $script:Dir2 'install_log.txt') -Force
            foreach ($old in @(Get-ChildItem -LiteralPath $ld -Filter 'install_log_*.txt' | Sort-Object Name -Descending | Select-Object -Skip 10)) { Remove-Item -LiteralPath $old.FullName -Force -ErrorAction SilentlyContinue }
        }
        foreach ($old in @(Get-ChildItem -LiteralPath (Split-Path $script:LogFile) -Filter 'install_log_*.txt' | Sort-Object Name -Descending | Select-Object -Skip 10)) { Remove-Item -LiteralPath $old.FullName -Force -ErrorAction SilentlyContinue }
    } catch { }
}
function Make-SupportZip {
    # one zip with the logs and basic PC details; never uploaded anywhere
    try {
        Save-Log
        $dest = Join-Path $(if ($env:USERPROFILE) { $env:USERPROFILE } else { [IO.Path]::GetTempPath() }) ('RFNoise_support_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.zip')
        $st = Join-Path ([IO.Path]::GetTempPath()) ('rfnoise_sup_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
        New-Item -ItemType Directory -Force -Path $st | Out-Null
        $info = @("RF Noise Map support information", ("Made: " + (Get-Date)), ("Windows: " + [Environment]::OSVersion.VersionString), ("64-bit Windows: " + [Environment]::Is64BitOperatingSystem),
                  ("PowerShell: " + $PSVersionTable.PSVersion), ("Python command: " + $script:PyCmd), ("Install folder: " + $script:Dir2))
        [IO.File]::WriteAllLines((Join-Path $st 'system_info.txt'), $info)
        if (Test-Path -LiteralPath $script:LogFile) { Copy-Item -LiteralPath $script:LogFile -Destination $st -Force }
        if ($script:Dir2 -and (Test-Path -LiteralPath (Join-Path $script:Dir2 'Logs'))) { Copy-Item -LiteralPath (Join-Path $script:Dir2 'Logs') -Destination (Join-Path $st 'Logs') -Recurse -Force }
        if ($script:Dir2 -and (Test-Path -LiteralPath (Join-Path $script:Dir2 'full_test_report.txt'))) { Copy-Item -LiteralPath (Join-Path $script:Dir2 'full_test_report.txt') -Destination $st -Force }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::CreateFromDirectory($st, $dest)
        Remove-Item -LiteralPath $st -Recurse -Force -ErrorAction SilentlyContinue
        Say "Support file saved:  $dest" 'Green'
        Say 'Attach that zip to your message to Claude. Nothing was sent anywhere.' 'Green'
        if ($script:IsWin -and -not $script:Test) { try { Start-Process explorer.exe -ArgumentList ('/select,"' + $dest + '"') } catch { } }
    } catch { Say "Could not make the support file: $($_.Exception.Message)" 'Yellow'; Say "The log itself is here: $($script:LogFile)" 'Yellow' }
}
function Offer-Support {
    if ($script:Silent) { Say "The log is saved here: $($script:LogFile)" 'Yellow'; return }
    if (AskYN 'Make a support file (one zip with the log) to send to Claude?' $true) { Make-SupportZip }
}
function Run-Preflight {
    Head 'Quick check of this computer (changes nothing)'
    $ver = [Environment]::OSVersion.Version
    Say ("Windows version: $($ver.Major).$($ver.Minor) build $($ver.Build);  64-bit: $([Environment]::Is64BitOperatingSystem);  PowerShell $($PSVersionTable.PSVersion)")
    if ($script:IsWin -and $ver.Major -lt 10) { Say 'Windows 10 or 11 is recommended. This older Windows may not work.' 'Yellow'; Note-Warn 'Old Windows version.' }
    if ($script:IsWin -and -not [Environment]::Is64BitOperatingSystem) { Say '32-bit Windows is not supported by the radio driver.' 'Yellow'; Note-Warn '32-bit Windows.' }
    try {
        $root = if ($env:SystemDrive) { $env:SystemDrive } else { 'C:' }
        $drv = Get-PSDrive -Name $root.TrimEnd(':') -ErrorAction Stop
        $mb = [math]::Round($drv.Free / 1MB)
        Say "Free space on ${root}: $mb MB"
        if ($mb -lt 300) { Say 'Less than 300 MB is free. Free up some space, then run this installer again.' 'Red'; Explain-Problem 'not enough space' $true | Out-Null; Pause-Key; Save-Log; exit 3 }
    } catch { }
    if ($script:IsWin -and -not $script:Test) {
        try { Invoke-WebRequest -Uri 'https://pypi.org' -UseBasicParsing -Method Head -TimeoutSec 6 | Out-Null; Say 'Internet: reachable.' 'Green' }
        catch { Say 'Internet: pypi.org could not be reached. Installing numpy and pyserial needs it (if they are already installed, this does not matter).' 'Yellow'; Note-Warn 'No internet during install.' }
    }
    if ($env:RFNOISE_INSTALLER -match '(?i)\.zip\\') { Say 'Tip: you started this from inside a zip file. Extract it (or copy it to Downloads) first if anything fails.' 'Yellow' }
}
function Write-UninstallEntry($dir, $ver, $launcher) {
    # shows RF Noise Map in Windows "Apps & features" so it can be removed from Settings
    if (-not $script:IsWin) { return }
    try {
        $k = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\RFNoiseMap'
        New-Item -Path $k -Force | Out-Null
        $un = Join-Path $dir 'Uninstall_RFNoise.bat'
        $vals = @{ DisplayName = 'RF Noise Map'; DisplayVersion = $ver; Publisher = 'KW4EX'; InstallLocation = $dir
                   UninstallString = ('"' + $un + '"'); DisplayIcon = (Join-Path $dir 'app\icon.ico'); URLInfoAbout = 'https://github.com/kw4ex/RFNoise-Mapping' }
        foreach ($n in $vals.Keys) { Set-ItemProperty -Path $k -Name $n -Value $vals[$n] }
        Set-ItemProperty -Path $k -Name NoModify -Value 1 -Type DWord
        Set-ItemProperty -Path $k -Name NoRepair -Value 1 -Type DWord
        $sz = [int]((Get-ChildItem -LiteralPath (Join-Path $dir 'app') -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1KB)
        Set-ItemProperty -Path $k -Name EstimatedSize -Value $sz -Type DWord
        Say 'Added to Windows "Apps & features" (so Windows Settings can uninstall it too).' 'Green'
    } catch { Say "Could not add the Windows program-list entry (not important): $($_.Exception.Message)" 'Yellow' }
}
function Get-ExistingInstall {
    if (-not $script:IsWin) { return $env:RFNOISE_TEST_EXISTING }
    $rk = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\RFNoiseMap'
    if (-not (Test-Path -LiteralPath $rk)) { return $null }
    try { $v = (Get-ItemProperty -Path $rk -ErrorAction Stop).InstallLocation; if ($v -and (Test-Path -LiteralPath (Join-Path $v 'app'))) { return $v } } catch { }
    return $null
}

# =========================================================================
$script:Stamp0 = Get-Date -Format 'yyyyMMdd_HHmmss'
$script:Dir2 = ''
$logBase = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { [IO.Path]::GetTempPath() }
$logFolder = Join-Path $logBase 'RFNoiseMap\Logs'
try { New-Item -ItemType Directory -Force -Path $logFolder | Out-Null } catch { $logFolder = [IO.Path]::GetTempPath() }
$script:LogFile = Join-Path $logFolder ('install_log_' + $script:Stamp0 + '.txt')
$log = $script:LogFile
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

Run-Preflight

# ---- an install is already on this PC: offer upgrade / check / uninstall ----------------------
$existing = Get-ExistingInstall
if ($script:OptUninst -and -not $existing) { Say 'No RF Noise Map install was found to remove.' 'Yellow'; Save-Log; exit 0 }
if ($existing -and -not $script:Test) {
    Head 'RF Noise Map is already installed'
    Say "Found in: $existing"
    Say '  1  Upgrade or repair it (keeps all your data)   (default)'
    Say '  2  Check it and make a support file (changes nothing)'
    Say '  3  Uninstall it'
    Say '  0  Quit'
    $pick = if ($script:OptUninst) { '3' } else { AskText 'Type 1, 2, 3 or 0' '1' }
    if ($pick -eq '0') { Say 'Nothing was changed.'; Save-Log; exit 0 }
    if ($pick -eq '3') {
        $un = Join-Path $existing 'Uninstall_RFNoise.bat'
        if (Test-Path -LiteralPath $un) {
            Save-Log
            if ($script:Silent) { & cmd.exe /c ('"' + $un + '" /silent /mode=1') } else { & cmd.exe /c ('"' + $un + '"') }
        } else { Say 'The uninstaller is missing. Run this installer again and choose 1 (repair), then uninstall.' 'Yellow' }
        exit 0
    }
    if ($pick -eq '2') {
        $script:Dir2 = $existing
        $ft = Join-Path $existing 'app\full_test.py'
        $sb = Join-Path $existing 'Start_RFNoise.bat'
        if ((Test-Path -LiteralPath $ft) -and (Test-Path -LiteralPath $sb)) {
            $m = [regex]::Match([IO.File]::ReadAllText($sb), '(?m)^set "PYCMD=(.*)"')
            if ($m.Success) {
                $script:PyCmd = $m.Groups[1].Value
                Say 'Running the full test (radio, GPS, pretend drive). Nothing is changed...'
                $o = Invoke-Py @($ft, '--report', (Join-Path $existing 'full_test_report.txt'))
                foreach ($l in ($o -split "`r?`n" | Where-Object { $_.Trim() })) { Say ('  ' + $l) }
                Explain-Problem $o $true | Out-Null
            }
        }
        Make-SupportZip
        exit 0
    }
    $script:ExistingDir = $existing
}

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
        Explain-Problem 'Python was not found' $true | Out-Null
        Offer-Support
        Pause-Key
        Save-Log
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
    Explain-Problem $script:Raw | Out-Null
    Offer-Support
    Pause-Key
    Save-Log
    exit 2
}

# ---- 2. Where to install ------------------------------------------------------
Head 'Step 2 of 7: Install folder'
$SUB = 'RFNoise'
$def = 'C:\RadioScripts'
if ($env:RFNOISE_TEST_DIR) { $def = $env:RFNOISE_TEST_DIR }
if ($script:ExistingDir) { $def = Split-Path $script:ExistingDir -Parent }
if ($script:OptDir) { $def = $script:OptDir }
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
$script:Dir2 = $dir
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
Say 'Checking whether RF Noise Map is running right now (a few seconds)...'
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
foreach ($f in @('Open_Panel.bat', 'Uninstall_RFNoise.ps1', 'README_RFNoise.txt', 'RFNoise_Help.html', 'RFNoise_User_Guide.pdf')) {
    Copy-Item -LiteralPath (Join-Path $pk $f) -Destination (Join-Path $dir $f) -Force
}
# the start, stop, uninstall, test and GPS-finder files carry the Python command found in step 1
foreach ($nm in @('Start_RFNoise', 'Stop_RFNoise', 'Uninstall_RFNoise', 'Test_Everything', 'Find_GPS', 'Make_Support_File', 'Open_Logs')) {
    $bt = [IO.File]::ReadAllText((Join-Path $pk ($nm + '.template.bat'))).Replace('@@PYCMD@@', $script:PyCmd)
    [IO.File]::WriteAllText((Join-Path $dir ($nm + '.bat')), $bt)
}
# the marker file tells the program to keep your data in this folder
[IO.File]::WriteAllText((Join-Path $dir 'rfnoise_install.flag'), "RF Noise Map install marker. Do not delete: it makes the program keep your data in this folder.`r`n")
foreach ($d in @('Drives', 'Maps', 'Exports', 'Backups', 'Settings', 'Recordings', 'Logs')) { New-Item -ItemType Directory -Force -Path (Join-Path $dir $d) | Out-Null }
if (-not (Test-Path -LiteralPath (Join-Path $appDir 'rfmap_app.py'))) { throw "Could not copy the program files into $dir." }
Say "Program files copied to $dir" 'Green'
Say 'Data folders ready: Drives, Maps, Exports, Backups, Settings, Recordings, Logs' 'Green'

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
    # Start menu: a folder with Start, Open logs and Uninstall
    try {
        $smf = Join-Path ([Environment]::GetFolderPath('Programs')) 'RF Noise Map'
        if ((Test-Path -LiteralPath $smf) -or (AskYN 'Add RF Noise Map to the Windows Start menu?' $true)) {
            New-Item -ItemType Directory -Force -Path $smf | Out-Null
            New-Shortcut (Join-Path $smf 'RF Noise Map.lnk') $launcher $dir 'Start RF Noise Map' $icon
            New-Shortcut (Join-Path $smf 'RF Noise Map - problem logs.lnk') (Join-Path $dir 'Open_Logs.bat') $dir 'Open the log folder' $icon
            New-Shortcut (Join-Path $smf 'Uninstall RF Noise Map.lnk') (Join-Path $dir 'Uninstall_RFNoise.bat') $dir 'Remove RF Noise Map' $icon
            Say 'Start menu entries added (RF Noise Map, problem logs, Uninstall).' 'Green'
        }
    } catch { Say "Could not add the Start menu entries (not important): $($_.Exception.Message)" 'Yellow' }
    Write-UninstallEntry $dir $newVer $launcher
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
        Say 'The self-test did not pass. The details are saved in the Logs folder of the install folder.' 'Yellow'
        Note-Warn 'The self-test did not pass.'
        $bad = @(($o1 + $o2) -split "`r?`n" | Where-Object { $_ -match 'Traceback|Error' } | Select-Object -First 6)
        foreach ($l in $bad) { Say ('  ' + $l.Trim()) }
        $null = Explain-Problem ($o1 + "`n" + $o2)
        Offer-Support
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
Say 'Your data:     the folders Drives, Maps, Exports, Backups, Settings and Recordings in the install folder.'
Say 'Stop it:       press Quit in the panel, or double-click Stop_RFNoise.bat.'
Say 'Test it:       Test_Everything.bat checks the radio, GPS and a pretend drive. Find_GPS.bat finds your GPS puck.'
Say 'Help file:     RFNoise_Help.html (also the Help button in the panel). A printable PDF guide is there too.'
Say 'To remove:     Windows Settings > Apps, or Uninstall_RFNoise.bat (you choose what happens to your data).'
if ($script:Warns.Count) {
    Say ''
    Say 'Things to look at (the install itself finished):' 'Yellow'
    foreach ($w in $script:Warns) { Say ('  - ' + $w) 'Yellow' }
}
Say ''
Say 'If anything goes wrong later:' 
Say '  - The install log is kept in the Logs folder of the install folder (the newest 10 are kept).'
Say '  - Program problems are written to Logs\program_errors.log. Open_Logs.bat opens that folder.'
Say '  - Make_Support_File.bat packs the logs into one zip to send to Claude.'
Save-Log
if ($script:IsWin -and -not $script:Test -and -not $script:Silent) {
    Say ''
    $goApp = AskYN 'Start RF Noise Map now?' $true
    $goHelp = AskYN 'Open the help file now?' $false
    if ($goApp) { Start-Process -FilePath $launcher -WorkingDirectory $dir; Start-Sleep -Seconds 1 }
    if ($goHelp) { Start-Process (Join-Path $dir 'RFNoise_Help.html') }
}

} catch {
    Say ''
    Say ('PROBLEM: ' + $_.Exception.Message) 'Red'
    Say 'Nothing was damaged.' 'Yellow'
    $null = Explain-Problem ($_.Exception.Message + "`n" + $script:Raw)
    Say ''
    Say ('The log of this install is saved here: ' + $script:LogFile) 'Gray'
    Offer-Support
    Save-Log
    Pause-Key
    exit 1
} finally {
    if ($tmp) { try { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue } catch { } }
}
