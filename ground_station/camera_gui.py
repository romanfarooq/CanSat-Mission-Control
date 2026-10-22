"""Camera tab; sensor connection and camera connection have separate lifetimes."""

import time
import queue
import tkinter as tk

from PIL import Image, ImageTk
from datetime import datetime, timezone

from camera_reader import CameraReader


class CameraPanel:
    """Display network frames and save their original JPEG bytes."""

    def __init__(self, app, notebook, bg, text, muted, accent):
        self.app = app
        self.reader = None
        self.frame = None
        self.photo = None
        self.closing = False
        self.bg, self.text, self.muted, self.accent = bg, text, muted, accent
        self.box = tk.Frame(notebook, bg=bg, padx=10, pady=8)
        notebook.add(self.box, text="Camera")

        controls = tk.Frame(self.box, bg=bg)
        controls.pack(fill="x")
        app.label(controls, "JPEG URL", 9, muted).pack(side="left", padx=(0, 8))
        self.url = tk.Entry(
            controls,
            bg=bg,
            fg=text,
            insertbackground=accent,
            font=(app.font_family, -13),
            width=36,
        )
        self.url.insert(0, "http://192.168.4.1/capture")
        self.url.pack(side="left", fill="x", expand=True)
        self.toggle = app.button(controls, "Start camera", self.connect)
        self.toggle.pack(side="left", padx=8)
        self.save = app.button(controls, "Save photo", self.save_photo)
        self.save.config(state="disabled")
        self.save.pack(side="left")

        self.preview = tk.Canvas(
            self.box, bg="#030813", height=80, width=600, highlightthickness=0
        )
        self.preview.pack(fill="both", expand=True, pady=(6, 3))
        self.status = app.label(
            self.box,
            "CAMERA OFFLINE / camera demo images are never generated",
            9,
            muted,
            anchor="w",
        )
        self.status.pack(fill="x")
        self.preview.bind("<Configure>", lambda event: self.draw())
        self.poll()

    def connect(self):
        if self.reader:
            self.reader.stop()
            self.toggle.config(state="disabled")
            self.status.config(text="Stopping camera…")
            return
        try:
            self.reader = CameraReader(self.url.get())
        except ValueError as exc:
            self.status.config(text=str(exc))
            return
        self.frame = None
        self.draw()
        self.save.config(state="disabled")
        self.reader.start()
        self.toggle.config(text="Stop camera")
        self.url.config(state="disabled")
        self.status.config(text="CAMERA / connecting…")

    def draw(self):
        """Scale the preview to the canvas without changing the saved image."""
        c = self.preview
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if self.frame is None:
            c.create_text(
                w / 2,
                h / 2,
                text="NO CAMERA IMAGE / connect the camera Wi-Fi and start preview",
                fill=self.muted,
                font=(self.app.font_family, -13),
            )
            return
        image = self.frame[1].copy()
        image.thumbnail((max(w - 8, 1), max(h - 8, 1)), Image.Resampling.LANCZOS)
        # Tk does not keep a Python reference; retain it while the canvas uses it.
        self.photo = ImageTk.PhotoImage(image, master=self.preview)
        c.create_image(w / 2, h / 2, image=self.photo)

    def save_photo(self):
        if self.frame is None:
            return
        try:
            directory = self.app.log_dir / "photos"
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
            path = directory / f"camera_{stamp}.jpg"
            with path.open("xb") as handle:
                handle.write(self.frame[0])
            self.status.config(text=f"SAVED / {path}")
        except OSError as exc:
            self.status.config(text=f"Photo save error / {exc}")

    def poll(self):
        """Move worker results onto widgets from Tk's own event loop."""
        if self.closing:
            return
        if self.reader:
            try:
                self.frame = self.reader.frames.get_nowait()
                self.draw()
                self.save.config(state="normal")
                self.status.config(
                    text=f"CAMERA LIVE / {self.reader.count} frames · {len(self.frame[0]):,} bytes · JPEG over Wi-Fi"
                )
            except queue.Empty:
                pass

            if self.reader.error:
                self.status.config(
                    text=f"CAMERA OFFLINE / {self.reader.error} · last image retained"
                )
            elif (
                self.reader.last_success
                and time.monotonic() - self.reader.last_success > 3
            ):
                self.status.config(text="CAMERA STALE / no new frame for three seconds")
            if not self.reader.thread.is_alive():
                self.reader = None
                self.toggle.config(text="Start camera", state="normal")
                self.url.config(state="normal")
                self.status.config(text="CAMERA STOPPED / last image retained")
        self.app.root.after(50, self.poll)

    def shutdown(self):
        self.closing = True
        if self.reader:
            self.reader.stop()

    @property
    def alive(self):
        return bool(self.reader and self.reader.thread.is_alive())
