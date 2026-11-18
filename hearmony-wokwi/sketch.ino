// Hearmony — Global Solution FIAP | Citizen Tech.
// O potenciômetro simula pontos de ruído; não mede decibéis.
// O ESP32 decide localmente e usa MQTT para trocar dados e limites.

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <cstring>
#define MQTT_USERNAME "esp32"
//#define MQTT_PASSWORD ""
//static const char MQTT_ROOT_CA[] = ;

// Entradas do potenciômetro e do botão.
constexpr uint8_t PIN_RUIDO = 34;
constexpr uint8_t PIN_BOTAO_SOM = 32;

// LEDs e buzzer para os alertas locais.
constexpr uint8_t PIN_LED_VERDE = 25;
constexpr uint8_t PIN_LED_AMARELO = 26;
constexpr uint8_t PIN_LED_VERMELHO = 27;
constexpr uint8_t PIN_BUZZER = 18;

constexpr char WIFI_SSID[] = "Wokwi-GUEST";
constexpr char WIFI_PASSWORD[] = "";
constexpr char MQTT_HOST[] = "h6ee1016.ala.us-east-1.emqxsl.com";
constexpr uint16_t MQTT_PORT = 8883;
constexpr char MQTT_CLIENT_ID[] = "hearmony-01";
constexpr char MQTT_TELEMETRY_TOPIC[] = "hearmony/device/hearmony-01/telemetry";
constexpr char MQTT_COMMAND_TOPIC[] = "hearmony/device/hearmony-01/commands";

WiFiClientSecure mqttTlsClient;
PubSubClient mqttClient(mqttTlsClient);

constexpr uint32_t INTERVALO_LEITURA_MS = 100;
constexpr uint32_t INTERVALO_PUBLICACAO_MS = 5000;
constexpr uint32_t INTERVALO_RECONEXAO_MS = 5000;
constexpr uint32_t DEBOUNCE_MS = 40;
constexpr int MARGEM_ATENCAO = 10;
constexpr int MARGEM_RETORNO = 5;

// Estados usados para classificar a escala simulada.
enum EstadoRuido : uint8_t { CONFORTO, ATENCAO, PROTECAO };

EstadoRuido estadoAtual = CONFORTO;
bool alertaSonoroHabilitado = true;
bool primeiraLeitura = true;
bool leituraBotaoAnterior = HIGH;
bool estadoBotaoEstavel = HIGH;
bool wifiConectadoAnterior = false;
uint32_t ultimaMudancaBotaoMs = 0;
uint32_t ultimaLeituraMs = 0;
uint32_t ultimaPublicacaoMs = 0;
uint32_t ultimaTentativaWifiMs = 0;
uint32_t ultimaTentativaMqttMs = 0;
int ruidoAtual = 0;
int limiteAtual = 70;

const char* nomeEstado(EstadoRuido estado) {
  switch (estado) {
    case ATENCAO: return "atencao";
    case PROTECAO: return "protecao";
    default: return "conforto";
  }
}

void aplicarLimite(int novoLimite) {
  if (novoLimite < 55 || novoLimite > 85) {
    Serial.printf("Comando ignorado: limite fora da faixa (55-85): %d\n", novoLimite);
    return;
  }
  limiteAtual = novoLimite;
  Serial.printf("Novo limite recebido por MQTT: %d pontos.\n", limiteAtual);
}

// Valida e aplica o limite recebido no tópico de comandos.
void receberMensagem(char* topic, byte* payload, unsigned int length) {
  if (String(topic) != MQTT_COMMAND_TOPIC || length == 0 || length > 256) return;
  String body;
  body.reserve(length);
  for (unsigned int i = 0; i < length; i++) body += static_cast<char>(payload[i]);

  const int campo = body.indexOf("\"threshold\"");
  if (campo < 0) return;
  const int separador = body.indexOf(':', campo);
  if (separador < 0) return;
  aplicarLimite(body.substring(separador + 1).toInt());
}

