# Registers the SKATE MCP server with Claude Desktop by merging an entry
# into claude_desktop_config.json without disturbing other MCP servers.
#
# Claude Desktop stores its config in different places depending on how it
# was installed:
#   - Classic installer:  %APPDATA%\Claude\claude_desktop_config.json
#   - Microsoft Store:    %LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\claude_desktop_config.json
# This script writes to every location that exists (and creates the classic
# one if none do), so the registration works for either install.
#
# Usage:
#   configure_claude_desktop.ps1 -Command <exe-or-python> [-ScriptPath <server.py>]

param(
    [Parameter(Mandatory = $true)][string]$Command,
    [string]$ScriptPath = ""
)

$ErrorActionPreference = "Stop"

function Update-ClaudeConfig {
    param([string]$ConfigDir, [string]$Command, [string]$ScriptPath)

    $configPath = Join-Path $ConfigDir "claude_desktop_config.json"
    New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null

    $config = $null
    if (Test-Path $configPath) {
        try {
            $config = Get-Content -Path $configPath -Raw | ConvertFrom-Json
        } catch {
            $backup = "$configPath.bak"
            Copy-Item -Path $configPath -Destination $backup -Force
            Write-Host "Existing config could not be parsed; a backup was saved to $backup"
            $config = $null
        }
    }
    if ($null -eq $config) { $config = [pscustomobject]@{} }

    if (-not $config.PSObject.Properties["mcpServers"]) {
        $config | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([pscustomobject]@{})
    }

    $serverArgs = @()
    if ($ScriptPath) { $serverArgs += $ScriptPath }
    $serverArgs += @("--transport", "stdio")

    $server = [pscustomobject]@{
        command = $Command
        args    = $serverArgs
    }

    if ($config.mcpServers.PSObject.Properties["skate"]) {
        $config.mcpServers.PSObject.Properties.Remove("skate")
    }
    $config.mcpServers | Add-Member -NotePropertyName "skate" -NotePropertyValue $server

    # Write UTF-8 WITHOUT a byte-order mark: Windows PowerShell 5.1's
    # Set-Content -Encoding UTF8 adds a BOM, which can break JSON parsers.
    $json = $config | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($configPath, $json, (New-Object System.Text.UTF8Encoding($false)))

    Write-Host "Updated: $configPath"
}

$targets = @()

# Classic (non-Store) install location.
$classicDir = Join-Path $env:APPDATA "Claude"
if (Test-Path $classicDir) { $targets += $classicDir }

# Microsoft Store (MSIX) install: virtualized AppData per package.
$packagesRoot = Join-Path $env:LOCALAPPDATA "Packages"
if (Test-Path $packagesRoot) {
    Get-ChildItem -Path $packagesRoot -Directory -Filter "Claude_*" -ErrorAction SilentlyContinue | ForEach-Object {
        $storeDir = Join-Path $_.FullName "LocalCache\Roaming\Claude"
        if (Test-Path (Join-Path $_.FullName "LocalCache")) { $targets += $storeDir }
    }
}

# If Claude Desktop has never run, seed the classic location anyway.
if ($targets.Count -eq 0) { $targets += $classicDir }

foreach ($dir in ($targets | Select-Object -Unique)) {
    Update-ClaudeConfig -ConfigDir $dir -Command $Command -ScriptPath $ScriptPath
}

Write-Host ""
Write-Host "SKATE MCP is configured for Claude Desktop."
