import json
from models.sensor_data import SensorData
from models.perfis import obter_perfil, normalizar_tipo


def _numero(valor):
    """Converte para float; rejeita booleanos (true/false não são medições)."""
    if isinstance(valor, bool):
        raise TypeError("booleano não é medição")
    return float(valor)


class SensorManager:
    def __init__(self, serial_manager, logger=None, tipo="estufa"):
        self.serial_manager = serial_manager
        self.logger = logger
        self.dados = None
        self.ultima_mensagem = None
        self.versao_dados = 0
        self.definir_tipo(tipo)

    def definir_tipo(self, tipo):
        self.tipo = normalizar_tipo(tipo)
        self.perfil = obter_perfil(self.tipo)

    def registrar(self, mensagem):
        if self.logger:
            self.logger.info(mensagem)

    def atualizar(self):
        linha = self.serial_manager.ler_linha()
        if linha is None:
            return False
        return self.processar_linha(linha)

    def processar_linha(self, linha, avisar=True):
        """Interpreta uma linha recebida pela Serial conforme o perfil da pool."""
        self.ultima_mensagem = linha
        dados = self.interpretar_json(linha)
        if dados is None:
            if avisar and self.logger:
                self.logger.warning("JSON inválido ou incompleto recebido do ESP32.")
            return False
        self.dados = dados
        self.versao_dados += 1
        return True

    def receber_mqtt(self, mensagem):
        """Recebe telemetria MQTT usando o mesmo contrato JSON da serial."""
        self.ultima_mensagem = mensagem
        dados = self.interpretar_json(mensagem)
        if dados is None:
            if self.logger:
                self.logger.warning(f"JSON MQTT inválido ou incompleto para o perfil '{self.perfil['nome']}'.")
            return False
        self.dados = dados
        self.versao_dados += 1
        return True

    def receber_http(self, mensagem):
        """Recebe telemetria via LAN/VPN HTTP POST usando o mesmo contrato JSON."""
        if isinstance(mensagem, dict):
            try:
                mensagem_str = json.dumps(mensagem, ensure_ascii=False)
            except (TypeError, ValueError):
                return False
        else:
            mensagem_str = mensagem
        self.ultima_mensagem = mensagem_str
        dados = self.interpretar_json(mensagem_str)
        if dados is None:
            if self.logger:
                self.logger.warning(f"JSON HTTP LAN inválido ou incompleto para o perfil '{self.perfil['nome']}'.")
            return False
        self.dados = dados
        self.versao_dados += 1
        return True

    def interpretar_json(self, mensagem):
        try:
            dados = json.loads(mensagem)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(dados, dict):
            return None

        tem_identificador = any(k in dados for k in ("pool_id", "dispositivo", "tipo"))

        valores = {}
        for medida in self.perfil["medidas"]:
            chave = medida["chave"]
            if chave not in dados:
                if medida["obrigatorio"] and not tem_identificador:
                    return None
                continue
            try:
                valores[chave] = _numero(dados[chave])
            except (TypeError, ValueError):
                if medida["obrigatorio"] and not tem_identificador:
                    return None
                # Opcional com valor inválido: ignora em vez de descartar a leitura toda

        extras = {chave: valor for chave, valor in dados.items() if chave not in valores}
        return SensorData(valores=valores, extras=extras)

    def obter_dados(self):
        return self.dados

    def possui_dados(self):
        return self.dados is not None
