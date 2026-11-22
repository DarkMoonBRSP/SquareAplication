"""
ESPMAP - Gerador Estruturado de Código ESP32 para SQUARE EXTREME 0.1
Gera sketches completos em C++ / Arduino (.ino) com suporte a múltiplos sensores
(iguais ou distintos), conexão Wi-Fi com reconexão automática e publicação MQTT padronizada.
"""

import json
from datetime import datetime

# Catálogo de sensores suportados com bibliotecas necessárias, pinos e trecho de leitura
SENSORES_CATALOGO = {
    "dht22": {
        "nome": "DHT22 / AM2302 (Temperatura e Umidade)",
        "biblioteca": ["#include <DHT.h>"],
        "pinos": [{"nome": "pino_dados", "rotulo": "Pino de Dados (GPIO)", "padrao": 4}],
        "declaracao": "DHT dht_{chave}({pino_dados}, DHT22);",
        "setup": "dht_{chave}.begin();",
        "leitura": [
            "float t_{chave} = dht_{chave}.readTemperature();",
            "float u_{chave} = dht_{chave}.readHumidity();",
            "if (!isnan(t_{chave})) doc[\"{chave}_temperatura\"] = t_{chave};",
            "if (!isnan(u_{chave})) doc[\"{chave}_umidade\"] = u_{chave};"
        ]
    },
    "dht11": {
        "nome": "DHT11 (Temperatura e Umidade Básica)",
        "biblioteca": ["#include <DHT.h>"],
        "pinos": [{"nome": "pino_dados", "rotulo": "Pino de Dados (GPIO)", "padrao": 4}],
        "declaracao": "DHT dht_{chave}({pino_dados}, DHT11);",
        "setup": "dht_{chave}.begin();",
        "leitura": [
            "float t_{chave} = dht_{chave}.readTemperature();",
            "float u_{chave} = dht_{chave}.readHumidity();",
            "if (!isnan(t_{chave})) doc[\"{chave}_temperatura\"] = t_{chave};",
            "if (!isnan(u_{chave})) doc[\"{chave}_umidade\"] = u_{chave};"
        ]
    },
    "ds18b20": {
        "nome": "DS18B20 (Temperatura 1-Wire À Prova D'água)",
        "biblioteca": ["#include <OneWire.h>", "#include <DallasTemperature.h>"],
        "declaracao": "OneWire oneWire_{chave}({pino_dados});\nDallasTemperature sensor_{chave}(&oneWire_{chave});",
        "pinos": [{"nome": "pino_dados", "rotulo": "Pino 1-Wire (GPIO)", "padrao": 15}],
        "setup": "sensor_{chave}.begin();",
        "leitura": [
            "sensor_{chave}.requestTemperatures();",
            "float t_{chave} = sensor_{chave}.getTempCByIndex(0);",
            "if (t_{chave} != DEVICE_DISCONNECTED_C) doc[\"{chave}\"] = t_{chave};"
        ]
    },
    "hcsr04": {
        "nome": "HC-SR04 / JSN-SR04T (Nível / Distância Ultrassônica)",
        "biblioteca": [],
        "pinos": [
            {"nome": "pino_trigger", "rotulo": "Pino Trigger (GPIO)", "padrao": 5},
            {"nome": "pino_echo", "rotulo": "Pino Echo (GPIO)", "padrao": 18}
        ],
        "setup": "pinMode({pino_trigger}, OUTPUT);\npinMode({pino_echo}, INPUT);",
        "leitura": [
            "digitalWrite({pino_trigger}, LOW); delayMicroseconds(2);",
            "digitalWrite({pino_trigger}, HIGH); delayMicroseconds(10);",
            "digitalWrite({pino_trigger}, LOW);",
            "long duracao_{chave} = pulseIn({pino_echo}, HIGH, 30000);",
            "float dist_{chave} = (duracao_{chave} > 0) ? (duracao_{chave} * 0.0343 / 2.0) : -1.0;",
            "if (dist_{chave} >= 0) doc[\"{chave}\"] = dist_{chave};"
        ]
    },
    "analogico": {
        "nome": "Sensor Analógico ADC (Umidade Solo / LDR / Nível Resistivo)",
        "biblioteca": [],
        "pinos": [{"nome": "pino_adc", "rotulo": "Pino Analógico (ex: GPIO 34, 35, 36, 39)", "padrao": 34}],
        "setup": "pinMode({pino_adc}, INPUT);",
        "leitura": [
            "int leitura_{chave} = analogRead({pino_adc});",
            "float tensao_{chave} = (leitura_{chave} / 4095.0) * 3.3;",
            "float pct_{chave} = map(leitura_{chave}, 0, 4095, 0, 100);",
            "doc[\"{chave}_raw\"] = leitura_{chave};",
            "doc[\"{chave}\"] = pct_{chave};"
        ]
    },
    "acs712": {
        "nome": "ACS712 (Sensor de Corrente Elétrica)",
        "biblioteca": [],
        "pinos": [{"nome": "pino_adc", "rotulo": "Pino Analógico (ex: GPIO 34)", "padrao": 34}],
        "setup": "pinMode({pino_adc}, INPUT);",
        "leitura": [
            "int raw_{chave} = analogRead({pino_adc});",
            "float v_{chave} = (raw_{chave} / 4095.0) * 3.3;",
            "float corrente_{chave} = abs((v_{chave} - 1.65) / 0.066); // Modelo 30A (66mV/A)",
            "doc[\"{chave}\"] = corrente_{chave};"
        ]
    },
    "vazao": {
        "nome": "YF-S201 (Sensor de Vazão de Água / Pulsos)",
        "biblioteca": [],
        "pinos": [{"nome": "pino_pulso", "rotulo": "Pino de Interrupção (ex: GPIO 14)", "padrao": 14}],
        "declaracao": "volatile int pulsos_{chave} = 0;\nvoid IRAM_ATTR contaPulso_{chave}() { pulsos_{chave}++; }",
        "setup": "pinMode({pino_pulso}, INPUT_PULLUP);\nattachInterrupt(digitalPinToInterrupt({pino_pulso}), contaPulso_{chave}, RISING);",
        "leitura": [
            "float vazao_{chave} = (pulsos_{chave} / 7.5); // L/min",
            "pulsos_{chave} = 0;",
            "doc[\"{chave}\"] = vazao_{chave};"
        ]
    }
}

