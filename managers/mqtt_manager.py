"""Cliente MQTT isolado da interface gráfica.

As callbacks do paho-mqtt ocorrem em uma thread própria; por isso a interface
consulta apenas cópias imutáveis do estado e da última mensagem recebida.
"""
import threading
import time
import socket

try:
    import paho.mqtt.client as mqtt
except ImportError:  # Permite abrir o programa e exibir um erro explicativo.
    mqtt = None


class MQTTManager:
    def __init__(self, config_manager, pool_id, logger=None):
        self.config = config_manager
        self.pool_id = pool_id
        self.logger = logger
        self.client = None
        self.conectado = False
        self.conectado_em = None
        self.total_mensagens = 0
        self.ultima_mensagem = None
        self.ultimo_erro = None
        self.ultima_tentativa = 0.0
        self.intervalo_reconexao = 5.0
        self._lock = threading.Lock()
        self._callback_mensagem = None

    def definir_callback_mensagem(self, callback):
        self._callback_mensagem = callback

    def _valor(self, chave, padrao=None):
        lista = self.config.obter("pools", "lista", [])
        for p in lista:
            if p.get("id") == self.pool_id:
                return p.get("mqtt", {}).get(chave, padrao)
        return padrao

    def _registrar(self, mensagem, erro=False):
        if self.logger:
            (self.logger.error if erro else self.logger.info)(mensagem)

    def conectar(self, silencioso=False):
        if self.conectado:
            return True
        if mqtt is None:
            self.ultimo_erro = "paho-mqtt não instalado"
            if not silencioso:
                self._registrar("MQTT indisponível: instale as dependências do projeto.", True)
            return False
        try:
            porta = int(self._valor("porta", "1883"))
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            usuario = str(self._valor("usuario", "")).strip()
            if usuario:
                client.username_pw_set(usuario, str(self._valor("senha", "")))
            client.on_connect = self._ao_conectar
            client.on_disconnect = self._ao_desconectar
            client.on_message = self._ao_receber
            client.on_connect_fail = self._ao_falhar_conexao
            host = str(self._valor("host", "localhost")).strip()
            client.connect_async(host, porta, keepalive=30)
            client.loop_start()
            self.client = client
            self.ultimo_erro = None
            if not silencioso:
                self._registrar(f"Tentando conectar ao broker MQTT ({host}:{porta}).")
            return True
        except (OSError, ValueError) as erro:
            self.ultimo_erro = str(erro)
            if not silencioso:
                self._registrar(f"Erro ao iniciar MQTT: {erro}", True)
            return False

    def _ao_conectar(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            self.conectado = False
            self.conectado_em = None
            self.ultimo_erro = f"Broker recusou a conexão ({reason_code})"
            self._registrar(f"MQTT recusado pelo broker: {reason_code}", True)
            return
        self.conectado = True
        self.conectado_em = time.strftime("%H:%M:%S")
        # Na pool, a chave salva é "topico"
        topico = str(self._valor("topico", "estufa/telemetria")).strip()
        if topico:
            client.subscribe(topico)
        self._registrar(f"MQTT conectado com sucesso; inscrito em '{topico}'.")

    def _ao_desconectar(self, client, userdata, disconnect_flags, reason_code, properties=None):
        estava_conectado = self.conectado
        self.conectado = False
        self.conectado_em = None
        if reason_code != 0 and estava_conectado:
            self.ultimo_erro = f"Conexão MQTT encerrada ({reason_code})"
            self._registrar(self.ultimo_erro, True)
        elif estava_conectado:
            self._registrar("MQTT desconectado.")

    def _ao_falhar_conexao(self, client, userdata):
        self.ultimo_erro = "Não foi possível alcançar o broker MQTT"

    def _ao_receber(self, client, userdata, mensagem):
        texto = mensagem.payload.decode("utf-8", errors="replace").strip()
        recebida_em = time.strftime("%d/%m/%Y %H:%M:%S")
        msg = {"topico": mensagem.topic, "payload": texto, "recebida_em": recebida_em}
        with self._lock:
            self.total_mensagens += 1
            self.ultima_mensagem = msg
        if self._callback_mensagem:
            self._callback_mensagem(msg)

    def publicar(self, texto, topico=None):
        if not self.conectado or not self.client:
            return False
        destino = topico or str(self._valor("topico_comando", "estufa/comando")).strip()
        resultado = self.client.publish(destino, texto)
        if resultado.rc != mqtt.MQTT_ERR_SUCCESS:
            self.ultimo_erro = f"Falha ao publicar no tópico {destino}"
            return False
        return True

    def desconectar(self):
        client, self.client = self.client, None
        self.conectado = False
        self.conectado_em = None
        if client:
            try:
                client.disconnect()
                client.loop_stop()
            except (OSError, RuntimeError):
                pass

    def reconectar_se_necessario(self):
        if self.conectado or not self._valor("conectar_ao_entrar", False) or not self._valor("reconexao_automatica", True):
            return False
        agora = time.monotonic()
        if agora - self.ultima_tentativa < self.intervalo_reconexao:
            return False
        self.ultima_tentativa = agora
        self.desconectar()
        return self.conectar(silencioso=True)

    def estado(self):
        with self._lock:
            ultima = dict(self.ultima_mensagem) if self.ultima_mensagem else None
            total = self.total_mensagens
            conectado_em = self.conectado_em
        return {
            "conectado": self.conectado,
            "conectado_em": conectado_em,
            "total_mensagens": total,
            "erro": self.ultimo_erro,
            "ultima_mensagem": ultima
        }

    @staticmethod
    def testar_broker(host, porta=1883, timeout=2.5):
        """Testa se o broker MQTT está acessível e calcula a latência TCP."""
        host = str(host).strip()
        try:
            porta = int(porta)
        except (ValueError, TypeError):
            return False, "Porta inválida.", None

        t0 = time.perf_counter()
        try:
            with socket.create_connection((host, porta), timeout=timeout):
                latencia_ms = round((time.perf_counter() - t0) * 1000, 1)
                return True, f"Broker acessível! Latência: {latencia_ms} ms", latencia_ms
        except socket.timeout:
            return False, f"Tempo esgotado ao tentar alcançar '{host}:{porta}' ({timeout}s).", None
        except ConnectionRefusedError:
            return False, f"Porta {porta} recusada em '{host}'. O broker MQTT está ativo?", None
        except Exception as e:
            return False, f"Falha ao conectar em '{host}:{porta}': {e}", None
