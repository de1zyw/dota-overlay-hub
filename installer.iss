; Inno Setup script for Dota Overlay Hub.
; Compiled automatically by .github/workflows/build-installer.yml on every
; GitHub Release - the exe it packages is the same PyInstaller --onefile
; build build.bat produces (bundles assets/gsi cfg/icon into itself via
; --add-data), so this installer only ever needs to place ONE file plus
; shortcuts. Installs per-user under %LOCALAPPDATA% by default - avoids a
; UAC prompt, since this is a single-user tool with no reason to touch
; Program Files.

#define MyAppName "Dota Overlay Hub"
#define MyAppExeName "Dota Overlay Hub.exe"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{8F2C9E6A-4D1B-4A7E-9C3F-2B6A1D8E5F41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=de1zyw
AppPublisherURL=https://github.com/de1zyw/dota-overlay-hub
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer_output
OutputBaseFilename=DotaOverlayHub-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
