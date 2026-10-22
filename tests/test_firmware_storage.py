"""Run the real SD logger against a small host filesystem/RTOS substitute.

A host C++ compiler is optional locally (CXX can select one); Ubuntu CI has g++.
These checks exercise firmware logic, not an SD driver or physical card.
"""

import csv
import io
import math
import os
import shlex
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MOCKS = r"""
#pragma once
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <limits>
#include <map>
#include <set>
#include <string>
#include <vector>

struct StopWriter {};
struct MockState {
  bool mounted = true, failOpen = false, failTask = false, failQueue = false;
  size_t writeLimit = size_t(-1);
  uint32_t now = 0, flightNumber = 0;
  bool failPreferencesOpen = false, failPreferencesWrite = false;
  int flushes = 0, closes = 0, receives = 0, deletedTasks = 0;
  std::map<std::string, std::string> files;
  std::set<std::string> dirs;
} state;

struct Preferences {
  bool begin(const char *, bool) { return !state.failPreferencesOpen; }
  uint32_t getUInt(const char *, uint32_t) { return state.flightNumber; }
  size_t putUInt(const char *, uint32_t value) {
    if (state.failPreferencesWrite) return 0;
    state.flightNumber = value;
    return sizeof(value);
  }
  void end() {}
};
struct ESPMock { uint64_t getEfuseMac() { return 0x112233445566ULL; } } ESP;
uint32_t millis() { return state.now; }
struct SerialMock {
  void println(const char *) {}
  template<typename... T> void printf(const char *, T...) {}
} Serial;

struct File {
  std::string path;
  bool valid = false;
  explicit operator bool() const { return valid; }
  size_t write(const uint8_t *data, size_t length) {
    if (!valid) return 0;
    size_t count = std::min(length, state.writeLimit);
    state.files[path].append(reinterpret_cast<const char *>(data), count);
    return count;
  }
  void flush() { ++state.flushes; }
  void close() { valid = false; ++state.closes; }
};
struct SPIClass { void begin(int, int, int, int) {} } SPI;
constexpr int CARD_NONE = 0, FILE_WRITE = 1;
struct SDMock {
  bool begin(int, SPIClass &, uint32_t) { return state.mounted; }
  int cardType() { return state.mounted ? 1 : CARD_NONE; }
  bool exists(const char *path) {
    return state.files.count(path) || state.dirs.count(path);
  }
  bool mkdir(const char *path) { return state.dirs.insert(path).second; }
  File open(const char *path, int) {
    File file;
    if (!state.failOpen) {
      file.path = path;
      file.valid = true;
      state.files[path].clear();
    }
    return file;
  }
} SD;

constexpr int pdTRUE = 1, pdFALSE = 0, pdPASS = 1;
inline uint32_t pdMS_TO_TICKS(uint32_t ms) { return ms; }
struct MockQueue {
  size_t capacity, itemSize;
  std::deque<std::vector<uint8_t>> items;
};
using QueueHandle_t = MockQueue *;
QueueHandle_t xQueueCreate(size_t capacity, size_t itemSize) {
  return state.failQueue ? nullptr : new MockQueue{capacity, itemSize, {}};
}
int xQueueSend(QueueHandle_t q, const void *item, int wait) {
  if (wait != 0 || q->items.size() == q->capacity) return pdFALSE;
  auto bytes = static_cast<const uint8_t *>(item);
  q->items.emplace_back(bytes, bytes + q->itemSize);
  return pdTRUE;
}
int xQueueReceive(QueueHandle_t q, void *item, uint32_t) {
  if (++state.receives > 20) throw StopWriter{};
  state.now += 100;
  if (q->items.empty()) return pdFALSE;
  memcpy(item, q->items.front().data(), q->itemSize);
  q->items.pop_front();
  return pdTRUE;
}
void vQueueDelete(QueueHandle_t q) { delete q; }
void (*writer)(void *) = nullptr;
int xTaskCreate(void (*task)(void *), const char *, int, void *, int, void *) {
  if (state.failTask) return pdFALSE;
  writer = task;
  return pdPASS;
}
void vTaskDelete(void *) { ++state.deletedTasks; }
"""

