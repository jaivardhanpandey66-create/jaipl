<#
.SYNOPSIS
    Installs zing on Windows. No administrator rights needed.

.DESCRIPTION
    Downloads the Python runtime and the zing source into your user profile,
    creates a `zing` command, and adds it to your PATH.

    Nothing is installed system-wide, and nothing outside your user profile is
    touched, so it can be removed by deleting one folder.

.EXAMPLE
    Paste this into PowerShell:

    iwr https://raw.githubusercontent.com/jaivardhanpandey66-create/zing/main/install.ps1 -useb | iex

.EXAMPLE
    From a checkout:

    powershell -ExecutionPolicy Bypass -File .\install.ps1
#>

$ErrorActionPreference = 'Stop'

# Keep the same Python release as everywhere else: zing needs 3.11 or newer
# and nothing newer than that.
$PythonVersion = '3.11.9'
$PythonZip    = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$SourceZip    = 'https://github.com/jaivardhanpandey66-create/zing/archive/refs/heads/main.zip'

$Root = Join-Path $env:LOCALAPPDATA 'zing'
$Bin  = Join-Path $env:LOCALAPPDATA 'Programs\zing'

function Write-Step($message) {
    Write-Host "==> $message" -ForegroundColor Cyan
}

function Fail($message) {
    Write-Host "zing installer: $message" -ForegroundColor Red
    Write-Host "See https://github.com/jaivardhanpandey66-create/zing for help." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------- checks

if ($PSVersionTable.PSVersion.Major -lt 5) {
    Fail 'PowerShell 5 or newer is required.'
}

# Expand-Archive arrived in PowerShell 5; on older builds we shell out.
function Expand-Zip($archive, $destination) {
    if (Get-Command Expand-Archive -ErrorAction SilentlyContinue) {
        Expand-Archive -Path $archive -DestinationPath $destination -Force
        return
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($archive, $destination)
}

Write-Step "installing into $Root"

# ---------------------------------------------------------- python runtime

$pythonDir = Join-Path $Root 'python'
$pythonExe = Join-Path $pythonDir 'python.exe'

# An existing Python 3.11+ on PATH is preferred: it is already trusted and
# keeps the install small.
$systemPython = $null
foreach ($candidate in @('python', 'python3', 'py')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    try {
        $version = & $cmd.Source -c "import sys;print(sys.version_info[:2])" 2>$null
    } catch { continue }
    if ($version -match '\((\d+), (\d+)\)') {
        $major = [int]$Matches[1]; $minor = [int]$Matches[2]
        if ($major -eq 3 -and $minor -ge 11) {
            $systemPython = $cmd.Source
            break
        }
    }
}

if ($systemPython) {
    Write-Step "using the Python already on your PATH ($systemPython)"
    $pythonExe = $systemPython
} else {
    Write-Step "downloading Python $PythonVersion"
    $zipPath = Join-Path $env:TEMP "python-$PythonVersion.zip"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $PythonZip -OutFile $zipPath -UseBasicParsing
    } catch {
        Fail "could not download Python: $($_.Exception.Message)"
    }

    if (Test-Path $pythonDir) { Remove-Item $pythonDir -Recurse -Force }
    New-Item -ItemType Directory -Path $pythonDir -Force | Out-Null
    try {
        Expand-Zip $zipPath $pythonDir
    } catch {
        Fail "could not unpack Python: $($_.Exception.Message)"
    }
    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue

    if (-not (Test-Path $pythonExe)) {
        Fail "python.exe was not found in $pythonDir after unpacking."
    }

    # The embeddable build ignores everything outside its ._pth file, so the
    # zing source has to be named there or `import arcide` cannot work.
    $pth = Get-ChildItem -Path $pythonDir -Filter 'python*._pth' | Select-Object -First 1
    if ($pth) {
        $lines = @(
            'python311.zip'
            '.'
            "import site"
            $Root
        )
        Set-Content -Path $pth.FullName -Value $lines -Encoding ASCII
        Write-Step 'configured the Python path for zing'
    }
}

# ------------------------------------------------------------ zing source

$srcZip = Join-Path $env:TEMP 'zing-source.zip'
Write-Step 'downloading zing'
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $SourceZip -OutFile $srcZip -UseBasicParsing
} catch {
    Fail "could not download zing: $($_.Exception.Message)"
}

$staging = Join-Path $env:TEMP 'zing-staging'
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
try {
    Expand-Zip $srcZip $staging
} catch {
    Fail "could not unpack zing: $($_.Exception.Message)"
}
Remove-Item $srcZip -Force -ErrorAction SilentlyContinue

# GitHub archives unpack into zing-main/; copy the contents, not the wrapper.
$inner = Get-ChildItem -Path $staging -Directory | Select-Object -First 1
if (-not $inner) { Fail 'the downloaded archive looked empty.' }