void manterConexaoMqtt(uint32_t agora) {
  if (WiFi.status() != WL_CONNECTED) return;
  mqttClient.loop();
  if (mqttClient.connected()
      || agora - ultimaTentativaMqttMs < INTERVALO_RECONEXAO_MS) {
    return;
  }
  ultimaTentativaMqttMs = agora;

  if (strlen(MQTT_ROOT_CA) == 0) {
    Serial.println("MQTT: configure o certificado CA no firmware.");
    return;
  }
  if (strlen(MQTT_USERNAME) == 0 || strlen(MQTT_PASSWORD) == 0) {
    Serial.println("MQTT: preencha usuário e senha no firmware.");
    return;
  }

  Serial.printf("MQTT: conectando a %s:%u...\n", MQTT_HOST, MQTT_PORT);
  if (mqttClient.connect(MQTT_CLIENT_ID, MQTT_USERNAME, MQTT_PASSWORD)) {
    Serial.println("MQTT conectado.");
    if (!mqttClient.subscribe(MQTT_COMMAND_TOPIC)) {
      Serial.println("MQTT: falha ao assinar o tópico de comandos.");
    } else {
      Serial.printf("MQTT: aguardando comandos em %s.\n", MQTT_COMMAND_TOPIC);
    }
  } else {
    Serial.printf("MQTT: conexão falhou (estado %d).\n", mqttClient.state());
  }
}

// Faz a média para reduzir pequenas oscilações da leitura analógica.
int lerMediaADC(uint8_t pino) {
  uint32_t soma = 0;
  constexpr uint8_t AMOSTRAS = 8;
  for (uint8_t i = 0; i < AMOSTRAS; i++) {
    soma += analogRead(pino);
    delay(2);
  }
  return soma / AMOSTRAS;
}

// Mantém a proteção até a leitura cair abaixo da margem de retorno.
EstadoRuido decidirEstado(int ruido, int limite, EstadoRuido anterior) {
  if (anterior == PROTECAO && ruido > limite - MARGEM_RETORNO) return PROTECAO;
  if (ruido >= limite) return PROTECAO;
  if (ruido >= limite - MARGEM_ATENCAO) return ATENCAO;
  return CONFORTO;
}

void atualizarIndicadores(EstadoRuido estado) {
  digitalWrite(PIN_LED_VERDE, estado == CONFORTO ? HIGH : LOW);
  digitalWrite(PIN_LED_AMARELO, estado == ATENCAO ? HIGH : LOW);
  digitalWrite(PIN_LED_VERMELHO, estado == PROTECAO ? HIGH : LOW);
}

void tocarAlerta(EstadoRuido novoEstado) {
  if (!alertaSonoroHabilitado) return;
  if (novoEstado == ATENCAO) tone(PIN_BUZZER, 520, 80);
  else if (novoEstado == PROTECAO) tone(PIN_BUZZER, 660, 220);
  else tone(PIN_BUZZER, 440, 70);
}

// Alterna o buzzer e filtra oscilações mecânicas do botão.
void tratarBotaoSom(uint32_t agora) {
  const bool leituraAtual = digitalRead(PIN_BOTAO_SOM);
  if (leituraAtual != leituraBotaoAnterior) {
    ultimaMudancaBotaoMs = agora;
    leituraBotaoAnterior = leituraAtual;
  }
  if ((agora - ultimaMudancaBotaoMs) >= DEBOUNCE_MS
      && leituraAtual != estadoBotaoEstavel) {
    estadoBotaoEstavel = leituraAtual;
    if (estadoBotaoEstavel == LOW) {
      alertaSonoroHabilitado = !alertaSonoroHabilitado;
      Serial.printf(
          "Alerta sonoro: %s\n",
          alertaSonoroHabilitado ? "habilitado" : "silenciado"
      );
    }
  }
}

void iniciarWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD, 6);
  ultimaTentativaWifiMs = millis();
  Serial.println("Wi-Fi Wokwi-GUEST: conectando...");
}

