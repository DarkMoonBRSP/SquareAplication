import time
import json
import random
import threading
import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"
PORTA = 1883

CONFIGURACOES = [
    {
        "nome": "🌱 Estufa",
        "topico": "estufa/telemetria",
        "gerar": lambda: {
            "temperatura": round(random.uniform(23.0, 31.0), 1),
            "umidade_solo": round(random.uniform(45.0, 75.0), 1),
            "umidade_ar": round(random.uniform(50.0, 80.0), 1),
            "luminosidade": random.randint(400, 950),
            "extras": {"atuadores": {"irrigacao": random.choice([True, False]), "ventilador": True}}
        }
    },
    {
        "nome": "🗑️ Lixeira",
        "topico": "lixeira/telemetria",
        "gerar": lambda: {
            "nivel_pct": round(random.uniform(15.0, 95.0), 1),
            "distancia_cm": round(random.uniform(5.0, 75.0), 1),
            "bateria_pct": round(random.uniform(80.0, 99.0), 1)
        }
    },
    {
        "nome": "💧 Reservatório",
        "topico": "reservatorio/telemetria",
        "gerar": lambda: {
            "nivel_pct": round(random.uniform(25.0, 85.0), 1),
            "volume_litros": round(random.uniform(2500.0, 8500.0), 0),
            "bomba": random.choice([True, False])
        }
    },
    {
        "nome": "⚡ Energia",
        "topico": "energia/telemetria",
        "gerar": lambda: {
            "potencia_w": round(random.uniform(350.0, 2200.0), 1),
            "tensao_v": round(random.uniform(125.0, 128.0), 1),
            "corrente_a": round(random.uniform(2.8, 17.0), 2),
            "kwh_acumulado": round(random.uniform(15.0, 120.0), 2)
        }
    },
    {
        "nome": "🚰 Consumo Água",
        "topico": "consumo_agua/telemetria",
        "gerar": lambda: {
            "vazao_lpm": round(random.uniform(5.0, 18.0), 1),
            "consumo_total_litros": round(random.uniform(200.0, 1800.0), 1)
        }
    }
]

def rodar_instancia(cfg, client, stop_event):
    topico = cfg["topico"]
    nome = cfg["nome"]
    while not stop_event.is_set():
        dados = cfg["gerar"]()
        payload = json.dumps(dados)
        client.publish(topico, payload)
        print(f"[{nome}] -> {topico}: {payload}")
        time.sleep(3)

def main():
    print("=" * 65)
    print("  🚀 SIMULADOR MESTRE: TODAS AS INSTÂNCIAS EM TEMPO REAL")
    print("=" * 65)
    print(f"Conectando ao broker {BROKER}:{PORTA}...")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    try:
        client.connect(BROKER, PORTA, 60)
        client.loop_start()
        print("✅ Conectado com sucesso!\n")
    except Exception as e:
        print(f"Erro de conexão: {e}")
        return

    stop_event = threading.Event()
    threads = []

    for cfg in CONFIGURACOES:
        t = threading.Thread(target=rodar_instancia, args=(cfg, client, stop_event), daemon=True)
        t.start()
        threads.append(t)

    print("Transmissão simultânea iniciada para todas as 5 instâncias.")
    print("Pressione CTRL + C para interromper.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nEncerrando todos os simuladores...")
        stop_event.set()
        client.disconnect()
        client.loop_stop()
        print("Todos os simuladores foram finalizados.")

if __name__ == '__main__':
    main()
