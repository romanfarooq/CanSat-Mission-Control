#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_BMP085.h>
#include <Adafruit_MPU6050.h>
#include <NMEAGPS.h>
#include <cmath>
#include <cstring>
#include "radio.h"
#include "telemetry.h"

namespace
{
  // Device objects and the latest values placed on the wire.
  Adafruit_MPU6050 mpu;
  Adafruit_BMP085 bmp;
  NMEAGPS gps;
  HardwareSerial gpsSerial(2);
  Telemetry packet;
  bool ready = false;
  float seaLevelPressure;

  // Unsigned millisecond differences remain valid across the millis() rollover.
  uint32_t lastSample = 0, lastEnvironment = 0;
  uint32_t lastLocation = 0, lastGpsAltitude = 0, lastSatellites = 0;
  uint32_t accepted = 0, rejected = 0, lastStatus = 0;

  // QMC5883L configuration registers use a one-byte address and value.
  bool qmcWrite(uint8_t reg, uint8_t value)
  {
    Wire.beginTransmission(0x0D);
    Wire.write(reg);
    Wire.write(value);
    return Wire.endTransmission() == 0;
  }

  bool readMagnetometer()
  {
    Wire.beginTransmission(0x0D);
    Wire.write(0x00);
    if (Wire.endTransmission(false) != 0 || Wire.requestFrom(uint8_t(0x0D), uint8_t(6)) != 6)
      return false;

    // Each axis arrives low byte first; recover its signed 16-bit value before scaling.
    float *axes[] = {&packet.mx, &packet.my, &packet.mz};
    for (auto axis : axes)
    {
      uint16_t word = Wire.read();
      word |= uint16_t(Wire.read()) << 8;
      *axis = int16_t(word) * Config::magneticMicroteslaPerCount;
    }

    // This planar heading has no tilt compensation or magnetic declination correction.
    packet.head = atan2f(packet.my, packet.mx) * 180.0f / PI;
    return true;
  }

  void readEnvironment()
  {
    packet.temp = bmp.readTemperature();
    packet.press = bmp.readPressure();
    packet.alt = bmp.readAltitude(seaLevelPressure);
  }

  void pollGPS(uint32_t now)
  {
    // Drain the GPS UART between sensor samples so complete sentences are not left waiting.
    while (gps.available(gpsSerial))
    {
      gps_fix fix = gps.read();
      if (fix.valid.location)
      {
        packet.lat = fix.latitude();
        packet.lon = fix.longitude();
        lastLocation = now;
      }
      if (fix.valid.altitude)
      {
        packet.gpsAlt = fix.altitude();
        lastGpsAltitude = now;
      }
      if (fix.valid.satellites)
      {
        packet.sat = fix.satellites;
        lastSatellites = now;
      }
    }

    // NMEA messages can update these fields independently, so expire them separately.
    if (now - lastLocation > Config::gpsTimeoutMs)
      packet.lat = packet.lon = NAN;
    if (now - lastGpsAltitude > Config::gpsTimeoutMs)
      packet.gpsAlt = NAN;
    if (now - lastSatellites > Config::gpsTimeoutMs)
      packet.sat = 0;
  }
} // namespace

void setup()
{
  Serial.begin(Config::baud);
  Wire.begin();
  gpsSerial.begin(9600, SERIAL_8N1, Config::gpsRx, Config::gpsTx);

  // A short startup pulse confirms the sensor board has begun setup.
  pinMode(Config::buzzer, OUTPUT);
  digitalWrite(Config::buzzer, HIGH);
  delay(200);
  digitalWrite(Config::buzzer, LOW);

  packet.lat = packet.lon = packet.gpsAlt = NAN;

  // A placeholder MAC must not silently send telemetry to an unintended peer.
  bool configured = false;
  for (auto byte : Config::receiverMac)
    configured |= byte != 0;
  if (!configured)
  {
    Serial.println("Set receiverMac in firmware/include/config.h first.");
    return;
  }

  // Sensor failures leave ready false; loop() will wait instead of transmitting zeros.
  if (!bmp.begin() || !mpu.begin())
  {
    Serial.println("BMP/MPU initialization failed. Check wiring.");
    return;
  }

  // QMC: reset period 1; continuous, 200 Hz, +/-8 G, OSR512 (0x1D).
  if (!qmcWrite(0x0B, 0x01) || !qmcWrite(0x09, 0x1D))
  {
    Serial.println("QMC5883L initialization failed.");
    return;
  }

  mpu.setAccelerometerRange(MPU6050_RANGE_2_G);
  mpu.setGyroRange(MPU6050_RANGE_500_DEG);
  mpu.setFilterBandwidth(MPU6050_BAND_184_HZ);

  // Seed the first packet with real environment data and the configured altitude reference.
  seaLevelPressure = bmp.readSealevelPressure(Config::referenceAltitudeM);
  readEnvironment();

  // Radio settings must match the receiver; peer registration selects its station MAC.
  if (!startRadio())
  {
    Serial.println("Radio initialization failed.");
    return;
  }
  esp_now_peer_info_t peer{};
  memcpy(peer.peer_addr, Config::receiverMac, 6);
  peer.channel = Config::channel;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK)
  {
    Serial.println("Cannot add receiver peer.");
    return;
  }

  ready = true;
  Serial.println("CanSat ready. Counters measure send requests, not radio delivery.");
}

void loop()
{
  if (!ready)
  {
    delay(100);
    return;
  }

  uint32_t now = millis();
  pollGPS(now);
  if (now - lastSample < Config::sampleMs)
  {
    delay(1);
    return;
  }
  lastSample = now;

  // Adafruit events report acceleration in m/s^2 and angular velocity in rad/s.
  sensors_event_t a, g, t;
  mpu.getEvent(&a, &g, &t);
  packet.ax = a.acceleration.x;
  packet.ay = a.acceleration.y;
  packet.az = a.acceleration.z;
  packet.gx = g.gyro.x;
  packet.gy = g.gyro.y;
  packet.gz = g.gyro.z;

  if (!readMagnetometer())
    packet.mx = packet.my = packet.mz = packet.head = NAN;

  // Pressure/temperature refresh more slowly; altitude is sampled on every pass.
  if (now - lastEnvironment >= Config::environmentMs)
  {
    readEnvironment();
    lastEnvironment = now;
  }
  else
  {
    packet.alt = bmp.readAltitude(seaLevelPressure);
  }

  // Timestamp after reads so it describes this assembled packet.
  packet.timestamp = millis();
  if (esp_now_send(Config::receiverMac, reinterpret_cast<uint8_t *>(&packet), sizeof(packet)) == ESP_OK)
    ++accepted;
  else
    ++rejected;

  // ESP_OK means the send request was accepted, not that the PC logged the packet.
  if (now - lastStatus >= 1000)
  {
    Serial.printf("Send requests accepted=%lu rejected=%lu\n", (unsigned long)accepted, (unsigned long)rejected);
    lastStatus = now;
  }
}
