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
MUTED = "#a7b8ce"
CYAN = "#55e2dc"
AMBER = "#ffc879"
TEXT_SCALES = {
    "Small": 0.8,
    "Medium": 0.9,
    "Auto": 1.0,
    "Large": 1.1,
    "Extra large": 1.2,
}


class Dashboard:
    """Build and refresh widgets on Tk's main thread."""

    def __init__(self, root, actions, log_dir):
        self.root = root
        self.actions = actions
        self.log_dir = log_dir
        self.fullscreen = False
        self.ui_scale = 1.0
        self.fonts = {}
        self.resize_job = None

        # Named fonts let existing widgets grow when the window gets larger.
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
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        style = self.style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(
            "TCombobox",
            fieldbackground=PANEL,
            background=LINE,
            foreground=TEXT,
            arrowcolor=CYAN,
            bordercolor=LINE,
            padding=(8, 8),
            arrowsize=18,
            font=self.ui_font(13),
        )
        root.option_add("*TCombobox*Listbox.font", self.ui_font(13))
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
            font=self.ui_font(13),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", PANEL)],
            foreground=[("selected", CYAN)],
            padding=[("selected", (14, 7)), ("!selected", (14, 7))],
        )
        style.configure(
            "Telemetry.Treeview",
            background=PANEL,
            fieldbackground=PANEL,
            foreground=TEXT,
            rowheight=25,
            font=self.ui_font(13),
        )
        style.configure(
            "Telemetry.Treeview.Heading",
            background=LINE,
            foreground=TEXT,
            font=self.ui_font(13),
        )
        self.values = {}
        self.build()
        root.bind("<F11>", self.toggle_fullscreen)
        root.bind("<Escape>", self.exit_fullscreen)
        root.bind("<Configure>", self.schedule_scale, add="+")
        root.after_idle(self.update_scale)

    def ui_font(self, pixels):
        if pixels not in self.fonts:
            self.fonts[pixels] = font.Font(
                root=self.root,
                family=self.font_family,
                size=-round(pixels * self.ui_scale),
            )
        return self.fonts[pixels]

    def schedule_scale(self, event):
        if event.widget is self.root:
            if self.resize_job is not None:
                self.root.after_cancel(self.resize_job)
            self.resize_job = self.root.after(100, self.update_scale)

    def update_scale(self, event=None):
        self.resize_job = None
        width, height = self.root.winfo_width(), self.root.winfo_height()
        # Fit the whole dashboard, including the footer, rather than scaling by width alone.
        automatic = max(1.0, min(width / 1220, height / 860, 2.5))
        preference = TEXT_SCALES[self.text_size.get()]
        scale = round(automatic * preference, 2)
        if scale != self.ui_scale:
            self.ui_scale = scale
            for pixels, named_font in self.fonts.items():
                named_font.configure(size=-max(1, round(pixels * scale)))
            self.style.configure("Telemetry.Treeview", rowheight=round(25 * scale))
            self.style.configure(
                "TNotebook.Tab", padding=(round(14 * scale), round(7 * scale))
            )
            tab_padding = (round(14 * scale), round(7 * scale))
            self.style.map(
                "TNotebook.Tab",
                padding=[("selected", tab_padding), ("!selected", tab_padding)],
            )
            self.style.configure("TCombobox", arrowsize=round(18 * scale))
            self.style.configure("TScrollbar", arrowsize=round(16 * scale))
            self.draw_dials(self.actions.model)
            self.draw_plot(self.actions.history)
            if self.actions.latest:
                self.render(self.actions.latest, self.actions.model)
            self.camera.draw()
        self.gps.configure(wraplength=max(200, width - 100))
        self.status.configure(wraplength=max(200, width - 56))
        # Keep the connection state and fullscreen control visible on narrow windows.
        header_width = (
            self.brand.winfo_reqwidth()
            + self.subtitle.winfo_reqwidth()
            + self.link.winfo_reqwidth()
            + self.fullscreen_button.winfo_reqwidth()
            + 70
        )
        if header_width > width - 56:
            self.subtitle.pack_forget()
        elif not self.subtitle.winfo_manager():
            self.subtitle.pack(side="left", padx=22)

    def toggle_fullscreen(self, event=None):
        self.set_fullscreen(not self.fullscreen)
        return "break"

    def exit_fullscreen(self, event=None):
        if self.fullscreen:
            self.set_fullscreen(False)
            return "break"

    def set_fullscreen(self, enabled):
        self.root.attributes("-fullscreen", enabled)
        self.fullscreen = enabled
        self.fullscreen_button.config(
            text="Exit fullscreen (Esc)" if enabled else "Fullscreen (F11)"
        )

    def label(self, parent, text="", size=10, color=TEXT, **kwargs):
        return tk.Label(
            parent,
            text=text,
            font=self.ui_font(round(size * 1.3)),
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
            font=self.ui_font(13),
        )

    def build(self):
        """Lay out the overview, tabs and connection controls."""
        header = tk.Frame(self.root, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 12))
        self.brand = self.label(header, "◉  C A N S A T", 23, CYAN)
        self.brand.pack(side="left")
        self.subtitle = self.label(
            header, "MISSION CONTROL  /  TELEMETRY CONSOLE", 10, MUTED
        )
        self.subtitle.pack(side="left", padx=22)
        self.fullscreen_button = self.button(
            header, "Fullscreen (F11)", self.toggle_fullscreen
        )
        self.fullscreen_button.pack(side="right")
        self.link = self.label(header, "● STANDBY", 11, AMBER)
        self.link.pack(side="right", padx=(0, 14))

        # Serial controls act on the session controller, not on the widgets.
        controls = tk.Frame(self.root, bg=PANEL, padx=14, pady=10)
        controls.grid(row=1, column=0, sticky="ew", padx=28)
        self.label(controls, "GROUND LINK", 9, MUTED).pack(side="left", padx=(0, 12))
        self.port = ttk.Combobox(
            controls, width=20, state="readonly", font=self.ui_font(13)
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
        self.clock.pack(side="right", padx=(14, 0))
        self.text_size = ttk.Combobox(
            controls,
            values=tuple(TEXT_SCALES),
            width=10,
            state="readonly",
            font=self.ui_font(13),
        )
        self.text_size.set("Auto")
        self.text_size.pack(side="right")
        self.text_size.bind("<<ComboboxSelected>>", self.update_scale)
        self.label(controls, "TEXT SIZE", 9, MUTED).pack(side="right", padx=(12, 8))

        stats = tk.Frame(self.root, bg=BG)
        stats.grid(row=2, column=0, sticky="ew", padx=28, pady=14)
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
        self.notebook.grid(row=3, column=0, sticky="nsew", padx=28)
        center = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(center, text="Flight overview")
        center.rowconfigure(0, weight=1)
        center.columnconfigure(0, weight=3, uniform="overview")
        center.columnconfigure(1, weight=1, uniform="overview")
        plot_box = tk.Frame(center, bg=PANEL, padx=16, pady=12)
        plot_box.grid(row=0, column=0, sticky="nsew")
        self.label(plot_box, "01  /  ALTITUDE TRACE", 10, MUTED).pack(anchor="w")
        self.plot = tk.Canvas(
            plot_box, bg=PANEL, width=500, height=140, highlightthickness=0
        )
        self.plot.pack(fill="both", expand=True, pady=(12, 0))
        compass_box = tk.Frame(center, bg=PANEL, padx=16, pady=12)
        compass_box.grid(row=0, column=1, sticky="nsew", padx=(14, 0))
        self.label(compass_box, "02  /  MAGNETIC BEARING", 10, MUTED).pack(anchor="w")
        self.compass = tk.Canvas(
            compass_box, bg=PANEL, width=260, height=140, highlightthickness=0
        )
        self.compass.pack(fill="both", expand=True)
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
        self.timing.grid(row=4, column=0, sticky="ew", padx=28, pady=(10, 0))

        lower = tk.Frame(self.root, bg=BG)
        lower.grid(row=5, column=0, sticky="ew", padx=28, pady=14)
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
        nav.grid(row=6, column=0, sticky="ew", padx=28)
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
        self.status.grid(row=7, column=0, sticky="ew", padx=28, pady=(10, 16))

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
        scale = self.ui_scale
        radius = max(15, min(w / 8, (h - 65 * scale) / 2))
        cy = (h - 20 * scale) / 2
        calibrated = len(model.samples) == 300
        for i, (axis, value) in enumerate(zip("XYZ", model.angles)):
            cx = w * (i + 0.5) / 3
            c.create_oval(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                outline=LINE,
                width=max(1, round(2 * self.ui_scale)),
            )
            for degree in range(0, 360, 30):
                angle = math.radians(degree)
                tick_length = (12 if degree % 90 == 0 else 6) * scale
                c.create_line(
                    cx + (radius - tick_length) * math.cos(angle),
                    cy - (radius - tick_length) * math.sin(angle),
                    cx + radius * math.cos(angle),
                    cy - radius * math.sin(angle),
                    fill=CYAN if degree == 0 else MUTED,
                    width=max(1, round((2 if degree % 90 == 0 else 1) * scale)),
                )
            if calibrated:
                self.draw_needle(c, cx, cy, radius, value)
            c.create_text(
                cx,
                h - 15 * scale,
                text=(
                    f"{axis}  {value:+.1f}°" if calibrated else f"{axis}  calibrating…"
                ),
                fill=CYAN,
                font=self.ui_font(14),
            )

    def draw_needle(self, canvas, cx, cy, radius, degrees):
        scale = self.ui_scale
        length = radius * 0.82
        head_length = min(radius * 0.24, 22 * scale)
        head_width = min(radius * 0.12, 9 * scale)
        shaft_width = min(radius * 0.05, 3 * scale)
        tail = min(radius * 0.15, 14 * scale)
        shoulder = length - head_length
        profile = (
            (-tail, -shaft_width),
            (shoulder, -shaft_width),
            (shoulder, -head_width),
            (length, 0),
            (shoulder, head_width),
            (shoulder, shaft_width),
            (-tail, shaft_width),
        )
        # Rotate one filled silhouette, keeping the arrowhead proportional at any window size.
        angle = math.radians(degrees)
        dx, dy = math.cos(angle), -math.sin(angle)
        points = []
        for along, across in profile:
            points.extend(
                (cx + along * dx - across * dy, cy + along * dy + across * dx)
            )
        canvas.create_polygon(points, fill=CYAN, outline="", tags="needle")
        hub = min(radius * 0.12, 7 * scale)
        canvas.create_oval(
            cx - hub,
            cy - hub,
            cx + hub,
            cy + hub,
            fill=PANEL,
            outline=CYAN,
            width=max(1, round(2 * scale)),
            tags="needle-hub",
        )
        canvas.create_oval(
            cx - hub * 0.35,
            cy - hub * 0.35,
            cx + hub * 0.35,
            cy + hub * 0.35,
            fill=TEXT,
            outline="",
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
        scale = self.ui_scale
        radius = max(30, min(cw, ch) * 0.4 - 30 * scale)
        for r in (radius, radius + 12 * scale):
            c.create_oval(
                cx - r,
                cy - r,
                cx + r,
                cy + r,
                outline=LINE,
                width=max(1, round(2 * scale)),
            )
        for text, x, y in [
            ("N", cx, cy - radius - 23 * scale),
            ("E", cx + radius + 23 * scale, cy),
            ("S", cx, cy + radius + 23 * scale),
            ("W", cx - radius - 23 * scale, cy),
        ]:
            c.create_text(x, y, text=text, fill=MUTED, font=self.ui_font(13))
        if math.isfinite(d["head"]):
            # Compass headings start at north and increase clockwise.
            self.draw_needle(c, cx, cy, radius, 90 - d["head"])
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
        scale = self.ui_scale
        left, top, bottom, right = 54 * scale, 20 * scale, 30 * scale, 10 * scale
        for i in range(5):
            y = top + i * (h - top - bottom) / 4
            c.create_line(left, y, w - right, y, fill=LINE)
        if len(history) < 2:
            c.create_text(
                w / 2,
                h / 2,
                text="AWAITING TELEMETRY",
                fill=MUTED,
                font=self.ui_font(13),
            )
            return
        vals = [v for _, v in history]
        low, high = min(vals) - 1, max(vals) + 1
        points = []
        for i, v in enumerate(vals):
            points.extend(
                (
                    left + i * (w - left - right) / (len(vals) - 1),
                    h - bottom - (v - low) * (h - top - bottom) / (high - low),
                )
            )
        c.create_line(*points, fill=CYAN, width=max(1, round(2 * scale)), smooth=False)
        c.create_text(
            25 * scale, top, text=f"{high:.0f}", fill=MUTED, font=self.ui_font(12)
        )
        c.create_text(
            25 * scale, h - bottom, text=f"{low:.0f}", fill=MUTED, font=self.ui_font(12)
        )
        c.create_text(
            w - 12 * scale,
            h - 10 * scale,
            anchor="e",
            text="m  /  latest 240 received samples",
            fill=MUTED,
            font=self.ui_font(12),
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
