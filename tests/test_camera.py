import sys
import time
import threading
import unittest

from PIL import Image
from io import BytesIO
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ground_station"))

from camera_reader import CameraReader, MAX_BYTES, decode_jpeg, validate_url


def jpeg(size=(32, 24)):
    output = BytesIO()
    Image.new("RGB", size, "#204060").save(output, "JPEG")
    return output.getvalue()


class CameraTests(unittest.TestCase):
    def test_jpeg_decoding(self):
        image = decode_jpeg(jpeg())
        self.assertEqual(image.size, (32, 24))
        self.assertEqual(image.mode, "RGB")

    def test_invalid_and_large_frames_rejected(self):
        for bad in (b"not a JPEG", b"x" * (MAX_BYTES + 1), jpeg((2001, 1000))):
            with self.assertRaises(ValueError):
                decode_jpeg(bad)
        png = BytesIO()
        Image.new("RGB", (2, 2)).save(png, "PNG")
        with self.assertRaises(ValueError):
            decode_jpeg(png.getvalue())

    def test_url_validation(self):
        for value in (
            "file:///etc/passwd",
            "camera",
            "http://",
            "ftp://camera/capture",
        ):
            with self.assertRaises(ValueError):
                validate_url(value)
        self.assertEqual(
            validate_url("http://192.168.4.1/capture"), "http://192.168.4.1/capture"
        )

    def test_http_preview_failure_recovery_and_bounded_queue(self):
        state = {"status": 200, "type": "image/jpeg"}
        content = jpeg()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(state["status"])
                self.send_header("Content-Type", state["type"])
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        reader = CameraReader(
            f"http://127.0.0.1:{server.server_port}/capture", interval=0.02
        )
        try:
            reader.start()
            deadline = time.monotonic() + 3
            while reader.count < 3 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertGreaterEqual(reader.count, 3)
            self.assertEqual(reader.frames.qsize(), 1)
            frame, image = reader.frames.get(timeout=1)
            self.assertEqual(frame, content)
            self.assertEqual(image.size, (32, 24))
            state["status"] = 503
            deadline = time.monotonic() + 3
            while reader.error is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIsNotNone(reader.error)
            state["status"] = 200
            deadline = time.monotonic() + 3
            while reader.error is not None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIsNone(reader.error)
            state["type"] = "text/html"
            deadline = time.monotonic() + 3
            while reader.error is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIn("image/jpeg", reader.error)
        finally:
            reader.stop()
            reader.thread.join(timeout=3)
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertFalse(reader.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
