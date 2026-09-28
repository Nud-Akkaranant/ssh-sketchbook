#define AppName "ssh-sketchbook"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{97EF3B3D-4075-43B4-80CA-DA9DCD9DA8AD}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=ssh-sketchbook contributors
AppPublisherURL=https://github.com/Nud-Akkaranant/ssh-sketchbook
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=ssh-sketchbook-setup
SetupIconFile=..\static\icon.ico
UninstallDisplayIcon={app}\ssh-sketchbook.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\dist\ssh-sketchbook\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\ssh-sketchbook.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\ssh-sketchbook.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ssh-sketchbook.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