# Keep the runtime, replace everything else so an upgrade is clean.
New-Item -ItemType Directory -Path $Root -Force | Out-Null
Get-ChildItem -Path $inner.FullName -Force | ForEach-Object {
    $dest = Join-Path $Root $_.Name
    if ($_.PSIsContainer) {
        if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
        Copy-Item $_.FullName $dest -Recurse -Force
    } else {
        Copy-Item $_.FullName $dest -Force
    }
}
Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue

# ---------------------------------------------------------------- launcher

Write-Step 'creating the zing command'
New-Item -ItemType Directory -Path $Bin -Force | Out-Null
$cmdPath = Join-Path $Bin 'zing.cmd'

@"
@echo off
REM zing launcher for Windows. Keeps the window open on error so the
REM message is readable, which matters when a beginner runs a broken file.
setlocal
set "HERE=%~dp0"
set "HOME=%LOCALAPPDATA%\zing"
if exist "%HERE%..\..\zing\python\python.exe" (
    set "ZING_PY=%HERE%..\..\zing\python\python.exe"
) else (
    set "ZING_PY=$pythonExe"
)
set "PYTHONPATH=%HOME%"
"%ZING_PY%" -m arcide.zing.cli %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
    echo.
    echo zing exited with code %CODE%
    pause
)
exit /b %CODE%
"@ | Set-Content -Path $cmdPath -Encoding ASCII

# ------------------------------------------------------------------- PATH

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$parts = @()
if ($userPath) { $parts = $userPath -split ';' | Where-Object { $_ } }
if ($parts -notcontains $Bin) {
    [Environment]::SetEnvironmentVariable('Path', (($parts + $Bin) -join ';'), 'User')
    $env:Path = "$env:Path;$Bin"
    Write-Step 'added zing to your PATH (restart the terminal to pick it up)'
} else {
    Write-Step 'zing is already on your PATH'
}

# ------------------------------------------------ file icon + association

# .zng is the file type used by two languages, so we only register when the
# type is not claimed already. HKCU means no administrator rights.
$classesRoot = Join-Path $env:LOCALAPPDATA 'jaipl\Software\Classes'
$dot = 'HKCU:\Software\Classes\.zng'
$prog = 'HKCU:\Software\Classes\Zing.Program'
$icoSource = Join-Path $Root 'packaging\icons\zing.ico'
$icoPath = Join-Path (Join-Path $Root 'resources') 'zing.ico'

if (Test-Path $icoSource) {
    New-Item -ItemType Directory -Path (Split-Path $icoPath) -Force | Out-Null
    Copy-Item $icoSource $icoPath -Force
    Write-Step 'installed the zing icon'
}

if (-not (Test-Path $dot)) {
    try {
        New-Item $dot -Force | Out-Null
        New-Item $prog -Force | Out-Null
        New-Item (Join-Path $prog 'DefaultIcon') -Force | Out-Null
        New-Item (Join-Path $prog 'shell\open\command') -Force | Out-Null
        if (Test-Path $icoPath) {
            Set-ItemProperty (Join-Path $prog 'DefaultIcon') -Name '(default)' -Value "`"$icoPath`",0"
        }
        Set-ItemProperty (Join-Path $prog 'shell\open\command') -Name '(default)' -Value "`"$cmdPath`" `"%1`""
        Set-ItemProperty $dot -Name '(default)' -Value 'Zing.Program'
        Write-Step '.zng files now open with zing and carry the zing icon'
        # Ask the shell to re-read its icon and association tables.
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class Sh {
    [DllImport("shell32.dll")]
    public static extern void SHChangeNotify(int w, uint f, IntPtr a, IntPtr b);
}
'@
        [Sh]::SHChangeNotify(0x8000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
    } catch {
        Write-Host "  note: could not register the file icon: $($_.Exception.Message)" -ForegroundColor Yellow
    }
} else {
    Write-Step '.zng was already associated with something else; left it alone'
    Write-Host '  (you can run the zing icon install manually later if you want)' -ForegroundColor Gray
}

# ----------------------------------------------------------------- verify
Write-Step 'checking it works'
try {
    $version = & $cmdPath version 2>&1
} catch {
    Fail "the launcher could not run: $($_.Exception.Message)"
}
Write-Host ""
Write-Host "  $version" -ForegroundColor Green
Write-Host ""
Write-Host 'Try this:' -ForegroundColor Gray
Write-Host '  zing repl'
Write-Host '  zing run hello.zng'
Write-Host ''
Write-Host "Files are in $Root" -ForegroundColor Gray
Write-Host 'To uninstall, delete that folder and remove it from your PATH.' -ForegroundColor Gray