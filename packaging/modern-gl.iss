; Inno Setup script (ISCC /DAppVersion=0.1.0 packaging\modern-gl.iss): the installer of the
; PyInstaller folder `dist/modern-gl` for one user, no administrator rights
; (%LOCALAPPDATA%\Programs\Modern GL). A newer setup over an older one updates in place:
; the same AppId, the old `_internal` is removed first so no stale file of the previous
; build stays. The company files live in «Documents\Modern GL» and are never touched.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7E2B5B3C-4C4E-4C1A-9E3D-2F1A6B8C0D11}
AppName=Modern GL
AppVersion={#AppVersion}
AppVerName=Modern GL {#AppVersion}
AppPublisher=Modern GL
DefaultDirName={localappdata}\Programs\Modern GL
DefaultGroupName=Modern GL
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=modern-gl-{#AppVersion}-setup
SetupIconFile=modern-gl.ico
UninstallDisplayIcon={app}\modern-gl.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\modern-gl\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Modern GL"; Filename: "{app}\modern-gl.exe"
Name: "{autodesktop}\Modern GL"; Filename: "{app}\modern-gl.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\modern-gl.exe"; Description: "{cm:LaunchProgram,Modern GL}"; Flags: nowait postinstall skipifsilent
