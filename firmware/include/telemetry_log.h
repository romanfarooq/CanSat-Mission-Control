#pragma once

#include "telemetry.h"

// Only the writer task touches the card after begin(). The sampling loop queues
// packet copies without waiting for SD I/O; a full queue drops the newest copy.
namespace TelemetryLog
{
  bool begin();
  bool enqueue(const Telemetry &packet);
} // namespace TelemetryLog
