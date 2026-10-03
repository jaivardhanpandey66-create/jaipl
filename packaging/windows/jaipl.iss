; Inno Setup script for the jaipl Windows installer.
;
; Build on any machine with Inno Setup 6 installed:
;     iscc jaipl.iss
; which produces jaipl-setup-<version>.exe -- the file the website links to.
;
; It bundles the Python runtime so the install needs nothing preinstalled,
; registers the .jai file type so double-clicking runs the file, and adds a
; "Run with jaipl" entry to the right-click menu.

#define AppName "jaipl"
#define AppVersion "0.1.0"
#define AppPublisher "jaipl"
#define AppURL "https://jaivardhanpandey66-create.github.io/jaipl"
#define RuntimeDir "runtime"

[Setup]
AppId={{7C4E1B2A-9F3D-4A6E-8B21-5D9C0E7F1A34}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={autopf}\jaipl
DefaultGroupName=jaipl
OutputBaseFilename=jaipl-setup-{#AppVersion}
OutputDir=..\dist
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Per-user by default so the installer never needs administrator rights.
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\jaipl.exe
ChangesAssociations=yes
AppMutex=jaipl-setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "addtopath"; Description: "Add jaipl to PATH so you can type 'jaipl' anywhere"; GroupDescription: "Command line:"
Name: "assoc"; Description: "Open .jai files by double-clicking them"; GroupDescription: "File types:"; Flags: checkedonce
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
; The launcher.
Source: "..\bin\jaipl.cmd"; DestDir: "{app}"; Flags: ignoreversion
; The interpreter runtime.
Source: "..\arcide\*"; DestDir: "{app}\{#RuntimeDir}\arcide"; Flags: ignoreversion recursesubdirs createallsubdirs
; Examples.
Source: "..\examples\*"; DestDir: "{app}\examples"; Flags: ignoreversion recursesubdirs skipifsourcedoesntexist
; The Python runtime. PythonEmbed is the official embeddable distribution;
; unpack it here so jaipl runs on a machine with no Python installed.
Source: "python-embed\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Dirs]
Name: "{app}"

[Icons]
Name: "{group}\jaipl"; Filename: "{app}\jaipl.cmd"; Parameters: "repl"; WorkingDir: "{app}"; Comment: "Open the jaipl prompt"
Name: "{group}\Uninstall jaipl"; Filename: "{uninstallexe}"
Name: "{autodesktop}\jaipl"; Filename: "{app}\jaipl.cmd"; Parameters: "repl"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; Make 'jaipl' runnable from any command prompt.
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
  ValueData: "{olddata};{app}"; Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))
; Register the .jai extension.
Root: HKCU; Subkey: "Software\Classes\.jai"; ValueType: string; ValueName: ""; \
  ValueData: "jaipl.source"; Flags: uninsdeletekey; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\.jai\OpenWithProgids"; \
  ValueType: string; ValueName: "jaipl.source"; ValueData: ""; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\jaipl.source"; ValueType: string; ValueName: ""; \
  ValueData: "jaipl source file"; Flags: uninsdeletekey; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\jaipl.source\DefaultIcon"; \
  ValueType: string; ValueName: ""; ValueData: "{app}\jaipl.exe,0"; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\jaipl.source\shell\open\command"; \
  ValueType: string; ValueName: ""; ValueData: """{app}\jaipl.cmd"" ""%1"""; \
  Flags: uninsdeletekey; Tasks: assoc

[Run]
Filename: "{app}\jaipl.cmd"; Parameters: "version"; \
  Description: "Check that jaipl works"; Flags: runhidden; Tasks: assoc

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