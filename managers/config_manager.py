import json
from copy import deepcopy
from pathlib import Path


class ConfigManager:
    PADRAO = {
        "aparencia": {"tema": "Moderno", "escala": "100%", "estilo_dashboard": "Padrão", "animacoes": True},
        "dashboard": {"intervalo_atualizacao": "1000 ms", "pontos_grafico": "60", "exibir_hardware": True, "exibir_atualizacoes": True, "exibir_sensores": True},
        "graficos": {"sensor_padrao": "Temperatura", "grade": True, "legenda": True, "atualizacao_automatica": True},
        "comunicacao": {"porta": "Automática", "deteccao_automatica": True, "velocidade": "115200", "timeout": "0.1 s", "reconexao_automatica": True},
        "mqtt": {"host": "localhost", "porta": "1883", "topico_telemetria": "estufa/telemetria", "topico_comando": "estufa/comando", "usuario": "", "senha": "", "conectar_ao_iniciar": False, "reconexao_automatica": True},
        "sql": {"caminho": "dados/estufa.db", "atualizacao_automatica": True},
        "sensores": {"temperatura": True, "umidade_solo": True, "umidade_ar": True, "luminosidade": True},
        "atuadores": {"bomba": True, "rele": True, "ventilacao": True, "iluminacao": True},
        "logs": {"ativados": True, "salvar_arquivo": True, "limite_registros": "20"},
        "sistema": {"iniciar_conectado": True, "iniciar_maximizado": False},
        "rede": {
            "host": "0.0.0.0",
            "porta": 5000,
            "modo_padrao": "lan_http",
            "exigir_token_telemetria": True,
            "debug": False,
        },
    }

    def __init__(self, caminho=None):
        raiz = Path(__file__).resolve().parent.parent
        self.caminho = Path(caminho) if caminho else raiz / "config" / "config.json"
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.dados = deepcopy(self.PADRAO)
        self.carregar()

    def carregar(self):
        if not self.caminho.exists(): self.salvar(); return
        try:
            with self.caminho.open("r", encoding="utf-8") as arquivo: salvo=json.load(arquivo)
            if isinstance(salvo,dict):
                self.dados=self._mesclar(deepcopy(self.PADRAO),salvo)
                # Migração de versões anteriores: Escuro/Sistema passam a Moderno.
                if self.dados["aparencia"].get("tema") in ("Escuro","Sistema"):
                    self.dados["aparencia"]["tema"]="Moderno"
                self.salvar()
        except (OSError,json.JSONDecodeError): self.dados=deepcopy(self.PADRAO); self.salvar()

    @staticmethod
    def _mesclar(base,atual):
        for chave,valor in atual.items():
            if isinstance(valor,dict) and isinstance(base.get(chave),dict): ConfigManager._mesclar(base[chave],valor)
            else: base[chave]=valor
        return base

    def salvar(self):
        try:
            temporario=self.caminho.with_suffix(".tmp")
            with temporario.open("w",encoding="utf-8") as arquivo: json.dump(self.dados,arquivo,ensure_ascii=False,indent=4)
            temporario.replace(self.caminho); return True
        except OSError:return False

    def obter(self,secao,chave,padrao=None): return self.dados.get(secao,{}).get(chave,padrao)
    def definir(self,secao,chave,valor,salvar=True):
        self.dados.setdefault(secao,{})[chave]=valor
        return self.salvar() if salvar else True
    def obter_secao(self,secao): return deepcopy(self.dados.get(secao,{}))
    def restaurar(self): self.dados=deepcopy(self.PADRAO); return self.salvar()
