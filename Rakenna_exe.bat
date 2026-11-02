@echo off
rem Rakentaa Opintolainalaskuri.exe:n ja asentaa sen pikakuvakkeineen.
rem Aja tama aina, kun opintolainalaskuri.py muuttuu. Vaatii: python -m pip install --user pyinstaller
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --windowed --name Opintolainalaskuri ^
  --icon kuvake\kuvake.ico --add-data "kuvake;kuvake" --version-file version_info.txt ^
  --exclude-module numpy opintolainalaskuri.py || goto :virhe
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0asenna.ps1" || goto :virhe
echo.
echo Valmis: Opintolainalaskuri on tyopoydalla ja Kaynnista-valikossa.
exit /b 0

:virhe
echo.
echo Rakennus epaonnistui - katso virheilmoitus ylta.
pause
exit /b 1