HARNESS = r"""
#include <cassert>
#include <iostream>
#include "telemetry_log.cpp"

void drain() {
  try { writer(nullptr); } catch (StopWriter &) {}
}
int main(int argc, char **argv) {
  assert(argc == 2);
  std::string test = argv[1];
  Telemetry p;
  if (test == "missing") {
    state.mounted = false;
    assert(!TelemetryLog::begin());
    assert(!TelemetryLog::enqueue(p));
    assert(state.files.empty() && writer == nullptr);
  } else if (test == "existing") {
    state.flightNumber = 1;
    state.files["/flights/flight_112233445566_000001.csv"] = "earlier flight";
    assert(TelemetryLog::begin());
    assert(state.files["/flights/flight_112233445566_000001.csv"] == "earlier flight");
    assert(state.files.count("/flights/flight_112233445566_000002.csv") == 1);
  } else if (test == "collision") {
    state.files["/flights/flight_112233445566_000001.csv"] = "preserve after NVS reset";
    assert(!TelemetryLog::begin());
    assert(state.files["/flights/flight_112233445566_000001.csv"] == "preserve after NVS reset");
    assert(writer == nullptr);
  } else if (test == "counter") {
    char name[40];
    assert(FlightId::reserveName(name, sizeof(name)));
    assert(std::string(name) == "flight_112233445566_000001");
    assert(FlightId::reserveName(name, sizeof(name)));
    assert(std::string(name) == "flight_112233445566_000002");
  } else if (test == "open" || test == "header" || test == "task" || test == "queue" ||
             test == "nvs-open" || test == "nvs-write" || test == "exhausted") {
    state.failPreferencesOpen = test == "nvs-open";
    state.failPreferencesWrite = test == "nvs-write";
    if (test == "exhausted") state.flightNumber = UINT32_MAX;
    state.failOpen = test == "open";
    state.writeLimit = test == "header" ? 3 : size_t(-1);
    state.failTask = test == "task";
    state.failQueue = test == "queue";
    assert(!TelemetryLog::begin());
    assert(!TelemetryLog::enqueue(p));
    assert(writer == nullptr);
  } else if (test == "full") {
    assert(TelemetryLog::begin());
    for (size_t n = 0; n < Config::sdQueueLength; ++n)
      assert(TelemetryLog::enqueue(p));
    assert(!TelemetryLog::enqueue(p));
  } else if (test == "short") {
    assert(TelemetryLog::begin());
    assert(TelemetryLog::enqueue(p));
    state.writeLimit = 3;
    drain();
    assert(!TelemetryLog::enqueue(p));
    assert(state.deletedTasks == 1 && state.closes == 1);
  } else if (test == "csv") {
    assert(TelemetryLog::begin());
    p.temp = 21.25f; p.alt = 2; p.press = 3; p.head = 4;
    p.ax = 5; p.ay = 6; p.az = 7; p.gx = 8; p.gy = 9; p.gz = 10;
    p.mx = 11; p.my = 12; p.mz = 13; p.sat = 14;
    p.lat = 33.6844f; p.lon = 73.0479f;
    p.gpsAlt = std::numeric_limits<float>::quiet_NaN();
    p.timestamp = UINT32_MAX;
    assert(TelemetryLog::enqueue(p));
    p.temp = 99; // The writer must own a copy, not a pointer to the live packet.
    drain();
    assert(state.flushes == 2); // Header, then buffered row even with an idle queue.
    std::cout << state.files["/flights/flight_112233445566_000001.csv"];
  } else {
    return 2;
  }
}
"""


class FirmwareStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        if not compiler or not shutil.which(compiler[0]):
            raise unittest.SkipTest(
                "A host C++ compiler is required for SD logger checks"
            )
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        (root / "freertos").mkdir()
        (root / "mocks.h").write_text(MOCKS)
        for header in (
            "Arduino.h",
            "Preferences.h",
            "SD.h",
            "SPI.h",
            "freertos/FreeRTOS.h",
            "freertos/queue.h",
            "freertos/task.h",
        ):
            (root / header).write_text('#include "mocks.h"\n')
        (root / "check.cpp").write_text(HARNESS)
        cls.binary = root / "storage-check"
        result = subprocess.run(
            compiler
            + [
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                str(root),
                "-I",
                str(ROOT / "firmware/include"),
                "-I",
                str(ROOT / "firmware/src"),
                str(root / "check.cpp"),
                "-o",
                str(cls.binary),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode:
            raise RuntimeError(
                f"Storage test harness compilation failed:\n{result.stderr}"
            )

    def run_case(self, name):
        return subprocess.run(
            [str(self.binary), name],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout

    def test_csv_fields_values_precision_and_packet_copy(self):
        rows = list(csv.reader(io.StringIO(self.run_case("csv"))))
        expected = "temp alt press head ax ay az gx gy gz mx my mz sat lat lon gpsAlt HardwareTimestamp".split()
        self.assertEqual(rows[0], expected)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[1]), 18)
        self.assertEqual(list(map(float, rows[1][:14])), [21.25] + list(range(2, 15)))
        for column, value in ((14, 33.6844), (15, 73.0479)):
            self.assertEqual(
                struct.pack("f", float(rows[1][column])), struct.pack("f", value)
            )
        self.assertTrue(math.isnan(float(rows[1][16])))
        self.assertEqual(int(rows[1][17]), 0xFFFFFFFF)

    def test_existing_flight_preserved(self):
        self.run_case("existing")
        self.run_case("collision")

    def test_persistent_counter_reserves_distinct_names(self):
        self.run_case("counter")

    def test_missing_card_disables_recorder(self):
        self.run_case("missing")

    def test_initialization_failures(self):
        for case in (
            "open",
            "header",
            "task",
            "queue",
            "nvs-open",
            "nvs-write",
            "exhausted",
        ):
            with self.subTest(case=case):
                self.run_case(case)

    def test_full_queue_drops_without_waiting(self):
        self.run_case("full")

    def test_short_write_stops_recording(self):
        self.run_case("short")
