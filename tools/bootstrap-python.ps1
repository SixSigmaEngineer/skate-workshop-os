<#
.SYNOPSIS
    Resolve a Python interpreter for SKATE and create the private .venv.

.DESCRIPTION
    SKATE should not care which Python a laptop happens to have. A hardcoded
    allowlist of interpreter versions goes stale every October when CPython
    ships a new minor release, and the user sees an error that reads like
    SKATE is broken. This script removes that failure mode.

    Resolution order:

      1. A Python already on the machine inside the tested range. Nothing is
         downloaded and behaviour is identical to previous SKATE releases.
      2. uv (https://github.com/astral-sh/uv) - already installed, bundled in
         tools\, or fetched on demand - used to install a known-good CPython
         and build the venv from it. No admin rights, nothing on PATH, nothing
         registered with Windows.
      3. Any Python newer than the tested range, used best-effort with a
         warning. Better to try and let pip report a real problem than to
         refuse to start on a version that probably works.

    Exit codes: 0 = venv ready. 1 = no usable interpreter.

.PARAMETER MaxTested
    Highest CPython minor version SKATE has actually been verified against.
    Raise this after testing a new release; it is the only value that needs
    to change to bless a newer Python.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $VenvPath,
    [string] $MinVersion    = '3.10',
    [string] $MaxTested     = '3.13',
    [string] $PreferVersion = '3.13',
    [string] $ToolsDir,
    [switch] $NoDownload
)

$ErrorActionPreference = 'Stop'

if (-not $ToolsDir) {
    $ToolsDir = Join-Path (Split-Path -Parent $PSScriptRoot) 'tools'
}

function Write-Step  ([string] $m) { Write-Host "  $m" }
function Write-Warn  ([string] $m) { Write-Host "  WARNING: $m" -ForegroundColor Yellow }

function ConvertTo-MinorVersion ([string] $text) {
    if ($text -match '^\s*(\d+)\.(\d+)') { return [version]"$($Matches[1]).$($Matches[2])" }
    return $null
}

$minV    = ConvertTo-MinorVersion $MinVersion
$testedV = ConvertTo-MinorVersion $MaxTested

# ---------------------------------------------------------------- discovery
function Get-InterpreterVersion ([string] $exe, [string[]] $prefixArgs) {
    try {
        $argList = @()
        if ($prefixArgs) { $argList += $prefixArgs }
        $argList += @('-c', 'import sys; print("%d.%d" % sys.version_info[:2])')
        $out = & $exe @argList 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        return ConvertTo-MinorVersion ($out | Select-Object -First 1)
    } catch { return $null }
}

function Get-PythonCandidates {
    $found = New-Object System.Collections.Generic.List[object]

    # The py launcher knows about every registered install, including ones
    # that were deliberately kept off PATH.
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $listing = & py -0p 2>$null
            foreach ($line in $listing) {
                if ($line -match '-V:(\d+\.\d+)') {
                    $tag = $Matches[1]
                    $v = Get-InterpreterVersion $py.Source @("-$tag")
                    if ($v) { $found.Add([pscustomobject]@{ Exe = $py.Source; Args = @("-$tag"); Version = $v }) }
                }
            }
        } catch { }
        # -0p is not available on very old launchers; probe explicitly as well.
        foreach ($tag in @('3.13', '3.12', '3.11', '3.10', '3.14', '3.15')) {
            if ($found | Where-Object { $_.Version -eq (ConvertTo-MinorVersion $tag) }) { continue }
            $v = Get-InterpreterVersion $py.Source @("-$tag")
            if ($v) { $found.Add([pscustomobject]@{ Exe = $py.Source; Args = @("-$tag"); Version = $v }) }
        }
    }

    foreach ($name in @('python', 'python3')) {
        foreach ($cmd in (Get-Command $name -All -ErrorAction SilentlyContinue)) {
            # Skip the Microsoft Store stub, which exits without running.
            if ($cmd.Source -like '*WindowsApps*') { continue }
            $v = Get-InterpreterVersion $cmd.Source @()
            if ($v) { $found.Add([pscustomobject]@{ Exe = $cmd.Source; Args = @(); Version = $v }) }
        }
    }

    return $found | Sort-Object -Property Version -Descending -Unique
}

