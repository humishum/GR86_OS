#include <Arduino.h>
#include "driver/i2s.h"

// --- Pins (change if you wired differently)
static const int I2S_BCLK = 26;   // SCK
static const int I2S_LRCK = 25;   // WS
static const int I2S_DATA_IN = 34; // SD (from both mics, tied together)

// --- Audio settings
static const int SAMPLE_RATE = 48000;                   // 44.1k also fine
static const i2s_bits_per_sample_t BITS = I2S_BITS_PER_SAMPLE_32BIT; // INMP441: 24 bits in 32-bit slots
static const int FRAMES_PER_READ = 256;                 // stereo frames per i2s_read
static const int DECIMATE = 8;                          // print every Nth frame to avoid flooding serial

// Buffer holds stereo frames => 2 samples per frame
static int32_t i2s_buffer[FRAMES_PER_READ * 2];

void setup() {
  Serial.begin(921600);
  delay(200);

  // I2S config (RX, Philips I2S, 32-bit slots, stereo)
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = BITS,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,      // stereo frames (R then L in memory)
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 6,
    .dma_buf_len = FRAMES_PER_READ,                     // frames per DMA buffer
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };

  i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_BCLK,
    .ws_io_num = I2S_LRCK,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = I2S_DATA_IN
  };

  // Install and start
  if (i2s_driver_install(I2S_NUM_0, &i2s_config, 0, nullptr) != ESP_OK) {
    Serial.println("I2S install failed");
    while (1) delay(1000);
  }
  if (i2s_set_pin(I2S_NUM_0, &pin_config) != ESP_OK) {
    Serial.println("I2S set_pin failed");
    while (1) delay(1000);
  }
  // Lock sample rate/format explicitly
  i2s_set_clk(I2S_NUM_0, SAMPLE_RATE, BITS, I2S_CHANNEL_STEREO);

  // Optional: clear DMA buffers
  i2s_zero_dma_buffer(I2S_NUM_0);

  Serial.println("# ready: sending CSV lines as ch0,ch1");
}

void loop() {
  size_t bytes_read = 0;
  esp_err_t ok = i2s_read(I2S_NUM_0, (void*)i2s_buffer,
                          sizeof(i2s_buffer), &bytes_read, portMAX_DELAY);
  if (ok != ESP_OK || bytes_read == 0) return;

  // Number of 32-bit samples (stereo samples interleaved)
  int n_samples = bytes_read / sizeof(int32_t);

  // Walk in pairs: (ch0, ch1). With I2S_CHANNEL_FMT_RIGHT_LEFT the order in memory
  // is typically Right,Left. For a quick wiring test, just call them ch0,ch1.
  // INMP441 gives 24-bit data in the top bits of 32-bit slots.
  static int decim = 0;
  for (int i = 0; i + 1 < n_samples; i += 2) {
    if ((decim++ % DECIMATE) != 0) continue;

    int32_t s0 = i2s_buffer[i];     // 32-bit signed
    int32_t s1 = i2s_buffer[i + 1];

    // Shift to 24-bit range (sign-preserving). Many apps do >>8 for INMP441.
    s0 >>= 8;
    s1 >>= 8;

    // CSV output: ch0,ch1
    Serial.print(s0);
    Serial.print(',');
    Serial.println(s1);
  }
}
