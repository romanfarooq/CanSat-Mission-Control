"""CanSat binary framing and gyro integration, independent of Tk."""

import math
import struct

from collections import deque

# This order must match the floats and timestamp in firmware/include/telemetry.h.
FIELDS = (
    "temp",
    "alt",
    "press",
    "head",
    "ax",
    "ay",
    "az",
    "gx",
    "gy",
    "gz",
    "mx",
    "my",
    "mz",
    "sat",
    "lat",
    "lon",
    "gpsAlt",
    "HardwareTimestamp",
)
HEADER = b"\xdd\xcc\xbb\xaa"
PAYLOAD = struct.Struct("<17fI")
CSV_FIELDS = ("ReceivedUTC", "Source", "PythonTimestamp") + FIELDS


class Decoder:
    """Keep partial serial reads until a complete telemetry packet arrives."""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, chunk):
        """Return all complete packets, retaining an unfinished packet for next time."""
        self.buffer.extend(chunk)
        records = []
        while True:
            start = self.buffer.find(HEADER)
            if start < 0:
                # Preserve possible split header, discard unrelated bytes.
                self.buffer[:] = self.buffer[-3:]
                break

            del self.buffer[:start]
            if len(self.buffer) < 76:
                break

            values = PAYLOAD.unpack_from(self.buffer, 4)
            del self.buffer[:76]
            records.append(dict(zip(FIELDS, values)))
        return records


class GyroState:
    """Stationary 300-sample bias, followed by body-axis rate integration."""

    def __init__(self):
        self.samples = []
        self.bias = [0.0] * 3
        self.angles = [0.0] * 3
        self.last = None
        self.corrected = [0.0] * 3
        self.intervals = deque(maxlen=30)

    def reset_angles(self):
        self.angles = [0.0] * 3

    def update(self, data):
        timestamp = data["HardwareTimestamp"]
        dt = (
            None if self.last is None else ((timestamp - self.last) & 0xFFFFFFFF) / 1000
        )
        self.last = timestamp
        # Reset/reboot and large gaps are not integrated; uint32 rollover is allowed.
        if dt is not None and 0 < dt <= 1:
            self.intervals.append(dt)

        rates = [data[k] for k in ("gx", "gy", "gz")]
        if not all(math.isfinite(v) for v in rates):
            return

        # Learn bias while stationary; integration begins with the following sample.
        if len(self.samples) < 300:
            self.samples.append(rates)
            if len(self.samples) == 300:
                self.bias = [
                    sum(row[i] for row in self.samples) / 300 for i in range(3)
                ]
            return

        self.corrected = [v - b for v, b in zip(rates, self.bias)]
        if dt is not None and 0 < dt <= 1:
            self.angles = [
                a + math.degrees(r * dt) for a, r in zip(self.angles, self.corrected)
            ]

    @property
    def hz(self):
        return len(self.intervals) / sum(self.intervals) if self.intervals else 0
