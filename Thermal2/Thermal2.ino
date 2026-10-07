#include <SPI.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <Adafruit_MLX90640.h>

// Display pin definitions for DIYmore ESP32 ST7789 boards
#define TFT_CS    15
#define TFT_DC    2
#define TFT_RST   4
#define TFT_BL    32  

Adafruit_ST7789 tft = Adafruit_ST7789(&SPI, TFT_CS, TFT_DC, TFT_RST);
Adafruit_MLX90640 mlx;

// MLX90640 Frame Buffer (32 x 24 = 768 pixels)
float frame[768]; 

// UI Layout Constants for Smooth Interpolated View
const int imgX = 10;
const int imgY = 15;
const int targetWidth = 160;  // Smooth rendering width
const int targetHeight = 120; // Smooth rendering height

void setup() {
  Serial.begin(500000); // Increased baud rate for fast 2D serial streaming
  Wire.begin();
  Wire.setClock(1000000); // 1MHz I2C fast mode

  pinMode(TFT_BL, OUTPUT);
  digitalWrite(TFT_BL, HIGH);

  tft.init(170, 320);
  tft.setRotation(1);
  tft.fillScreen(ST77XX_BLACK);

  tft.setFont(); 
  tft.setTextColor(ST77XX_WHITE);
  tft.setTextSize(2);
  tft.setCursor(20, 70);
  tft.println("Initialising Thermal Camera...");

  if (!mlx.begin(MLX90640_I2CADDR_DEFAULT, &Wire)) {
    Serial.println("MLX90640 thermal camera not found!");
    tft.fillScreen(ST77XX_BLACK);
    tft.setCursor(20, 70);
    tft.setTextColor(ST77XX_RED);
    tft.println("Sensor Missing!");
    while (1) { delay(1000); }
  } else {
    mlx.setMode(MLX90640_CHESS);
    mlx.setRefreshRate(MLX90640_8_HZ);
  }

  tft.fillScreen(ST77XX_BLACK);
  
  // Draw static UI borders and labels
  tft.drawRect(imgX - 1, imgY - 1, targetWidth + 2, targetHeight + 2, ST77XX_WHITE);
  
  tft.setTextSize(1);
  tft.setCursor(185, 15);
  tft.setTextColor(ST77XX_CYAN);
  tft.print("THERMAL CAM");

  tft.setCursor(185, 40);
  tft.setTextColor(ST77XX_RED);
  tft.print("MAX:");

  tft.setCursor(185, 80);
  tft.setTextColor(0x07FF); // Cyan
  tft.print("MIN:");

  tft.setCursor(185, 120);
  tft.setTextColor(ST77XX_GREEN);
  tft.print("CENTRE:");
}

// Smooth colour interpolation helper
uint16_t interpolateColor(uint16_t c1, uint16_t c2, float mix) {
  uint8_t r1 = (c1 >> 11) & 0x1F;
  uint8_t g1 = (c1 >> 5) & 0x3F;
  uint8_t b1 = c1 & 0x1F;
  
  uint8_t r2 = (c2 >> 11) & 0x1F;
  uint8_t g2 = (c2 >> 5) & 0x3F;
  uint8_t b2 = c2 & 0x1F;

  uint8_t r = r1 + (int)((r2 - r1) * mix);
  uint8_t g = g1 + (int)((g2 - g1) * mix);
  uint8_t b = b1 + (int)((b2 - b1) * mix);

  return (r << 11) | (g << 5) | b;
}

// Ironbow/Thermal colour map: Black -> Blue -> Magenta -> Red -> Yellow -> White
uint16_t getThermalColor(float temp, float minT, float maxT) {
  if (maxT <= minT) maxT = minT + 1.0f;
  float norm = (temp - minT) / (maxT - minT);
  if (norm < 0.0f) norm = 0.0f;
  if (norm > 1.0f) norm = 1.0f;

  if (norm < 0.2f) {
    return interpolateColor(0x0000, 0x001F, norm * 5.0f);       // Black -> Blue
  } else if (norm < 0.4f) {
    return interpolateColor(0x001F, 0xF81F, (norm - 0.2f) * 5.0f); // Blue -> Magenta
  } else if (norm < 0.7f) {
    return interpolateColor(0xF81F, 0xF800, (norm - 0.4f) * 3.33f);// Magenta -> Red
  } else if (norm < 0.9f) {
    return interpolateColor(0xF800, 0xFFE0, (norm - 0.7f) * 5.0f); // Red -> Yellow
  } else {
    return interpolateColor(0xFFE0, 0xFFFF, (norm - 0.9f) * 10.0f);// Yellow -> White
  }
}

