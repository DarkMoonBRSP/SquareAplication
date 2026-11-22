import time
import json
import random
import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"
PORTA = 1883
TOPICO = "lixeira/telemetria"

def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print(f"✅ [LIXEIRA] Conectado ao broker MQTT ({BROKER}:{PORTA})")
        print(f"📡 Publicando telemetria em: {TOPICO}\n")
    else:
        print(f"❌ [LIXEIRA] Falha de conexão: {reason_code}")

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect

    print("=" * 55)
    print("  🗑️ SIMULADOR DE INFORMAÇÕES: LIXEIRA INTELIGENTE")
    print("=" * 55)

    try:
        client.connect(BROKER, PORTA, 60)
        client.loop_start()
    except Exception as e:
        print(f"Erro ao conectar ao broker: {e}")
        return

    # Lixeira vai enchendo gradativamente até ser "esvaziada"
    nivel_pct = 25.0
    altura_total_cm = 80.0
    bateria_pct = 98.0

    try:
        while True:
            # Simula descarte de resíduos gradativo
            nivel_pct += random.uniform(1.5, 4.0)
            
            # Se encher mais de 98%, simula esvaziamento pela equipe de coleta
            if nivel_pct >= 98.0:
                print("♻️ [LIXEIRA] Capacidade máxima atingida! Simulando esvaziamento pela equipe de limpeza...")
                time.sleep(2)
                nivel_pct = random.uniform(5.0, 15.0)

            distancia_cm = round(max(5.0, altura_total_cm * (1.0 - (nivel_pct / 100.0))), 1)
            bateria_pct = round(max(10.0, bateria_pct - 0.05), 1)
            nivel_arredondado = round(nivel_pct, 1)

            # Classificação
            if nivel_arredondado < 50.0:
                status = "Vazia"
            elif nivel_arredondado < 90.0:
                status = "Atenção"
            else:
                status = "Coleta urgente"

            payload = {
                "nivel_pct": nivel_arredondado,
                "distancia_cm": distancia_cm,
                "bateria_pct": bateria_pct
            }

            mensagem = json.dumps(payload)
            client.publish(TOPICO, mensagem)
            print(f"📤 [LIXEIRA] Ocupação: {nivel_arredondado}% ({status}) | Distância: {distancia_cm}cm | Bateria: {bateria_pct}%")
            time.sleep(3)

    except KeyboardInterrupt:
        print("\n🗑️ Simulador de Lixeira finalizado.")
        client.disconnect()
        client.loop_stop()

if __name__ == '__main__':
    main()
