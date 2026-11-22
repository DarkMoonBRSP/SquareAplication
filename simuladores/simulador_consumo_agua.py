import time
import json
import random
import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"
PORTA = 1883
TOPICO = "consumo_agua/telemetria"

def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print(f"✅ [ÁGUA] Conectado ao broker MQTT ({BROKER}:{PORTA})")
        print(f"📡 Publicando telemetria em: {TOPICO}\n")
    else:
        print(f"❌ [ÁGUA] Falha de conexão: {reason_code}")

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect

    print("=" * 55)
    print("  🚰 SIMULADOR DE INFORMAÇÕES: CONSUMO DE ÁGUA")
    print("=" * 55)

    try:
        client.connect(BROKER, PORTA, 60)
        client.loop_start()
    except Exception as e:
        print(f"Erro ao conectar ao broker: {e}")
        return

    consumo_total_litros = 1450.0

    try:
        while True:
            # Alterna entre torneira/chuveiro aberto e períodos sem consumo
            em_consumo = random.choices([True, False], weights=[0.75, 0.25])[0]

            if em_consumo:
                vazao_lpm = round(random.uniform(4.0, 16.5), 1)
                # Volume nos 3 segundos: (L/min * 3) / 60 = L/20
                litros_delta = (vazao_lpm * 3.0) / 60.0
            else:
                vazao_lpm = 0.0
                litros_delta = 0.0

            consumo_total_litros = round(consumo_total_litros + litros_delta, 1)

            payload = {
                "vazao_lpm": vazao_lpm,
                "consumo_total_litros": consumo_total_litros
            }

            mensagem = json.dumps(payload)
            client.publish(TOPICO, mensagem)
            print(f"📤 [ÁGUA] Vazão Atual: {vazao_lpm} L/min | Consumo Total: {consumo_total_litros} L")
            time.sleep(3)

    except KeyboardInterrupt:
        print("\n🚰 Simulador de Água finalizado.")
        client.disconnect()
        client.loop_stop()

if __name__ == '__main__':
    main()
