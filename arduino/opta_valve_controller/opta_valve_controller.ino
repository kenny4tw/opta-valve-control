#include <Arduino.h>
#include <Ethernet.h>
#include "OptaBlue.h"

using namespace Opta;

// Network settings. Use static IP fallback if DHCP is unavailable.
byte MAC_ADDRESS[] = {0x02, 0xA1, 0xB2, 0xC3, 0xD4, 0xE5};
IPAddress STATIC_IP(192, 168, 1, 50);
IPAddress DNS_IP(8, 8, 8, 8);
IPAddress GATEWAY_IP(192, 168, 1, 1);
IPAddress SUBNET_MASK(255, 255, 255, 0);

EthernetServer server(80);

// AFX00007 mapping (adjust if your wiring uses different channels).
constexpr uint8_t EXPANSION_INDEX = 0;
constexpr uint8_t VALVE1_OUTPUT_CH = 0;  // O1
constexpr uint8_t VALVE2_OUTPUT_CH = 1;  // O2
constexpr uint8_t I1_FEEDBACK_CH = 0;    // I1
constexpr uint8_t I2_FEEDBACK_CH = 1;    // I2
constexpr uint8_t I3_FLOW_CH = 2;        // I3
constexpr uint8_t I4_LEVEL_CH = 3;       // I4

constexpr float VALVE1_MIN_MA = 4.0f;
constexpr float VALVE1_MAX_MA = 20.0f;
constexpr float VALVE2_MIN_MA = 18.0f;
constexpr float VALVE2_MAX_MA = 20.0f;

constexpr unsigned long SENSOR_UPDATE_MS = 250;

AnalogExpansion analogExp;
bool expansionReady = false;

float valve1CmdmA = 4.0f;   // Default closed.
float valve2CmdmA = 20.0f;  // Default open.
bool running = true;

float i1mA = 0.0f;
float i2mA = 0.0f;
float i3mA = 0.0f;
float i4mA = 0.0f;
unsigned long lastSensorRead = 0;

float clampf(float value, float low, float high) {
  if (value < low) {
    return low;
  }
  if (value > high) {
    return high;
  }
  return value;
}

float mapCurrent(float milliAmp, float outMin, float outMax) {
  float clamped = clampf(milliAmp, 4.0f, 20.0f);
  return outMin + ((clamped - 4.0f) / 16.0f) * (outMax - outMin);
}

void trySetupExpansion() {
  analogExp = OptaController.getExpansion(EXPANSION_INDEX);
  if (!analogExp) {
    expansionReady = false;
    return;
  }

  analogExp.beginChannelAsCurrentDac(VALVE1_OUTPUT_CH);
  analogExp.beginChannelAsCurrentDac(VALVE2_OUTPUT_CH);

  analogExp.beginChannelAsAdc(I1_FEEDBACK_CH, OA_CURRENT_ADC, false, false, false, 0);
  analogExp.beginChannelAsAdc(I2_FEEDBACK_CH, OA_CURRENT_ADC, false, false, false, 0);
  analogExp.beginChannelAsAdc(I3_FLOW_CH, OA_CURRENT_ADC, false, false, false, 0);
  analogExp.beginChannelAsAdc(I4_LEVEL_CH, OA_CURRENT_ADC, false, false, false, 0);

  expansionReady = true;
}

void applyOutputs() {
  if (!expansionReady) {
    return;
  }

  float out1 = running ? clampf(valve1CmdmA, VALVE1_MIN_MA, VALVE1_MAX_MA) : VALVE1_MIN_MA;
  float out2 = running ? clampf(valve2CmdmA, VALVE2_MIN_MA, VALVE2_MAX_MA) : 20.0f;

  analogExp.pinCurrent(VALVE1_OUTPUT_CH, out1);
  analogExp.pinCurrent(VALVE2_OUTPUT_CH, out2);
}

void readInputs() {
  if (!expansionReady) {
    return;
  }

  analogExp.updateAnalogInputs();
  i1mA = analogExp.pinCurrent(I1_FEEDBACK_CH, false);
  i2mA = analogExp.pinCurrent(I2_FEEDBACK_CH, false);
  i3mA = analogExp.pinCurrent(I3_FLOW_CH, false);
  i4mA = analogExp.pinCurrent(I4_LEVEL_CH, false);
}

float parseJsonFloat(const String &json, const char *key, bool *found) {
  String token = String("\"") + key + String("\"");
  int keyPos = json.indexOf(token);
  if (keyPos < 0) {
    *found = false;
    return 0.0f;
  }

  int colonPos = json.indexOf(':', keyPos + token.length());
  if (colonPos < 0) {
    *found = false;
    return 0.0f;
  }

  int start = colonPos + 1;
  while (start < (int)json.length() && (json[start] == ' ' || json[start] == '\t' || json[start] == '\r' || json[start] == '\n')) {
    start++;
  }

  int end = start;
  while (end < (int)json.length()) {
    char c = json[end];
    bool numberChar = (c >= '0' && c <= '9') || c == '.' || c == '-' || c == '+' || c == 'e' || c == 'E';
    if (!numberChar) {
      break;
    }
    end++;
  }

  if (end <= start) {
    *found = false;
    return 0.0f;
  }

  *found = true;
  return json.substring(start, end).toFloat();
}

bool parseJsonBool(const String &json, const char *key, bool *found) {
  String token = String("\"") + key + String("\"");
  int keyPos = json.indexOf(token);
  if (keyPos < 0) {
    *found = false;
    return false;
  }

  int colonPos = json.indexOf(':', keyPos + token.length());
  if (colonPos < 0) {
    *found = false;
    return false;
  }

  int start = colonPos + 1;
  while (start < (int)json.length() && (json[start] == ' ' || json[start] == '\t' || json[start] == '\r' || json[start] == '\n')) {
    start++;
  }

  if (json.startsWith("true", start)) {
    *found = true;
    return true;
  }
  if (json.startsWith("false", start)) {
    *found = true;
    return false;
  }

  *found = false;
  return false;
}

