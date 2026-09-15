#define AppName "Theologia Search"
#define AppVersion "1.0.0"
#define AppPublisher "Theologia Search"
#define AppExeName "TheologiaSearch.exe"
#define DistDir "..\\dist\\TheologiaSearch"

[Setup]
AppId={{8E35C7A4-9DBA-4A75-8EA8-1A4B07A7A1C5}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Theologia Search
DefaultGroupName={#AppName}
DisableProgramGroupPage=no
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=Theologia Search Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#DistDir}\_internal\README.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistDir}\_internal\CATALOG.txt"; DestDir: "{app}"; Flags: ignoreversion

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
