#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <esp_camera.h>

#include "camera.h"

namespace
{
  WebServer server(80);
  bool ready = false;
  uint32_t frames = 0;

  // Serve one frame per request; the desktop controls how often it asks for another.
  void capture()
  {
    camera_fb_t *frame = esp_camera_fb_get();
    if (!frame)
    {
      server.send(503, "text/plain", "Camera capture failed");
      return;
    }

    server.sendHeader("Cache-Control", "no-store");
    server.setContentLength(frame->len);
    server.send(200, "image/jpeg", "");
    WiFiClient client = server.client();
    client.setTimeout(2000);
    // Wi-Fi TCP only; large image payloads never enter the 76-byte ESP-NOW stream.
    const size_t written = client.write(frame->buf, frame->len);
    if (written == frame->len)
      ++frames;

    // Return the SDK-owned buffer even if the client did not receive the whole frame.
    esp_camera_fb_return(frame);
  }

  bool initializeCamera()
  {
    camera_config_t cfg{};
    cfg.pin_pwdn = CameraConfig::pwdn;
    cfg.pin_reset = CameraConfig::reset;
    cfg.pin_xclk = CameraConfig::xclk;
    cfg.pin_sccb_sda = CameraConfig::sda;
    cfg.pin_sccb_scl = CameraConfig::scl;
    cfg.pin_d0 = CameraConfig::d0;
    cfg.pin_d1 = CameraConfig::d1;
    cfg.pin_d2 = CameraConfig::d2;
    cfg.pin_d3 = CameraConfig::d3;
    cfg.pin_d4 = CameraConfig::d4;
    cfg.pin_d5 = CameraConfig::d5;
    cfg.pin_d6 = CameraConfig::d6;
    cfg.pin_d7 = CameraConfig::d7;
    cfg.pin_vsync = CameraConfig::vsync;
    cfg.pin_href = CameraConfig::href;
    cfg.pin_pclk = CameraConfig::pclk;

    // LEDC drives the sensor clock. JPEG keeps the Wi-Fi payload compact.
    cfg.ledc_timer = LEDC_TIMER_0;
    cfg.ledc_channel = LEDC_CHANNEL_0;
    cfg.xclk_freq_hz = 20000000;
    cfg.pixel_format = PIXFORMAT_JPEG;

    // Use a smaller frame when external RAM is absent. One buffer limits memory use.
    cfg.frame_size = psramFound() ? FRAMESIZE_VGA : FRAMESIZE_QVGA;
    cfg.jpeg_quality = 12;
    cfg.fb_count = 1;
    cfg.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
    cfg.grab_mode = CAMERA_GRAB_WHEN_EMPTY;

    esp_err_t result = esp_camera_init(&cfg);
    if (result != ESP_OK)
      Serial.printf("Camera initialization failed: 0x%x\n", result);
    return result == ESP_OK;
  }
} // namespace

void setup()
{
  Serial.begin(115200);
  if (!initializeCamera())
    return;

  // This payload board provides its own local network, independent of sensor ESP-NOW.
  WiFi.persistent(false);
  WiFi.mode(WIFI_AP);
  if (!WiFi.softAP(CameraConfig::accessPoint, CameraConfig::password, CameraConfig::channel))
  {
    Serial.println("Camera Wi-Fi access point failed");
    return;
  }

  server.on("/capture", HTTP_GET, capture);
  server.on("/health", HTTP_GET,
            []
            {
              server.sendHeader("Cache-Control", "no-store");
              server.send(200, "application/json",
                          String("{\"camera\":true,\"frames\":") + frames + "}");
            });
  server.on(
      "/", HTTP_GET, []
      { server.send(200, "text/plain", "CanSat camera ready. JPEG: /capture. Status: /health."); });

  server.begin();
  ready = true;
  Serial.printf("Join Wi-Fi %s; JPEG URL: http://", CameraConfig::accessPoint);
  Serial.print(WiFi.softAPIP());
  Serial.println("/capture");
}

void loop()
{
  if (ready)
    server.handleClient();
  delay(2);
}
