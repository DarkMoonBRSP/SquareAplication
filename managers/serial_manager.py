import time

import serial
from serial.tools import list_ports


class SerialManager:
    INDICADORES_ESP32 = (
        "esp32", "espressif", "cp210", "cp210x", "ch340", "ch341",
        "ftdi", "silicon labs", "usb serial"
    )

    def __init__(self, velocidade=115200, timeout=0.1, logger=None):
        self.velocidade = int(velocidade)
        self.timeout = float(timeout)
        self.conexao = None
        self.porta = None
        self.porta_preferencial = None
        self.logger = logger
        self.ultima_tentativa = 0.0
        self.intervalo_reconexao = 5.0

    def registrar(self, mensagem):
        if self.logger:
            self.logger.info(mensagem)

    def definir_porta_preferencial(self, porta):
        self.porta_preferencial = porta

    def configurar(self, velocidade=None, timeout=None):
        if self.esta_conectado():
            # Alterações de porta/baud exigem reconexão para serem efetivadas.
            if velocidade is not None and int(velocidade) != self.velocidade:
                self.velocidade = int(velocidade)
                return
            if timeout is not None:
                self.timeout = float(timeout)
                try:
                    self.conexao.timeout = self.timeout
                except (AttributeError, serial.SerialException):
                    pass
            return
        if velocidade is not None:
            self.velocidade = int(velocidade)
        if timeout is not None:
            self.timeout = float(timeout)

    def listar_portas(self):
        return list(list_ports.comports())

    def procurar_esp32(self, silencioso=False):
        portas = self.listar_portas()
        if not portas:
            if not silencioso:
                self.registrar("Nenhuma porta serial encontrada.")
            return None

        for porta in portas:
            info = " ".join(str(valor or "") for valor in (
                porta.device, porta.description, porta.manufacturer,
                getattr(porta, "product", ""), porta.hwid
            )).lower()
            if any(indicador in info for indicador in self.INDICADORES_ESP32):
                if not silencioso:
                    self.registrar(f"Possível ESP32 encontrado em {porta.device}.")
                return porta.device

        if not silencioso:
            self.registrar("Nenhum dispositivo compatível com ESP32 foi encontrado.")
        return None

    def conectar(self, porta=None, silencioso=False):
        if self.esta_conectado():
            return True

        alvo = porta or self.porta_preferencial or self.procurar_esp32(silencioso=silencioso)
        if not alvo:
            return False

        try:
            self.conexao = serial.Serial(alvo, self.velocidade, timeout=self.timeout)
            self.porta = alvo
            self.registrar(f"ESP32 conectado na porta {alvo} a {self.velocidade} baud.")
            return True
        except (serial.SerialException, OSError) as erro:
            self.conexao = None
            self.porta = None
            if self.logger and not silencioso:
                self.logger.error(f"Erro ao conectar ao ESP32: {erro}")
            return False

    def reconectar(self):
        agora = time.monotonic()
        if agora - self.ultima_tentativa < self.intervalo_reconexao:
            return False
        self.ultima_tentativa = agora
        self.desconectar(silencioso=True)
        return self.conectar(silencioso=True)

    def desconectar(self, silencioso=False):
        if self.conexao is None:
            return
        try:
            if self.conexao.is_open:
                self.conexao.close()
                if not silencioso:
                    self.registrar("ESP32 desconectado.")
        except (serial.SerialException, OSError) as erro:
            if self.logger:
                self.logger.error(f"Erro ao desconectar ESP32: {erro}")
        finally:
            self.conexao = None
            self.porta = None

    def esta_conectado(self):
        return self.conexao is not None and self.conexao.is_open

    def obter_porta(self):
        return self.porta

    def ler_linha(self):
        if not self.esta_conectado():
            return None
        try:
            if self.conexao.in_waiting == 0:
                return None
            linha = self.conexao.readline()
            return linha.decode("utf-8", errors="ignore").strip() if linha else None
        except (serial.SerialException, OSError) as erro:
            if self.logger:
                self.logger.error(f"Erro na comunicação serial: {erro}")
            self.desconectar(silencioso=True)
            return None
