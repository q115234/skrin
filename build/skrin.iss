; Установщик «Скрина» (Inno Setup 6). Собирается из build.ps1 — версия приходит параметром /DAppVer.
; Все вопросы — здесь, при установке: папки, редактор, звук, PrtScn, автозапуск. Ответы пишутся в
; %APPDATA%\Skrin\setup.json, Скрин при запуске переносит их в настройки — окно настроек само не открывается.
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
Name: "prtscn"; Description: "Клавиша PrtScn — для Скрина (вместо «Ножниц» Windows). Без галочки Скрин снимает по Ctrl+PrtScn"; GroupDescription: "Клавиши:"
Name: "yandexoff"; Description: "Выключить скриншоты Яндекс Браузера по горячим клавишам (иначе по PrtScn снимают обе программы; открытый браузер перезапустится, вкладки вернутся)"; GroupDescription: "Клавиши:"; Check: YandexInstalled
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
; Windows 11 по PrtScn открывает «Ножницы» — отдать клавишу Скрину. При удалении НЕ стираем: значение 0 мог
; поставить и сам человек (или другая программа скриншотов), стирание вернуло бы «Ножницы» без спроса.
Root: HKCU; Subkey: "Control Panel\Keyboard"; ValueType: dword; ValueName: "PrintScreenKeyForSnippingEnabled"; ValueData: 0; Tasks: prtscn
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Skrin"; ValueData: """{app}\Skrin.exe"" --autostart"; Tasks: autostart
; при удалении убрать автозапуск, даже если его включали из настроек программы
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Skrin"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Skrin.exe"; Description: "Запустить Скрин"; Flags: nowait postinstall skipifsilent
; обновление из программы ставится тихо (/SILENT) — после него запустить «Скрин» снова
Filename: "{app}\Skrin.exe"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM Skrin.exe"; Flags: runhidden; RunOnceId: "KillSkrin"

[Code]
var
  DirPage: TInputDirWizardPage;
  OptPage: TInputOptionWizardPage;
  Cfg: TArrayOfString;     // настройки уже установленного Скрина (config.json) — чтобы спросить с ними же
  HaveCfg: Boolean;
  PrevCountdown: Integer;

const
  OPT_EDITOR = 0; OPT_SAVE = 1; OPT_JPG = 2; OPT_SYS = 3; OPT_MIC = 4; OPT_COUNT = 5;

function YandexInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\Yandex\YandexBrowser\User Data\Local State'));
end;

// ---------- чтение config.json (json.dumps с indent=2: «"ключ": значение» — по строке на ключ) ----------
function CfgRaw(const Key: String): String;
var
  I: Integer;
  L: String;
begin
  Result := '';
  if not HaveCfg then
    Exit;
  for I := 0 to GetArrayLength(Cfg) - 1 do begin
    L := Trim(Cfg[I]);
    if Pos('"' + Key + '":', L) = 1 then begin
      Result := Trim(Copy(L, Length(Key) + 4, MaxInt));
      if (Length(Result) > 0) and (Result[Length(Result)] = ',') then
        Result := Copy(Result, 1, Length(Result) - 1);
      Exit;
    end;
  end;
end;

function CfgBool(const Key: String; Default: Boolean): Boolean;
var
  V: String;
begin
  V := CfgRaw(Key);
  if V = 'true' then
    Result := True
  else if V = 'false' then
    Result := False
  else
    Result := Default;
end;

function CfgStr(const Key, Default: String): String;
var
  V: String;
