"""Perfis de aplicação do ExtremeSquare.

Cada perfil define quais medições um tipo de dispositivo envia no JSON
(via Serial ou MQTT) e como o dashboard deve exibi-las.

- medidas:    valores numéricos. Os marcados como "obrigatorio" precisam vir
              no JSON para a leitura ser aceita; os demais são opcionais.
- estados:    valores liga/desliga (true/false), ex.: bomba d'água.
- indicador:  medida exibida como barra de nível (0 a 100%), com faixas de cor.
              Cada faixa vale para valores menores que "ate".
"""

PERFIS = {
    "estufa": {
        "nome": "Estufa Inteligente",
        "icone": "tree-fill",
        "medidas": [
            {"chave": "temperatura", "rotulo": "Temperatura", "unidade": "°C", "icone": "thermometer-half", "obrigatorio": True},
            {"chave": "umidade_solo", "rotulo": "Umidade do solo", "unidade": "%", "icone": "droplet-half", "obrigatorio": True},
            {"chave": "umidade_ar", "rotulo": "Umidade do ar", "unidade": "%", "icone": "cloud-haze", "obrigatorio": True},
            {"chave": "luminosidade", "rotulo": "Luminosidade", "unidade": "lux", "icone": "brightness-high", "obrigatorio": True},
        ],
        "estados": [],
        "indicador": None,
    },
    "lixeira": {
        "nome": "Lixeira Inteligente",
        "icone": "trash-fill",
        "medidas": [
            {"chave": "nivel_pct", "rotulo": "Ocupação", "unidade": "%", "icone": "trash", "obrigatorio": True},
            {"chave": "distancia_cm", "rotulo": "Distância do sensor", "unidade": "cm", "icone": "rulers", "obrigatorio": False},
            {"chave": "bateria_pct", "rotulo": "Bateria", "unidade": "%", "icone": "battery-half", "obrigatorio": False},
        ],
        "estados": [],
        "indicador": {
            "chave": "nivel_pct",
            "titulo": "Ocupação da lixeira",
            "faixas": [
                {"ate": 50, "cor": "success", "texto": "Vazia"},
                {"ate": 90, "cor": "warning", "texto": "Atenção"},
                {"ate": 1000, "cor": "danger", "texto": "Coleta urgente"},
            ],
        },
    },
    "reservatorio": {
        "nome": "Nível de Reservatório",
        "icone": "droplet-half",
        "medidas": [
            {"chave": "nivel_pct", "rotulo": "Nível", "unidade": "%", "icone": "droplet-half", "obrigatorio": True},
            {"chave": "volume_litros", "rotulo": "Volume", "unidade": "L", "icone": "moisture", "obrigatorio": False},
        ],
        "estados": [
            {"chave": "bomba", "rotulo": "Bomba d'água"},
        ],
        "indicador": {
            "chave": "nivel_pct",
            "titulo": "Nível do reservatório",
            "faixas": [
                {"ate": 20, "cor": "danger", "texto": "Nível crítico"},
                {"ate": 50, "cor": "warning", "texto": "Nível baixo"},
                {"ate": 1000, "cor": "info", "texto": "Nível adequado"},
            ],
        },
    },
    "energia": {
        "nome": "Medidor de Energia",
        "icone": "lightning-charge-fill",
        "medidas": [
            {"chave": "potencia_w", "rotulo": "Potência", "unidade": "W", "icone": "lightning-charge", "obrigatorio": True},
            {"chave": "tensao_v", "rotulo": "Tensão", "unidade": "V", "icone": "plug", "obrigatorio": False},
            {"chave": "corrente_a", "rotulo": "Corrente", "unidade": "A", "icone": "activity", "obrigatorio": False},
            {"chave": "kwh_acumulado", "rotulo": "Consumo acumulado", "unidade": "kWh", "icone": "speedometer2", "obrigatorio": False},
        ],
        "estados": [],
        "indicador": None,
    },
    "consumo_agua": {
        "nome": "Consumo de Água",
        "icone": "water",
        "medidas": [
            {"chave": "vazao_lpm", "rotulo": "Vazão", "unidade": "L/min", "icone": "water", "obrigatorio": True},
            {"chave": "consumo_total_litros", "rotulo": "Consumo total", "unidade": "L", "icone": "droplet", "obrigatorio": False},
        ],
        "estados": [],
        "indicador": None,
    },
}

TIPO_PADRAO = "estufa"


def obter_perfil(tipo):
    """Retorna o perfil do tipo informado (pools antigas sem tipo caem em 'estufa')."""
    return PERFIS.get(tipo) or PERFIS[TIPO_PADRAO]


def normalizar_tipo(tipo):
    return tipo if tipo in PERFIS else TIPO_PADRAO
