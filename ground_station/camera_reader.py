"""Bounded JPEG-over-HTTP camera worker; no Tk calls or synthetic camera images."""

import time
import queue
import threading

from io import BytesIO
from PIL import Image, UnidentifiedImageError
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, Request

MAX_BYTES = 512 * 1024
MAX_PIXELS = 2_000_000


def validate_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Use a complete http:// or https:// JPEG capture URL.")
    return url


def decode_jpeg(data):
    """Decode a bounded camera frame into an image independent of its byte stream."""
    if len(data) > MAX_BYTES:
        raise ValueError("Camera frame exceeds 512 KiB limit.")
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != "JPEG":
                raise ValueError("Camera endpoint must return a JPEG image.")
            if image.width * image.height > MAX_PIXELS:
                raise ValueError("Camera frame exceeds two megapixels.")
            # Load inside the context so later rendering does not need the closed stream.
            image.load()
            return image.convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError("Camera returned an invalid JPEG image.") from exc


class CameraReader:
    """Fetch JPEG frames in a worker, retaining only the most recent preview."""

    def __init__(self, url, interval=0.25, timeout=2):
        self.url = validate_url(url.strip())
        self.interval = interval
        self.timeout = timeout
        self.frames = queue.Queue(maxsize=1)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.error = None
        self.last_success = None
        self.count = 0
        # Do not route a local camera through HTTP_PROXY environment settings.
        self.opener = build_opener(ProxyHandler({}))

    def start(self):
        self.thread.start()

    def fetch(self):
        """Read one HTTP JPEG with byte, dimension and transfer-time limits."""
        request = Request(
            self.url, headers={"Accept": "image/jpeg", "Cache-Control": "no-cache"}
        )
        with self.opener.open(request, timeout=self.timeout) as response:
            if response.headers.get_content_type() != "image/jpeg":
                raise ValueError(
                    "Endpoint did not return image/jpeg. Use the /capture URL."
                )

            chunks, size = [], 0
            deadline = time.monotonic() + 4
            while True:
                if self.stop_event.is_set():
                    return None
                if time.monotonic() > deadline:
                    raise ValueError("Camera frame transfer exceeded four seconds.")
                chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("Camera frame exceeds 512 KiB limit.")

            jpeg = b"".join(chunks)
        return jpeg, decode_jpeg(jpeg)

    def run(self):
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                frame = self.fetch()
                if frame is None:
                    break
                # Only the most recent preview is retained; memory does not grow.
                try:
                    self.frames.get_nowait()
                except queue.Empty:
                    pass
                self.frames.put_nowait(frame)
                self.count += 1
                self.last_success = time.monotonic()
                self.error = None
            except HTTPError as exc:
                self.error = str(exc)
                exc.close()
            except (OSError, ValueError) as exc:
                self.error = str(exc)

            # Event.wait allows stop() to interrupt the normal/retry interval.
            self.stop_event.wait(
                max(0, self.interval - (time.monotonic() - started))
                if not self.error
                else 1
            )

    def stop(self):
        self.stop_event.set()
