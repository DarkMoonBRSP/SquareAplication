"""Simulador de ESP32 enviando telemetria direta via LAN/VPN HTTP POST (sem broker MQTT).

Usa apenas a biblioteca padrão do Python (urllib.request / json / argparse).
Exemplo de uso:
    python simulador_lan_http.py --pool-id 1A2B3C4D --token SEU_TOKEN --tipo estufa --host 192.168.100.8
"""
import argparse
import json
import random
import time
import urllib.error
import urllib.request

GERADORES = {
    "estufa": lambda: {
        "temperatura": round(random.uniform(22.0, 31.0), 1),
        "umidade_solo": round(random.uniform(40.0, 75.0), 1),
        "umidade_ar": round(random.uniform(50.0, 80.0), 1),
        "luminosidade": random.randint(300, 950),
        "extras": {"atuadores": {"irrigacao": random.choice([True, False]), "ventilador": True}},
    },
    "lixeira": lambda: {
        "nivel_pct": round(random.uniform(15.0, 95.0), 1),
        "distancia_cm": round(random.uniform(5.0, 80.0), 1),
        "bateria_pct": round(random.uniform(70.0, 99.0), 1),
    },
    "reservatorio": lambda: {
        "nivel_pct": round(random.uniform(25.0, 85.0), 1),
        "volume_litros": round(random.uniform(2500.0, 8500.0), 0),
        "bomba": random.choice([True, False]),
    },
    "energia": lambda: {
        "potencia_w": round(random.uniform(300.0, 2400.0), 1),
        "tensao_v": round(random.uniform(124.0, 128.5), 1),
        "corrente_a": round(random.uniform(2.5, 18.0), 2),
        "kwh_acumulado": round(random.uniform(10.0, 150.0), 2),
    },
    "consumo_agua": lambda: {
        "vazao_lpm": round(random.uniform(4.0, 22.0), 1),
        "consumo_total_litros": round(random.uniform(120.0, 1500.0), 1),
    },
}


def main():
    parser = argparse.ArgumentParser(description="Simulador ESP32 via LAN/VPN HTTP POST (sem broker)")
    parser.add_argument("--host", default="127.0.0.1", help="IP ou hostname do servidor SQUARE (ex: 192.168.100.8)")
    parser.add_argument("--porta", type=int, default=5000, help="Porta HTTP do servidor (padrão: 5000)")
    parser.add_argument("--pool-id", required=True, help="ID HEX da Pool (ex: A1B2C3D4)")
    parser.add_argument("--token", default="", help="Token da Pool (Header X-API-Key)")
    parser.add_argument("--tipo", choices=list(GERADORES.keys()), default="estufa", help="Perfil da pool")
    parser.add_argument("--intervalo", type=float, default=2.0, help="Intervalo de envio em segundos")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.porta}/api/telemetria"
    gerar = GERADORES[args.tipo]
    inicio = time.monotonic()

    print("=" * 64)
    print("  SIMULADOR LAN HTTP DIRECT - SQUARE EXTREME 0.2 (SEM BROKER)")
    print("=" * 64)
    print(f"  Endpoint : {url}")
    print(f"  Pool ID  : {args.pool_id} ({args.tipo})")
    print(f"  Token    : {'<definido>' if args.token else '<vazio>'}")
    print("  Pressione CTRL+C para encerrar.\n")

    try:
        while True:
            payload = gerar()
            payload["pool_id"] = args.pool_id
            payload["tipo"] = args.tipo
            payload["uptime_seg"] = int(time.monotonic() - inicio)

            corpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if args.token:
                headers["X-API-Key"] = args.token

            req = urllib.request.Request(url, data=corpo, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    resposta = json.loads(resp.read().decode("utf-8"))
                    comandos = resposta.get("comandos") or []
                    print(f"[POST 200] {corpo.decode('utf-8')}")
                    if comandos:
                        print(f"  -> [COMANDOS RECEBIDOS DO SQUARE]: {comandos}")
            except urllib.error.HTTPError as err:
                detalhe = err.read().decode("utf-8", errors="ignore")
                print(f"[POST {err.code}] Erro HTTP: {detalhe}")
            except Exception as err:
                print(f"[ERRO] Falha ao alcançar {url}: {err}")

            time.sleep(max(args.intervalo, 0.2))
    except KeyboardInterrupt:
        print("\nSimulador encerrado.")


if __name__ == "__main__":
    main()
