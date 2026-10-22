#pragma once

#include <Arduino.h>
#include <Preferences.h>

namespace FlightId
{
  inline bool reserveName(char *name, size_t capacity)
  {
    Preferences preferences;
    if (!preferences.begin("cansat-flights", false))
      return false;

    uint32_t number = preferences.getUInt("last", 0);
    if (number == UINT32_MAX)
    {
      preferences.end();
      return false;
    }

    // Reserve before creating anything on SD. Failed starts may leave gaps,
    // but a reset must not reuse a number that has already been recorded.
    ++number;
    bool stored = preferences.putUInt("last", number) == sizeof(number);
    preferences.end();
    if (!stored)
      return false;

    // Device identity keeps cards moved between boards from sharing a counter.
    const auto device = (unsigned long long)(ESP.getEfuseMac() & 0xFFFFFFFFFFFFULL);
    int length = snprintf(name, capacity, "flight_%012llX_%06lu", device, (unsigned long)number);
    return length > 0 && size_t(length) < capacity;
  }
} // namespace FlightId
