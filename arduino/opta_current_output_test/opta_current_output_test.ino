#include <Arduino.h>
#include "OptaBlue.h"

using namespace Opta;

// Finder/Arduino Opta analog expansion diagnostic sketch for 4-20 mA outputs.
// Bench test recommendation:
//   O1+ ---- 250 ohm resistor ---- O1-
//   O2+ ---- 250 ohm resistor ---- O2-
// Expected measured voltage across the resistor:
//   4 mA  -> about 1.00 V
//   12 mA -> about 3.00 V
//   20 mA -> about 5.00 V

constexpr uint8_t EXPANSION_INDEX = 0;

// Current DAC channels according to Arduino Opta analog expansion examples.
constexpr uint8_t OUTPUT1_CHANNEL = 4;
constexpr uint8_t OUTPUT2_CHANNEL = 5;

constexpr unsigned long STEP_HOLD_MS = 8000;

AnalogExpansion analog_expansion;
bool expansion_ready = false;
unsigned long last_step_change_ms = 0;
uint8_t step_index = 0;
bool auto_cycle_enabled = true;

const float TEST_LEVELS_MA[] = {4.0f, 12.0f, 20.0f};
const uint8_t CANDIDATE_OUTPUT_CHANNELS[] = {4, 5, 6, 7};


bool setupExpansion() {
  analog_expansion = OptaController.getExpansion(EXPANSION_INDEX);
  if (!analog_expansion) {
    return false;
  }

  for (uint8_t channel : CANDIDATE_OUTPUT_CHANNELS) {
    analog_expansion.beginChannelAsCurrentDac(channel);
  }

  return true;
}


void applyOutputs(float milli_amp) {
  analog_expansion.pinCurrent(OUTPUT1_CHANNEL, milli_amp);
  analog_expansion.pinCurrent(OUTPUT2_CHANNEL, milli_amp);

  Serial.print("Applied ");
  Serial.print(milli_amp, 3);
  Serial.println(" mA to O1 and O2 test outputs");
}


void applySingleChannel(uint8_t channel, float milli_amp) {
  for (uint8_t candidate : CANDIDATE_OUTPUT_CHANNELS) {
    analog_expansion.pinCurrent(candidate, 4.0f);
  }

  analog_expansion.pinCurrent(channel, milli_amp);

  Serial.print("Applied ");
  Serial.print(milli_amp, 3);
  Serial.print(" mA on internal channel ");
  Serial.println(channel);
}


void printInstructions() {
  Serial.println();
  Serial.println("=== Opta current output test ===");
  Serial.println("Wiring for bench test:");
  Serial.println("  O1+ ---- 250 ohm ---- O1-");
  Serial.println("  O2+ ---- 250 ohm ---- O2-");
  Serial.println("Measure voltage across the resistor.");
  Serial.println("Expected values:");
  Serial.println("  4 mA  -> about 1.00 V");
  Serial.println("  12 mA -> about 3.00 V");
  Serial.println("  20 mA -> about 5.00 V");
  Serial.println();
  Serial.println("Serial commands:");
  Serial.println("  4  -> set both outputs to 4.0 mA");
  Serial.println("  12 -> set both outputs to 12.0 mA");
  Serial.println("  20 -> set both outputs to 20.0 mA");
  Serial.println("  a  -> resume automatic cycle 4/12/20 mA");
  Serial.println("  s  -> stop automatic cycle and hold current values");
  Serial.println("  c4 -> set only internal channel 4 to 20.0 mA");
  Serial.println("  c5 -> set only internal channel 5 to 20.0 mA");
  Serial.println("  c6 -> set only internal channel 6 to 20.0 mA");
  Serial.println("  c7 -> set only internal channel 7 to 20.0 mA");
  Serial.println();
}


void handleSerialCommand() {
  if (!Serial.available()) {
    return;
  }

  String cmd = Serial.readStringUntil('\n');
  cmd.trim();

  if (cmd.equals("4")) {
    auto_cycle_enabled = false;
    applyOutputs(4.0f);
  } else if (cmd.equals("12")) {
    auto_cycle_enabled = false;
    applyOutputs(12.0f);
  } else if (cmd.equals("20")) {
    auto_cycle_enabled = false;
    applyOutputs(20.0f);
  } else if (cmd.equalsIgnoreCase("a")) {
    auto_cycle_enabled = true;
    step_index = 0;
    last_step_change_ms = 0;
    Serial.println("Automatic cycle resumed");
  } else if (cmd.equalsIgnoreCase("s")) {
    auto_cycle_enabled = false;
    Serial.println("Automatic cycle stopped");
  } else if (cmd.equalsIgnoreCase("c4")) {
    auto_cycle_enabled = false;
    applySingleChannel(4, 20.0f);
  } else if (cmd.equalsIgnoreCase("c5")) {
    auto_cycle_enabled = false;
    applySingleChannel(5, 20.0f);
  } else if (cmd.equalsIgnoreCase("c6")) {
    auto_cycle_enabled = false;
    applySingleChannel(6, 20.0f);
  } else if (cmd.equalsIgnoreCase("c7")) {
    auto_cycle_enabled = false;
    applySingleChannel(7, 20.0f);
  } else {
    Serial.print("Unknown command: ");
    Serial.println(cmd);
  }
}


void setup() {
  Serial.begin(115200);
  delay(2000);

  Serial.println("Booting Opta current output test...");
  OptaController.begin();

  expansion_ready = setupExpansion();
  if (!expansion_ready) {
    Serial.println("Analog expansion not detected on index 0");
    Serial.println("Check the expansion connection and 24 V supply");
    return;
  }

  printInstructions();
  applyOutputs(TEST_LEVELS_MA[step_index]);
  last_step_change_ms = millis();
}


void loop() {
  OptaController.update();

  if (!expansion_ready) {
    static unsigned long last_retry_ms = 0;
    if (millis() - last_retry_ms >= 2000) {
      last_retry_ms = millis();
      expansion_ready = setupExpansion();
      if (expansion_ready) {
        printInstructions();
        applyOutputs(TEST_LEVELS_MA[step_index]);
        last_step_change_ms = millis();
      }
    }
    return;
  }

  handleSerialCommand();

  if (auto_cycle_enabled && millis() - last_step_change_ms >= STEP_HOLD_MS) {
    step_index = (step_index + 1) % (sizeof(TEST_LEVELS_MA) / sizeof(TEST_LEVELS_MA[0]));
    applyOutputs(TEST_LEVELS_MA[step_index]);
    last_step_change_ms = millis();
  }
}