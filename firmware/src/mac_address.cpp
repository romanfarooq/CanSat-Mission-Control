#include <Arduino.h>
#include <WiFi.h>

#include "config.h"

void setup()
{
  Serial.begin(Config::baud);
  // The transmitter needs this station MAC, not an access-point MAC.
  WiFi.mode(WIFI_STA);
}

void loop()
{
  Serial.print("Receiver station MAC: ");
  Serial.println(WiFi.macAddress());
  delay(1000);
}
