#include <Arduino.h>
#include <esp_arduino_version.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <cstring>

#include "radio.h"
#include "telemetry.h"

namespace
{
  bool ready = false;
  QueueHandle_t packets = nullptr;

  // The callback only validates/copies. Serial writes run in loop(), outside Wi-Fi task.
  void acceptPacket(const uint8_t *bytes, int length)
  {
    if (!bytes || length != sizeof(Telemetry))
      return;

    Telemetry packet;
    memcpy(&packet, bytes, sizeof(packet));
    if (packet.header == telemetryHeader)
    {
      // A full queue drops the newest frame; never block the Wi-Fi task.
      xQueueSend(packets, &packet, 0);
    }
  }

// The callback metadata changed in core 3.x; payload handling stays the same.
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  void onReceive(const esp_now_recv_info_t *, const uint8_t *bytes, int length)
#else
  void onReceive(const uint8_t *, const uint8_t *bytes, int length)
#endif
  {
    acceptPacket(bytes, length);
  }
} // namespace

void setup()
{
  Serial.begin(Config::baud);
  pinMode(Config::led, OUTPUT);

  // Allocate before registering the callback, which may run as soon as radio data arrives.
  packets = xQueueCreate(32, sizeof(Telemetry));
  ready = packets && startRadio() && esp_now_register_recv_cb(onReceive) == ESP_OK;
  // Keep USB output binary-only, including startup/failure paths.
}

void loop()
{
  if (!ready)
  {
    digitalWrite(Config::led, (millis() / 150) % 2);
    delay(20);
    return;
  }

  // Serial output can block, so it belongs here rather than in the Wi-Fi callback.
  Telemetry packet;
  if (xQueueReceive(packets, &packet, pdMS_TO_TICKS(10)) == pdTRUE)
  {
    Serial.write(reinterpret_cast<const uint8_t *>(&packet), sizeof(packet));
    digitalWrite(Config::led, (millis() / 800) % 2);
  }
}
