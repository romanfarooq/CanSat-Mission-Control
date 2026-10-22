"""Serial sessions, demo packets and the Tk update loop."""

import math
import time
import queue

from pathlib import Path
from collections import deque
from serial.tools import list_ports

from serial_reader import SerialReader
from telemetry import FIELDS, GyroState
from dashboard import AMBER, CYAN, MUTED, Dashboard


class MissionControl:
    """Own session state while workers handle serial and camera I/O."""

    def __init__(self, root, demo=False, log_dir=None):
        self.root = root
        # Session data belongs here; workers communicate through bounded queues.
        self.reader = None
        self.messages = queue.Queue(maxsize=4096)
        self.model = GyroState()
        self.demo = demo
        self.started = time.monotonic()
        self.last_packet = None
        self.packet_count = 0
        self.history = deque(maxlen=240)
        self.latest = None
        self.closing = False
        self.notice = "Connect the ground receiver to begin."
        self.log_dir = (
            Path(log_dir)
            if log_dir
            else Path(__file__).resolve().parent.parent / "logs"
        )

        self.view = Dashboard(root, self, self.log_dir)
        self.refresh_ports()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(50, self.tick)

    def refresh_ports(self):
        ports = [p.device for p in list_ports.comports()]
        self.view.port["values"] = ports
        if ports and self.view.port.get() not in ports:
            self.view.port.set(ports[0])

    def reset_session(self):
        """Start a fresh preview and calibration after the previous reader stops."""
        self.messages = queue.Queue(maxsize=4096)
        self.model = GyroState()
        self.started = time.monotonic()
        self.last_packet = None
        self.packet_count = 0
        self.history.clear()
        self.latest = None
        self.view.reset_fields(self.model)

    def connect(self):
        """Toggle the live receiver without opening a second reader on its port."""
        if self.reader:
            # tick() re-enables Connect after the worker flushes and exits.
            self.reader.stop()
            self.notice = "Disconnecting; flushing CSV…"
            self.view.connect_button.config(state="disabled")
            return
        if not self.view.port.get():
            self.notice = "No serial port selected. Connect receiver, then Refresh."
            return
        self.demo = False
        self.view.demo_button.config(text="Start demo")
        self.reset_session()
        self.reader = SerialReader(self.view.port.get(), self.log_dir, self.messages)
        self.reader.start()
        self.notice = "Opening receiver…"
        self.view.connect_button.config(text="Disconnect")

    def toggle_demo(self):
        if self.reader:
            self.notice = "Disconnect the live receiver before starting a demo."
            return
        self.demo = not self.demo
        self.reset_session()
        self.view.demo_button.config(text="Stop demo" if self.demo else "Start demo")
        self.notice = (
            "DEMO / synthetic values · CSV logging disabled"
            if self.demo
            else "Demo stopped."
        )

    def accept(self, record):
        """Process one preview packet without changing the raw CSV record."""
        self.latest = dict(record)
        self.latest.setdefault(
            "PythonTimestamp", int((time.monotonic() - self.started) * 1000)
        )
        self.last_packet = time.monotonic()
        self.packet_count += 1
        self.model.update(record)
        if math.isfinite(record["alt"]):
            self.history.append((record["HardwareTimestamp"] / 1000, record["alt"]))

    def synthetic(self):
        """Produce demo sensor values; these never enter the live CSV writer."""
        t = time.monotonic() - self.started
        d = dict.fromkeys(FIELDS, 0.0)
        d.update(
            temp=22 + math.sin(t / 20),
            alt=125 + 35 * math.sin(t / 15),
            press=99800,
            head=(t * 4) % 360,
            az=9.81,
            ax=0.2 * math.sin(t),
            mx=24 * math.cos(t / 15),
            my=24 * math.sin(t / 15),
            mz=39,
            sat=9,
            lat=24.8607,
            lon=67.0011,
            gpsAlt=130,
            HardwareTimestamp=int(t * 1000) & 0xFFFFFFFF,
        )
        # Stationary gyro during the 300-sample bias acquisition.
        if len(self.model.samples) == 300:
            d.update(gx=0.03 * math.sin(t), gy=0.02 * math.cos(t), gz=0.01)
        return d

    def tick(self):
        """Drain queued packets and refresh the window about every 50 ms."""
        if self.closing:
            # Poll instead of joining here so the window stays responsive on close.
            if (
                self.reader and self.reader.thread.is_alive()
            ) or self.view.camera.alive:
                self.root.after(50, self.tick)
                return
            self.root.destroy()
            return
        # Integrate every queued sample, even though the display refresh is slower.
        for _ in range(4096):
            try:
                kind, value = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == "packet":
                self.accept(value)
            elif kind == "connected":
                self.notice = f"CSV / {value}"
            elif kind == "error":
                self.notice = f"Connection/log error / {value}"

        # A thread can finish even when its final queue message was dropped.
        if self.reader and not self.reader.thread.is_alive():
            if self.reader.error:
                self.notice = f"Connection/log error / {self.reader.error}"
            self.reader = None
            self.view.connect_button.config(text="Connect", state="normal")
            if not self.notice.startswith("Connection/log error"):
                self.notice = "Disconnected. CSV closed."

        if self.demo:
            self.accept(self.synthetic())
        now = time.monotonic()
        state, color = ("DEMO · SYNTHETIC", AMBER) if self.demo else ("STANDBY", MUTED)
        if self.reader:
            state, color = (
                ("LIVE", CYAN)
                if self.last_packet and now - self.last_packet < 2
                else ("NO DATA", AMBER)
            )
        elif not self.demo and self.latest:
            state, color = "DISCONNECTED · LAST VALUES", AMBER
        self.view.link.config(text=f"● {state}", fg=color)
        seconds = int(now - self.started)
        self.view.clock.config(text=f"T+ {seconds//60:02}:{seconds%60:02}")
        self.view.render(self.latest, self.model)
        self.view.draw_plot(self.history)
        drops = self.reader.preview_dropped if self.reader else 0
        self.view.status.config(
            text=f"{self.notice}   |   {self.packet_count:,} preview packets · {self.model.hz:.1f} Hz · preview skipped: {drops}"
        )
        self.root.after(50, self.tick)

    def close(self):
        """Request worker shutdown; the next ticks wait before destroying Tk."""
        self.closing = True
        self.view.camera.shutdown()
        if self.reader:
            self.reader.stop()
        self.notice = "Closing receiver and CSV…"
