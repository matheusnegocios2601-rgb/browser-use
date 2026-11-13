@echo off
setlocal
cd /d "%~dp0"
title Navegador por Voz

if exist ".venv\Scripts\pythonw.exe" goto iniciar

echo ============================================================
echo  Navegador por Voz - preparo inicial (so na primeira vez)
echo.
echo  Vai instalar o Python e as bibliotecas DENTRO desta pasta
echo  (nada e instalado no sistema). Precisa de internet e leva
echo  alguns minutos. O modelo de voz (~463 MB, huggingface.co)
echo  e baixado depois, ja dentro do aplicativo.
echo ============================================================
echo.

where uv >nul 2>nul
if not errorlevel 1 goto com_uv
if not exist "%USERPROFILE%\.local\bin\uv.exe" goto baixar_uv
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
goto com_uv

:baixar_uv
echo Baixando o instalador de Python "uv" (astral.sh)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul
if errorlevel 1 goto sem_uv

:com_uv
uv venv --python 3.12 .venv
if errorlevel 1 goto falhou
uv pip install --python ".venv\Scripts\python.exe" -r requisitos.txt
if errorlevel 1 goto falhou
goto atalho

:sem_uv
echo Nao consegui instalar o "uv". Tentando com um Python ja instalado...
where py >nul 2>nul
if errorlevel 1 goto sem_python
py -3 -m venv .venv
if errorlevel 1 goto falhou
".venv\Scripts\python.exe" -m pip install -r requisitos.txt
if errorlevel 1 goto falhou
goto atalho

:sem_python
echo.
echo NAO FOI POSSIVEL PREPARAR O APLICATIVO.
echo Instale o Python 3.12 em https://www.python.org/downloads/ (marque "Add to PATH")
echo e de dois cliques neste arquivo de novo.
pause
exit /b 1

:falhou
echo.
echo O preparo falhou. Confira a internet e tente de novo. Se persistir, apague a pasta .venv.
pause
exit /b 1

:atalho
echo Criando o atalho "Navegador por Voz" na Area de Trabalho...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Navegador por Voz.lnk'); $s.TargetPath='%~dp0.venv\Scripts\pythonw.exe'; $s.Arguments='-m voznav'; $s.WorkingDirectory='%~dp0'; $s.Description='Navegador por Voz'; $s.Save()"
echo Pronto.

:iniciar
start "" ".venv\Scripts\pythonw.exe" -m voznav
exit /b 0
