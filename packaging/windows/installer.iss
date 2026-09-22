; Inno Setup 6 Script for Ag Attention Bridge
; Builds a self-contained, per-user setup wizard for Windows (no admin rights required)

#define MyAppName "Ag Attention Bridge"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Karl Schmidt"
#define MyAppURL "https://github.com/FarrelAD/ag-attention-bridge"
#define MyAppExeName "ag-attention-bridge.exe"

[Setup]
AppId={{D8C9A31E-50E2-446A-8A46-C9E74A271B33}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\AgAttentionBridge
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=AgAttentionBridge-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "autostart"; Description: "Start {#MyAppName} automatically when Windows starts"; GroupDescription: "Additional options:"

[Files]
; Dist directory output from PyInstaller
Source: "..\..\dist\AgAttentionBridge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: autostart

[Registry]
; Add {app} to User PATH
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Terminate running processes before removal
Filename: "taskkill.exe"; Parameters: "/F /IM {#MyAppExeName} /T"; Flags: runhidden; RunOnceId: "KillApp"
Filename: "taskkill.exe"; Parameters: "/F /IM ag-hook-adapter.exe /T"; Flags: runhidden; RunOnceId: "KillAdapter"

[Code]
// Helper function to prevent duplicate PATH entries
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath)
  then begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + UpperCase(Param) + ';', ';' + UpperCase(OrigPath) + ';') = 0;
end;

// Hook registration on installation
procedure RegisterAntigravityHooks();
var
  ConfigDir, HooksFile, AdapterPath, Content: string;
begin
  ConfigDir := ExpandConstant('{userprofile}\.gemini\config');
  HooksFile := ConfigDir + '\hooks.json';
  AdapterPath := ExpandConstant('{app}\ag-hook-adapter.exe');
  // Inno Setup can invoke powershell or python helper to merge JSON hooks
  Exec('powershell.exe', '-NoProfile -Command "param($h,$a) ' +
    '$cfg = @{}; if (Test-Path $h) { try { $cfg = Get-Content -Raw $h | ConvertFrom-Json } catch {} }; ' +
    '$cfg | Add-Member -NotePropertyName \"ag-attention-bridge\" -NotePropertyValue @{ ' +
    '  PreToolUse = @(@{ matcher = \"ask_question|ask_permission\"; hooks = @(@{ type=\"command\"; command=\"`\"$a`\" --event PreToolUse\"; timeout=30 }) }); ' +
    '  PreInvocation = @(@{ type=\"command\"; command=\"`\"$a`\" --event PreInvocation\"; timeout=15 }); ' +
    '  PostInvocation = @(@{ type=\"command\"; command=\"`\"$a`\" --event PostInvocation\"; timeout=15 }); ' +
    '  Stop = @(@{ type=\"command\"; command=\"`\"$a`\" --event Stop\"; timeout=15 }) ' +
    '} -Force; ' +
    'New-Item -ItemType Directory -Force (Split-Path -Parent $h) | Out-Null; ' +
    '$cfg | ConvertTo-Json -Depth 10 | Set-Content $h -Encoding utf8" ' +
    '-args "' + HooksFile + '","' + AdapterPath + '"', '', SW_HIDE, ewWaitUntilTerminated, Content);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    RegisterAntigravityHooks();
  end;
end;

// Hook removal on uninstallation
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  HooksFile, Content: string;
begin
  if CurUninstallStep = usUninstall then
  begin
    HooksFile := ExpandConstant('{userprofile}\.gemini\config\hooks.json');
    Exec('powershell.exe', '-NoProfile -Command "param($h) ' +
      'if (Test-Path $h) { try { $cfg = Get-Content -Raw $h | ConvertFrom-Json; ' +
      'if ($cfg.PSObject.Properties.Match(\"ag-attention-bridge\").Count -gt 0) { ' +
      '$cfg.PSObject.Properties.Remove(\"ag-attention-bridge\"); ' +
      '$cfg | ConvertTo-Json -Depth 10 | Set-Content $h -Encoding utf8 } } catch {} }" ' +
      '-args "' + HooksFile + '"', '', SW_HIDE, ewWaitUntilTerminated, Content);
  end;
end;
