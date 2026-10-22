"""Exercise real pyserial I/O, CSV flush, error reporting and shutdown via a PTY."""

import os
import sys
import csv
import time
import queue
import struct
import tempfile
import unittest

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ground_station"))

from serial_reader import SerialReader


@unittest.skipUnless(os.name == "posix", "Pseudo-terminal integration uses POSIX")
class SerialTests(unittest.TestCase):
    def test_serial_to_csv_and_orderly_shutdown(self):
        master, slave = os.openpty()
        try:
            with tempfile.TemporaryDirectory() as directory:
                messages = queue.Queue()
                worker = SerialReader(os.ttyname(slave), directory, messages)
                worker.start()
                self.assertEqual(messages.get(timeout=3)[0], "connected")
                frame = struct.pack("<I17fI", 0xAABBCCDD, *range(17), 1234)
                os.write(master, b"noise" + frame[:15])
                os.write(master, frame[15:] + frame)
                packets = []
                deadline = time.monotonic() + 3
                while len(packets) < 2 and time.monotonic() < deadline:
                    kind, value = messages.get(timeout=3)
                    if kind == "packet":
                        packets.append(value)
                worker.stop()
                worker.thread.join(timeout=2)
                self.assertFalse(worker.thread.is_alive())
                self.assertEqual(len(packets), 2)
                files = list(Path(directory).glob("*.csv"))
                with files[0].open() as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[0]["HardwareTimestamp"], "1234")
                self.assertEqual(rows[0]["Source"], "LIVE")
                self.assertGreaterEqual(int(rows[0]["PythonTimestamp"]), 0)
                self.assertTrue(rows[0]["ReceivedUTC"].endswith("+00:00"))
        finally:
            os.close(master)
            os.close(slave)

    def test_missing_port_reports_error_and_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            messages = queue.Queue()
            worker = SerialReader("/no/such/cansat", directory, messages)
            worker.start()
            worker.thread.join(timeout=3)
            self.assertFalse(worker.thread.is_alive())
            self.assertEqual(messages.get(timeout=1)[0], "error")


if __name__ == "__main__":
    unittest.main()
