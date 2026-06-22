@echo off
chcp 65001 >nul
title 卸载 小小桌宠

echo ========================================
echo     卸载 小小桌宠 Demo
echo ========================================
echo.

set "APP_DIR=%ProgramFiles%\小小桌宠"

:: 关闭进程
taskkill /f /im 小小桌宠Demo.exe 2>nul

:: 删除文件
echo 删除文件...
if exist "%APP_DIR%" (
    rmdir /s /q "%APP_DIR%" 2>nul
    echo   ✓
) else (echo   未安装)

:: 删除快捷方式
echo 删除桌面快捷方式...
if exist "%PUBLIC%\Desktop\小小桌宠.lnk" (
    del /f "%PUBLIC%\Desktop\小小桌宠.lnk" 2>nul
)
echo   ✓

:: 删除开始菜单
echo 删除开始菜单...
set "START_MENU=%ProgramData%\Microsoft\Windows\Start Menu\Programs\小小桌宠"
if exist "%START_MENU%" (
    rmdir /s /q "%START_MENU%" 2>nul
)
echo   ✓

:: 删除注册表
echo 删除注册表项...
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\小小桌宠" /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run\小小桌宠" /f >nul 2>&1
echo   ✓

echo.
echo 卸载完成！
echo.
pause