begin
  V := CfgRaw(Key);
  if (Length(V) >= 2) and (V[1] = '"') and (V[Length(V)] = '"') then begin
    V := Copy(V, 2, Length(V) - 2);
    StringChangeEx(V, '\\', #1, True);
    StringChangeEx(V, '\"', '"', True);
    StringChangeEx(V, #1, '\', True);
    Result := V;
  end else
    Result := Default;
end;

// ---------- запись ответов ----------
function JsonStr(const S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '\', '\\', True);
  StringChangeEx(Result, '"', '\"', True);
  Result := '"' + Result + '"';
end;

function JsonBool(B: Boolean): String;
begin
  if B then
    Result := 'true'
  else
    Result := 'false';
end;

procedure WriteAnswers();
var
  A: TArrayOfString;
  Fmt: String;
  Cd: Integer;
begin
  if OptPage.Values[OPT_JPG] then Fmt := 'jpg' else Fmt := 'png';
  if not OptPage.Values[OPT_COUNT] then
    Cd := 0
  else if PrevCountdown > 0 then
    Cd := PrevCountdown
  else
    Cd := 3;
  SetArrayLength(A, 13);
  A[0] := '{';
  A[1] := '  "shot_dir": ' + JsonStr(DirPage.Values[0]) + ',';
  A[2] := '  "video_dir": ' + JsonStr(DirPage.Values[1]) + ',';
  A[3] := '  "open_editor": ' + JsonBool(OptPage.Values[OPT_EDITOR]) + ',';
  A[4] := '  "save_on_copy": ' + JsonBool(OptPage.Values[OPT_SAVE]) + ',';
  A[5] := '  "shot_format": "' + Fmt + '",';
  A[6] := '  "system_audio": ' + JsonBool(OptPage.Values[OPT_SYS]) + ',';
  A[7] := '  "mic": ' + JsonBool(OptPage.Values[OPT_MIC]) + ',';
  A[8] := '  "countdown": ' + IntToStr(Cd) + ',';
  A[9] := '  "prtscn": ' + JsonBool(WizardIsTaskSelected('prtscn')) + ',';
  A[10] := '  "yandex_off": ' + JsonBool(WizardIsTaskSelected('yandexoff'));
  A[11] := '}';
  A[12] := '';
  ForceDirectories(ExpandConstant('{userappdata}\Skrin'));
  SaveStringsToUTF8FileWithoutBOM(ExpandConstant('{userappdata}\Skrin\setup.json'), A, False);
end;

// ---------- страницы с вопросами ----------
procedure InitializeWizard();
var
  Desk: String;
begin
  HaveCfg := LoadStringsFromFile(ExpandConstant('{userappdata}\Skrin\config.json'), Cfg);
  PrevCountdown := StrToIntDef(CfgRaw('countdown'), 3);
  Desk := ExpandConstant('{userdesktop}\Скриншоты');

  DirPage := CreateInputDirPage(wpSelectDir, 'Куда сохранять',
    'Папки для скриншотов и видео',
    'Скриншоты (по Ctrl+C) и видео будут сохраняться сюда. Если папки нет, Скрин её создаст.',
    False, '');
  DirPage.Add('Скриншоты:');
  DirPage.Add('Видео:');
  DirPage.Values[0] := CfgStr('shot_dir', Desk);
  DirPage.Values[1] := CfgStr('video_dir', DirPage.Values[0]);

  OptPage := CreateInputOptionPage(DirPage.ID, 'Скриншоты и видео',
    'Как работать со снимками и записью экрана',
    'Отметьте, что нужно. Потом всё можно поменять в настройках (меню значка Скрина рядом с часами).',
    False, False);
  OptPage.Add('Выделил область — сразу открывать её в окне редактора (иначе рисовать поверх экрана, ' +
    'а редактор — кнопкой или клавишей O)');
  OptPage.Add('По Ctrl+C не только копировать в буфер обмена, но и сохранять файл в папку');
  OptPage.Add('Сохранять скриншоты в JPG (файлы меньше), а не в PNG');
  OptPage.Add('Записывать в видео звук компьютера');
  OptPage.Add('Записывать в видео микрофон');
  OptPage.Add('Отсчёт 3-2-1 перед записью видео');
  OptPage.Values[OPT_EDITOR] := CfgBool('open_editor', True);
  OptPage.Values[OPT_SAVE] := CfgBool('save_on_copy', True);
  OptPage.Values[OPT_JPG] := CfgRaw('shot_format') = '"jpg"';
  OptPage.Values[OPT_SYS] := CfgBool('system_audio', True);
  OptPage.Values[OPT_MIC] := CfgBool('mic', True);
  OptPage.Values[OPT_COUNT] := PrevCountdown <> 0;
end;

// тихое обновление из программы: страницы не проверять (папка на вынутой флешке не должна срывать обновление)
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := WizardSilent and ((PageID = DirPage.ID) or (PageID = OptPage.ID));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  // до копирования файлов, чтобы ответы точно были на месте, когда Скрин запустится.
  // Тихое обновление из программы вопросов не показывает — тогда настройки не трогаем (кроме первой установки).
  if (CurStep = ssInstall) and ((not WizardSilent) or (not HaveCfg)) then
    WriteAnswers();
end;

// перед установкой поверх старой версии — закрыть запущенный «Скрин»
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  R: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM Skrin.exe', '', SW_HIDE, ewWaitUntilTerminated, R);
  Sleep(500);
  Result := '';
end;
