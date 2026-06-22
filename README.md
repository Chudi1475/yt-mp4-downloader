# YouTube to MP4 Downloader

Fast desktop app to grab YouTube videos as MP4, up to **4K (2160p)**. Built on
yt-dlp + ffmpeg with multi-connection downloads so it pulls files as fast as your
connection allows.

![quality](https://img.shields.io/badge/quality-up%20to%204K-ff3b30) ![python](https://img.shields.io/badge/python-3.9%2B-blue)

## Features

- Paste a YouTube link, get an MP4
- Quality presets: Best / 4K / 2K / 1080p / 720p, or extract MP3 audio
- **Fast:** parallel fragment downloads (1-32 connections), plus optional aria2c
  turbo mode (16 connections per stream)
- Auto-merges separate 4K video + audio streams into one MP4
- Falls back to a bundled ffmpeg if you don't have one installed
- Live progress bar with speed + ETA
- Playlist support
- Clean dark GUI

## Quick start (Windows)

Double-click **`run.bat`** — it installs everything and launches the app.

Or do it manually:

```bash
pip install -r requirements.txt
python app.py
```

## Get the fastest speeds (optional)

The app is already fast, but installing **aria2c** unlocks turbo mode
(multi-connection downloads that beat YouTube's per-connection limits):

```bash
winget install aria2.aria2
```

Restart the app and tick **Turbo mode**.

## ffmpeg

Needed to merge 4K streams and make MP3s. If you don't have it, the app uses a
bundled copy automatically. For the best results install the full build:

```bash
winget install Gyan.FFmpeg
```

## Build a standalone .exe (one-click app, no Python needed)

Double-click **`build_exe.bat`**, or run:

```bash
python -m PyInstaller --noconfirm --onefile --windowed --name "YT MP4 Downloader" \
  --icon icon.ico --collect-all customtkinter --collect-all yt_dlp app.py
```

The `.exe` lands in `dist/`. Right-click it -> Send to -> Desktop to get a
one-click launcher (no terminal).

## Notes

Only download videos you have the rights to, and respect YouTube's Terms of
Service. 4K/2K downloads use VP9 or AV1 video inside an MP4 container (YouTube
doesn't serve H.264 above 1080p) — these play fine in VLC, modern browsers, and
Windows 11.
