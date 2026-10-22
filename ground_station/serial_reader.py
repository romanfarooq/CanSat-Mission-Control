"""A worker owns serial + CSV. Only the Tk thread touches widgets."""

import csv
import time
import queue
import serial
import threading

from pathlib import Path
from datetime import datetime, timezone

from telemetry import CSV_FIELDS, Decoder


class SerialReader:
    """Own the serial port and CSV file for one live connection."""

    def __init__(self, port, log_dir, messages):
        self.port = port
        self.log_dir = Path(log_dir)
        self.messages = messages
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.error = None
        self.count = 0
        self.preview_dropped = 0

    def start(self):
        self.thread.start()

    def publish(self, kind, value):
        try:
            self.messages.put_nowait((kind, value))
        except queue.Full:
            # CSV has already been written. Report preview losses in status.
            self.preview_dropped += 1

    def run(self):
        """Read, decode and log packets without calling Tk from this thread."""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
            filename = self.log_dir / f"cansat_{stamp}.csv"
            with serial.Serial(
                self.port, 115200, timeout=0.1
            ) as connection, filename.open("x", newline="") as logfile:
                writer = csv.DictWriter(logfile, fieldnames=CSV_FIELDS)
                writer.writeheader()
                self.publish("connected", str(filename))
                decoder = Decoder()
                started = time.monotonic()
                last_flush = started

                # A short serial timeout lets stop() interrupt an idle connection.
                while not self.stop_event.is_set():
                    read_size = min(max(connection.in_waiting, 1), 8192)
                    chunk = connection.read(read_size)

                    for record in decoder.feed(chunk):
                        record["ReceivedUTC"] = datetime.now(timezone.utc).isoformat(
                            timespec="milliseconds"
                        )
                        record["Source"] = "LIVE"
                        record["PythonTimestamp"] = int(
                            (time.monotonic() - started) * 1000
                        )
                        # Logging comes first: a busy preview must not discard CSV rows.
                        writer.writerow(record)
                        self.count += 1
                        self.publish("packet", record)

                    if time.monotonic() - last_flush >= 1:
                        logfile.flush()
                        last_flush = time.monotonic()
        except (serial.SerialException, OSError) as exc:
            self.error = str(exc)
            self.publish("error", self.error)
        finally:
            # The context managers close serial and flush CSV before this notification.
            self.publish("stopped", None)

    def stop(self):
        self.stop_event.set()
