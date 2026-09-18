#define MyAppName "Shadow Media Studio Pro"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Shadow Media Studio"
#define MyAppExeName "Shadow.exe"

[Setup]
AppId={{B8E54C55-7D35-4C78-9F26-0A8A4CF1C0E7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=no
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=installer
OutputBaseFilename=Shadow-Media-Studio-Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=EULA.txt
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
; Shadow Media Studio Pro is a 100% offline, private desktop media studio.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "contextmenu"; Description: "Add 'Compress with Shadow Media Studio' to Windows Explorer context menu"; GroupDescription: "Windows Explorer Integration:"

[Files]
Source: "dist\Shadow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCR; Subkey: "*\shell\ShadowMediaStudio"; ValueType: string; ValueName: ""; ValueData: "Compress with Shadow Media Studio"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCR; Subkey: "*\shell\ShadowMediaStudio"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKCR; Subkey: "*\shell\ShadowMediaStudio\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: contextmenu

Root: HKCR; Subkey: "Directory\shell\ShadowMediaStudio"; ValueType: string; ValueName: ""; ValueData: "Compress folder with Shadow Media Studio"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCR; Subkey: "Directory\shell\ShadowMediaStudio"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKCR; Subkey: "Directory\shell\ShadowMediaStudio\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: contextmenu

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