void updateControlFromJson(const String &body) {
  bool found = false;

  float v1 = parseJsonFloat(body, "valve1_cmd_mA", &found);
  if (found) {
    valve1CmdmA = clampf(v1, VALVE1_MIN_MA, VALVE1_MAX_MA);
  }

  float v2 = parseJsonFloat(body, "valve2_cmd_mA", &found);
  if (found) {
    valve2CmdmA = clampf(v2, VALVE2_MIN_MA, VALVE2_MAX_MA);
  }

  bool runVal = parseJsonBool(body, "running", &found);
  if (found) {
    running = runVal;
  }

  applyOutputs();
}

String controlJson() {
  String json = "{";
  json += "\"running\":" + String(running ? "true" : "false");
  json += ",\"valve1_cmd_mA\":" + String(clampf(valve1CmdmA, VALVE1_MIN_MA, VALVE1_MAX_MA), 3);
  json += ",\"valve2_cmd_mA\":" + String(clampf(valve2CmdmA, VALVE2_MIN_MA, VALVE2_MAX_MA), 3);
  json += "}";
  return json;
}

String dataJson() {
  float flowLS = mapCurrent(i3mA, 0.0f, 300.0f);

  String json = "{";
  json += "\"i1_mA\":" + String(i1mA, 3);
  json += ",\"i2_mA\":" + String(i2mA, 3);
  json += ",\"i3_mA\":" + String(i3mA, 3);
  json += ",\"i4_mA\":" + String(i4mA, 3);
  json += ",\"flow_l_s\":" + String(flowLS, 3);
  json += ",\"valve1_cmd_mA\":" + String(clampf(valve1CmdmA, VALVE1_MIN_MA, VALVE1_MAX_MA), 3);
  json += ",\"valve2_cmd_mA\":" + String(clampf(valve2CmdmA, VALVE2_MIN_MA, VALVE2_MAX_MA), 3);
  json += ",\"running\":" + String(running ? "true" : "false");
  json += "}";
  return json;
}

String readRequest(EthernetClient &client, unsigned long timeoutMs = 1500) {
  unsigned long start = millis();
  String request;

  while (client.connected() && (millis() - start) < timeoutMs) {
    while (client.available()) {
      char c = (char)client.read();
      request += c;
      if (request.length() > 4096) {
        return request;
      }
    }

    if (request.indexOf("\r\n\r\n") >= 0) {
      int contentLength = 0;
      int clPos = request.indexOf("Content-Length:");
      if (clPos >= 0) {
        int lineEnd = request.indexOf("\r\n", clPos);
        if (lineEnd > clPos) {
          String clValue = request.substring(clPos + 15, lineEnd);
          clValue.trim();
          contentLength = clValue.toInt();
        }
      }

      int bodyPos = request.indexOf("\r\n\r\n") + 4;
      while (((int)request.length() - bodyPos) < contentLength && client.connected() && (millis() - start) < timeoutMs) {
        while (client.available()) {
          request += (char)client.read();
        }
      }
      return request;
    }
  }

  return request;
}

void sendJson(EthernetClient &client, int code, const String &body) {
  client.print("HTTP/1.1 ");
  client.print(code);
  client.println(code == 200 ? " OK" : " ERROR");
  client.println("Content-Type: application/json");
  client.print("Content-Length: ");
  client.println(body.length());
  client.println("Connection: close");
  client.println();
  client.print(body);
}

void handleHttp() {
  EthernetClient client = server.available();
  if (!client) {
    return;
  }

  String request = readRequest(client);
  if (request.length() == 0) {
    client.stop();
    return;
  }

  int firstLineEnd = request.indexOf("\r\n");
  String firstLine = firstLineEnd > 0 ? request.substring(0, firstLineEnd) : request;

  bool isGetData = firstLine.startsWith("GET /data.json");
  bool isGetControl = firstLine.startsWith("GET /control.json");
  bool isPostControl = firstLine.startsWith("POST /control.json");

  if (isGetData) {
    sendJson(client, 200, dataJson());
  } else if (isGetControl) {
    sendJson(client, 200, controlJson());
  } else if (isPostControl) {
    int bodyPos = request.indexOf("\r\n\r\n");
    String body = bodyPos >= 0 ? request.substring(bodyPos + 4) : String("");
    updateControlFromJson(body);
    sendJson(client, 200, controlJson());
  } else {
    sendJson(client, 404, String("{\"error\":\"not found\"}"));
  }

  delay(1);
  client.stop();
}

void setup() {
  Serial.begin(115200);
  delay(1500);

  OptaController.begin();
  trySetupExpansion();
  applyOutputs();

  if (Ethernet.begin(MAC_ADDRESS) == 0) {
    Ethernet.begin(MAC_ADDRESS, STATIC_IP, DNS_IP, GATEWAY_IP, SUBNET_MASK);
  }

  server.begin();
  Serial.print("Opta valve controller online at IP: ");
  Serial.println(Ethernet.localIP());
}

void loop() {
  OptaController.update();

  if (!expansionReady) {
    static unsigned long lastRetry = 0;
    if (millis() - lastRetry > 2000) {
      lastRetry = millis();
      trySetupExpansion();
      applyOutputs();
    }
  }

  if (millis() - lastSensorRead >= SENSOR_UPDATE_MS) {
    lastSensorRead = millis();
    readInputs();
  }

  handleHttp();
}
