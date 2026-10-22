#pragma once

#include <cstddef>
#include <cstdint>
#include <type_traits>

constexpr uint32_t telemetryHeader = 0xAABBCCDD;
// Wire format: 4-byte header, 17 float32 fields, uint32 milliseconds.

struct Telemetry
{
  uint32_t header = telemetryHeader;

  // Environment: degrees C, metres, pascals, planar magnetic degrees.
  float temp = 0, alt = 0, press = 0, head = 0;

  // Acceleration is m/s^2; gyro values are angular rates in rad/s.
  float ax = 0, ay = 0, az = 0, gx = 0, gy = 0, gz = 0;

  // Magnetic field is in microtesla. GPS angles are decimal degrees, altitude metres.
  float mx = 0, my = 0, mz = 0;
  float sat = 0, lat = 0, lon = 0, gpsAlt = 0;

  // Milliseconds since sensor-board boot, sampled just before transmission.
  uint32_t timestamp = 0;
};

// Both firmware targets and the Python decoder depend on this exact layout.
static_assert(sizeof(float) == 4, "Protocol requires float32");
static_assert(sizeof(Telemetry) == 76, "Protocol layout changed");
static_assert(offsetof(Telemetry, timestamp) == 72, "Timestamp offset changed");
static_assert(std::is_trivially_copyable<Telemetry>::value, "Packet must be copyable");
