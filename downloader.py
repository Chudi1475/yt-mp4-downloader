"""Download engine: thin wrapper around yt-dlp tuned for speed + MP4 output."""
import os
import shutil

import yt_dlp


class DownloadCancelled(Exception):
    """Raised from a hook to abort an in-flight download."""


# Quality preset -> yt-dlp format selector.
# 4K/2K on YouTube is VP9/AV1 (no H.264 above 1080p), merged into an MP4 container.
QUALITY_FORMATS = {
    "Best available": "bestvideo*+bestaudio/best",
    "4K (2160p)": "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best",
    "1440p (2K)": "bestvideo[height<=1440]+bestaudio/best[height<=1440]/best",
    "1080p (Full HD)": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
    "720p (HD)": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
    "Audio only (MP3)": "bestaudio/best",
}

AUDIO_ONLY = "Audio only (MP3)"


def find_ffmpeg():
    """Full path to ffmpeg. Prefer the system binary, fall back to a bundled one."""
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def find_aria2c():
    """Full path to aria2c, or None. Falls back to the winget install location
    since a fresh winget install isn't on PATH until the shell restarts."""
    found = shutil.which("aria2c")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    candidate = os.path.join(local, "Microsoft", "WinGet", "Links", "aria2c.exe")
    return candidate if os.path.isfile(candidate) else None


def has_aria2c():
    return find_aria2c() is not None


class Downloader:
    def __init__(self, progress_cb=None, log_cb=None):
        self.progress_cb = progress_cb
        self.log_cb = log_cb
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _log(self, msg):
        if self.log_cb:
            self.log_cb(msg)

    def _progress_hook(self, d):
        if self._cancel:
            raise DownloadCancelled()
        if self.progress_cb:
            self.progress_cb(d)

    def _pp_hook(self, d):
        if self._cancel:
            raise DownloadCancelled()
        status, name = d.get("status"), d.get("postprocessor")
        if status == "started":
            self._log(f"Processing ({name})...")
        elif status == "finished":
            self._log(f"Finished processing ({name}).")

    def build_opts(self, out_dir, quality, ffmpeg_loc, use_aria2c,
                   concurrency, download_playlist):
        fmt = QUALITY_FORMATS.get(quality, QUALITY_FORMATS["Best available"])

        opts = {
            "outtmpl": os.path.join(out_dir, "%(title)s [%(id)s].%(ext)s"),
            "format": fmt,
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._pp_hook],
            "noprogress": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": not download_playlist,
            "windowsfilenames": True,
            "trim_file_name": 200,
            "retries": 10,
            "fragment_retries": 10,
            "concurrent_fragment_downloads": max(1, int(concurrency)),
            "continuedl": True,
            "overwrites": False,
        }

        if ffmpeg_loc:
            opts["ffmpeg_location"] = ffmpeg_loc

        if quality == AUDIO_ONLY:
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }]
        else:
            # Always land on a single .mp4 (yt-dlp falls back to .mkv only if a
            # codec genuinely can't go in MP4).
            opts["merge_output_format"] = "mp4"

        aria_path = find_aria2c() if use_aria2c else None
        if aria_path:
            opts["external_downloader"] = aria_path
            opts["external_downloader_args"] = {
                "aria2c": ["-x", "16", "-s", "16", "-k", "1M",
                           "--console-log-level=warn", "--summary-interval=0"]
            }
            self._log("Turbo mode on: aria2c, 16 connections per stream.")

        return opts

    def download(self, url, out_dir, quality="Best available", use_aria2c=False,
                 concurrency=16, download_playlist=False):
        self._cancel = False
        os.makedirs(out_dir, exist_ok=True)

        ffmpeg_loc = find_ffmpeg()
        if not ffmpeg_loc:
            self._log("WARNING: ffmpeg not found. 4K merging and MP3 may fail. "
                      "Install it with: winget install Gyan.FFmpeg")

        opts = self.build_opts(out_dir, quality, ffmpeg_loc, use_aria2c,
                               concurrency, download_playlist)
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
