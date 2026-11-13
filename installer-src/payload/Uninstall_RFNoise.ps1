# RF Noise Map - uninstaller (Windows PowerShell 5.1 or newer)
# Started by Uninstall_RFNoise.bat. Plain text on purpose: open it in Notepad to see what it does.
# Options (used by the installer's silent mode):  -Mode 1|2|3   -Silent
param([string]$Dir = '', [string]$Mode = '', [switch]$Silent)
$ErrorActionPreference = 'Continue'
$script:IsWin = ($env:OS -eq 'Windows_NT')
$script:Test = [bool]$env:RFNOISE_TEST
if ($env:RFNOISE_UNINSTALL_SILENT) { $Silent = $true }
if (-not $Dir) { $Dir = (Get-Location).Path }
$Dir = $Dir.Trim('"').TrimEnd('\', '/')

function Say($t, $c = 'Gray') { Write-Host $t -ForegroundColor $c }
function Head($t) { Write-Host ''; Write-Host ('=== ' + $t + ' ===') -ForegroundColor Cyan }
function Ask($q, $d = '') {
    if ($Silent) { return $d }
    if ($d) { $r = Read-Host "$q [$d]" } else { $r = Read-Host $q }
    if ($null -eq $r -or $r.Trim() -eq '') { return $d }
    return $r.Trim()
}
function SizeText($p) {
    if (-not (Test-Path -LiteralPath $p)) { return '-' }
    $n = 0
    try { $n = (Get-ChildItem -LiteralPath $p -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum } catch { }
    if (-not $n) { $n = 0 }
    if ($n -ge 1MB) { return ('{0:N1} MB' -f ($n / 1MB)) }
    if ($n -ge 1KB) { return ('{0:N0} KB' -f ($n / 1KB)) }
    return "$n bytes"
}
function CountFiles($p) {
    if (-not (Test-Path -LiteralPath $p)) { return 0 }
    return @(Get-ChildItem -LiteralPath $p -Recurse -File -Force -ErrorAction SilentlyContinue).Count
}

# ---- the uninstall log lives OUTSIDE the install folder so it survives -------------
$logRoot = Join-Path $(if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { [IO.Path]::GetTempPath() }) 'RFNoiseMap\Logs'
New-Item -ItemType Directory -Force -Path $logRoot -ErrorAction SilentlyContinue | Out-Null
$log = Join-Path $logRoot ('uninstall_log_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.txt')
try { Start-Transcript -Path $log -Force | Out-Null } catch { }

try {
    Clear-Host
    Say '==========================================================' 'Cyan'
    Say '   Uninstall RF Noise Map' 'Cyan'
    Say '==========================================================' 'Cyan'
    if (-not (Test-Path -LiteralPath (Join-Path $Dir 'app')) -and -not (Test-Path -LiteralPath (Join-Path $Dir 'rfnoise_install.flag'))) {
        Say "This does not look like an RF Noise Map folder: $Dir" 'Yellow'
        Say 'Nothing was changed. Run Uninstall_RFNoise.bat from inside the RFNoise folder.'
        return
    }
    Say "Folder: $Dir"
    $progItems = @('app', 'app_previous')
    $dataItems = @('Drives', 'Maps', 'Exports', 'Backups', 'Settings', 'Recordings')
    $logsItem = 'Logs'

    Head 'What is installed'
    Say '  PROGRAM (removed by every option):'
    foreach ($i in $progItems) { if (Test-Path -LiteralPath (Join-Path $Dir $i)) { Say ('    {0,-14} {1}' -f $i, (SizeText (Join-Path $Dir $i))) } }
    Say '    start/stop/help files, shortcuts, and the entry in Windows "Apps & features"'
    Say '  YOUR DATA (kept unless you choose option 2 or 3):'
    $dataFound = @()
    foreach ($i in $dataItems) {
        $p = Join-Path $Dir $i
        if (Test-Path -LiteralPath $p) { $dataFound += $i; Say ('    {0,-14} {1} files, {2}' -f $i, (CountFiles $p), (SizeText $p)) }
    }
    if (-not $dataFound) { Say '    (none)' }
    if (Test-Path -LiteralPath (Join-Path $Dir $logsItem)) { Say ('  LOGS: {0}  ({1})' -f $logsItem, (SizeText (Join-Path $Dir $logsItem))) }

    Head 'What do you want to do?'
    Say '  1  Remove the program only. KEEP my drives, maps and recordings.   (recommended)'
    Say '  2  Remove the program AND my data. A backup zip is made first.'
    Say '  3  Remove EVERYTHING, no backup.'
    Say '  0  Cancel. Nothing is changed.'
    if (-not $Mode) { $Mode = Ask 'Type 1, 2, 3 or 0' '1' }
    if ($Mode -notin @('1', '2', '3')) { Say 'Cancelled. Nothing was changed.' 'Green'; return }
    if ($Mode -eq '3' -and -not $Silent) {
        Say 'This deletes every recorded drive, map and recording, and cannot be undone.' 'Yellow'
        if ((Ask 'Type DELETE (capital letters) to continue' '') -cne 'DELETE') { Say 'Cancelled. Nothing was changed.' 'Green'; return }
    } elseif ($Mode -eq '1' -and -not $Silent) {
        if ((Ask 'Remove the program now? (y/n)' 'y').ToLower() -notin @('y', 'yes')) { Say 'Cancelled. Nothing was changed.' 'Green'; return }
    }

    # ---- 1. close the program --------------------------------------------------------
    Head 'Step 1: closing the program'
    $py = ''
    $sb = Join-Path $Dir 'Start_RFNoise.bat'
    if (Test-Path -LiteralPath $sb) {
        $m = [regex]::Match([IO.File]::ReadAllText($sb), '(?m)^set "PYCMD=(.*)"')
        if ($m.Success) { $py = $m.Groups[1].Value }
    }
    if ($py -and $script:IsWin -and (Test-Path -LiteralPath (Join-Path $Dir 'app\rfmap_app.py'))) {
        try { & cmd.exe /c ('{0} "{1}" --stop >nul 2>&1' -f $py, (Join-Path $Dir 'app\rfmap_app.py')) } catch { }
        Start-Sleep -Seconds 2
    }
    if ($script:IsWin) {
        try {
            Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                Where-Object { $_.CommandLine -and ($_.CommandLine -like '*rfmap_app.py*' -or $_.CommandLine -like '*rf_logger.py*' -or $_.CommandLine -like '*panadapter.py*') -and $_.Name -match '^(python|pythonw|py|pyw)' } |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        } catch { }
    }
    Say 'Done.' 'Green'

    # ---- 2. backup (option 2) ------------------------------------------------------------
    $keepData = $true
    if ($Mode -eq '2') {
        Head 'Step 2: backup of your data'
        $keepData = $true
        if ($dataFound) {
            $bz = Join-Path $(if ($env:USERPROFILE) { $env:USERPROFILE } else { [IO.Path]::GetTempPath() }) ('RFNoiseMap_backup_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.zip')
            try {
                Add-Type -AssemblyName System.IO.Compression.FileSystem
                $tmpd = Join-Path ([IO.Path]::GetTempPath()) ('rfnoise_bk_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
                New-Item -ItemType Directory -Force -Path $tmpd | Out-Null
                foreach ($i in $dataFound) { Copy-Item -LiteralPath (Join-Path $Dir $i) -Destination (Join-Path $tmpd $i) -Recurse -Force }
                [IO.Compression.ZipFile]::CreateFromDirectory($tmpd, $bz)
                Remove-Item -LiteralPath $tmpd -Recurse -Force -ErrorAction SilentlyContinue
                if ((Test-Path -LiteralPath $bz) -and ((Get-Item -LiteralPath $bz).Length -gt 0)) {
                    Say "Backup saved:  $bz" 'Green'
                    $keepData = $false
                }
            } catch { Say "The backup failed: $($_.Exception.Message)" 'Yellow' }
            if ($keepData) { Say 'Because the backup failed, your data will be KEPT (nothing is deleted).' 'Yellow' }
        } else { $keepData = $false; Say 'No data to back up.' }
    } elseif ($Mode -eq '3') { $keepData = $false }

    # ---- 3. shortcuts, Start menu, Windows list ------------------------------------------
    Head 'Step 3: shortcuts and the Windows program list'
    if ($script:IsWin) {
        foreach ($f in @('Desktop', 'Startup')) {
            $p = [Environment]::GetFolderPath($f)
            if ($p) { Get-ChildItem -LiteralPath $p -Filter 'RF Noise Map*.lnk' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue }
        }
        $pr = [Environment]::GetFolderPath('Programs')
        if ($pr) {
            $sm = Join-Path $pr 'RF Noise Map'
            if (Test-Path -LiteralPath $sm) { Remove-Item -LiteralPath $sm -Recurse -Force -ErrorAction SilentlyContinue }
            Get-ChildItem -LiteralPath $pr -Filter 'RF Noise Map*.lnk' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
        }
        try { Remove-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\RFNoiseMap' -Recurse -Force -ErrorAction SilentlyContinue } catch { }
        Say 'Removed: Desktop, Start menu and sign-in shortcuts, and the "Apps & features" entry.' 'Green'
    } else { Say '(not Windows: skipped)' }

    # ---- 4. files --------------------------------------------------------------------------------
    Head 'Step 4: removing files'
    $failed = @()
    function Remove-Safe($p) {
        if (-not (Test-Path -LiteralPath $p)) { return }
        try { Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop }
        catch { $script:failed += $p; Say ("  could not remove: $p  ($($_.Exception.Message))") 'Yellow' }
    }
    foreach ($i in $progItems) { Remove-Safe (Join-Path $Dir $i) }
    foreach ($f in @('Start_RFNoise.bat', 'Stop_RFNoise.bat', 'Open_Panel.bat', 'Test_Everything.bat', 'Find_GPS.bat', 'Make_Support_File.bat',
                     'Open_Logs.bat', 'README_RFNoise.txt', 'RFNoise_Help.html', 'RFNoise_User_Guide.pdf', 'install_log.txt',
                     'full_test_report.txt', 'rfnoise_install.flag')) { Remove-Safe (Join-Path $Dir $f) }
    foreach ($f in @(Get-ChildItem -LiteralPath $Dir -Filter 'Start_RFNoise.bat.*.bak' -ErrorAction SilentlyContinue)) { Remove-Safe $f.FullName }
    if (-not $keepData) {
        foreach ($i in ($dataItems + @($logsItem))) { Remove-Safe (Join-Path $Dir $i) }
        Say 'Your data was deleted.' 'Green'
    } else {
        Say "Your data was KEPT in: $Dir" 'Green'
    }
    # the uninstaller's own files stay until this window closes; the .bat removes them and the empty folder
    Say 'Program files removed.' 'Green'

    Head 'What was NOT removed (on purpose)'
    Say '  - Python, numpy and pyserial (other programs may use them)'
    Say '  - the SDRplay driver and PothosSDR (remove them in Windows "Apps & features" if you want)'
    Say "  - the uninstall record:  $log"
    if ($failed.Count) {
        Say ''
        Say 'Some files could not be removed (a program may still be using them, or an antivirus / OneDrive is busy).' 'Yellow'
        Say 'Close RF Noise Map and any browser tab or folder window showing these files, then run the uninstaller again.' 'Yellow'
    }
    Say ''
    Say 'Finished.' 'Green'
} catch {
    Say ''
    Say ('PROBLEM: ' + $_.Exception.Message) 'Red'
    Say "Nothing else was changed. The details are saved in: $log" 'Yellow'
} finally {
    try { Stop-Transcript | Out-Null } catch { }
}