void loop() {
  if (mlx.getFrame(frame) != 0) {
    return; 
  }

  // Calculate min and max temperatures in the frame
  float minTemp = 100.0;
  float maxTemp = -100.0;
  for (int i = 0; i < 768; i++) {
    if (frame[i] < minTemp) minTemp = frame[i];
    if (frame[i] > maxTemp) maxTemp = frame[i];
  }

  // Get centre pixel temperature
  float centreTemp = frame[11 * 32 + 15];

  // --- Render Smooth Bilinearly Interpolated Thermal Image ---
  tft.startWrite(); // Begin SPI transaction for fast pixel pushing
  for (int py = 0; py < targetHeight; py++) {
    // Map screen Y to sensor vertical grid with inversion
    float vf = (float)(targetHeight - 1 - py) / (targetHeight - 1) * 23.0f;
    int sy0 = (int)vf;
    int sy1 = (sy0 < 23) ? sy0 + 1 : 23;
    float sdy = vf - sy0;

    for (int px = 0; px < targetWidth; px++) {
      // Map screen X to sensor horizontal grid
      float u = (float)px / (targetWidth - 1) * 31.0f;
      int x0 = (int)u;
      int x1 = (x0 < 31) ? x0 + 1 : 31;
      float dx = u - x0;

      // Fetch 4 surrounding native sensor pixels
      float t00 = frame[sy0 * 32 + x0];
      float t10 = frame[sy0 * 32 + x1];
      float t01 = frame[sy1 * 32 + x0];
      float t11 = frame[sy1 * 32 + x1];

      // Bilinear interpolation formula
      float t_top = t00 * (1.0f - dx) + t10 * dx;
      float t_bot = t01 * (1.0f - dx) + t11 * dx;
      float temp = t_top * (1.0f - sdy) + t_bot * sdy;

      uint16_t colour = getThermalColor(temp, minTemp, maxTemp);
      tft.writePixel(imgX + px, imgY + py, colour);
    }
  }
  tft.endWrite(); // End SPI transaction

  // Draw crosshair at the centre
  int crossX = imgX + (targetWidth / 2);
  int crossY = imgY + (targetHeight / 2);
  tft.drawFastHLine(crossX - 4, crossY, 9, ST77XX_WHITE);
  tft.drawFastVLine(crossX, crossY - 4, 9, ST77XX_WHITE);

  // --- Update Sidebar Telemetry Readouts ---
  tft.fillRect(185, 55, 120, 16, ST77XX_BLACK);
  tft.setCursor(185, 55);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_RED);
  char buf[16];
  sprintf(buf, "%.1f C", maxTemp);
  tft.print(buf);

  tft.fillRect(185, 95, 120, 16, ST77XX_BLACK);
  tft.setCursor(185, 95);
  tft.setTextColor(0x07FF);
  sprintf(buf, "%.1f C", minTemp);
  tft.print(buf);

  tft.fillRect(185, 135, 120, 16, ST77XX_BLACK);
  tft.setCursor(185, 135);
  tft.setTextColor(ST77XX_GREEN);
  sprintf(buf, "%.1f C", centreTemp);
  tft.print(buf);

  // Draw vertical colour legend bar on the far right edge
  int barX = 305;
  int barY = 15;
  int barHeight = 120;
  for (int y = 0; y < barHeight; y++) {
    float norm = 1.0f - ((float)y / (float)barHeight);
    uint16_t barColour = getThermalColor(minTemp + norm * (maxTemp - minTemp), minTemp, maxTemp);
    tft.drawFastHLine(barX, barY + y, 10, barColour);
  }
  tft.drawRect(barX - 1, barY - 1, 12, barHeight + 2, ST77XX_WHITE);

  // --- Stream Raw 768-Pixel Frame over Serial for Python ---
  Serial.println("FRAME_START");
  for (int i = 0; i < 768; i++) {
    Serial.print(frame[i], 2);
    if (i < 767) {
      Serial.print(",");
    }
  }
  Serial.println("\nFRAME_END");
}