import time
import json
import random
import sys
import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"
PORTA = 1883

GERADORES = {
    "1": {
        "tipo": "estufa",
        "nome": "🌱 Estufa Inteligente",
        "topico": "estufa/telemetria",
        "gerar": lambda: {
            "temperatura": round(random.uniform(22.0, 31.0), 1),
            "umidade_solo": round(random.uniform(40.0, 75.0), 1),
            "umidade_ar": round(random.uniform(50.0, 80.0), 1),
            "luminosidade": random.randint(300, 950),
            "extras": {"atuadores": {"irrigacao": random.choice([True, False]), "ventilador": True}}
        }
    },
    "2": {
        "tipo": "lixeira",
        "nome": "🗑️ Lixeira Inteligente",
        "topico": "lixeira/telemetria",
        "gerar": lambda: {
            "nivel_pct": round(random.uniform(15.0, 95.0), 1),
            "distancia_cm": round(random.uniform(5.0, 80.0), 1),
            "bateria_pct": round(random.uniform(70.0, 99.0), 1)
        }
    },
    "3": {
        "tipo": "reservatorio",
        "nome": "💧 Nível de Reservatório",
        "topico": "reservatorio/telemetria",
        "gerar": lambda: {
            "nivel_pct": round(random.uniform(25.0, 85.0), 1),
            "volume_litros": round(random.uniform(2500.0, 8500.0), 0),
            "bomba": random.choice([True, False])
        }
    },
    "4": {
        "tipo": "energia",
        "nome": "⚡ Medidor de Energia Elétrica",
        "topico": "energia/telemetria",
        "gerar": lambda: {
            "potencia_w": round(random.uniform(300.0, 2400.0), 1),
            "tensao_v": round(random.uniform(124.0, 128.5), 1),
            "corrente_a": round(random.uniform(2.5, 18.0), 2),
            "kwh_acumulado": round(random.uniform(10.0, 150.0), 2)
        }
    },
    "5": {
        "tipo": "consumo_agua",
        "nome": "🚰 Consumo de Água / Hidrômetro",
        "topico": "consumo_agua/telemetria",
        "gerar": lambda: {
            "vazao_lpm": round(random.uniform(4.0, 22.0), 1),
            "consumo_total_litros": round(random.uniform(120.0, 1500.0), 1)
        }
    }
}

def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print(f"✅ Conectado com sucesso ao broker {BROKER}:{PORTA}")
    else:
        print(f"❌ Falha ao conectar: {reason_code}")

def main():
    print("=" * 60)
    print("  SIMULADOR MQTT MULTI-APLICAÇÃO - EXTREMESQUARE")
    print("=" * 60)
    print("Escolha a aplicação a simular:")
    for k, v in GERADORES.items():
        print(f" [{k}] {v['nome']} (Tópico padrão: {v['topico']})")
    
    escolha = "1"
    if len(sys.argv) > 1 and sys.argv[1] in GERADORES:
        escolha = sys.argv[1]
    else:
        try:
            entrada = input("\nDigite a opção desejada [1-5] (Padrão 1): ").strip()
            if entrada in GERADORES:
                escolha = entrada
        except (KeyboardInterrupt, EOFError):
            print("\nEncerrado.")
            return

    perfil = GERADORES[escolha]
    topico = perfil["topico"]

    try:
        topico_personalizado = input(f"Tópico MQTT [{topico}]: ").strip()
        if topico_personalizado:
            topico = topico_personalizado
    except (KeyboardInterrupt, EOFError):
        pass

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect

    print(f"\nIniciando simulação para: {perfil['nome']}")
    print(f"Publicando a cada 3 segundos em '{topico}'...")
    client.connect(BROKER, PORTA, 60)
    client.loop_start()

    try:
        while True:
            dados = perfil["gerar"]()
            payload = json.dumps(dados)
            client.publish(topico, payload)
            print(f"📤 [{topico}]: {payload}")
            time.sleep(3)
    except KeyboardInterrupt:
        print("\nSimulador encerrado.")
        client.disconnect()
        client.loop_stop()

if __name__ == '__main__':
    main()
