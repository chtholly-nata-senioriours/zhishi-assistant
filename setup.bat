@echo off
chcp 65001 >nul
title 知时助手 - 安装程序

echo ========================================
echo      知时助手 Demo - 安装程序
echo ========================================
echo.

:: 检查管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 建议以管理员身份运行此安装程序。
    echo        否则可能无法创建开始菜单和开机自启。
    echo.
)

:: 目标目录
set "APP_DIR=%ProgramFiles%\知时助手"
set "START_MENU=%ProgramData%\Microsoft\Windows\Start Menu\Programs\知时助手"

echo 安装目录: %APP_DIR%
echo.

:: 检查源文件
if not exist "%~dp0知时助手.exe" (
    if exist "%~dp0dist\知时助手\知时助手.exe" (
        set "SRC_DIR=%~dp0dist\知时助手"
    ) else (
        echo [错误] 找不到 知时助手.exe！
        echo        请将本脚本放在 知时助手.exe 同级目录下运行。
        pause
        exit /b 1
    )
) else (
    set "SRC_DIR=%~dp0"
)

:: 创建目标目录
echo [1/4] 复制文件...
if not exist "%APP_DIR%" mkdir "%APP_DIR%"
xcopy /E /I /Y /Q "%SRC_DIR%" "%APP_DIR%" >nul
if %errorlevel% neq 0 (
    echo [错误] 文件复制失败！
    pause
    exit /b 1
)
echo   ✓

:: 创建桌面快捷方式
echo [2/4] 创建快捷方式...
if not exist "%PUBLIC%\Desktop\知时助手.lnk" (
    mshta "javascript:var s=CreateObject('WScript.Shell').CreateShortcut('%PUBLIC%\Desktop\知时助手.lnk');s.TargetPath='%APP_DIR%\知时助手.exe';s.WorkingDirectory='%APP_DIR%';s.IconLocation='%APP_DIR%\图标.ico';s.Description='知时助手';s.Save();close()" 2>nul
    if exist "%PUBLIC%\Desktop\知时助手.lnk" (echo   ✓) else (echo   ⚠ 创建失败，可手动创建)
) else (echo   ✓ 快捷方式已存在)

:: 创建开始菜单
echo [3/4] 创建开始菜单...
if not exist "%START_MENU%" mkdir "%START_MENU%"
mshta "javascript:var s=CreateObject('WScript.Shell').CreateShortcut('%START_MENU%\知时助手.lnk');s.TargetPath='%APP_DIR%\知时助手.exe';s.WorkingDirectory='%APP_DIR%';s.IconLocation='%APP_DIR%\图标.ico';s.Save();close()" 2>nul
mshta "javascript:var s=CreateObject('WScript.Shell').CreateShortcut('%START_MENU%\卸载知时助手.lnk');s.TargetPath='%APP_DIR%\unins.bat';s.IconLocation='shell32.dll,131';s.Save();close()" 2>nul
echo   ✓

:: 添加卸载信息到注册表
echo [4/4] 注册卸载信息...
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\知时助手" /v "DisplayName" /t REG_SZ /d "知时助手 Demo" /f >nul 2>&1
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\知时助手" /v "UninstallString" /t REG_SZ /d "\"%APP_DIR%\unins.bat\"" /f >nul 2>&1
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\知时助手" /v "DisplayIcon" /t REG_SZ /d "\"%APP_DIR%\图标.ico\"" /f >nul 2>&1
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\知时助手" /v "DisplayVersion" /t REG_SZ /d "1.7.0" /f >nul 2>&1
echo   ✓

echo.
echo ========================================
echo       安装完成！
echo ========================================
echo.
echo   📍 安装路径: %APP_DIR%
echo   🖥️ 桌面快捷方式: 已创建
echo   📋 开始菜单: 已创建
echo   ⚙️  控制面板卸载: 已注册
echo.
echo 按任意键启动知时助手...
pause >nul
start "" "%APP_DIR%\知时助手.exe"
