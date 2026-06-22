@echo off
cd /d "%~dp0"
echo Installing build dependencies...
python -m pip install -r requirements.txt pyinstaller pillow
echo Building standalone exe...
python -m PyInstaller --noconfirm --onefile --windowed ^
  --name "YT MP4 Downloader" ^
  --icon icon.ico ^
  --collect-all customtkinter ^
  --collect-all yt_dlp ^
  app.py
echo.
echo Done. The exe is in the "dist" folder.
pause
