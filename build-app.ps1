# ============================================================================
#  build-app.ps1 — build the distributable standalone SKATE app.
#
#  Produces:
#    build\app-staging\SKATE\   the standalone app (onedir, no Python
#                                needed on target PCs) + vault-seed
#
#  Unlike build-portable.ps1 (personal use), this NEVER includes your real
#  notes or settings.json — new users get the demo vault as their seed.
#
#  Prereqs:  run Start SKATE.bat once (creates .venv)
# ============================================================================

$ErrorActionPreference = "Stop"

$Root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python  = Join-Path $Root ".venv\Scripts\python.exe"
$Icon    = Join-Path $Root "ui\static\favicon.ico"
$Staging = Join-Path $Root "build\app-staging"
$Work    = Join-Path $Root "build\app-work"
$Launcher = Join-Path $Root "portable_launcher.py"
$McpLauncher = Join-Path $Root "mcp_server\packaged_launcher.py"
$DemoVault = Join-Path $Root "demo-vault"

if (-not (Test-Path $Python)) {
    throw "SKATE's venv not found. Run Start SKATE.bat once first."
}
if (-not (Test-Path $Launcher)) {
    throw "Packaging is not ready: portable_launcher.py must be finalized first."
}
if (-not (Test-Path (Join-Path $DemoVault "conversations"))) {
    throw "Packaging is not ready: add the approved fictitious demo-vault first."
}

$env:PYTHONNOUSERSITE = "1"

& $Python -m pip install --no-cache-dir pyinstaller

Write-Host "`n[1/3] Building standalone app (PyInstaller onedir)..." -ForegroundColor Cyan
& $Python -m PyInstaller `
    --name "SKATE" `
    --onedir `
    --windowed `
    --noconfirm `
    --clean `
    --icon $Icon `
    --distpath $Staging `
    --workpath $Work `
    --specpath $Work `
    --paths (Join-Path $Root "ui") `
    --collect-submodules uvicorn `
    --collect-submodules webview `
    --collect-submodules pystray `
    --collect-all imageio_ffmpeg `
    --hidden-import PIL.Image `
    --hidden-import frontmatter `
    --hidden-import markdown.extensions.extra `
    --hidden-import embeddings `
    --hidden-import skate_lib `
    --add-data "$Root\ui\templates;ui\templates" `
    --add-data "$Root\ui\static;ui\static" `
    $Launcher
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed while building SKATE.exe."
}

$AppDir = Join-Path $Staging "SKATE"
if (-not (Test-Path (Join-Path $AppDir "SKATE.exe"))) {
    throw "Build finished, but SKATE.exe was not found."
}

Write-Host "`n[2/3] Building standalone MCP companion..." -ForegroundColor Cyan
$VenvCfg  = Join-Path $Root ".venv\pyvenv.cfg"
$BaseHome = (Get-Content $VenvCfg | Where-Object { $_ -match "^home\s*=" }) -replace "^home\s*=\s*", ""
$DllDirs  = @((Join-Path $BaseHome "Library\bin"), $BaseHome, (Join-Path $BaseHome "DLLs"))
$Needed   = @("libssl*.dll", "libcrypto*.dll", "libffi*.dll", "liblzma*.dll", "libbz2*.dll", "libexpat*.dll", "ffi*.dll")
$RuntimeDlls = @()
foreach ($dir in $DllDirs) {
    if (-not (Test-Path $dir)) { continue }
    foreach ($pattern in $Needed) {
        $RuntimeDlls += Get-ChildItem -Path $dir -Filter $pattern -File -ErrorAction SilentlyContinue
    }
}
$RuntimeDlls = $RuntimeDlls | Sort-Object FullName -Unique

