#pragma once

#include <Arduino.h>

namespace Config
{
  constexpr uint8_t channel = 1;
  constexpr uint32_t baud = 115200;

  // Replace with your receiver's station MAC (run the mac_address target).
  // Zero is intentionally invalid: the transmitter refuses to start until configured.
  constexpr uint8_t receiverMac[6] = {0, 0, 0, 0, 0, 0};

  constexpr int gpsRx = 16, gpsTx = 17, buzzer = 4, led = 2;

  // I2C uses the selected Arduino board's default SDA/SCL.
  constexpr uint32_t sampleMs = 50, environmentMs = 2000, gpsTimeoutMs = 3000;

  // Example reference altitude; set this to the known launch-site altitude.
  constexpr float referenceAltitudeM = 10.0f;

  // QMC5883L is configured for +/-8 gauss (3000 counts/gauss).
  constexpr float magneticMicroteslaPerCount = 100.0f / 3000.0f;
} // namespace Config
