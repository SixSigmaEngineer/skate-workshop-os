# Registers the SKATE MCP server with Claude Desktop by merging an entry
# into %APPDATA%\Claude\claude_desktop_config.json without disturbing any
# other configured MCP servers.
#
# Usage:
#   configure_claude_desktop.ps1 -Command <exe-or-python> [-ScriptPath <server.py>]

param(
    [Parameter(Mandatory = $true)][string]$Command,
    [string]$ScriptPath = ""
)

$ErrorActionPreference = "Stop"

$configDir = Join-Path $env:APPDATA "Claude"
$configPath = Join-Path $configDir "claude_desktop_config.json"

New-Item -ItemType Directory -Force -Path $configDir | Out-Null

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

$config | ConvertTo-Json -Depth 10 | Set-Content -Path $configPath -Encoding UTF8

Write-Host "SKATE MCP is configured for Claude Desktop."
Write-Host "Config: $configPath"
