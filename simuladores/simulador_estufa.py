import time
import json
import random
import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"
PORTA = 1883
TOPICO = "estufa/telemetria"

def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print(f"✅ [ESTUFA] Conectado ao broker MQTT ({BROKER}:{PORTA})")
        print(f"📡 Publicando telemetria em: {TOPICO}\n")
    else:
        print(f"❌ [ESTUFA] Falha de conexão: {reason_code}")

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    
    print("=" * 55)
    print("  🌱 SIMULADOR DE INFORMAÇÕES: ESTUFA INTELIGENTE")
    print("=" * 55)
    
    try:
        client.connect(BROKER, PORTA, 60)
        client.loop_start()
    except Exception as e:
        print(f"Erro ao conectar ao broker: {e}")
        return

    temp = 25.5
    solo = 60.0
    ar = 65.0

    try:
        while True:
            # Variação suave dos dados
            temp = round(temp + random.uniform(-0.4, 0.4), 1)
            temp = max(18.0, min(38.0, temp))

            solo = round(solo + random.uniform(-0.8, 0.8), 1)
            solo = max(20.0, min(90.0, solo))

            ar = round(ar + random.uniform(-0.6, 0.6), 1)
            ar = max(35.0, min(85.0, ar))

            lux = random.randint(350, 950)
            irrigacao = solo < 45.0
            ventilador = temp > 28.0

            payload = {
                "temperatura": temp,
                "umidade_solo": solo,
                "umidade_ar": ar,
                "luminosidade": lux,
                "extras": {
                    "atuadores": {
                        "irrigacao": irrigacao,
                        "ventilador": ventilador
                    }
                }
            }

            mensagem = json.dumps(payload)
            client.publish(TOPICO, mensagem)
            print(f"📤 [ESTUFA] Temp: {temp}°C | Solo: {solo}% | Ar: {ar}% | Lux: {lux} | Irrigação: {'ON' if irrigacao else 'OFF'}")
            time.sleep(3)

    except KeyboardInterrupt:
        print("\n🌱 Simulador de Estufa finalizado.")
        client.disconnect()
        client.loop_stop()

if __name__ == '__main__':
    main()
