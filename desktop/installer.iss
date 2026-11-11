; Synchro desktop installer: the player, its engine runtime, CPU models, FFmpeg and mpv.
; Built by desktop/build_bundle.py, which passes AppVersion, Bundle and Output.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8C1B7F2E-5A4D-4C3B-9E21-6F0D3A7B5C11}
AppName=Synchro
AppVersion={#AppVersion}
AppPublisher=Synchro
AppComments=Video player with Russian voiceover
DefaultDirName={localappdata}\Programs\Synchro
DisableProgramGroupPage=yes
; Per-user install: no administrator rights needed.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#Output}
OutputBaseFilename=Synchro-Setup-{#AppVersion}
; Models are already compressed weights; fast LZMA keeps the build quick for little size cost.
Compression=lzma2/fast
SolidCompression=no
; The payload exceeds 2 GB, the limit of one setup file.
DiskSpanning=yes
DiskSliceSize=max
WizardStyle=modern
UninstallDisplayIcon={app}\Synchro.exe
UninstallDisplayName=Synchro

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#Bundle}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Synchro"; Filename: "{app}\Synchro.exe"
Name: "{autodesktop}\Synchro"; Filename: "{app}\Synchro.exe"; Tasks: desktopicon

[Registry]
; "Open with > Synchro" for video files, without taking over the default player.
Root: HKCU; Subkey: "Software\Classes\Applications\Synchro.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "Synchro"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\Synchro.exe\shell\open\command"; ValueType: string; ValueData: """{app}\Synchro.exe"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\Applications\Synchro.exe\SupportedTypes"; ValueType: string; ValueName: ".mp4"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Synchro.exe\SupportedTypes"; ValueType: string; ValueName: ".mkv"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Synchro.exe\SupportedTypes"; ValueType: string; ValueName: ".avi"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Synchro.exe\SupportedTypes"; ValueType: string; ValueName: ".mov"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Synchro.exe\SupportedTypes"; ValueType: string; ValueName: ".webm"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Synchro.exe\SupportedTypes"; ValueType: string; ValueName: ".m4v"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Synchro.exe\SupportedTypes"; ValueType: string; ValueName: ".wmv"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Synchro.exe\SupportedTypes"; ValueType: string; ValueName: ".ts"; ValueData: ""

[Run]
Filename: "{app}\Synchro.exe"; Description: "Start Synchro"; Flags: nowait postinstall skipifsilent