# ---------------------------------------------------------------------- uv
function Get-UvPath {
    foreach ($candidate in @(
        (Join-Path $ToolsDir 'uv.exe'),
        (Join-Path $env:LOCALAPPDATA 'skate\uv.exe')
    )) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Install-Uv {
    if ($NoDownload) { return $null }

    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'aarch64' } else { 'x86_64' }
    $url  = "https://github.com/astral-sh/uv/releases/latest/download/uv-$arch-pc-windows-msvc.zip"
    $dest = Join-Path $env:LOCALAPPDATA 'skate'

    Write-Step "No suitable Python found. Fetching uv to install one (about 35 MB, no admin rights needed)..."
    Write-Step "  from $url"
    try {
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        $zip = Join-Path $dest 'uv.zip'
        $progress = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip -TimeoutSec 180
        } finally {
            $ProgressPreference = $progress
        }
        Expand-Archive -LiteralPath $zip -DestinationPath $dest -Force
        Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue

        $exe = Get-ChildItem -LiteralPath $dest -Filter 'uv.exe' -Recurse -ErrorAction SilentlyContinue |
               Select-Object -First 1
        if ($exe) {
            if ($exe.FullName -ne (Join-Path $dest 'uv.exe')) {
                Move-Item -LiteralPath $exe.FullName -Destination (Join-Path $dest 'uv.exe') -Force
            }
            return (Join-Path $dest 'uv.exe')
        }
    } catch {
        Write-Warn "could not download uv: $($_.Exception.Message)"
    }
    return $null
}

function New-VenvFromUv ([string] $uv) {
    Write-Step "Using uv to install a private CPython $PreferVersion..."
    & $uv python install $PreferVersion
    if ($LASTEXITCODE -ne 0) { Write-Warn "uv could not install Python $PreferVersion."; return $false }

    # --seed puts pip inside the venv so the rest of the launcher is unchanged.
    & $uv venv --seed --python $PreferVersion $VenvPath
    if ($LASTEXITCODE -ne 0) { Write-Warn 'uv could not create the environment.'; return $false }
    return $true
}

function New-VenvFromInterpreter ($candidate) {
    $argList = @()
    if ($candidate.Args) { $argList += $candidate.Args }
    $argList += @('-m', 'venv', $VenvPath)
    & $candidate.Exe @argList
    return ($LASTEXITCODE -eq 0)
}

# -------------------------------------------------------------------- main
$venvPython = Join-Path $VenvPath 'Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) { exit 0 }

Write-Step "Creating SKATE's private Python environment..."

$candidates = @(Get-PythonCandidates)
$tested = $candidates | Where-Object { $_.Version -ge $minV -and $_.Version -le $testedV } |
          Sort-Object -Property Version -Descending
$newer  = $candidates | Where-Object { $_.Version -gt $testedV } |
          Sort-Object -Property Version

# 1. A Python we have actually tested against.
foreach ($c in $tested) {
    Write-Step "Found Python $($c.Version) - using it."
    if (New-VenvFromInterpreter $c) { exit 0 }
    Write-Warn "Python $($c.Version) could not create the environment; trying the next option."
}

# 2. Provision a known-good interpreter with uv.
if ($candidates.Count -gt 0) {
    $have = ($candidates | ForEach-Object { $_.Version.ToString() }) -join ', '
    Write-Step "Python $have found, but SKATE is verified on $MinVersion-$MaxTested."
}
$uv = Get-UvPath
if (-not $uv) { $uv = Install-Uv }
if ($uv) {
    if (New-VenvFromUv $uv) {
        Write-Step "Private CPython $PreferVersion installed. SKATE will use it instead of the system Python."
        exit 0
    }
}

# 3. Best effort on a newer interpreter rather than refusing to start.
foreach ($c in $newer) {
    Write-Warn "Trying Python $($c.Version), which is newer than SKATE's tested range ($MinVersion-$MaxTested)."
    Write-Warn 'If a dependency has no wheel for it yet, the install step below will say so.'
    if (New-VenvFromInterpreter $c) { exit 0 }
}

Write-Host ''
Write-Host 'ERROR: SKATE could not find or install a usable Python.' -ForegroundColor Red
if ($candidates.Count -gt 0) {
    Write-Host ("  Detected: Python " + (($candidates | ForEach-Object { $_.Version.ToString() }) -join ', '))
}
Write-Host "  SKATE is verified on Python $MinVersion through $MaxTested."
Write-Host '  Either install one from https://www.python.org/downloads/ (tick "Add Python to PATH"),'
Write-Host '  or allow this launcher to reach github.com so it can fetch a private copy automatically.'
exit 1
