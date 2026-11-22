import time
import json
import random
import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"
PORTA = 1883
TOPICO = "reservatorio/telemetria"

def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print(f"✅ [RESERVATÓRIO] Conectado ao broker MQTT ({BROKER}:{PORTA})")
        print(f"📡 Publicando telemetria em: {TOPICO}\n")
    else:
        print(f"❌ [RESERVATÓRIO] Falha de conexão: {reason_code}")

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect

    print("=" * 55)
    print("  💧 SIMULADOR DE INFORMAÇÕES: NÍVEL DE RESERVATÓRIO")
    print("=" * 55)

    try:
        client.connect(BROKER, PORTA, 60)
        client.loop_start()
    except Exception as e:
        print(f"Erro ao conectar ao broker: {e}")
        return

    capacidade_maxima_litros = 10000.0
    nivel_pct = 72.0
    bomba_ligada = False

    try:
        while True:
            # Lógica automatizada da bomba d'água
            if bomba_ligada:
                # Bomba enchendo o tanque
                nivel_pct += random.uniform(2.5, 4.0)
                if nivel_pct >= 85.0:
                    bomba_ligada = False
                    print("🛑 [RESERVATÓRIO] Nível adequado atingido. Desligando bomba...")
            else:
                # Consumo de água esvaziando o tanque
                nivel_pct -= random.uniform(1.0, 2.5)
                if nivel_pct <= 22.0:
                    bomba_ligada = True
                    print("⚠️ [RESERVATÓRIO] Nível crítico atingido! Ligando bomba automaticamente...")

            nivel_pct = max(5.0, min(100.0, nivel_pct))
            nivel_arredondado = round(nivel_pct, 1)
            volume_atual = round(capacidade_maxima_litros * (nivel_arredondado / 100.0), 0)

            # Classificação
            if nivel_arredondado < 20.0:
                classificacao = "Crítico"
            elif nivel_arredondado < 50.0:
                classificacao = "Baixo"
            else:
                classificacao = "Adequado"

            payload = {
                "nivel_pct": nivel_arredondado,
                "volume_litros": volume_atual,
                "bomba": bomba_ligada
            }

            mensagem = json.dumps(payload)
            client.publish(TOPICO, mensagem)
            print(f"📤 [RESERVATÓRIO] Nível: {nivel_arredondado}% ({classificacao}) | Volume: {volume_atual:.0f}L | Bomba: {'LIGADA' if bomba_ligada else 'DESLIGADA'}")
            time.sleep(3)

    except KeyboardInterrupt:
        print("\n💧 Simulador de Reservatório finalizado.")
        client.disconnect()
        client.loop_stop()

if __name__ == '__main__':
    main()
