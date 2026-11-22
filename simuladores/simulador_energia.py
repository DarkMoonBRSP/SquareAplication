import time
import json
import random
import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"
PORTA = 1883
TOPICO = "energia/telemetria"

def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print(f"✅ [ENERGIA] Conectado ao broker MQTT ({BROKER}:{PORTA})")
        print(f"📡 Publicando telemetria em: {TOPICO}\n")
    else:
        print(f"❌ [ENERGIA] Falha de conexão: {reason_code}")

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect

    print("=" * 55)
    print("  ⚡ SIMULADOR DE INFORMAÇÕES: MEDIDOR DE ENERGIA")
    print("=" * 55)

    try:
        client.connect(BROKER, PORTA, 60)
        client.loop_start()
    except Exception as e:
        print(f"Erro ao conectar ao broker: {e}")
        return

    tensao_base = 127.0
    kwh_acumulado = 42.350

    try:
        while True:
            # Tensão da rede varia levemente em torno de 127V
            tensao_v = round(tensao_base + random.uniform(-2.5, 2.5), 1)

            # Cargas elétricas variam com picos ocasionais (ex: chuveiro / ar condicionado ligando)
            modo = random.choices(["baixo", "medio", "alto"], weights=[0.5, 0.35, 0.15])[0]
            if modo == "baixo":
                potencia_w = round(random.uniform(180.0, 550.0), 1)
            elif modo == "medio":
                potencia_w = round(random.uniform(650.0, 1600.0), 1)
            else:
                potencia_w = round(random.uniform(1800.0, 3200.0), 1)

            # Corrente calculada I = P / V
            corrente_a = round(potencia_w / tensao_v, 2)

            # Incrementa o consumo de kWh proporcional aos 3 segundos transcorridos
            # kWh = (Potência em W * 3s) / (3600s * 1000)
            kwh_delta = (potencia_w * 3.0) / 3600000.0
            kwh_acumulado = round(kwh_acumulado + kwh_delta, 4)

            payload = {
                "potencia_w": potencia_w,
                "tensao_v": tensao_v,
                "corrente_a": corrente_a,
                "kwh_acumulado": round(kwh_acumulado, 2)
            }

            mensagem = json.dumps(payload)
            client.publish(TOPICO, mensagem)
            print(f"📤 [ENERGIA] Potência: {potencia_w}W | Tensão: {tensao_v}V | Corrente: {corrente_a}A | Total: {kwh_acumulado:.2f} kWh")
            time.sleep(3)

    except KeyboardInterrupt:
        print("\n⚡ Simulador de Energia finalizado.")
        client.disconnect()
        client.loop_stop()

if __name__ == '__main__':
    main()
