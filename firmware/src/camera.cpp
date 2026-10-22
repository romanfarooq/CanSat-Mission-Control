#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <esp_camera.h>
#include <SD_MMC.h>

#include "camera.h"
#include "flight_id.h"

namespace
{
  WebServer server(80);
  bool ready = false;
  bool sdReady = false;
  char photoDirectory[40] = "";
  uint32_t frames = 0;
  uint32_t photos = 0, photoErrors = 0, lastPhoto = 0;

  bool initializeStorage()
  {
    if (!CameraConfig::sdEnabled)
      return false;

    // Use the AI Thinker slot in 1-bit mode. Never auto-format a user's card.
    if (!SD_MMC.begin("/sdcard", true, false) || SD_MMC.cardType() == CARD_NONE)
    {
      Serial.println("Camera SD unavailable; Wi-Fi preview can continue.");
      return false;
    }
    if (!SD_MMC.exists("/photos") && !SD_MMC.mkdir("/photos"))
    {
      Serial.println("Cannot create camera SD /photos directory.");
      return false;
    }

    char name[40];
    if (!FlightId::reserveName(name, sizeof(name)))
    {
      Serial.println("Cannot reserve camera flight number in ESP32 Preferences.");
      return false;
    }
    snprintf(photoDirectory, sizeof(photoDirectory), "/photos/%s", name);
    if (SD_MMC.exists(photoDirectory))
    {
      Serial.println("Camera flight directory already exists; recording stopped. Check NVS reset.");
      return false;
    }
    if (!SD_MMC.mkdir(photoDirectory))
    {
      Serial.println("Cannot create camera SD flight directory.");
      return false;
    }
    Serial.printf("Camera SD photos: %s\n", photoDirectory);
    return true;
  }

  void recordPhoto()
  {
    if (!sdReady)
      return;
    lastPhoto = millis();
    // With one frame buffer, an idle camera may hold an older queued image.
    // Discard it so the stored photo comes from a new capture at this interval.
    camera_fb_t *previous = esp_camera_fb_get();
    if (previous)
      esp_camera_fb_return(previous);
    camera_fb_t *frame = esp_camera_fb_get();
    if (!frame)
    {
      ++photoErrors;
      Serial.println("SD photo capture failed; will retry at the next interval.");
      return;
    }

    char path[64];
    snprintf(path, sizeof(path), "%s/photo_%06lu.jpg", photoDirectory, (unsigned long)(photos + 1));
    File photo = SD_MMC.open(path, FILE_WRITE);
    bool saved = photo && photo.write(frame->buf, frame->len) == frame->len;
    if (photo)
      photo.close(); // Flush each image instead of keeping a file open between captures.
    esp_camera_fb_return(frame);

    if (saved)
    {
      ++photos;
      Serial.printf("SD photo saved: %s\n", path);
    }
    else
    {
      ++photoErrors;
      sdReady = false;
      SD_MMC.remove(path); // Do not leave a partial JPEG labelled as a saved image.
      Serial.println("SD photo write failed; recording stopped. Check card and free space.");
    }
  }

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

  sdReady = initializeStorage();
  recordPhoto(); // First image at startup; subsequent images do not require a client.

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
                          String("{\"camera\":true,\"frames\":") + frames + ",\"sd_ready\":" +
                              (sdReady ? "true" : "false") + ",\"photos_saved\":" + photos +
                              ",\"photo_errors\":" + photoErrors + "}");
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
  if (sdReady && millis() - lastPhoto >= CameraConfig::photoIntervalMs)
    recordPhoto();
  delay(2);
}
