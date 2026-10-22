import sys
import math
import struct
import unittest

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ground_station"))

from telemetry import Decoder, FIELDS, GyroState, HEADER


class TelemetryTests(unittest.TestCase):
    def packet(self, timestamp=123):
        return struct.pack("<I17fI", 0xAABBCCDD, *range(17), timestamp)

    def test_every_fragment_boundary_and_noise(self):
        packet = self.packet()
        for cut in range(1, 76):
            decoder = Decoder()
            result = decoder.feed(b"boot noise" + packet[:cut]) + decoder.feed(
                packet[cut:]
            )
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["HardwareTimestamp"], 123)
            self.assertEqual(result[0]["gpsAlt"], 16)

    def test_concatenation_and_partial_header(self):
        decoder = Decoder()
        self.assertEqual(decoder.feed(b"noise" + HEADER[:2]), [])
        records = decoder.feed(self.packet()[2:] + self.packet(456))
        self.assertEqual([d["HardwareTimestamp"] for d in records], [123, 456])

    def test_noise_buffer_is_bounded(self):
        decoder = Decoder()
        decoder.feed(b"x" * 100000)
        self.assertLessEqual(len(decoder.buffer), 3)

    def test_nan_gps_survives_wire_format(self):
        values = list(range(17))
        values[14] = float("nan")
        record = Decoder().feed(struct.pack("<I17fI", 0xAABBCCDD, *values, 10))[0]
        self.assertTrue(math.isnan(record["lat"]))

    def test_bias_integration_reboot_and_rollover(self):
        state = GyroState()
        record = dict.fromkeys(FIELDS, 0)
        record.update(gx=0.1, gy=0.2, gz=0.3)
        for i in range(300):
            record["HardwareTimestamp"] = i * 50
            state.update(record)
        self.assertAlmostEqual(state.bias[0], 0.1)
        record.update(gx=1.1, HardwareTimestamp=15000)
        state.update(record)
        self.assertAlmostEqual(state.angles[0], math.degrees(0.05))
        angle = state.angles[0]
        record["HardwareTimestamp"] = 1  # reboot: skip integration
        state.update(record)
        self.assertAlmostEqual(state.angles[0], angle)
        state.last = 0xFFFFFFF0
        record["HardwareTimestamp"] = 34  # uint32 rollover, +50ms
        state.update(record)
        self.assertAlmostEqual(state.angles[0], angle + math.degrees(0.05))


if __name__ == "__main__":
    unittest.main()
