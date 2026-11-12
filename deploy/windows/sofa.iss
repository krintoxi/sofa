; Sofa for Windows: the installer (Inno Setup 6). Built on GitHub's Windows machines by .github/workflows/windows.yml:
;
;     python tools\windows-build.py                         (build\windows\Sofa: Sofa's code, vendor\python, vendor\ffmpeg)
;     iscc /DAppVersion=1.5.9 deploy\windows\sofa.iss       (build\windows\sofa-1.5.9-windows-x64-setup.exe)
;
; Sofa is installed for the person installing it, with no administrator needed, in %LOCALAPPDATA%\Programs\Sofa:
; Sofa updates its own code in place (Server -> Updates, sofa/updater.py), so its folder has to be theirs. Two things
; are Windows' own settings and need an administrator's yes, asked once, together: the firewall rule (explained on
; its own page) and, when ticked, long paths. Signing: deploy/windows/README.md.
;
; Silent installs (an IT person, the workflow's own check): /VERYSILENT /SUPPRESSMSGBOXES, and
;     /LIBRARY="D:\Media"    where the library goes on a first install (default: %USERPROFILE%\Entertainment)
;     /NOFIREWALL            leave Windows Firewall as it is
;     /TASKS="startup,longpaths"   what to tick (startup is ticked by default)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define Stage "..\..\build\windows\Sofa"
#define Python "{app}\vendor\python"
#define Tray "{app}\deploy\windows\sofa-tray.pyw"
#define RuleName "Sofa"

[Setup]
AppId={{61DF8341-AA47-4BAA-8C9B-F30F17A92050}
AppName=Sofa
AppVersion={#AppVersion}
AppVerName=Sofa {#AppVersion}
AppPublisher=EdgeVenture
AppPublisherURL=https://edgeventure.uk
AppSupportURL=https://github.com/krintoxi/sofa/issues
AppUpdatesURL=https://github.com/krintoxi/sofa/releases
AppCopyright=Copyright (c) 2026 EdgeVenture
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Sofa
VersionInfoDescription=Sofa, a home media server: setup
DefaultDirName={autopf}\Sofa
DisableDirPage=auto
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Windows 10 1809: Windows' own Bonjour (DNS-SD) and what Python 3.14 needs
MinVersion=10.0.17763
WizardStyle=modern
SetupIconFile=sofa.ico
UninstallDisplayIcon={app}\deploy\windows\sofa.ico
UninstallDisplayName=Sofa
LicenseFile=..\..\LICENSE
OutputDir=..\..\build\windows
OutputBaseFilename=sofa-{#AppVersion}-windows-x64-setup
Compression=lzma2/max
SolidCompression=yes
; Sofa is stopped by its own app before files change (PrepareToInstall), not by Windows' Restart Manager.
CloseApplications=no
RestartApplications=no
ShowLanguageDialog=no
#ifdef Sign
; iscc /DSign /Ssofa="signtool.exe sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /f sofa.pfx /p ... $f"
SignTool=sofa
SignedUninstaller=yes
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startup"; Description: "Start Sofa when I sign in to Windows (it waits in the notification area, by the clock)"
Name: "desktopicon"; Description: "A Sofa icon on the desktop"; Flags: unchecked
Name: "longpaths"; Description: "Allow file paths longer than 260 characters (a setting for all of Windows: deep folders of long episode names; Windows asks for permission)"; Flags: unchecked

[Files]
Source: "{#Stage}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\build\windows\installed-commit"; DestDir: "{app}\data"; Flags: ignoreversion uninsneveruninstall

[Icons]
Name: "{autoprograms}\Sofa"; Filename: "{#Python}\pythonw.exe"; Parameters: """{#Tray}"""; WorkingDir: "{app}"; IconFilename: "{app}\deploy\windows\sofa.ico"; Comment: "Your home media server"; AppUserModelID: "EdgeVenture.Sofa"
Name: "{autodesktop}\Sofa"; Filename: "{#Python}\pythonw.exe"; Parameters: """{#Tray}"""; WorkingDir: "{app}"; IconFilename: "{app}\deploy\windows\sofa.ico"; Comment: "Your home media server"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Sofa"; ValueData: """{#Python}\pythonw.exe"" ""{#Tray}"" --background"; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{#Python}\pythonw.exe"; Parameters: """{#Tray}"" --first-run"; WorkingDir: "{app}"; Description: "Start Sofa now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{#Python}\pythonw.exe"; Parameters: """{#Tray}"" --quit"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; RunOnceId: "QuitSofa"

[UninstallDelete]
; What an update may have added since (sofa/updater.py swaps these folders whole); data\ is asked about separately.
Type: filesandordirs; Name: "{app}\sofa"
Type: filesandordirs; Name: "{app}\client"
Type: filesandordirs; Name: "{app}\deploy"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\docs"
Type: filesandordirs; Name: "{app}\integrations"
Type: filesandordirs; Name: "{app}\roku"
Type: filesandordirs; Name: "{app}\vendor"
Type: filesandordirs; Name: "{app}\.sofa-old"
Type: filesandordirs; Name: "{app}\.sofa-new"
Type: filesandordirs; Name: "{app}\.sofa-old-done"
Type: filesandordirs; Name: "{app}\.sofa-undone"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\sofa.py"
Type: files; Name: "{app}\README.md"
Type: files; Name: "{app}\LICENSE"
Type: files; Name: "{app}\NOTICE"
Type: files; Name: "{app}\TRADEMARKS.md"
Type: files; Name: "{app}\.gitignore"

[Code]
var
  LibraryPage: TInputDirWizardPage;
  FirewallPage: TInputOptionWizardPage;
  WasRunning: Boolean;

function HasSwitch(Name: String): Boolean;
var
  i: Integer;
begin
  Result := False;
  for i := 1 to ParamCount do
    if CompareText(ParamStr(i), Name) = 0 then
      Result := True;
end;

function FirstInstall: Boolean;
begin
  Result := not FileExists(ExpandConstant('{app}\data\config.json'));
end;

function LibraryDir(Param: String): String;
begin
  if not FirstInstall then
    Result := ''
  else if WizardSilent then
  begin
    Result := ExpandConstant('{param:LIBRARY|}');
    if Result = '' then
      Result := ExpandConstant('{%USERPROFILE}\Entertainment');
  end
  else
    Result := LibraryPage.Values[0];
end;

function WantFirewall: Boolean;
begin
  if WizardSilent then
    Result := not HasSwitch('/NOFIREWALL')
  else
    Result := FirewallPage.Values[0];
end;

procedure InitializeWizard;
begin
  LibraryPage := CreateInputDirPage(wpSelectDir,
    'Your library',
    'Where should Sofa keep your shows, movies and music?',
    'Sofa makes these folders here: Shows, Movies, Music, Music Videos, and an Inbox. Drop new things in the Inbox ' +
    'and Sofa names them and files them away. Your media never goes anywhere else.' + #13#10#13#10 +
    'A big drive is a good place (D:\Media, say). More folders, on other drives too, can be added later on ' +
    'Sofa''s Server page, under Storage.',
    False, '');
  LibraryPage.Add('');
  LibraryPage.Values[0] := ExpandConstant('{%USERPROFILE}\Entertainment');

  FirewallPage := CreateInputOptionPage(LibraryPage.ID,
    'TVs and phones at home',
    'Should they be able to reach Sofa through Windows Firewall?',
    'Your TVs, phones, tablets and the Sofa apps open Sofa over your home network: Sofa answers on port 8090 and ' +
    'tells the devices at home that it''s there (SSDP for TVs, Bonjour for the apps). Windows Firewall blocks all ' +
    'of that until it''s allowed.' + #13#10#13#10 +
    'Ticked, Sofa adds one rule to Windows Firewall: Sofa''s own copy of Python, in Sofa''s folder, may accept ' +
    'connections on private networks (what Windows calls a home network), never on public ones such as a cafe''s ' +
    'Wi-Fi. Windows asks for an administrator''s permission once, next. Nothing else on this computer is opened.' + #13#10#13#10 +
    'Not ticked, Sofa still works on this computer (http://localhost:8090), and Windows shows its own question ' +
    'when Sofa starts. If Windows has your home network as Public, set it to Private: Settings, Network & ' +
    'internet, your network.',
    False, False);
  FirewallPage.Add('Allow Sofa on private (home) networks');
  FirewallPage.Values[0] := True;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = LibraryPage.ID) and not FirstInstall;
end;

function TrayCommand(Args: String; Wait: Boolean): Integer;
var
  rc: Integer;
  how: TExecWait;
begin
  Result := -1;
  if Wait then how := ewWaitUntilTerminated else how := ewNoWait;
  if FileExists(ExpandConstant('{#Python}\pythonw.exe')) and FileExists(ExpandConstant('{#Tray}')) then
    if Exec(ExpandConstant('{#Python}\pythonw.exe'), '"' + ExpandConstant('{#Tray}') + '" ' + Args,
            ExpandConstant('{app}'), SW_HIDE, how, rc) then
      Result := rc;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  // An update over a running Sofa: its app stops it (cleanly) and leaves, so its files can be replaced.
  WasRunning := TrayCommand('--status', True) = 0;
  TrayCommand('--quit', True);
  Result := '';
end;

function FirewallRuleExists: Boolean;
var
  rc: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\netsh.exe'), 'advfirewall firewall show rule name="{#RuleName}"', '',
                 SW_HIDE, ewWaitUntilTerminated, rc) and (rc = 0);
end;

function RunElevated(Commands: String): Boolean;
var
  rc: Integer;
begin
  // One "Do you want to allow..." from Windows for everything that needs an administrator.
  Result := ShellExec('runas', ExpandConstant('{cmd}'), '/s /c "' + Commands + '"', '', SW_HIDE,
                      ewWaitUntilTerminated, rc) and (rc = 0);
  Log('Elevated: ' + Commands + ' -> ' + IntToStr(rc));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  cmds, py: String;
begin
  if CurStep = ssPostInstall then
  begin
    if LibraryDir('') <> '' then                     // a first install: the library's folders where they were asked for
      TrayCommand('--set-library "' + AddBackslash(LibraryDir('')) + '."', True);     // (no \" at the end of D:\)
    if not WizardIsTaskSelected('startup') then
      RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Sofa');
    cmds := '';
    py := ExpandConstant('{#Python}\python.exe');
    if WantFirewall then
      cmds := 'netsh advfirewall firewall delete rule name="{#RuleName}" >nul 2>&1 & ' +
              'netsh advfirewall firewall add rule name="{#RuleName}" dir=in action=allow enable=yes profile=private ' +
              'program="' + py + '" description="Sofa, the home media server: TVs, phones and the Sofa apps at home reach it (added by Sofa''s installer)"';
    if WizardIsTaskSelected('longpaths') then
    begin
      if cmds <> '' then cmds := cmds + ' & ';
      cmds := cmds + 'reg add "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled /t REG_DWORD /d 1 /f';
    end;
    if cmds <> '' then
      RunElevated(cmds);
    if WantFirewall and not FirewallRuleExists and not WizardSilent then
      MsgBox('Windows Firewall wasn''t changed (the permission was declined). Sofa works on this computer; for TVs ' +
             'and phones, allow Sofa when Windows asks, or run this installer again.', mbInformation, MB_OK);
    if WizardSilent and WasRunning then
      TrayCommand('--background', False);          // an update done quietly: Sofa back as it was
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  rc: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Sofa');     // (also when the menu set it)
    if Exec(ExpandConstant('{sys}\netsh.exe'), 'advfirewall firewall show rule name="{#RuleName}"', '', SW_HIDE,
            ewWaitUntilTerminated, rc) and (rc = 0) then
      ShellExec('runas', ExpandConstant('{sys}\netsh.exe'), 'advfirewall firewall delete rule name="{#RuleName}"', '',
                SW_HIDE, ewWaitUntilTerminated, rc);
  end;
  if CurUninstallStep = usPostUninstall then
  begin
    if DirExists(ExpandConstant('{app}\data')) and not UninstallSilent then
      if MsgBox('Also delete Sofa''s own data on this computer: accounts, watch history, settings, artwork and ' +
                'backups (' + ExpandConstant('{app}\data') + ')?' + #13#10#13#10 +
                'Your shows, movies and music are not touched either way. Keep it to pick up where you left off ' +
                'if you install Sofa again.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(ExpandConstant('{app}\data'), True, True, True);
    RemoveDir(ExpandConstant('{app}'));
  end;
end;
