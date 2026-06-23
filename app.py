"""Native desktop shell (pywebview + Edge WebView2) for the YT -> MP4 engine.

The UI lives in web/index.html and talks to this Api over the JS bridge; the
download work stays in downloader.py (yt-dlp)."""
import os
import sys
import threading

import webview

from downloader import (DownloadCancelled, Downloader, QUALITY_FORMATS,
                        find_ffmpeg, has_aria2c)


def resource_path(rel):
    """Path that works both in dev and inside a PyInstaller onefile bundle."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


# Where downloads land by default.
DEFAULT_DIR = r"C:\Users\Chudi\Desktop\Desktop#2\YoutubeDownloads"


def ensure_default_dir():
    try:
        os.makedirs(DEFAULT_DIR, exist_ok=True)
        return DEFAULT_DIR
    except Exception:
        return os.path.join(os.path.expanduser("~"), "Downloads")


class Api:
    def __init__(self):
        self._window = None
        self._dl = None
        self._thread = None
        self.downloading = False
        # accurate-progress state (spans both video + audio streams)
        self._grand_total = None
        self._completed = 0
        self._counted = set()
        self._trim = False

    def set_window(self, w):
        self._window = w

    def _js(self, fn, *args):
        import json
        payload = ",".join(json.dumps(a) for a in args)
        try:
            self._window.evaluate_js(f"window.{fn} && window.{fn}({payload})")
        except Exception:
            pass

    # ------------------------------------------------------------- environment
    def get_env(self):
        return {
            "ffmpeg": bool(find_ffmpeg()),
            "aria2c": has_aria2c(),
            "qualities": list(QUALITY_FORMATS.keys()),
            "default_dir": ensure_default_dir(),
        }

    def get_clipboard(self):
        try:
            import tkinter as tk
            r = tk.Tk()
            r.withdraw()
            r.update()
            val = r.clipboard_get()
            r.destroy()
            return val
        except Exception:
            return ""

    def choose_folder(self):
        res = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if res:
            return res[0] if isinstance(res, (list, tuple)) else res
        return None

    def open_folder(self, path):
        try:
            if path and os.path.isdir(path):
                os.startfile(path)
                return True
        except Exception:
            pass
        return False

    def open_result(self, path):
        """Open the finished file in the default player."""
        try:
            if path and os.path.isfile(path):
                os.startfile(path)
                return True
        except Exception:
            pass
        fallback = os.path.dirname(path) if path else DEFAULT_DIR
        return self.open_folder(fallback)

    def reveal(self, path):
        """Open the containing folder with the file highlighted."""
        try:
            if path and os.path.exists(path):
                import subprocess
                subprocess.Popen(["explorer", "/select,",
                                  os.path.normpath(path)])
                return True
        except Exception:
            pass
        return self.open_folder(os.path.dirname(path) if path else "")

    @staticmethod
    def _parse_time(s):
        """'1:23' / '1:02:03' / '83' / '83.5' -> seconds (float), or None."""
        s = (s or "").strip()
        if not s:
            return None
        try:
            if ":" in s:
                sec = 0.0
                for part in s.split(":"):
                    sec = sec * 60 + float(part or 0)
                return sec
            return float(s)
        except Exception:
            return None

    def minimize(self):
        if self._window:
            self._window.minimize()

    def close(self):
        if self._window:
            self._window.destroy()

    def fetch_info(self, url):
        """Cheap metadata probe for the preview card (no download)."""
        url = (url or "").strip()
        if not url:
            return None
        try:
            import yt_dlp
            opts = {"quiet": True, "no_warnings": True, "skip_download": True,
                    "noplaylist": True, "extract_flat": False}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if info.get("entries"):
                info = info["entries"][0]
            heights = sorted({f.get("height") for f in info.get("formats", [])
                              if f.get("height")})
            return {
                "title": info.get("title"),
                "channel": info.get("uploader") or info.get("channel"),
                "duration": info.get("duration"),
                "thumbnail": info.get("thumbnail"),
                "max_height": max(heights) if heights else None,
            }
        except Exception as e:
            return {"error": str(e)}

    # --------------------------------------------------------------- download
    def cancel(self):
        if self._dl:
            self._dl.cancel()

    def start_download(self, opts):
        # Only block if a download is GENUINELY still running. If the flag is
        # stale (previous run finished), fall through so the next one starts now.
        if self.downloading and self._thread and self._thread.is_alive():
            return
        self.downloading = False
        url = (opts.get("url") or "").strip()
        if not url:
            self._js("onError", "Enter a YouTube URL first.")
            return
        out_dir = (opts.get("folder") or ensure_default_dir()).strip()
        quality = opts.get("quality") or "Best available"
        use_aria = bool(opts.get("turbo"))
        conc = int(opts.get("connections") or 16)
        playlist = bool(opts.get("playlist"))

        start_sec = end_sec = None
        if opts.get("trim"):
            start_sec = self._parse_time(opts.get("trim_start"))
            end_sec = self._parse_time(opts.get("trim_end"))
            if start_sec is None and end_sec is None:
                start_sec = None  # nothing valid -> ignore trim
            elif start_sec is None:
                start_sec = 0.0
        self._trim = start_sec is not None or end_sec is not None

        # reset accurate-progress accumulators
        self._grand_total = None
        self._completed = 0
        self._counted = set()

        self.downloading = True
        self._dl = Downloader(progress_cb=self._on_progress, log_cb=self._on_log,
                              pp_cb=self._on_pp)
        self._thread = threading.Thread(
            target=self._run,
            args=(url, out_dir, quality, use_aria, conc, playlist,
                  start_sec, end_sec),
            daemon=True)
        self._thread.start()

    def _run(self, url, out_dir, quality, use_aria, conc, playlist,
             start_sec, end_sec):
        try:
            self._dl.download(url, out_dir, quality, use_aria, conc, playlist,
                              start_sec, end_sec)
            self._js("onDone", self._dl.final_path or "")
        except DownloadCancelled:
            self._js("onCancelled")
        except Exception as e:  # noqa: BLE001 - surface any error to the UI
            self._js("onError", str(e))
        finally:
            self.downloading = False

    def _overall_percent(self, d):
        """A single 0-99 figure that spans the whole job (video + audio),
        instead of yt-dlp's per-stream percent that resets mid-download.
        Capped at 99; 100 is reserved for a fully finished, openable file."""
        info = d.get("info_dict") or {}
        status = d.get("status")
        cur_total = d.get("total_bytes") or d.get("total_bytes_estimate")
        done = d.get("downloaded_bytes", 0) or 0

        if not self._trim and self._grand_total is None:
            total, ok = 0, True
            reqs = info.get("requested_formats")
            if reqs:
                for f in reqs:
                    sz = f.get("filesize") or f.get("filesize_approx")
                    if sz:
                        total += sz
                    else:
                        ok = False
            else:
                sz = info.get("filesize") or info.get("filesize_approx")
                total, ok = (sz, True) if sz else (0, False)
            if ok and total > 0:
                self._grand_total = total

        if status == "finished":
            fn = d.get("filename")
            if fn and fn not in self._counted:
                self._counted.add(fn)
                self._completed += (cur_total or done or 0)

        if not self._trim and self._grand_total:
            frac = (self._completed + (0 if status == "finished" else done)) \
                / self._grand_total
        elif cur_total:
            frac = done / cur_total
        else:
            return None
        return max(0.0, min(99.0, round(frac * 100, 1)))

    def _on_progress(self, d):
        info = d.get("info_dict") or {}
        self._js("onProgress", {
            "status": d.get("status"),
            "title": info.get("title"),
            "downloaded": d.get("downloaded_bytes", 0),
            "total": d.get("total_bytes") or d.get("total_bytes_estimate"),
            "speed": d.get("speed"),
            "eta": d.get("eta"),
            "percent": self._overall_percent(d),
        })

    def _on_log(self, msg):
        self._js("onLog", msg)

    def _on_pp(self, name, status):
        # The merge / audio-extract step has no byte progress; tell the UI to
        # show an active "finishing" animation instead of a frozen 99%.
        if status == "started" and name in ("Merger", "FFmpegExtractAudio",
                                            "FFmpegVideoConvertor"):
            self._js("onPhase", "finishing")


def main():
    api = Api()
    window = webview.create_window(
        "YT MP4 Downloader",
        url=resource_path(os.path.join("web", "index.html")),
        js_api=api,
        width=940, height=860, min_size=(840, 760),
        frameless=True, easy_drag=False, resizable=True,
        background_color="#eef1f8",
    )
    api.set_window(window)

    if os.environ.get("YTDL_SELFTEST"):
        def _selfclose():
            import time
            import tempfile
            time.sleep(5)
            out = os.path.join(tempfile.gettempdir(), "ytdl_selftest.txt")
            try:
                res = window.evaluate_js(
                    "(document.getElementById('downloadBtn')?'btn':'nobtn')+'|'"
                    "+document.querySelectorAll('.chip').length+'|'"
                    "+(document.getElementById('trim')?'trim':'notrim')+'|'"
                    "+(document.getElementById('openFileBtn')?'open':'noopen')+'|'"
                    "+getComputedStyle(document.getElementById('downloadBtn')).opacity+'|'"
                    "+document.getElementById('folderPath').textContent+'|'"
                    "+'card='+getComputedStyle(document.getElementById('progressWrap')).display+'|'"
                    "+'accent='+getComputedStyle(document.documentElement).getPropertyValue('--a1').trim()+'|'"
                    "+(window.__lastErr||'noerr')")
                with open(out, "w", encoding="utf-8") as f:
                    f.write(str(res))
            except Exception as e:
                with open(out, "w", encoding="utf-8") as f:
                    f.write("ERR:" + str(e))
            try:
                window.destroy()
            except Exception:
                pass
        webview.start(_selfclose, gui="edgechromium")
    else:
        webview.start(gui="edgechromium")


if __name__ == "__main__":
    main()
