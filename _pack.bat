@echo off
chcp 65001 >nul
rem 打包 Reality Compiler v3.0 xinshengji
for %%I in ("%~dp0.") do set "SRC=%%~fI"
set "TMP=%SRC%\.pack_tmp"
set "DIST=%SRC%\dist"
set "OUT=%DIST%\reality-compiler-v3.0 xinshengji.zip"

if not exist "%DIST%" mkdir "%DIST%"

if exist "%OUT%" del /q "%OUT%"
if exist "%TMP%" rmdir /s /q "%TMP%"

rem 复制（排除缓存/日志/运行时数据/临时文件）
robocopy "%SRC%" "%TMP%" /E /XD .git __pycache__ logs .run data .streamlit .venv .pack_tmp dist .pytest_cache .mypy_cache .ruff_cache /XF *.pyc *.db *.db-shm *.db-wal *.sqlite *.sqlite3 _srv.log _srv2.log _srv3.log _srv4.log _srv5.log _srv6.log _srv.err _visual_* _app.txt _diag3.txt _mem2.txt >nul
if errorlevel 8 goto :fail

rem 压缩
powershell -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%TMP%\*' -DestinationPath '%OUT%' -Force"
if errorlevel 1 goto :fail

if exist "%TMP%" rmdir /s /q "%TMP%"

echo ZIP DONE
exit /b 0

:fail
echo ZIP FAILED
if exist "%TMP%" rmdir /s /q "%TMP%"
exit /b 1
