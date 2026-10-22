#include <Arduino.h>
#include <SD.h>
#include <SPI.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>
#include <atomic>

#include "config.h"
#include "flight_id.h"
#include "telemetry_log.h"

namespace
{
  File flight;
  QueueHandle_t queue = nullptr;
  std::atomic<bool> active{false};

  constexpr char csvHeader[] = "temp,alt,press,head,ax,ay,az,gx,gy,gz,mx,my,mz,sat,lat,lon,gpsAlt,HardwareTimestamp\n";

  bool writePacket(const Telemetry &p)
  {
    // Nine significant digits preserve float32 readings, including GPS. NaN stays
    // visible in the CSV; onboard time is milliseconds since boot, not UTC.
    char row[512];
    int length = snprintf(row, sizeof(row),
                          "%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,"
                          "%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%lu\n",
                          p.temp, p.alt, p.press, p.head, p.ax, p.ay, p.az, p.gx, p.gy, p.gz, p.mx,
                          p.my, p.mz, p.sat, p.lat, p.lon, p.gpsAlt, (unsigned long)p.timestamp);
    return length > 0 && size_t(length) < sizeof(row) && flight.write(reinterpret_cast<const uint8_t *>(row), length) == size_t(length);
  }

  void writeFlight(void *)
  {
    uint32_t lastFlush = millis();
    bool dirty = false;
    for (;;)
    {
      Telemetry packet;
      if (xQueueReceive(queue, &packet, pdMS_TO_TICKS(100)) == pdTRUE)
      {
        if (!writePacket(packet))
        {
          active.store(false);
          flight.close();
          Serial.println("SD telemetry write failed; recording stopped. Check card and free space.");
          vTaskDelete(nullptr);
          return;
        }
        dirty = true;
      }

      if (dirty && millis() - lastFlush >= Config::sdFlushMs)
      {
        flight.flush();
        dirty = false;
        lastFlush = millis();
      }
    }
  }
} // namespace

bool TelemetryLog::begin()
{
  if (!Config::sdEnabled)
    return false;

  SPI.begin(Config::sdSck, Config::sdMiso, Config::sdMosi, Config::sdCs);
  if (!SD.begin(Config::sdCs, SPI, Config::sdFrequencyHz) || SD.cardType() == CARD_NONE)
  {
    Serial.println("SD telemetry unavailable; continuing without onboard recording.");
    return false;
  }
  if (!SD.exists("/flights") && !SD.mkdir("/flights"))
  {
    Serial.println("Cannot create SD /flights directory.");
    return false;
  }

  char name[40], path[64];
  if (!FlightId::reserveName(name, sizeof(name)))
  {
    Serial.println("Cannot reserve SD flight number in ESP32 Preferences.");
    return false;
  }
  snprintf(path, sizeof(path), "/flights/%s.csv", name);
  if (SD.exists(path))
  {
    Serial.println("SD flight file already exists; recording stopped to preserve it. Check NVS reset.");
    return false;
  }
  flight = SD.open(path, FILE_WRITE);
  if (!flight || flight.write(reinterpret_cast<const uint8_t *>(csvHeader), sizeof(csvHeader) - 1) != sizeof(csvHeader) - 1)
  {
    flight.close();
    Serial.println("Cannot create SD telemetry file.");
    return false;
  }
  flight.flush();

  queue = xQueueCreate(Config::sdQueueLength, sizeof(Telemetry));
  if (!queue)
  {
    flight.close();
    Serial.println("Cannot allocate SD telemetry queue.");
    return false;
  }

  active.store(true);
  if (xTaskCreate(writeFlight, "sd-telemetry", 4096, nullptr, 1, nullptr) != pdPASS)
  {
    active.store(false);
    vQueueDelete(queue);
    queue = nullptr;
    flight.close();
    Serial.println("Cannot start SD telemetry writer.");
    return false;
  }
  Serial.printf("SD telemetry: %s\n", path);
  return true;
}

bool TelemetryLog::enqueue(const Telemetry &packet)
{
  return active.load() && xQueueSend(queue, &packet, 0) == pdTRUE;
}
