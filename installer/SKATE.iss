#define MyAppName "SKATE"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "NeraTech LLC"
#define MyAppExeName "SKATE.exe"

[Setup]
AppId={{4A04BC9F-C5B7-47E9-A8E5-89525D5AB9C8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\SKATE
DefaultGroupName=SKATE
DisableProgramGroupPage=yes
OutputDir=..\build\installer
OutputBaseFilename=SKATE-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\ui\static\favicon.ico
UninstallDisplayIcon={app}\SKATE.exe
LicenseFile=..\LICENSE

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "connectcodex"; Description: "Connect SKATE memory to Codex and ChatGPT desktop"; GroupDescription: "AI agent connection:"
Name: "connectclaude"; Description: "Connect SKATE memory to Claude Desktop"; GroupDescription: "AI agent connection:"

[Files]
Source: "..\build\app-staging\SKATE\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installed.marker"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\SKATE"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\SKATE"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\Configure SKATE MCP for Codex.bat"; Parameters: "/quiet"; Description: "Connect SKATE memory to Codex"; Flags: postinstall shellexec skipifsilent; Tasks: connectcodex
Filename: "{app}\Configure SKATE MCP for Claude Desktop.bat"; Parameters: "/quiet"; Description: "Connect SKATE memory to Claude Desktop"; Flags: postinstall shellexec skipifsilent; Tasks: connectclaude
Filename: "{app}\{#MyAppExeName}"; Description: "Launch SKATE"; Flags: nowait postinstall skipifsilent
