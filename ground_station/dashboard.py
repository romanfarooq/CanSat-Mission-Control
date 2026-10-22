"""Tk widgets and telemetry drawings for the Mission Control window."""

import math
import tkinter as tk

from tkinter import font, ttk

from telemetry import FIELDS
from camera_gui import CameraPanel

BG = "#080e1d"
PANEL = "#111d32"
LINE = "#253650"
TEXT = "#e4edf9"
MUTED = "#8a9dbb"
CYAN = "#55e2dc"
AMBER = "#ffc879"


class Dashboard:
    """Build and refresh widgets on Tk's main thread."""

    def __init__(self, root, actions, log_dir):
        self.root = root
        self.actions = actions
        self.log_dir = log_dir

        # Use a font available on this machine; pixel sizes keep layout predictable.
        families = {name.lower(): name for name in font.families(root)}
        self.font_family = next(
            (
                families[name.lower()]
                for name in ("Segoe UI", "DejaVu Sans", "Liberation Sans", "Arial")
                if name.lower() in families
            ),
            "Helvetica",
        )

        root.title("CanSat / Mission Control")
        root.geometry("1220x860")
        root.minsize(1080, 800)
        root.configure(bg=BG)

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(
            "TCombobox",
            fieldbackground=PANEL,
            background=LINE,
            foreground=TEXT,
            arrowcolor=CYAN,
            bordercolor=LINE,
            font=(self.font_family, -13),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", PANEL)],
            foreground=[("readonly", TEXT)],
        )
        style.configure(
            "TNotebook",
            background=BG,
            borderwidth=0,
            bordercolor=LINE,
            lightcolor=LINE,
            darkcolor=LINE,
        )
        style.configure(
            "TNotebook.Tab",
            background=LINE,
            foreground=TEXT,
            padding=(14, 7),
            font=(self.font_family, -13),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", PANEL)],
            foreground=[("selected", CYAN)],
        )
        style.configure(
            "Telemetry.Treeview",
            background=PANEL,
            fieldbackground=PANEL,
            foreground=TEXT,
            rowheight=25,
            font=(self.font_family, -13),
        )
        style.configure(
            "Telemetry.Treeview.Heading",
            background=LINE,
            foreground=TEXT,
            font=(self.font_family, -13),
        )
        self.values = {}
        self.build()

    def label(self, parent, text="", size=10, color=TEXT, **kwargs):
        return tk.Label(
            parent,
            text=text,
            font=(self.font_family, -round(size * 1.3)),
            fg=color,
            bg=parent.cget("bg"),
            **kwargs,
        )

    def button(self, parent, text, command):
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=LINE,
            fg=TEXT,
            activebackground=CYAN,
            activeforeground=BG,
            relief="flat",
            padx=14,
            pady=8,
            cursor="hand2",
            font=(self.font_family, -13),
        )

    def build(self):
        """Lay out the overview, tabs and connection controls."""
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=28, pady=(22, 12))
        self.label(header, "◉  C A N S A T", 23, CYAN).pack(side="left")
        self.label(header, "MISSION CONTROL  /  TELEMETRY CONSOLE", 10, MUTED).pack(
            side="left", padx=22
        )
        self.link = self.label(header, "● STANDBY", 11, AMBER)
        self.link.pack(side="right")

        # Serial controls act on the session controller, not on the widgets.
        controls = tk.Frame(self.root, bg=PANEL, padx=14, pady=10)
        controls.pack(fill="x", padx=28)
        self.label(controls, "GROUND LINK", 9, MUTED).pack(side="left", padx=(0, 12))
        self.port = ttk.Combobox(
            controls, width=20, state="readonly", font=(self.font_family, -13)
        )
        self.port.pack(side="left")
        self.button(controls, "Refresh", self.actions.refresh_ports).pack(
            side="left", padx=8
        )
        self.connect_button = self.button(controls, "Connect", self.actions.connect)
        self.connect_button.pack(side="left")
        self.demo_button = self.button(
            controls,
            "Stop demo" if self.actions.demo else "Start demo",
            self.actions.toggle_demo,
        )
        self.demo_button.pack(side="left", padx=8)
        self.clock = self.label(controls, "T+ 00:00", 12, CYAN)
        self.clock.pack(side="right")

        stats = tk.Frame(self.root, bg=BG)
        stats.pack(fill="x", padx=28, pady=14)
        for i, (key, title, unit) in enumerate(
            [
                ("alt", "BAROMETRIC ALTITUDE", "m"),
                ("temp", "TEMPERATURE", "°C"),
                ("press", "PRESSURE", "hPa"),
                ("sat", "GPS SATELLITES", "tracked"),
            ]
        ):
            card = tk.Frame(stats, bg=PANEL, padx=18, pady=12)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            stats.columnconfigure(i, weight=1)
            self.label(card, title, 9, MUTED).pack(anchor="w")
            val = self.label(card, "—", 27, TEXT)
            val.pack(anchor="w", pady=(5, 0))
            self.values[key] = val
            self.label(card, unit, 9, CYAN).pack(anchor="w")

        # Tabs share the same incoming data and calibration state.
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=28)
        center = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(center, text="Flight overview")
        plot_box = tk.Frame(center, bg=PANEL, padx=16, pady=12)
        plot_box.pack(side="left", fill="both", expand=True)
        self.label(plot_box, "01  /  ALTITUDE TRACE", 10, MUTED).pack(anchor="w")
        self.plot = tk.Canvas(
            plot_box, bg=PANEL, width=500, height=140, highlightthickness=0
        )
        self.plot.pack(fill="both", expand=True, pady=(12, 0))
        compass_box = tk.Frame(center, bg=PANEL, padx=16, pady=12)
        compass_box.pack(side="right", fill="both", padx=(14, 0))
        self.label(compass_box, "02  /  MAGNETIC BEARING", 10, MUTED).pack(anchor="w")
        self.compass = tk.Canvas(
            compass_box, bg=PANEL, width=260, height=140, highlightthickness=0
        )
        self.compass.pack(expand=True)
        self.heading_label = self.label(
            compass_box, "—  /  planar, uncorrected", 10, CYAN
        )
        self.heading_label.pack()

        self.build_details()
        self.timing = self.label(
            self.root,
            "HW — ms  /  SW — ms  /  |B| — µT  /  RATE — Hz",
            10,
            CYAN,
            anchor="w",
        )
        self.timing.pack(fill="x", padx=28, pady=(10, 0))

        lower = tk.Frame(self.root, bg=BG)
        lower.pack(fill="x", padx=28, pady=14)
        for i, (title, fields, unit) in enumerate(
            [
                ("03  /  ACCELERATION", ("ax", "ay", "az"), "m/s²"),
                ("04  /  GYRO · BIAS ADJUSTED", ("gx", "gy", "gz"), "rad/s"),
                ("05  /  MAGNETIC FIELD", ("mx", "my", "mz"), "µT"),
            ]
        ):
            box = tk.Frame(lower, bg=PANEL, padx=16, pady=12)
            box.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 14, 0))
            lower.columnconfigure(i, weight=1)
            self.label(box, title, 9, MUTED).pack(anchor="w", pady=(0, 6))
            for axis, key in zip("XYZ", fields):
                row = tk.Frame(box, bg=PANEL)
                row.pack(fill="x")
                self.label(row, axis, 10, CYAN).pack(side="left")
                self.values[key] = self.label(row, f"— {unit}", 12)
                self.values[key].pack(side="right")

        nav = tk.Frame(self.root, bg=PANEL, padx=16, pady=10)
        nav.pack(fill="x", padx=28)
        self.gps = self.label(nav, "GPS  /  awaiting position", 10, MUTED)
        self.gps.pack(anchor="w")
        self.angles = self.label(
            nav, "BODY-AXIS INTEGRALS  /  stationary calibration: 0 / 300", 10, CYAN
        )
        self.angles.pack(side="left", pady=(8, 0))
        self.button(
            nav, "Reset angles", lambda: self.actions.model.reset_angles()
        ).pack(side="right")
        self.status = self.label(self.root, self.actions.notice, 9, MUTED, anchor="w")
        self.status.pack(fill="x", padx=28, pady=(10, 16))

    def build_details(self):
        """Add the complete raw table, gyro dials and independent camera tab."""
        details = tk.Frame(self.notebook, bg=PANEL, padx=12, pady=10)
        self.notebook.add(details, text="All telemetry")
        self.raw_table = ttk.Treeview(
            details,
            columns=("field", "value", "unit"),
            show="headings",
            style="Telemetry.Treeview",
            height=5,
        )
        for key, width in [("field", 310), ("value", 280), ("unit", 200)]:
            self.raw_table.heading(key, text=key.upper())
            self.raw_table.column(key, width=width, stretch=True)
        scrollbar = ttk.Scrollbar(
            details, orient="vertical", command=self.raw_table.yview
        )
        self.raw_table.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.raw_table.pack(fill="both", expand=True)
        names = {
            "temp": ("Temperature", "°C"),
            "alt": ("Barometric altitude", "m"),
            "press": ("Pressure · raw", "Pa"),
            "head": ("Heading · transmitted", "degrees"),
            "sat": ("GPS satellite count", "count"),
            "lat": ("Latitude", "degrees"),
            "lon": ("Longitude", "degrees"),
            "gpsAlt": ("GPS altitude", "m"),
            "HardwareTimestamp": ("Hardware timestamp", "ms since board boot"),
        }
        for key in FIELDS:
            if key not in names:
                group, unit = {
                    "a": ("Acceleration", "m/s²"),
                    "g": ("Gyro · raw", "rad/s"),
                    "m": ("Magnetic field", "µT"),
                }[key[0]]
                names[key] = (f"{group} {key[1].upper()}", unit)
            title, unit = names[key]
            self.raw_table.insert("", "end", iid=key, values=(title, "—", unit))
        for key, title, unit in [
            ("PythonTimestamp", "Software receive timestamp", "ms since connection"),
            ("mag", "Magnetic field magnitude |B|", "µT"),
            ("hz", "Update rate", "Hz · hardware intervals"),
        ]:
            self.raw_table.insert("", "end", iid=key, values=(title, "—", unit))
        gyro = tk.Frame(self.notebook, bg=PANEL, padx=12, pady=10)
        self.notebook.add(gyro, text="Gyro angles")
        self.label(
            gyro, "BODY-AXIS INTEGRALS  /  degrees · not Euler attitude", 10, MUTED
        ).pack(anchor="w")
        self.dials = tk.Canvas(
            gyro, bg=PANEL, width=700, height=140, highlightthickness=0
        )
        self.dials.pack(fill="both", expand=True)
        self.draw_dials(self.actions.model)
        self.camera = CameraPanel(self, self.notebook, PANEL, TEXT, MUTED, CYAN)

    def draw_dials(self, model):
        c = self.dials
        c.delete("all")
        w, h = max(c.winfo_width(), 300), max(c.winfo_height(), 100)
        radius = max(15, min(w / 8, (h - 65) / 2))
        cy = (h - 20) / 2
        calibrated = len(model.samples) == 300
        for i, (axis, value) in enumerate(zip("XYZ", model.angles)):
            cx = w * (i + 0.5) / 3
            c.create_oval(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                outline=LINE,
                width=2,
            )
            for degree in range(0, 360, 30):
                angle = math.radians(degree)
                c.create_line(
                    cx + (radius - 6) * math.cos(angle),
                    cy - (radius - 6) * math.sin(angle),
                    cx + radius * math.cos(angle),
                    cy - radius * math.sin(angle),
                    fill=MUTED,
                )
            if calibrated:
                angle = math.radians(value)
                c.create_line(
                    cx,
                    cy,
                    cx + (radius - 8) * math.cos(angle),
                    cy - (radius - 8) * math.sin(angle),
                    fill=CYAN,
                    width=3,
                    arrow="last",
                )
            c.create_text(
                cx,
                h - 15,
                text=(
                    f"{axis}  {value:+.1f}°" if calibrated else f"{axis}  calibrating…"
                ),
                fill=CYAN,
                font=(self.font_family, -14),
            )

    @staticmethod
    def number(value, places=2):
        return f"{value:.{places}f}" if math.isfinite(value) else "—"

    def render(self, data, model):
        """Format the latest packet without modifying its values."""
        d = data
        if not d:
            return
        magnitude = math.sqrt(sum(d[key] ** 2 for key in ("mx", "my", "mz")))
        for key in FIELDS:
            places = (
                0
                if key in ("HardwareTimestamp", "sat")
                else (6 if key in ("lat", "lon") else 3)
            )
            self.raw_table.set(key, "value", self.number(d[key], places))
        for key, value in [
            ("PythonTimestamp", d["PythonTimestamp"]),
            ("mag", magnitude),
            ("hz", model.hz),
        ]:
            self.raw_table.set(
                key, "value", self.number(value, 0 if key == "PythonTimestamp" else 2)
            )
        self.timing.config(
            text=f"HW {d['HardwareTimestamp']} ms  /  SW {d['PythonTimestamp']:.0f} ms  /  |B| {self.number(magnitude)} µT  /  RATE {model.hz:.1f} Hz"
        )
        self.draw_dials(model)

        # The summary card uses hPa; the raw table and CSV keep pressure in Pa.
        for key in ("alt", "temp", "press", "sat"):
            value = d[key] / 100 if key == "press" else d[key]
            self.values[key].config(text=self.number(value, 0 if key == "sat" else 1))

        calibrated = len(model.samples) == 300
        for key in ("ax", "ay", "az", "gx", "gy", "gz", "mx", "my", "mz"):
            value = model.corrected["xyz".index(key[1])] if key[0] == "g" else d[key]
            unit = "rad/s" if key[0] == "g" else ("m/s²" if key[0] == "a" else "µT")
            text = (
                f"{self.number(value, 3)} {unit}"
                if key[0] != "g" or calibrated
                else "calibrating…"
            )
            self.values[key].config(text=text)
        self.gps.config(
            text=f"GPS  /  LAT {self.number(d['lat'], 6)}°    LON {self.number(d['lon'], 6)}°    ALT {self.number(d['gpsAlt'])} m    |    legacy packets have no fix-age flag"
        )
        if calibrated:
            self.angles.config(
                text="BODY-AXIS INTEGRALS  /  "
                + "    ".join(
                    f"{axis} {angle:+.1f}°" for axis, angle in zip("XYZ", model.angles)
                )
            )
        else:
            self.angles.config(
                text=f"STATIONARY GYRO CALIBRATION  /  {len(model.samples)} / 300 · keep still"
            )
        c = self.compass
        c.delete("all")
        cw, ch = c.winfo_width(), c.winfo_height()
        cx, cy = cw / 2, ch / 2
        radius = max(30, min(cw, ch) / 2 - 30)
        for r in (radius, radius + 12):
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=LINE)
        for text, x, y in [
            ("N", cx, cy - radius - 23),
            ("E", cx + radius + 23, cy),
            ("S", cx, cy + radius + 23),
            ("W", cx - radius - 23, cy),
        ]:
            c.create_text(x, y, text=text, fill=MUTED, font=(self.font_family, -13))
        if math.isfinite(d["head"]):
            angle = math.radians(d["head"])
            c.create_line(
                cx,
                cy,
                cx + radius * math.sin(angle),
                cy - radius * math.cos(angle),
                fill=CYAN,
                width=3,
                arrow="last",
            )
            self.heading_label.config(
                text=f"{d['head'] % 360:05.1f}°  /  planar, uncorrected"
            )
        else:
            self.heading_label.config(text="—  /  magnetic data unavailable")
        c.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill=TEXT, outline="")

    def draw_plot(self, history):
        """Plot recent finite altitudes with equal spacing between samples."""
        c = self.plot
        c.delete("all")
        w, h = max(c.winfo_width(), 200), max(c.winfo_height(), 150)
        for i in range(5):
            y = 20 + i * (h - 50) / 4
            c.create_line(54, y, w - 10, y, fill=LINE)
        if len(history) < 2:
            c.create_text(w / 2, h / 2, text="AWAITING TELEMETRY", fill=MUTED)
            return
        vals = [v for _, v in history]
        low, high = min(vals) - 1, max(vals) + 1
        points = []
        for i, v in enumerate(vals):
            points.extend(
                (
                    54 + i * (w - 64) / (len(vals) - 1),
                    h - 30 - (v - low) * (h - 50) / (high - low),
                )
            )
        c.create_line(*points, fill=CYAN, width=2, smooth=False)
        c.create_text(25, 20, text=f"{high:.0f}", fill=MUTED)
        c.create_text(25, h - 30, text=f"{low:.0f}", fill=MUTED)
        c.create_text(
            w - 12,
            h - 10,
            anchor="e",
            text="m  /  latest 240 received samples",
            fill=MUTED,
        )

    def reset_fields(self, model):
        """Clear displayed session values while leaving the camera connected."""
        for widget in self.values.values():
            widget.config(text="—")
        self.gps.config(text="GPS  /  awaiting position")
        self.heading_label.config(text="—  /  planar, uncorrected")
        self.compass.delete("all")
        self.timing.config(text="HW — ms  /  SW — ms  /  |B| — µT  /  RATE — Hz")
        for key in self.raw_table.get_children():
            self.raw_table.set(key, "value", "—")
        self.draw_dials(model)
