#pragma once

#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#include "config.h"

inline bool startRadio()
{
  WiFi.mode(WIFI_STA);
  // Same channel and standard 802.11b/g/n protocols at both ends.

  return esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N) == ESP_OK &&
         esp_wifi_set_channel(Config::channel, WIFI_SECOND_CHAN_NONE) == ESP_OK &&
         esp_now_init() == ESP_OK;
}
