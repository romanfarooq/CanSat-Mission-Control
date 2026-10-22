"""Optional desktop check: python tests/gui_smoke.py (Tk + display required)."""

import os
import sys
import csv
import time
import struct
import tempfile
import threading
import tkinter as tk

from io import BytesIO
from PIL import Image
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ground_station"))

from main import MissionControl
from telemetry import FIELDS


def pump(root, condition, timeout=4):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert condition(), "GUI did not reach expected state"


root = tk.Tk()
root.geometry("1100x800+0+0")
errors = []
root.report_callback_exception = lambda *args: errors.append(args)
with tempfile.TemporaryDirectory() as directory:
    app = MissionControl(root, demo=True, log_dir=directory)
    root.update()
    pump(root, lambda: app.packet_count >= 2)
    assert (
        app.view.status.winfo_y() + app.view.status.winfo_height()
        <= root.winfo_height()
    ), "Footer clipped"
    assert "DEMO" in app.view.link.cget("text")
    assert set(FIELDS).issubset(app.view.raw_table.get_children())
    assert app.view.raw_table.set("PythonTimestamp", "value") != "—"
    assert app.view.raw_table.set("mag", "value") != "—"
    assert "HW" in app.view.timing.cget("text") and "SW" in app.view.timing.cget("text")
    app.view.notebook.select(1)
    root.update()
    assert app.view.raw_table.winfo_ismapped()
    app.view.notebook.select(2)
    root.update()
    assert app.view.dials.winfo_ismapped()
    app.model.samples = [[0, 0, 0]] * 300
    app.model.angles = [15, 30, 60]
    app.view.draw_dials(app.model)
    labels = [
        app.view.dials.itemcget(item, "text")
        for item in app.view.dials.find_all()
        if app.view.dials.type(item) == "text"
    ]
    assert labels == ["X  +15.0°", "Y  +30.0°", "Z  +60.0°"]
    app.view.notebook.select(0)
    assert list(Path(directory).iterdir()) == [], "Demo must not create logs"
    app.toggle_demo()
    assert not app.demo and app.latest is None
    if os.name == "posix":
        master, slave = os.openpty()
        try:
            app.view.port.set(os.ttyname(slave))
            app.connect()
            pump(root, lambda: app.notice.startswith("CSV /"))
            frame = struct.pack("<I17fI", 0xAABBCCDD, *range(17), 50)
            os.write(master, frame)
            pump(root, lambda: app.packet_count == 1)
            assert "LIVE" in app.view.link.cget("text")
            assert app.view.values["alt"].cget("text") == "1.0"
            assert app.view.raw_table.set("gx", "value") == "7.000"
            assert app.view.raw_table.set("HardwareTimestamp", "value") == "50"
            assert app.view.raw_table.set("press", "value") == "2.000"
            app.connect()  # disconnect, drain and flush
            pump(root, lambda: app.reader is None)
            assert "DISCONNECTED" in app.view.link.cget("text")
            with next(Path(directory).glob("*.csv")).open() as handle:
                assert len(list(csv.DictReader(handle))) == 1
        finally:
            os.close(master)
            os.close(slave)
    app.toggle_demo()
    assert app.demo and app.packet_count == 0
    app.model.angles = [10, 20, 30]

    # Exercise reset action against a newly replaced model after a session change.
    def buttons(widget):
        for child in widget.winfo_children():
            if isinstance(child, tk.Button) and child.cget("text") == "Reset angles":
                yield child
            yield from buttons(child)

    next(buttons(root)).invoke()
    assert app.model.angles == [0, 0, 0]
    content = BytesIO()
    Image.new("RGB", (64, 48), "#205070").save(content, "JPEG")
    jpeg = content.getvalue()

    class CameraHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpeg)))
            self.end_headers()
            self.wfile.write(jpeg)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), CameraHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        app.view.notebook.select(3)
        app.view.camera.url.delete(0, "end")
        app.view.camera.url.insert(0, f"http://127.0.0.1:{server.server_port}/capture")
        app.view.camera.connect()
        pump(root, lambda: app.view.camera.frame is not None)
        assert app.view.camera.photo is not None
        assert "CAMERA LIVE" in app.view.camera.status.cget("text")
        assert app.view.camera.frame[0] == jpeg
        app.view.camera.save_photo()
        saved = next((Path(directory) / "photos").glob("*.jpg"))
        assert saved.read_bytes() == jpeg
        app.view.camera.connect()  # stop camera while telemetry demo continues
        pump(root, lambda: app.view.camera.reader is None)
        assert app.demo and app.view.camera.frame is not None
        app.view.camera.connect()  # exercise closing with active camera worker
        pump(root, lambda: app.view.camera.frame is not None)
        app.close()
        root.mainloop()
        assert not app.view.camera.alive
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
assert not errors, errors
print(
    "PASS: telemetry + camera HTTP preview, JPEG photo saving, independent disconnect and orderly close"
)
