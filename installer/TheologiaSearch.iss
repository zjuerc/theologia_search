#define AppName "Theologia Search"
#define AppVersion "1.0.0"
#define AppPublisher "Theologia Search"
#define AppExeName "TheologiaSearch.exe"
#ifndef DistDir
#define DistDir "..\\dist\\TheologiaSearch"
#endif
#ifndef LicenseDir
#define LicenseDir "..\\license"
#endif

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
LicenseFile={#LicenseDir}\LICENSE.txt

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#DistDir}\_internal\README.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistDir}\_internal\CATALOG.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistDir}\_internal\license\*"; DestDir: "{app}\license"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\Licenses\Theologia Search License"; Filename: "{app}\license\LICENSE.txt"
Name: "{group}\Licenses\Third-Party Notices"; Filename: "{app}\license\THIRD-PARTY-NOTICES.txt"
Name: "{group}\Licenses\Cinzel OFL License"; Filename: "{app}\license\OFL-Cinzel.txt"
Name: "{group}\Licenses\EB Garamond OFL License"; Filename: "{app}\license\OFL-EBGaramond.txt"
Name: "{group}\Licenses\CCEL Copyright Policy"; Filename: "{app}\license\CCEL-Copyright-Policy.txt"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