void manterConexaoWiFi(uint32_t agora) {
  const wl_status_t status = WiFi.status();
  if (status == WL_CONNECTED) {
    if (!wifiConectadoAnterior) {
      Serial.print("Wi-Fi conectado; IP: ");
      Serial.println(WiFi.localIP());
    }
    wifiConectadoAnterior = true;
    return;
  }
  if (wifiConectadoAnterior) {
    Serial.println("Wi-Fi desconectado; decisão local segue ativa.");
  }
  wifiConectadoAnterior = false;
  if (agora - ultimaTentativaWifiMs >= INTERVALO_RECONEXAO_MS) {
    ultimaTentativaWifiMs = agora;
    WiFi.reconnect();
  }
}

// Publica a leitura atual sem interromper as decisões locais.
void publicarTelemetria() {
  const bool ancSimulado = (estadoAtual == PROTECAO);
  char payload[180];
  snprintf(
      payload,
      sizeof(payload),
      "{\"device\":\"hearmony-01\",\"noise\":%d,\"threshold\":%d,"
      "\"state\":\"%s\",\"anc_simulado\":%s,\"alert_sound\":%s,"
      "\"unit\":\"pontos\"}",
      ruidoAtual,
      limiteAtual,
      nomeEstado(estadoAtual),
      ancSimulado ? "true" : "false",
      alertaSonoroHabilitado ? "true" : "false"
  );

  Serial.printf(
      "Ruído: %d/100 | limite: %d | estado: %s | ANC simulado: %s\n",
      ruidoAtual,
      limiteAtual,
      nomeEstado(estadoAtual),
      ancSimulado ? "ATIVO" : "inativo"
  );
  if (mqttClient.connected()) {
    if (mqttClient.publish(MQTT_TELEMETRY_TOPIC, payload, true)) {
      Serial.println("Telemetria publicada via MQTT.");
    } else {
      Serial.println(
          "MQTT: falha ao publicar telemetria; "
          "controle local segue funcionando."
      );
    }
  } else {
    Serial.println("MQTT indisponível; controle local segue funcionando.");
  }
}

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  pinMode(PIN_LED_VERDE, OUTPUT);
  pinMode(PIN_LED_AMARELO, OUTPUT);
  pinMode(PIN_LED_VERMELHO, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_BOTAO_SOM, INPUT_PULLUP);
  atualizarIndicadores(CONFORTO);

  if (strlen(MQTT_ROOT_CA) > 0) mqttTlsClient.setCACert(MQTT_ROOT_CA);

  mqttTlsClient.setTimeout(3);
  mqttClient.setServer(MQTT_HOST, MQTT_PORT);
  mqttClient.setCallback(receberMensagem);
  mqttClient.setBufferSize(256);
  mqttClient.setKeepAlive(30);

  Serial.println("Hearmony iniciado: decisão de ruído executada localmente.");
  Serial.println("A escala simulada não representa dB nem cancelamento real.");
  iniciarWiFi();
}

void loop() {
  const uint32_t agora = millis();
  tratarBotaoSom(agora);
  manterConexaoWiFi(agora);
  manterConexaoMqtt(agora);

  if (agora - ultimaLeituraMs >= INTERVALO_LEITURA_MS) {
    ultimaLeituraMs = agora;
    const int ruidoADC = lerMediaADC(PIN_RUIDO);
    ruidoAtual = map(ruidoADC, 0, 4095, 0, 100);
    const EstadoRuido novoEstado = decidirEstado(ruidoAtual, limiteAtual, estadoAtual);
    if (primeiraLeitura || novoEstado != estadoAtual) {
      if (!primeiraLeitura) tocarAlerta(novoEstado);
      estadoAtual = novoEstado;
      atualizarIndicadores(estadoAtual);
      Serial.printf("Mudança de estado: %s\n", nomeEstado(estadoAtual));
      primeiraLeitura = false;
      publicarTelemetria();
      ultimaPublicacaoMs = millis();
    }
  }

  if (agora - ultimaPublicacaoMs >= INTERVALO_PUBLICACAO_MS) {
    ultimaPublicacaoMs = agora;
    publicarTelemetria();
  }
  delay(5);
}