$McpArgs = @(
    "--name", "SKATE-MCP",
    "--onefile", "--console", "--noconfirm", "--clean",
    "--icon", $Icon,
    "--distpath", $AppDir,
    "--workpath", (Join-Path $Work "mcp"),
    "--specpath", (Join-Path $Work "mcp"),
    "--paths", $Root,
    "--paths", (Join-Path $Root "ui"),
    "--collect-submodules", "mcp.server",
    "--collect-submodules", "mcp.shared",
    "--hidden-import", "frontmatter",
    "--hidden-import", "embeddings",
    "--hidden-import", "skate_lib",
    "--hidden-import", "mcp_server.service"
)
foreach ($dll in $RuntimeDlls) {
    $McpArgs += @("--add-binary", "$($dll.FullName);.")
}
$McpArgs += $McpLauncher
& $Python -m PyInstaller @McpArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed while building SKATE-MCP.exe."
}

if (-not (Test-Path (Join-Path $AppDir "SKATE-MCP.exe"))) {
    throw "Build finished, but SKATE-MCP.exe was not found."
}

# --- Conda OpenSSL fix: conda Pythons keep libssl/libcrypto in Library\bin,
#     which PyInstaller misses, breaking `import _ssl` on machines without conda.
$Internal = Join-Path $AppDir "_internal"
$CopiedSsl = $false
foreach ($dir in $DllDirs) {
    if (-not (Test-Path $dir)) { continue }
    foreach ($pattern in $Needed) {
        Get-ChildItem -Path $dir -Filter $pattern -ErrorAction SilentlyContinue | ForEach-Object {
            Copy-Item $_.FullName -Destination $Internal -Force
            Write-Host "    bundled runtime DLL: $($_.Name)"
            if ($_.Name -like "libssl*") { $CopiedSsl = $true }
        }
    }
}
if (-not $CopiedSsl -and -not (Test-Path (Join-Path $Internal "libssl*.dll"))) {
    Write-Host "    NOTE: no libssl found to bundle - fine for python.org builds, check ssl on a clean PC for conda builds." -ForegroundColor Yellow
}

Write-Host "`n[3/3] Staging vault seed (demo data only — never your real notes)..." -ForegroundColor Cyan
$Seed = Join-Path $AppDir "vault-seed"
New-Item -ItemType Directory -Force -Path $Seed | Out-Null
Copy-Item -LiteralPath (Join-Path $Root "demo-vault\conversations") -Destination (Join-Path $Seed "conversations") -Recurse -Force
Copy-Item -LiteralPath (Join-Path $Root "demo-vault\sessions")      -Destination (Join-Path $Seed "sessions") -Recurse -Force
Copy-Item -LiteralPath (Join-Path $Root "demo-vault\INDEX.md")      -Destination (Join-Path $Seed "INDEX.md") -Force
Copy-Item -LiteralPath (Join-Path $Root "templates")                -Destination (Join-Path $Seed "templates") -Recurse -Force

# Optional skills ship with the app when present.
foreach ($name in @("skills")) {
    $SourceDir = Join-Path $Root $name
    if (Test-Path -LiteralPath $SourceDir) {
        Copy-Item -LiteralPath $SourceDir -Destination (Join-Path $AppDir $name) -Recurse -Force
    }
}
foreach ($file in @("README.md", "LICENSE", "TECH_STACK.md")) {
    Copy-Item -LiteralPath (Join-Path $Root $file) -Destination (Join-Path $AppDir $file) -Force
}
foreach ($file in @("Configure SKATE MCP for Codex.bat", "Start SKATE MCP HTTP.bat")) {
    Copy-Item -LiteralPath (Join-Path $Root $file) -Destination (Join-Path $AppDir $file) -Force
}

# --- Safety gate: fail the build if secrets or client content reached staging ---
if (Get-ChildItem -Path $AppDir -Recurse -Filter "settings.json" -ErrorAction SilentlyContinue) {
    throw "SAFETY: settings.json (API keys) found in staging - aborting build."
}
$Leak = Select-String -Path (Join-Path $Seed "conversations\*\*.md") -Pattern "Northwestern Mutual" -SimpleMatch -ErrorAction SilentlyContinue
if ($Leak) {
    throw "SAFETY: client content found in the vault seed - aborting build."
}
Write-Host "    Safety gate passed: no settings.json, no client content in staging." -ForegroundColor Green

Write-Host "`nDone. Standalone app: $AppDir" -ForegroundColor Green
