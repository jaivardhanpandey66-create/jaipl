; Inno Setup script for the zing Windows installer.
;
; Build on any machine with Inno Setup 6 installed:
;     iscc zing.iss
; which produces zing-setup-<version>.exe -- the file the website links to.
;
; It bundles the Python runtime so the install needs nothing preinstalled,
; registers the .zig file type so double-clicking runs the file, and adds a
; "Run with zing" entry to the right-click menu.

#define AppName "zing"
#define AppVersion "0.1.0"
#define AppPublisher "zing"
#define AppURL "https://jaivardhanpandey66-create.github.io/zing"
#define RuntimeDir "runtime"

[Setup]
AppId={{7C4E1B2A-9F3D-4A6E-8B21-5D9C0E7F1A34}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={autopf}\zing
DefaultGroupName=zing
OutputBaseFilename=zing-setup-{#AppVersion}
OutputDir=..\dist
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Per-user by default so the installer never needs administrator rights.
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\zing.exe
ChangesAssociations=yes
AppMutex=zing-setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "addtopath"; Description: "Add zing to PATH so you can type 'zing' anywhere"; GroupDescription: "Command line:"
Name: "assoc"; Description: "Open .zig files by double-clicking them"; GroupDescription: "File types:"; Flags: checkedonce
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
; The launcher.
Source: "zing.cmd"; DestDir: "{app}"; Flags: ignoreversion
; The classic zing icon, shown in Explorer for .zig files.
Source: "..\..\packaging\icons\zing.ico"; DestDir: "{app}"; Flags: ignoreversion
; The interpreter runtime.
Source: "..\arcide\*"; DestDir: "{app}\{#RuntimeDir}\arcide"; Flags: ignoreversion recursesubdirs createallsubdirs
; Examples.
Source: "..\examples\*"; DestDir: "{app}\examples"; Flags: ignoreversion recursesubdirs skipifsourcedoesntexist
; The Python runtime. PythonEmbed is the official embeddable distribution;
; unpack it here so zing runs on a machine with no Python installed.
Source: "python-embed\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Dirs]
Name: "{app}"

[Icons]
Name: "{group}\zing"; Filename: "{app}\zing.cmd"; Parameters: "repl"; WorkingDir: "{app}"; Comment: "Open the zing prompt"
Name: "{group}\Uninstall zing"; Filename: "{uninstallexe}"
Name: "{autodesktop}\zing"; Filename: "{app}\zing.cmd"; Parameters: "repl"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; Make 'zing' runnable from any command prompt.
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
  ValueData: "{olddata};{app}"; Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))
; Register the .zig extension.
Root: HKCU; Subkey: "Software\Classes\.zig"; ValueType: string; ValueName: ""; \
  ValueData: "zing.source"; Flags: uninsdeletekey; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\.zig\OpenWithProgids"; \
  ValueType: string; ValueName: "zing.source"; ValueData: ""; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\zing.source"; ValueType: string; ValueName: ""; \
  ValueData: "zing source file"; Flags: uninsdeletekey; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\zing.source\DefaultIcon"; \
  ValueType: string; ValueName: ""; ValueData: "{app}\zing.ico,0"; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\zing.source\shell\open\command"; \
  ValueType: string; ValueName: ""; ValueData: """{app}\zing.cmd"" ""%1"""; \
  Flags: uninsdeletekey; Tasks: assoc

[Run]
Filename: "{app}\zing.cmd"; Parameters: "version"; \
  Description: "Check that zing works"; Flags: runhidden; Tasks: assoc

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Param + ';', ';' + OrigPath + ';') = 0;
end;