; Установщик «Скрина» (Inno Setup 6). Собирается из build.ps1 — версия приходит параметром /DAppVer.
#ifndef AppVer
  #define AppVer "1.0.0"
#endif

[Setup]
AppId={{8C1B6E2A-5F4D-4E3B-9A51-7D2C0B9E4F11}
AppName=Скрин
AppVersion={#AppVer}
AppVerName=Скрин {#AppVer}
AppPublisher=Скрин
DefaultDirName={localappdata}\Programs\Skrin
DefaultGroupName=Скрин
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=SkrinSetup-{#AppVer}
SetupIconFile=skrin.ico
UninstallDisplayIcon={app}\Skrin.exe
UninstallDisplayName=Скрин — скриншоты и запись экрана
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "prtscn"; Description: "Клавиша PrtScn — для Скрина (вместо «Ножниц» Windows)"; GroupDescription: "Дополнительно:"
Name: "autostart"; Description: "Запускать вместе с Windows"; GroupDescription: "Дополнительно:"
Name: "desktopicon"; Description: "Значок на рабочем столе"; GroupDescription: "Дополнительно:"; Flags: unchecked

[Files]
Source: "dist\Skrin\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\bin\ffmpeg.exe"; DestDir: "{app}\bin"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\Скрин"; Filename: "{app}\Skrin.exe"
Name: "{userprograms}\Скрин — настройки"; Filename: "{app}\Skrin.exe"; Parameters: "--settings"
Name: "{userdesktop}\Скрин"; Filename: "{app}\Skrin.exe"; Tasks: desktopicon

[Registry]
; Windows 11 по PrtScn открывает «Ножницы» — отдать клавишу Скрину (при удалении — вернуть как было у Windows)
Root: HKCU; Subkey: "Control Panel\Keyboard"; ValueType: dword; ValueName: "PrintScreenKeyForSnippingEnabled"; ValueData: 0; Tasks: prtscn; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Skrin"; ValueData: """{app}\Skrin.exe"""; Tasks: autostart
; при удалении убрать автозапуск, даже если его включали из настроек программы
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Skrin"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Skrin.exe"; Description: "Запустить Скрин"; Flags: nowait postinstall skipifsilent
; обновление из программы ставится тихо (/SILENT) — после него запустить «Скрин» снова
Filename: "{app}\Skrin.exe"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM Skrin.exe"; Flags: runhidden; RunOnceId: "KillSkrin"

[Code]
// перед установкой поверх старой версии — закрыть запущенный «Скрин»
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  R: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM Skrin.exe', '', SW_HIDE, ewWaitUntilTerminated, R);
  Sleep(500);
  Result := '';
end;
