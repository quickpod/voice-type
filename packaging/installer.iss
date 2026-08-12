; Inno Setup — VoiceType. Signed single-file installer, compiled in CI.
#define AppName "VoiceType"
#define AppVersion "1.0.3"

[Setup]
AppMutex=QuickOpen.VoiceType
AppId={{51A0F001-0017-4E5B-8C71-9B0E2F3A0017}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=QuickOpen (quickopen.ai)
AppPublisherURL=https://quickopen.ai/projects/voice-type
DefaultDirName={autopf}\VoiceType
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\VoiceType.exe
OutputDir=dist
OutputBaseFilename=VoiceType-Setup
SetupIconFile=..\voice-type.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardImageFile=branding\wizard-large.bmp
WizardSmallImageFile=branding\wizard-small.bmp
AppCopyright=Apache-2.0. 100%% AI-built, published on QuickOpen (quickopen.ai).
VersionInfoCompany=QuickOpen
VersionInfoProductName=VoiceType
VersionInfoVersion=1.0.3.0
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel2=VoiceType is a 100%% AI-built, open-source offline tool, published on QuickOpen (quickopen.ai).%n%nThis will install it on your computer.
BeveledLabel=QuickOpen · quickopen.ai

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "trustca"; Description: "Trust the QuickOpen Root CA (lets Windows verify QuickOpen signatures)"; GroupDescription: "Security:"; Flags: unchecked

[Files]
Source: "staging\VoiceType.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "staging\quickopen-root.crt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "staging\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme skipifsourcedoesntexist
Source: "staging\LICENSE"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\VoiceType"; Filename: "{app}\VoiceType.exe"; IconFilename: "{app}\VoiceType.exe"
Name: "{group}\Uninstall VoiceType"; Filename: "{uninstallexe}"
Name: "{autodesktop}\VoiceType"; Filename: "{app}\VoiceType.exe"; IconFilename: "{app}\VoiceType.exe"; Tasks: desktopicon

[Run]
Filename: "certutil.exe"; Parameters: "-addstore -user Root ""{app}\quickopen-root.crt"""; Tasks: trustca; Flags: runhidden; StatusMsg: "Trusting the QuickOpen Root CA..."
Filename: "{app}\VoiceType.exe"; Description: "Launch VoiceType now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\VoiceType"

