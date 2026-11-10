; Windows installer for NoteFall (Inno Setup 6). Built by scripts/build_app.py:
;   iscc /DAppVersion=0.4.0 /DSourceDir=dist\NoteFall /DOutputDir=dist /DIconFile=build\icon.ico notefall.iss
; Installs for the current user only, so no admin prompt. Running a newer
; setup over an old one updates it in place (the app does this by itself).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E0B3C52-4F1D-4B7A-9C55-2F1A6E9D7B10}
AppName=NoteFall
AppVersion={#AppVersion}
AppVerName=NoteFall {#AppVersion}
AppPublisher=Sumayer Uddin
AppPublisherURL=https://github.com/Suma-Udd/notefall
AppUpdatesURL=https://github.com/Suma-Udd/notefall/releases/latest
DefaultDirName={localappdata}\Programs\NoteFall
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableWelcomePage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=NoteFall-{#AppVersion}-windows-x64-Setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\NoteFall.exe
UninstallDisplayName=NoteFall
Compression=lzma2/ultra64
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Put NoteFall on the desktop"

[InstallDelete]
; clear the previous version's files so updates never mix old and new
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\NoteFall"; Filename: "{app}\NoteFall.exe"
Name: "{autodesktop}\NoteFall"; Filename: "{app}\NoteFall.exe"; Tasks: desktopicon

[Run]
; no skipifsilent: after a quiet update NoteFall opens again by itself
Filename: "{app}\NoteFall.exe"; Description: "Open NoteFall"; Flags: nowait postinstall
