#pragma once

#include <Arduino.h>

// Separate AI Thinker ESP32-CAM / OV2640 payload.
// Pin mapping follows Espressif's AI Thinker camera example for Arduino core 2.0.17.
namespace CameraConfig
{
  constexpr int pwdn = 32, reset = -1, xclk = 0, sda = 26, scl = 27;
  constexpr int d0 = 5, d1 = 18, d2 = 19, d3 = 21;
  constexpr int d4 = 36, d5 = 39, d6 = 34, d7 = 35;
  constexpr int vsync = 25, href = 23, pclk = 22;

  constexpr uint8_t channel = 1;
  constexpr char password[] = "cansat-view"; // Change before deployment (8+ characters).
  constexpr char accessPoint[] = "CanSat-Camera";
} // namespace CameraConfig
