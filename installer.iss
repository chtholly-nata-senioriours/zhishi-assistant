; 知时助手 Demo 安装脚本
; 使用方法: 右键此文件 → Compile (需要安装 Inno Setup)
; 下载: https://jrsoftware.org/isdl.php

#define MyAppName "知时助手"
#define MyAppVersion "1.9.0"
#define MyAppPublisher "PetDemo"
#define MyAppURL ""
#define MyAppExeName "知时助手.exe"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=Output
OutputBaseFilename=知时助手_Setup
Compression=lzma
SolidCompression=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
PrivilegesRequired=admin
SetupIconFile=图标.ico


[Files]
Source: "dist\知时助手\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "图标.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\图标.ico"
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: "{app}\{#MyAppExeName}"; Flags: uninsdeletevalue
