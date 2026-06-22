"""Modern desktop GUI for downloading YouTube videos as MP4 (up to 4K)."""
import os
import queue
import threading

from tkinter import filedialog

import customtkinter as ctk

from downloader import (AUDIO_ONLY, QUALITY_FORMATS, DownloadCancelled,
                        Downloader, find_ffmpeg, has_aria2c)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ACCENT = "#ff3b30"          # youtube-ish red accent
ACCENT_HOVER = "#d32f2f"
PAD = 14


def human_bytes(n):
    if not n:
        return "0 B"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def human_time(s):
    if s is None:
        return "--:--"
    s = int(s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("YouTube to MP4 Downloader")
        self.geometry("760x740")
        self.minsize(680, 700)

        self.msg_queue = queue.Queue()
        self.downloader = None
        self.worker = None
        self.downloading = False
        self.indeterminate = False

        self.grid_columnconfigure(0, weight=1)
        self._build_ui()
        self.after(100, self._poll_queue)

    # ---------------------------------------------------------------- UI build
    def _build_ui(self):
        row = 0

        header = ctk.CTkLabel(
            self, text="  YouTube  ->  MP4",
            font=ctk.CTkFont(size=26, weight="bold"))
        header.grid(row=row, column=0, sticky="w", padx=PAD, pady=(PAD, 0))
        row += 1
        ctk.CTkLabel(
            self, text="Download videos in up to 4K, as fast as your line allows.",
            text_color="gray70").grid(row=row, column=0, sticky="w",
                                      padx=PAD, pady=(0, PAD))
        row += 1

        # ---- URL ----
        url_frame = ctk.CTkFrame(self)
        url_frame.grid(row=row, column=0, sticky="ew", padx=PAD, pady=6)
        url_frame.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(
            url_frame, placeholder_text="Paste a YouTube link here...",
            height=42, font=ctk.CTkFont(size=14))
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(12, 6), pady=12)
        ctk.CTkButton(url_frame, text="Paste", width=80, height=42,
                      command=self._paste).grid(row=0, column=1, padx=(0, 12), pady=12)
        row += 1

        # ---- options ----
        opt = ctk.CTkFrame(self)
        opt.grid(row=row, column=0, sticky="ew", padx=PAD, pady=6)
        opt.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(opt, text="Quality").grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 0))
        self.quality = ctk.CTkOptionMenu(opt, values=list(QUALITY_FORMATS.keys()))
        self.quality.set("4K (2160p)")
        self.quality.grid(row=1, column=0, sticky="w", padx=12, pady=(2, 6))
        ctk.CTkLabel(opt, text="4K/2K use VP9/AV1 inside MP4 (plays in VLC, browsers, Win11).",
                     text_color="gray60", font=ctk.CTkFont(size=11)).grid(
            row=2, column=0, columnspan=3, sticky="w", padx=12)

        # output folder
        ctk.CTkLabel(opt, text="Save to").grid(
            row=3, column=0, sticky="w", padx=12, pady=(10, 0))
        self.folder_var = ctk.StringVar(
            value=os.path.join(os.path.expanduser("~"), "Downloads"))
        self.folder_entry = ctk.CTkEntry(opt, textvariable=self.folder_var)
        self.folder_entry.grid(row=4, column=0, columnspan=2, sticky="ew",
                               padx=12, pady=(2, 12))
        ctk.CTkButton(opt, text="Browse", width=90, command=self._browse).grid(
            row=4, column=2, sticky="e", padx=(0, 12), pady=(2, 12))

        # speed slider
        ctk.CTkLabel(opt, text="Parallel connections (speed)").grid(
            row=5, column=0, sticky="w", padx=12)
        self.conc_val = ctk.CTkLabel(opt, text="16", width=30)
        self.conc_val.grid(row=5, column=2, sticky="e", padx=(0, 12))
        self.conc = ctk.CTkSlider(opt, from_=1, to=32, number_of_steps=31,
                                  command=self._on_conc)
        self.conc.set(16)
        self.conc.grid(row=6, column=0, columnspan=3, sticky="ew",
                       padx=12, pady=(2, 12))

        # checkboxes
        self.aria_var = ctk.BooleanVar(value=has_aria2c())
        aria_text = ("Turbo mode (aria2c, 16 connections)" if has_aria2c()
                     else "Turbo mode  -  install aria2c to enable")
        self.aria_cb = ctk.CTkCheckBox(opt, text=aria_text, variable=self.aria_var)
        if not has_aria2c():
            self.aria_cb.configure(state="disabled")
        self.aria_cb.grid(row=7, column=0, columnspan=3, sticky="w",
                          padx=12, pady=(0, 6))

        self.playlist_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(opt, text="Download whole playlist (if the link is one)",
                        variable=self.playlist_var).grid(
            row=8, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 12))
        row += 1

        # ---- action buttons ----
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=row, column=0, sticky="ew", padx=PAD, pady=6)
        actions.grid_columnconfigure(0, weight=1)
        self.download_btn = ctk.CTkButton(
            actions, text="Download", height=48, fg_color=ACCENT,
            hover_color=ACCENT_HOVER, font=ctk.CTkFont(size=16, weight="bold"),
            command=self._start)
        self.download_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.cancel_btn = ctk.CTkButton(actions, text="Cancel", width=110, height=48,
                                        fg_color="gray30", hover_color="gray25",
                                        command=self._cancel, state="disabled")
        self.cancel_btn.grid(row=0, column=1, padx=(0, 6))
        ctk.CTkButton(actions, text="Open folder", width=120, height=48,
                      fg_color="gray30", hover_color="gray25",
                      command=self._open_folder).grid(row=0, column=2)
        row += 1

        # ---- progress ----
        self.now_label = ctk.CTkLabel(self, text="Ready.", anchor="w",
                                      font=ctk.CTkFont(size=13, weight="bold"))
        self.now_label.grid(row=row, column=0, sticky="ew", padx=PAD, pady=(10, 0))
        row += 1
        self.progress = ctk.CTkProgressBar(self, height=16)
        self.progress.set(0)
        self.progress.grid(row=row, column=0, sticky="ew", padx=PAD, pady=6)
        row += 1
        stat = ctk.CTkFrame(self, fg_color="transparent")
        stat.grid(row=row, column=0, sticky="ew", padx=PAD)
        stat.grid_columnconfigure(0, weight=1)
        self.pct_label = ctk.CTkLabel(stat, text="0%",
                                      font=ctk.CTkFont(size=13, weight="bold"))
        self.pct_label.grid(row=0, column=0, sticky="w")
        self.detail_label = ctk.CTkLabel(stat, text="", text_color="gray70")
        self.detail_label.grid(row=0, column=1, sticky="e")
        row += 1

        # ---- log ----
        self.grid_rowconfigure(row, weight=1)
        self.log = ctk.CTkTextbox(self, height=150, font=ctk.CTkFont(size=12))
        self.log.grid(row=row, column=0, sticky="nsew", padx=PAD, pady=(10, PAD))
        self.log.configure(state="disabled")

        ff = find_ffmpeg()
        self._log("ffmpeg: " + (ff if ff else "NOT FOUND - run: winget install Gyan.FFmpeg"))
        self._log("aria2c: " + ("found (turbo available)" if has_aria2c()
                                else "not installed (optional, for extra speed)"))

    # ------------------------------------------------------------- small actions
    def _on_conc(self, v):
        self.conc_val.configure(text=str(int(float(v))))

    def _paste(self):
        try:
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, self.clipboard_get().strip())
        except Exception:
            pass

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.folder_var.get() or os.getcwd())
        if d:
            self.folder_var.set(d)

    def _open_folder(self):
        path = self.folder_var.get()
        if os.path.isdir(path):
            os.startfile(path)
        else:
            self._log("Folder does not exist yet.")

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ----------------------------------------------------------------- download
    def _start(self):
        if self.downloading:
            return
        url = self.url_entry.get().strip()
        if not url:
            self._log("Enter a YouTube URL first.")
            return
        out_dir = self.folder_var.get().strip()
        if not out_dir:
            self._log("Pick a folder to save to.")
            return

        quality = self.quality.get()
        use_aria = self.aria_var.get()
        conc = int(self.conc.get())
        playlist = self.playlist_var.get()

        self._set_downloading(True)
        self.now_label.configure(text="Starting...")
        self._log(f"\n=== Downloading: {url}")
        self._log(f"Quality: {quality} | folder: {out_dir}")

        self.indeterminate = use_aria
        if use_aria:
            self.progress.configure(mode="indeterminate")
            self.progress.start()
            self.pct_label.configure(text="turbo")
        else:
            self.progress.configure(mode="determinate")
            self.progress.set(0)
            self.pct_label.configure(text="0%")

        self.downloader = Downloader(progress_cb=self._on_progress,
                                     log_cb=self._on_log)
        self.worker = threading.Thread(
            target=self._run, args=(url, out_dir, quality, use_aria, conc, playlist),
            daemon=True)
        self.worker.start()

    def _run(self, url, out_dir, quality, use_aria, conc, playlist):
        try:
            self.downloader.download(url, out_dir, quality, use_aria, conc, playlist)
            self.msg_queue.put(("done", None))
        except DownloadCancelled:
            self.msg_queue.put(("cancelled", None))
        except Exception as e:  # noqa: BLE001 - surface any yt-dlp error to the UI
            self.msg_queue.put(("error", str(e)))

    def _cancel(self):
        if self.downloader and self.downloading:
            self.downloader.cancel()
            self.now_label.configure(text="Cancelling...")

    def _on_progress(self, d):
        self.msg_queue.put(("progress", d))

    def _on_log(self, msg):
        self.msg_queue.put(("log", msg))

    def _set_downloading(self, on):
        self.downloading = on
        self.download_btn.configure(state="disabled" if on else "normal",
                                    text="Downloading..." if on else "Download")
        self.cancel_btn.configure(state="normal" if on else "disabled")

    def _finish_progress(self, ok):
        if self.indeterminate:
            self.progress.stop()
            self.progress.configure(mode="determinate")
        self.progress.set(1 if ok else 0)
        self.pct_label.configure(text="100%" if ok else "0%")
        self.indeterminate = False

    # -------------------------------------------------------------- queue pump
    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    self._update_progress(payload)
                elif kind == "done":
                    self._finish_progress(True)
                    self.now_label.configure(text="Done. Saved to your folder.")
                    self.detail_label.configure(text="")
                    self._log("Download complete.")
                    self._set_downloading(False)
                elif kind == "cancelled":
                    self._finish_progress(False)
                    self.now_label.configure(text="Cancelled.")
                    self._log("Cancelled.")
                    self._set_downloading(False)
                elif kind == "error":
                    self._finish_progress(False)
                    self.now_label.configure(text="Error - see log below.")
                    self._log("ERROR: " + payload)
                    self._set_downloading(False)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _update_progress(self, d):
        status = d.get("status")
        info = d.get("info_dict") or {}
        title = info.get("title")
        if title:
            self.now_label.configure(text=("Downloading: " + title)[:90])

        if status == "downloading":
            if self.indeterminate:
                self.detail_label.configure(text="downloading (turbo)...")
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes", 0)
            speed, eta = d.get("speed"), d.get("eta")
            if total:
                pct = done / total
                self.progress.set(pct)
                self.pct_label.configure(text=f"{pct * 100:.1f}%")
            spd = f"{human_bytes(speed)}/s" if speed else "--"
            self.detail_label.configure(
                text=f"{spd}  -  ETA {human_time(eta)}  -  "
                     f"{human_bytes(done)} / {human_bytes(total) if total else '?'}")
        elif status == "finished":
            self.now_label.configure(text="Merging video + audio into MP4...")
            self.detail_label.configure(text="processing")


if __name__ == "__main__":
    App().mainloop()