class ESPMAPManager:
    """Gerador de código C++ / Arduino e MicroPython para ESP32 (LAN HTTP direta ou MQTT)."""

    @staticmethod
    def obter_catalogo():
        return SENSORES_CATALOGO

    @staticmethod
    def _sensores_padrao(tipo):
        padroes = {
            "estufa": [
                {"tipo": "dht22", "chave": "sensor_ar", "nome": "DHT22 Estufa", "pino_dados": 4},
                {"tipo": "analogico", "chave": "umidade_solo", "nome": "Umidade Solo", "pino_adc": 34},
            ],
            "reservatorio": [
                {"tipo": "hcsr04", "chave": "nivel", "nome": "Sensor Nível Caixa", "pino_trigger": 5, "pino_echo": 18},
            ],
            "lixeira": [
                {"tipo": "hcsr04", "chave": "nivel_lixeira", "nome": "Sensor Enchimento", "pino_trigger": 5, "pino_echo": 18},
            ],
            "energia": [
                {"tipo": "acs712", "chave": "corrente", "nome": "Corrente AC", "pino_adc": 34},
            ],
            "consumo_agua": [
                {"tipo": "vazao", "chave": "vazao", "nome": "Fluxômetro Água", "pino_pulso": 14},
            ],
        }
        return padroes.get(tipo, [
            {"tipo": "dht22", "chave": "ambiente", "nome": "Sensor Principal", "pino_dados": 4},
        ])

    @staticmethod
    def _substituir_pinos(template_str, sensor_cfg, catalogo_entry, chave):
        res = template_str
        for p in catalogo_entry.get("pinos", []):
            nome_p = p["nome"]
            val_p = sensor_cfg.get(nome_p, p["padrao"])
            res = res.replace(f"{{{nome_p}}}", str(val_p))
        return res.replace("{chave}", chave)

    @staticmethod
    def _montar_arduino(sensores, includes_base):
        includes = set(includes_base)
        declaracoes = []
        setups = []
        leituras = []

        for idx, s in enumerate(sensores):
            tipo_s = s.get("tipo", "dht22")
            chave = s.get("chave", f"sensor_{idx+1}")
            cat = SENSORES_CATALOGO.get(tipo_s, SENSORES_CATALOGO["analogico"])

            for inc in cat.get("biblioteca", []):
                includes.add(inc)

            if "declaracao" in cat:
                declaracoes.append(ESPMAPManager._substituir_pinos(cat["declaracao"], s, cat, chave))

            if "setup" in cat:
                stp = ESPMAPManager._substituir_pinos(cat["setup"], s, cat, chave)
                setups.append(f"  // Setup: {s.get('nome', chave)}\n  " + stp.replace("\n", "\n  "))

            leit_block = [f"  // Leitura: {s.get('nome', chave)} ({tipo_s})"]
            for linha in cat.get("leitura", []):
                leit_block.append("  " + ESPMAPManager._substituir_pinos(linha, s, cat, chave))
            leituras.append("\n".join(leit_block))

        return (
            "\n".join(sorted(includes)),
            "\n".join(declaracoes),
            "\n".join(setups),
            "\n\n".join(leituras),
        )

    @staticmethod
    def _montar_micropython(sensores, extra_imports):
        imports = [
            "import network",
            "import time",
            "import ujson",
            "from machine import Pin, ADC, time_pulse_us",
        ] + list(extra_imports)
        inits = []
        leituras = []
        tem_dht = False
        tem_onewire = False

        for idx, s in enumerate(sensores):
            tipo_s = s.get("tipo", "dht22")
            chave = s.get("chave", f"sensor_{idx+1}")
            nome_s = s.get("nome", chave)

            if tipo_s in ("dht22", "dht11"):
                tem_dht = True
                pino = s.get("pino_dados", 4)
                classe = "DHT22" if tipo_s == "dht22" else "DHT11"
                inits.append(f"# {nome_s} ({classe})\ndht_{chave} = dht.{classe}(Pin({pino}))")
                leituras.append(f"""    # Leitura: {nome_s} ({tipo_s})
    try:
        dht_{chave}.measure()
        t = dht_{chave}.temperature()
        u = dht_{chave}.humidity()
        doc['{chave}_temperatura'] = round(float(t), 2)
        doc['{chave}_umidade'] = round(float(u), 2)
    except Exception as e:
        print('[Sensor] Erro {chave}:', e)""")

            elif tipo_s == "ds18b20":
                tem_onewire = True
                pino = s.get("pino_dados", 15)
                inits.append(f"# {nome_s} (DS18B20 1-Wire)\now_{chave} = onewire.OneWire(Pin({pino}))\nds_{chave} = ds18x20.DS18X20(ow_{chave})\nroms_{chave} = ds_{chave}.scan()")
                leituras.append(f"""    # Leitura: {nome_s} (ds18b20)
    try:
        if roms_{chave}:
            ds_{chave}.convert_temp()
            time.sleep_ms(750)
            doc['{chave}'] = round(float(ds_{chave}.read_temp(roms_{chave}[0])), 2)
    except Exception as e:
        print('[Sensor] Erro {chave}:', e)""")

            elif tipo_s == "hcsr04":
                p_trig = s.get("pino_trigger", 5)
                p_echo = s.get("pino_echo", 18)
                inits.append(f"# {nome_s} (Ultrassom HC-SR04)\ntrig_{chave} = Pin({p_trig}, Pin.OUT)\necho_{chave} = Pin({p_echo}, Pin.IN)")
                leituras.append(f"""    # Leitura: {nome_s} (hcsr04)
    try:
        trig_{chave}.value(0)
        time.sleep_us(2)
        trig_{chave}.value(1)
        time.sleep_us(10)
        trig_{chave}.value(0)
        dur_{chave} = time_pulse_us(echo_{chave}, 1, 30000)
        if dur_{chave} > 0:
            doc['{chave}'] = round((dur_{chave} * 0.0343) / 2.0, 2)
    except Exception as e:
        print('[Sensor] Erro {chave}:', e)""")

            elif tipo_s == "analogico":
                p_adc = s.get("pino_adc", 34)
                inits.append(f"# {nome_s} (Analógico ADC)\nadc_{chave} = ADC(Pin({p_adc}))\nadc_{chave}.atten(ADC.ATTN_11DB)")
                leituras.append(f"""    # Leitura: {nome_s} (analogico)
    try:
        raw_{chave} = adc_{chave}.read()
        doc['{chave}_raw'] = raw_{chave}
        doc['{chave}'] = round((raw_{chave} / 4095.0) * 100.0, 1)
    except Exception as e:
        print('[Sensor] Erro {chave}:', e)""")

            elif tipo_s == "acs712":
                p_adc = s.get("pino_adc", 34)
                inits.append(f"# {nome_s} (ACS712 Corrente)\nadc_{chave} = ADC(Pin({p_adc}))\nadc_{chave}.atten(ADC.ATTN_11DB)")
                leituras.append(f"""    # Leitura: {nome_s} (acs712)
    try:
        raw_{chave} = adc_{chave}.read()
        v_{chave} = (raw_{chave} / 4095.0) * 3.3
        doc['{chave}'] = round(abs((v_{chave} - 1.65) / 0.066), 2)
    except Exception as e:
        print('[Sensor] Erro {chave}:', e)""")

            elif tipo_s == "vazao":
                p_pulso = s.get("pino_pulso", 14)
                inits.append(f"""# {nome_s} (Fluxômetro Vazão)
pulsos_{chave} = 0
def cb_pulso_{chave}(pin):
    global pulsos_{chave}
    pulsos_{chave} += 1
pin_vazao_{chave} = Pin({p_pulso}, Pin.IN, Pin.PULL_UP)
pin_vazao_{chave}.irq(trigger=Pin.IRQ_RISING, handler=cb_pulso_{chave})""")
                leituras.append(f"""    # Leitura: {nome_s} (vazao)
    try:
        global pulsos_{chave}
        doc['{chave}'] = round(pulsos_{chave} / 7.5, 2)
        pulsos_{chave} = 0
    except Exception as e:
        print('[Sensor] Erro {chave}:', e)""")

        if tem_dht:
            imports.append("import dht")
        if tem_onewire:
            imports.append("import onewire, ds18x20")

        return "\n".join(imports), "\n\n".join(inits), "\n\n".join(leituras)

    @staticmethod
    def gerar_codigo(pool, wifi_ssid="SuaRedeWiFi", wifi_pass="SuaSenhaWiFi", sensores=None,
                     intervalo_segundos=2, protocolo="lan_http", server_host=None, server_port=5000, api_token=None):
        """
        Gera o código .ino completo para ESP32:
        - protocolo='lan_http': envio direto via HTTP POST para a LAN/VPN do SQUARE (sem broker MQTT).
        - protocolo='mqtt': envio tradicional via broker MQTT (PubSubClient).
        """
        pool_id = pool.get("id", "DESCONHECIDO")
        pool_nome = pool.get("nome", "Dispositivo IoT")
        tipo = pool.get("tipo", "estufa")
        protocolo = (protocolo or "lan_http").strip().lower()
        sensores = sensores or ESPMAPManager._sensores_padrao(tipo)
        data_geracao = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        if protocolo == "lan_http":
            host = (server_host or "192.168.1.100").strip()
            porta = int(server_port or 5000)
            token = (api_token if api_token is not None else pool.get("api_token", "")) or ""
            includes_str, declaracoes_str, setups_str, leituras_str = ESPMAPManager._montar_arduino(
                sensores, ["#include <WiFi.h>", "#include <HTTPClient.h>", "#include <ArduinoJson.h>"]
            )
            return f"""/*
 * ==============================================================================
 * SQUARE EXTREME 0.2 - FIRMWARE LAN/VPN DIRETA ESP32 (SEM BROKER MQTT)
 * ==============================================================================
 * Dispositivo : {pool_nome}
 * Pool ID HEX : {pool_id}
 * Aplicação   : {tipo.upper()}
 * Protocolo   : HTTP POST Direto (LAN / VPN)
 * Gerado em   : {data_geracao}
 *
 * BIBLIOTECAS NECESSÁRIAS NO ARDUINO IDE:
 *  1. HTTPClient e WiFi (já inclusas no pacote oficial do ESP32)
 *  2. ArduinoJson por Benoit Blanchon (v6 ou v7)
 *  3. Bibliotecas específicas dos sensores (ex: DHT sensor library)
 * ==============================================================================
 */

{includes_str}

// --- CONFIGURAÇÃO DE REDE WI-FI (LAN LOCAL) ---
const char* WIFI_SSID = "{wifi_ssid}";
const char* WIFI_PASSWORD = "{wifi_pass}";

// --- ENDPOINT DIRETO DO SERVIDOR SQUARE (SEM BROKER) ---
const char* SERVER_URL = "http://{host}:{porta}/api/telemetria";
const char* API_TOKEN = "{token}";
const char* POOL_ID = "{pool_id}";

// Intervalo de transmissão (milissegundos)
const unsigned long INTERVALO_LEITURA = {intervalo_segundos * 1000};
unsigned long ultimoEnvio = 0;

// --- DECLARAÇÕES DE SENSORES CONFIGURADOS ---
{declaracoes_str}

void conectarWiFi() {{
  delay(10);
  Serial.println();
  Serial.print("[WiFi] Conectando a ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int tentativas = 0;
  while (WiFi.status() != WL_CONNECTED && tentativas < 30) {{
    delay(500);
    Serial.print(".");
    tentativas++;
  }}

  if (WiFi.status() == WL_CONNECTED) {{
    Serial.println("");
    Serial.println("[WiFi] Conectado com sucesso!");
    Serial.print("[WiFi] IP do ESP32: ");
    Serial.println(WiFi.localIP());
    Serial.print("[LAN] Enviando direto para: ");
    Serial.println(SERVER_URL);
  }} else {{
    Serial.println("\\n[WiFi] Falha ao conectar. Tentará novamente no loop.");
  }}
}}

void processarComando(const char* acao, const char* valor) {{
  Serial.print("[COMANDO RECEBIDO] Acao=");
  Serial.print(acao);
  Serial.print(" | Valor=");
  Serial.println(valor);
  // Implemente aqui o acionamento de relés / atuadores locais conforme a ação recebida.
}}

void setup() {{
  Serial.begin(115200);
  delay(1000);
  Serial.println("\\n--- INICIALIZANDO ESP32 SQUARE EXTREME 0.2 (LAN DIRETA) ---");
  Serial.println("Pool ID: " + String(POOL_ID));

  // Inicializa sensores
{setups_str}

  conectarWiFi();
}}

void loop() {{
  if (WiFi.status() != WL_CONNECTED) {{
    conectarWiFi();
    delay(1000);
    return;
  }}

  unsigned long agora = millis();
  if (agora - ultimoEnvio >= INTERVALO_LEITURA) {{
    ultimoEnvio = agora;

    StaticJsonDocument<768> doc;
    doc["pool_id"] = POOL_ID;
    doc["dispositivo"] = "{pool_nome}";
    doc["tipo"] = "{tipo}";
    doc["uptime_seg"] = millis() / 1000;

    // Leituras dos sensores cadastrados
{leituras_str}

    char jsonBuffer[768];
    serializeJson(doc, jsonBuffer);

    Serial.print("[TELEMETRIA LAN] ");
    Serial.println(jsonBuffer);

    HTTPClient http;
    http.begin(SERVER_URL);
    http.setTimeout(5000);
    http.addHeader("Content-Type", "application/json");
    if (strlen(API_TOKEN) > 0) {{
      http.addHeader("X-API-Key", API_TOKEN);
    }}

    int httpCode = http.POST((uint8_t*)jsonBuffer, strlen(jsonBuffer));
    if (httpCode > 0) {{
      Serial.printf("[LAN HTTP] Status %d\\n", httpCode);
      if (httpCode == 200) {{
        String resposta = http.getString();
        StaticJsonDocument<512> docResp;
        DeserializationError err = deserializeJson(docResp, resposta);
        if (!err && docResp["comandos"].is<JsonArray>()) {{
          JsonArray cmds = docResp["comandos"].as<JsonArray>();
          for (JsonObject cmd : cmds) {{
            processarComando(cmd["acao"] | "", cmd["valor"] | "");
          }}
        }}
      }}
    }} else {{
      Serial.printf("[LAN HTTP] Erro de envio: %s\\n", http.errorToString(httpCode).c_str());
    }}
    http.end();
  }}
}}
"""

        # Modo MQTT tradicional
        mqtt_host = pool.get("mqtt", {}).get("host", "192.168.1.100")
        mqtt_porta = pool.get("mqtt", {}).get("porta", "1883")
        mqtt_topico = pool.get("mqtt", {}).get("topico", f"{tipo}/telemetria")
        mqtt_user = pool.get("mqtt", {}).get("usuario", "")
        mqtt_pass = pool.get("mqtt", {}).get("senha", "")

        includes_str, declaracoes_str, setups_str, leituras_str = ESPMAPManager._montar_arduino(
            sensores, ["#include <WiFi.h>", "#include <PubSubClient.h>", "#include <ArduinoJson.h>"]
        )

        codigo = f"""/*
 * ==============================================================================
 * SQUARE EXTREME 0.2 - FIRMWARE AUTOMATIZADO ESP32 (ESPMAP - MODO MQTT)
 * ==============================================================================
 * Dispositivo : {pool_nome}
 * Pool ID HEX : {pool_id}
 * Aplicação   : {tipo.upper()}
 * Gerado em   : {data_geracao}
 * 
 * BIBLIOTECAS NECESSÁRIAS NO ARDUINO IDE (Gerenciador de Bibliotecas):
 *  1. PubSubClient por Nick O'Leary
 *  2. ArduinoJson por Benoit Blanchon (v6 ou v7)
 *  3. DHT sensor library por Adafruit (se usar DHT)
 *  4. DallasTemperature e OneWire (se usar DS18B20)
 * ==============================================================================
 */

{includes_str}

// --- CONFIGURAÇÃO DE REDE WI-FI ---
const char* WIFI_SSID = "{wifi_ssid}";
const char* WIFI_PASSWORD = "{wifi_pass}";

// --- CONFIGURAÇÃO BROKER MQTT ---
const char* MQTT_SERVER = "{mqtt_host}";
const int MQTT_PORT = {mqtt_porta};
const char* MQTT_USER = "{mqtt_user}";
const char* MQTT_PASSWORD = "{mqtt_pass}";
const char* MQTT_TOPIC_TELEMETRIA = "{mqtt_topico}";
const char* POOL_ID = "{pool_id}";

// Intervalo de transmissão (milissegundos)
const unsigned long INTERVALO_LEITURA = {intervalo_segundos * 1000}; 

WiFiClient espClient;
PubSubClient mqttClient(espClient);
unsigned long ultimoEnvio = 0;

// --- DECLARAÇÕES DE SENSORES CONFIGURADOS ---
{declaracoes_str}

void conectarWiFi() {{
  delay(10);
  Serial.println();
  Serial.print("[WiFi] Conectando a ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int tentativas = 0;
  while (WiFi.status() != WL_CONNECTED && tentativas < 30) {{
    delay(500);
    Serial.print(".");
    tentativas++;
  }}

  if (WiFi.status() == WL_CONNECTED) {{
    Serial.println("");
    Serial.println("[WiFi] Conectado com sucesso!");
    Serial.print("[WiFi] Endereço IP: ");
    Serial.println(WiFi.localIP());
  }} else {{
    Serial.println("\\n[WiFi] Falha ao conectar. Tentará novamente no loop.");
  }}
}}

void reconectarMQTT() {{
  while (!mqttClient.connected()) {{
    Serial.print("[MQTT] Tentando conectar ao Broker...");
    String clientId = "ESP32_ExtremeSquare_" + String(POOL_ID) + "_" + String(random(0xffff), HEX);
    
    bool conectado = false;
    if (strlen(MQTT_USER) > 0) {{
      conectado = mqttClient.connect(clientId.c_str(), MQTT_USER, MQTT_PASSWORD);
    }} else {{
      conectado = mqttClient.connect(clientId.c_str());
    }}

    if (conectado) {{
      Serial.println(" Conectado!");
      Serial.print("[MQTT] Publicando no tópico: ");
      Serial.println(MQTT_TOPIC_TELEMETRIA);
    }} else {{
      Serial.print(" Falhou, rc=");
      Serial.print(mqttClient.state());
      Serial.println(" Tentando novamente em 5 segundos...");
      delay(5000);
      if (WiFi.status() != WL_CONNECTED) {{
        conectarWiFi();
      }}
    }}
  }}
}}

void setup() {{
  Serial.begin(115200);
  delay(1000);
  Serial.println("\\n--- INICIALIZANDO DISPOSITIVO SQUARE EXTREME ---");
  Serial.println("Pool ID: " + String(POOL_ID));

  // Inicializa sensores
{setups_str}

  conectarWiFi();
  mqttClient.setServer(MQTT_SERVER, MQTT_PORT);
  mqttClient.setBufferSize(1024); // Buffer para JSON completo
}}

void loop() {{
  if (WiFi.status() != WL_CONNECTED) {{
    conectarWiFi();
  }}

  if (!mqttClient.connected()) {{
    reconectarMQTT();
  }}
  mqttClient.loop();

  unsigned long agora = millis();
  if (agora - ultimoEnvio >= INTERVALO_LEITURA) {{
    ultimoEnvio = agora;

    // Constrói payload JSON estruturado com todos os sensores
    StaticJsonDocument<768> doc;
    doc["pool_id"] = POOL_ID;
    doc["dispositivo"] = "{pool_nome}";
    doc["tipo"] = "{tipo}";
    doc["uptime_seg"] = millis() / 1000;

    // Leituras dos sensores cadastrados
{leituras_str}

    // Serializa e envia via MQTT
    char jsonBuffer[768];
    serializeJson(doc, jsonBuffer);

    Serial.print("[TELEMETRIA ENVIADA] ");
    Serial.println(jsonBuffer);

    if (mqttClient.publish(MQTT_TOPIC_TELEMETRIA, jsonBuffer)) {{
      Serial.println("[MQTT] Publicação bem-sucedida!");
    }} else {{
      Serial.println("[MQTT] ERRO ao publicar payload!");
    }}
  }}
}}
"""
        return codigo

    @staticmethod
    def gerar_codigo_micropython(pool, wifi_ssid="SuaRedeWiFi", wifi_pass="SuaSenhaWiFi", sensores=None,
                                 intervalo_segundos=2, protocolo="lan_http", server_host=None, server_port=5000, api_token=None):
        """
        Gera o código MicroPython (main.py) para ESP32:
        - protocolo='lan_http': envio direto via urequests.post para a LAN/VPN do SQUARE (sem broker MQTT).
        - protocolo='mqtt': envio via umqtt.simple para broker MQTT.
        """
        pool_id = pool.get("id", "DESCONHECIDO")
        pool_nome = pool.get("nome", "Dispositivo IoT")
        tipo = pool.get("tipo", "estufa")
        protocolo = (protocolo or "lan_http").strip().lower()
        sensores = sensores or ESPMAPManager._sensores_padrao(tipo)
        data_geracao = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        if protocolo == "lan_http":
            host = (server_host or "192.168.1.100").strip()
            porta = int(server_port or 5000)
            token = (api_token if api_token is not None else pool.get("api_token", "")) or ""
            imports_str, inits_str, leituras_str = ESPMAPManager._montar_micropython(
                sensores, ["import urequests"]
            )
            return f'''# -*- coding: utf-8 -*-
"""
==============================================================================
SQUARE EXTREME 0.2 - FIRMWARE MICROPYTHON LAN/VPN DIRETA (SEM BROKER MQTT)
==============================================================================
Dispositivo : {pool_nome}
Pool ID HEX : {pool_id}
Aplicação   : {tipo.upper()}
Protocolo   : HTTP POST Direto (LAN / VPN)
Gerado em   : {data_geracao}

INSTRUÇÕES DE INSTALAÇÃO NO ESP32:
 1. Instale o firmware MicroPython no ESP32 (já inclui urequests nativo).
 2. Salve este arquivo como 'main.py' na raiz do dispositivo ESP32.
 3. Não é necessário instalar broker MQTT nem biblioteca externa.
==============================================================================
"""

{imports_str}

# --- CONFIGURAÇÃO DE REDE WI-FI (LAN LOCAL) ---
WIFI_SSID = "{wifi_ssid}"
WIFI_PASSWORD = "{wifi_pass}"

# --- ENDPOINT DIRETO DO SERVIDOR SQUARE (SEM BROKER) ---
SERVER_URL = "http://{host}:{porta}/api/telemetria"
API_TOKEN = "{token}"
POOL_ID = "{pool_id}"
POOL_NOME = "{pool_nome}"
TIPO_POOL = "{tipo}"

# Intervalo de envio (segundos)
INTERVALO_LEITURA = {intervalo_segundos}

# --- INICIALIZAÇÃO DOS SENSORES ---
{inits_str}

def conectar_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print(f"[WiFi] Conectando a '{{WIFI_SSID}}'...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        tentativas = 0
        while not wlan.isconnected() and tentativas < 40:
            time.sleep(0.5)
            print(".", end="")
            tentativas += 1
        print("")
    if wlan.isconnected():
        print(f"[WiFi] Conectado! IP ESP32: {{wlan.ifconfig()[0]}} -> Servidor: {{SERVER_URL}}")
    else:
        print("[WiFi] Falha ao conectar ao Wi-Fi.")
    return wlan

def ler_sensores():
    """Realiza a leitura de todos os sensores configurados e retorna o dict."""
    doc = {{
        "pool_id": POOL_ID,
        "dispositivo": POOL_NOME,
        "tipo": TIPO_POOL,
        "uptime_seg": time.ticks_ms() // 1000
    }}

{leituras_str}

    return doc

def processar_comando(cmd):
    """Processa comandos retornados pelo servidor SQUARE na resposta do POST."""
    print(f"[COMANDO RECEBIDO] Acao={{cmd.get('acao')}} | Valor={{cmd.get('valor')}}")

def enviar_telemetria(payload):
    """Envia JSON diretamente para o SQUARE e consome comandos pendentes."""
    headers = {{"Content-Type": "application/json"}}
    if API_TOKEN:
        headers["X-API-Key"] = API_TOKEN
    resp = None
    try:
        resp = urequests.post(SERVER_URL, data=ujson.dumps(payload), headers=headers)
        if resp.status_code == 200:
            dados_resp = resp.json()
            for cmd in dados_resp.get("comandos", []):
                processar_comando(cmd)
            print("[LAN HTTP] Telemetria aceita pelo SQUARE!")
        else:
            print(f"[LAN HTTP] Servidor retornou status {{resp.status_code}}")
    except Exception as err:
        print(f"[LAN HTTP] Erro no envio: {{err}}")
    finally:
        if resp is not None:
            resp.close()

def main():
    print("\\n--- INICIALIZANDO MICROPYTHON SQUARE EXTREME 0.2 (LAN DIRETA) ---")
    print(f"Pool ID: {{POOL_ID}} | Dispositivo: {{POOL_NOME}}")

    conectar_wifi()
    ultimo_envio = 0

    while True:
        try:
            wlan = network.WLAN(network.STA_IF)
            if not wlan.isconnected():
                conectar_wifi()

            agora = time.time()
            if agora - ultimo_envio >= INTERVALO_LEITURA:
                ultimo_envio = agora
                payload = ler_sensores()
                print(f"[TELEMETRIA LAN] {{ujson.dumps(payload)}}")
                enviar_telemetria(payload)

            time.sleep(0.1)

        except Exception as loop_err:
            print(f"[ERRO NO LOOP] {{loop_err}}")
            time.sleep(2)

if __name__ == "__main__":
    main()
'''

        # Modo MQTT tradicional
        mqtt_host = pool.get("mqtt", {}).get("host", "192.168.1.100")
        mqtt_porta = int(pool.get("mqtt", {}).get("porta", 1883))
        mqtt_topico = pool.get("mqtt", {}).get("topico", f"{tipo}/telemetria")
        mqtt_user = pool.get("mqtt", {}).get("usuario", "")
        mqtt_pass = pool.get("mqtt", {}).get("senha", "")

        imports_str, inits_str, leituras_str = ESPMAPManager._montar_micropython(
            sensores, ["from umqtt.simple import MQTTClient"]
        )

        user_py = f'"{mqtt_user}"' if mqtt_user else "None"
        pass_py = f'"{mqtt_pass}"' if mqtt_pass else "None"

        codigo = f'''# -*- coding: utf-8 -*-
"""
==============================================================================
SQUARE EXTREME 0.2 - FIRMWARE MICROPYTHON ESP32 (ESPMAP - MODO MQTT)
==============================================================================
Dispositivo : {pool_nome}
Pool ID HEX : {pool_id}
Aplicação   : {tipo.upper()}
Gerado em   : {data_geracao}

INSTRUÇÕES DE INSTALAÇÃO NO ESP32:
 1. Instale o firmware MicroPython no ESP32.
 2. Instale o pacote 'umqtt.simple' (via Thonny ou: import mip; mip.install("umqtt.simple")).
 3. Salve este arquivo como 'main.py' na raiz do dispositivo ESP32.
==============================================================================
"""

{imports_str}

# --- CONFIGURAÇÃO DE REDE WI-FI ---
WIFI_SSID = "{wifi_ssid}"
WIFI_PASSWORD = "{wifi_pass}"

# --- CONFIGURAÇÃO BROKER MQTT ---
MQTT_SERVER = "{mqtt_host}"
MQTT_PORT = {mqtt_porta}
MQTT_USER = {user_py}
MQTT_PASSWORD = {pass_py}
MQTT_TOPIC_TELEMETRIA = "{mqtt_topico}"
POOL_ID = "{pool_id}"
POOL_NOME = "{pool_nome}"
TIPO_POOL = "{tipo}"

# Intervalo de envio (segundos)
INTERVALO_LEITURA = {intervalo_segundos}

# --- INICIALIZAÇÃO DOS SENSORES ---
{inits_str}

def conectar_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print(f"[WiFi] Conectando a '{{WIFI_SSID}}'...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        tentativas = 0
        while not wlan.isconnected() and tentativas < 40:
            time.sleep(0.5)
            print(".", end="")
            tentativas += 1
        print("")
    if wlan.isconnected():
        print(f"[WiFi] Conectado com sucesso! IP: {{wlan.ifconfig()[0]}}")
    else:
        print("[WiFi] Falha ao conectar ao Wi-Fi.")
    return wlan

def conectar_mqtt():
    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        conectar_wifi()

    client_id = f"ESP32_ExtremeSquare_{{POOL_ID}}_{{time.ticks_ms() & 0xffff:04x}}"
    print(f"[MQTT] Conectando a {{MQTT_SERVER}}:{{MQTT_PORT}} (Client ID: {{client_id}})...")
    try:
        client = MQTTClient(
            client_id=client_id,
            server=MQTT_SERVER,
            port=MQTT_PORT,
            user=MQTT_USER,
            password=MQTT_PASSWORD,
            keepalive=60
        )
        client.connect()
        print(f"[MQTT] Conectado! Publicando em: {{MQTT_TOPIC_TELEMETRIA}}")
        return client
    except Exception as e:
        print(f"[MQTT] Falha na conexão: {{e}}")
        return None

def ler_sensores():
    """Realiza a leitura de todos os sensores configurados e retorna o dict."""
    doc = {{
        "pool_id": POOL_ID,
        "dispositivo": POOL_NOME,
        "tipo": TIPO_POOL,
        "uptime_seg": time.ticks_ms() // 1000
    }}

{leituras_str}

    return doc

def main():
    print("\\n--- INICIALIZANDO FIRMWARE MICROPYTHON SQUARE EXTREME ---")
    print(f"Pool ID: {{POOL_ID}} | Dispositivo: {{POOL_NOME}}")

    conectar_wifi()
    client = None
    ultimo_envio = 0

    while True:
        try:
            wlan = network.WLAN(network.STA_IF)
            if not wlan.isconnected():
                conectar_wifi()

            if client is None:
                client = conectar_mqtt()
                if client is None:
                    time.sleep(5)
                    continue

            agora = time.time()
            if agora - ultimo_envio >= INTERVALO_LEITURA:
                ultimo_envio = agora

                payload = ler_sensores()
                json_str = ujson.dumps(payload)
                print(f"[TELEMETRIA ENVIADA] {{json_str}}")

                try:
                    client.publish(MQTT_TOPIC_TELEMETRIA, json_str)
                    print("[MQTT] Publicação bem-sucedida!")
                except Exception as pub_err:
                    print(f"[MQTT] Erro ao publicar: {{pub_err}}")
                    client = None

            time.sleep(0.1)

        except Exception as loop_err:
            print(f"[ERRO NO LOOP] {{loop_err}}")
            time.sleep(2)
            client = None

if __name__ == "__main__":
    main()
'''
        return codigo
