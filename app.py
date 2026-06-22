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


class Api:
    def __init__(self):
        self._window = None
        self._dl = None
        self.downloading = False

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
            "default_dir": os.path.join(os.path.expanduser("~"), "Downloads"),
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
        if self.downloading:
            return
        url = (opts.get("url") or "").strip()
        if not url:
            self._js("onError", "Enter a YouTube URL first.")
            return
        out_dir = (opts.get("folder")
                   or os.path.join(os.path.expanduser("~"), "Downloads")).strip()
        quality = opts.get("quality") or "Best available"
        use_aria = bool(opts.get("turbo"))
        conc = int(opts.get("connections") or 16)
        playlist = bool(opts.get("playlist"))

        self.downloading = True
        self._dl = Downloader(progress_cb=self._on_progress, log_cb=self._on_log)
        threading.Thread(
            target=self._run,
            args=(url, out_dir, quality, use_aria, conc, playlist),
            daemon=True).start()

    def _run(self, url, out_dir, quality, use_aria, conc, playlist):
        try:
            self._dl.download(url, out_dir, quality, use_aria, conc, playlist)
            self._js("onDone")
        except DownloadCancelled:
            self._js("onCancelled")
        except Exception as e:  # noqa: BLE001 - surface any error to the UI
            self._js("onError", str(e))
        finally:
            self.downloading = False

    def _on_progress(self, d):
        info = d.get("info_dict") or {}
        self._js("onProgress", {
            "status": d.get("status"),
            "title": info.get("title"),
            "downloaded": d.get("downloaded_bytes", 0),
            "total": d.get("total_bytes") or d.get("total_bytes_estimate"),
            "speed": d.get("speed"),
            "eta": d.get("eta"),
        })

    def _on_log(self, msg):
        self._js("onLog", msg)


def main():
    api = Api()
    window = webview.create_window(
        "YT MP4 Downloader",
        url=resource_path(os.path.join("web", "index.html")),
        js_api=api,
        width=940, height=860, min_size=(840, 760),
        frameless=True, easy_drag=False, resizable=True,
        background_color="#07070c",
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
                    "+(getComputedStyle(document.body).backgroundColor)")
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
