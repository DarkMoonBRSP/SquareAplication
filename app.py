# ExtremeSquare (SQUARE) — Plataforma IoT em Tempo Real
# Copyright (C) 2026 Luiz Miguel Ribeiro da Silva
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Este programa é software livre: você pode redistribuí-lo e/ou modificá-lo
# sob os termos da Licença Pública Geral Affero GNU v3.0 (veja LICENSE).

import dataclasses
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO

from managers.config_manager import ConfigManager
from managers.logger import Logger
from managers.mqtt_manager import MQTTManager
from managers.serial_manager import SerialManager
from managers.sensor_manager import SensorManager
from managers.sql_manager import SQLManager
from managers.account_manager import AccountManager
from managers.automation_manager import AutomationManager
from models.perfis import PERFIS, obter_perfil, normalizar_tipo
from functools import wraps
from flask import session, redirect, url_for, send_file, Response, has_request_context
import os
import hmac
import threading
import uuid
import random
import json
import io
import time
from werkzeug.middleware.proxy_fix import ProxyFix
from managers.network_manager import obter_ou_criar_secret_key, gerar_token_dispositivo, obter_info_rede

app = Flask(__name__)
app.secret_key = obter_ou_criar_secret_key()
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*", allow_unsafe_werkzeug=True)

# Mock data for pools
MOCK_POOLS = []

# Aplicações suportadas por cada pool (define qual dashboard será exibido)
TIPOS_POOL = tuple(PERFIS)

config_manager = ConfigManager()
logger = Logger(config_manager)
account_manager = AccountManager(config_manager, logger=logger)
automation_manager = AutomationManager(config_manager, logger=logger)

@app.before_request
def verificar_primeiro_acesso():
    """Se não houver nenhuma conta ADM cadastrada, força redirecionamento para o setup inicial."""
    caminho = request.path
    if (
        caminho.startswith('/static')
        or caminho == '/setup'
        or caminho == '/login'
        or caminho.startswith('/api/telemetria')
        or caminho == '/api/health'
    ):
        return None
    if session.get('usuario') == 'DEV':
        return None
    if not account_manager.tem_administrador():
        return redirect(url_for('setup'))
    return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logado'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def pool_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('pool_ativo'):
            return redirect(url_for('pools'))
        return f(*args, **kwargs)
    return decorated_function

def get_timeout():
    try:
        return float(str(config_manager.obter("comunicacao", "timeout", "0.1 s")).replace("s", "").strip())
    except ValueError:
        return 0.1

velocidade = int(config_manager.obter("comunicacao", "velocidade", "115200"))
timeout = get_timeout()
serial_manager = SerialManager(velocidade=velocidade, timeout=timeout, logger=logger)

def tipo_da_pool(pool_id):
    pool = next((p for p in config_manager.obter("pools", "lista", []) if p["id"] == pool_id), {})
    return normalizar_tipo(pool.get("tipo"))

def obter_porta_servidor():
    try:
        return int(os.environ.get("SQUARE_PORT") or config_manager.obter("rede", "porta", 5000))
    except (TypeError, ValueError):
        return 5000


def garantir_tokens_pools():
    """Garante que toda pool possua api_token único e modo_conexao definidos."""
    lista = config_manager.obter("pools", "lista", [])
    modo_padrao = config_manager.obter("rede", "modo_padrao", "lan_http")
    alterou = False
    for p in lista:
        if not p.get("api_token"):
            p["api_token"] = gerar_token_dispositivo()
            alterou = True
        if not p.get("modo_conexao"):
            p["modo_conexao"] = modo_padrao
            alterou = True
        if "lan_habilitada" not in p:
            p["lan_habilitada"] = True
            alterou = True
    if alterou:
        config_manager.salvar()


class PoolRuntime:
    def __init__(self, pool_id):
        self.pool_id = pool_id
        # Cada pool possui seu próprio logger isolado
        self.logger = Logger(config_manager, pool_id=pool_id)
        self.mqtt = MQTTManager(config_manager, pool_id, logger=self.logger)
        self.sql = SQLManager(config_manager, pool_id, logger=self.logger)
        self.sensor = SensorManager(serial_manager, logger=self.logger, tipo=tipo_da_pool(pool_id))
        self.ultimo_pacote_tempo = 0.0
        self.ultima_fonte = None
        self.ultimo_ip_dispositivo = None
        self.total_pacotes_http = 0
        self.ultimo_pacote_http_em = None
        self.ultimo_payload_http = None
        self.sensores_atividade = {}
        self.comandos_pendentes = []
        self._cmd_lock = threading.Lock()

    def enfileirar_comando(self, acao, valor=None, origem="painel"):
        item = {
            "id": uuid.uuid4().hex[:8],
            "acao": str(acao).strip(),
            "valor": valor,
            "origem": origem,
            "criado_em": time.strftime("%H:%M:%S"),
        }
        with self._cmd_lock:
            self.comandos_pendentes.append(item)
            if len(self.comandos_pendentes) > 50:
                self.comandos_pendentes = self.comandos_pendentes[-50:]
        return item

    def consumir_comandos(self):
        with self._cmd_lock:
            cmds = list(self.comandos_pendentes)
            self.comandos_pendentes.clear()
        return cmds

runtimes = {}


def _publicar_telemetria_valida(pool_id, rt, fonte, agora):
    dados = rt.sensor.obter_dados()
    if not dados:
        return False
    dados_dict = dados.para_dict()
    for k, v in dados_dict.items():
        if k not in ("extras", "pool_id", "dispositivo", "tipo", "uptime_seg"):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                rt.sensores_atividade[k] = {
                    "ultimo_recebido": agora,
                    "valor": v
                }
    dados_dict['fonte'] = fonte
    socketio.emit('sensor_data', dados_dict, to=f'dashboard_{pool_id}')
    socketio.emit('update_hardware', get_hardware_state(pool_id), to=f'dashboard_{pool_id}')
    automation_manager.processar_telemetria(pool_id, dados_dict, socketio=socketio)
    return True


def _persistir_mensagem_pool(rt, topico, payload_str, recebido_em=None):
    rt.sql.garantir_tabela_mqtt()
    try:
        rt.sql.executar(
            "INSERT INTO mqtt_messages (topico, payload, recebido_em) VALUES (:t, :p, :r)",
            {"t": topico, "p": payload_str, "r": recebido_em or time.strftime("%d/%m/%Y %H:%M:%S")}
        )
    except Exception as e:
        rt.logger.error(f"Erro DB: {e}")


def processar_telemetria_lan(pool_id, payload_dict, ip_origem=None):
    """Processa telemetria recebida diretamente via HTTP POST (LAN / VPN) sem broker MQTT."""
    rt = get_runtime(pool_id)
    if not rt:
        return False, []

    agora = time.time()
    ip_anterior = rt.ultimo_ip_dispositivo
    primeiro_http = (rt.total_pacotes_http == 0)

    rt.ultimo_pacote_tempo = agora
    rt.ultima_fonte = "http_lan"
    rt.ultimo_ip_dispositivo = ip_origem
    rt.total_pacotes_http += 1
    rt.ultimo_pacote_http_em = time.strftime("%H:%M:%S")

    if primeiro_http or (ip_origem and ip_origem != ip_anterior):
        rt.logger.info(f"Telemetria LAN HTTP recebida de {ip_origem or 'desconhecido'}.")

    aceito = False
    if rt.sensor.receber_http(payload_dict):
        aceito = _publicar_telemetria_valida(pool_id, rt, "http_lan", agora)
    else:
        socketio.emit('update_hardware', get_hardware_state(pool_id), to=f'dashboard_{pool_id}')

    payload_str = json.dumps(payload_dict, ensure_ascii=False)
    rt.ultimo_payload_http = payload_str
    _persistir_mensagem_pool(rt, f"lan/http/{pool_id}", payload_str)
    return aceito, rt.consumir_comandos()


def get_runtime(pool_id):
    if not pool_id:
        return None
    if pool_id not in runtimes:
        rt = PoolRuntime(pool_id)

        # Inicia callback MQTT específica para esta pool (quando MQTT estiver habilitado)
        def cb(msg):
            agora = time.time()
            rt.ultimo_pacote_tempo = agora
            rt.ultima_fonte = "mqtt"
            if rt.sensor.receber_mqtt(msg['payload']):
                _publicar_telemetria_valida(pool_id, rt, "mqtt", agora)
            _persistir_mensagem_pool(rt, msg['topico'], msg['payload'], msg.get('recebida_em'))

        rt.mqtt.definir_callback_mensagem(cb)

        # Só conecta ao broker MQTT se a pool estiver configurada explicitamente para usá-lo
        pool_data = next((p for p in config_manager.obter("pools", "lista", []) if p["id"] == pool_id), {})
        if pool_data.get("mqtt", {}).get("conectar_ao_entrar", False):
            rt.mqtt.conectar()

        runtimes[pool_id] = rt
    return runtimes[pool_id]

def obter_status_todas_pools():
    """Retorna o status em tempo real de cada pool (LAN HTTP, MQTT ou serial)."""
    pools_lista = config_manager.obter("pools", "lista", [])
    agora = time.time()
    status_dict = {}
    for p in pools_lista:
        pid = p["id"]
        rt = runtimes.get(pid)
        recebendo_dados = bool(rt and rt.ultimo_pacote_tempo > 0 and (agora - rt.ultimo_pacote_tempo) <= 30.0)
        mqtt_conectado = bool(rt and rt.mqtt and rt.mqtt.conectado)
        esta_ativo = p.get("ativo", True)
        funcionando = recebendo_dados or mqtt_conectado
        status_real = "ativo" if (funcionando or esta_ativo) else "inativo"
        if recebendo_dados:
            detalhes = "Recebendo dados (LAN HTTP)" if rt.ultima_fonte == "http_lan" else "Recebendo dados (MQTT)"
        elif mqtt_conectado:
            detalhes = "Broker Conectado"
        elif esta_ativo:
            detalhes = "Pronto (LAN/VPN)"
        else:
            detalhes = "Inativo"
        status_dict[pid] = {
            "status": status_real,
            "funcionando": funcionando,
            "detalhes": detalhes,
            "mqtt_conectado": mqtt_conectado,
            "ultima_fonte": rt.ultima_fonte if rt else None,
            "ultimo_pacote": rt.ultimo_pacote_tempo if rt else 0
        }
    return status_dict

def carregar_todas_pools(ativar_todas=True):
    """Carrega e inicializa todos os runtimes das pools em segundo plano (sem forçar broker MQTT)."""
    pools_lista = config_manager.obter("pools", "lista", [])
    carregadas = 0
    alterou_config = False

    for p in pools_lista:
        pid = p["id"]
        if ativar_todas and not p.get("ativo"):
            p["ativo"] = True
            alterou_config = True

        mqtt_cfg = p.setdefault("mqtt", {})
        rt = get_runtime(pid)
        if rt:
            if mqtt_cfg.get("conectar_ao_entrar", False) and not rt.mqtt.conectado:
                rt.mqtt.conectar()
            carregadas += 1

    if alterou_config:
        config_manager.salvar()

    return carregadas

# Garante tokens e inicializa todas as pools cadastradas ao ligar o app
garantir_tokens_pools()
carregar_todas_pools(ativar_todas=True)

def get_hardware_state(pool_id=None):
    rt = runtimes.get(pool_id)
    flags_resumo = automation_manager.obter_resumo_pool(pool_id) if pool_id else {"estado": "ok", "total_ativas": 0, "flags": []}
    pool_cfg = next((p for p in config_manager.obter("pools", "lista", []) if p["id"] == pool_id), {}) if pool_id else {}
    agora = time.time()

    esp32_conectado = False
    esp32_fonte = None
    esp32_segundos = None

    lan_habilitada = bool(pool_cfg.get("lan_habilitada", True)) if pool_id else True
    if rt and rt.ultimo_pacote_tempo > 0:
        esp32_segundos = round(agora - rt.ultimo_pacote_tempo, 1)
        if esp32_segundos <= 15.0:
            if rt.ultima_fonte == "http_lan":
                if lan_habilitada:
                    esp32_conectado = True
                    esp32_fonte = "http_lan"
            elif rt.ultima_fonte == "mqtt" or (rt.mqtt and rt.mqtt.conectado):
                esp32_conectado = True
                esp32_fonte = "mqtt"
            else:
                esp32_conectado = True
                esp32_fonte = "serial"

    if not esp32_conectado and serial_manager.esta_conectado():
        esp32_conectado = True
        esp32_fonte = "serial"
        esp32_segundos = 0

    sensores_status = {}
    if rt:
        for m in rt.sensor.perfil.get("medidas", []):
            chave = m["chave"]
            sensores_status[chave] = {
                "nome": m.get("rotulo", chave),
                "unidade": m.get("unidade", ""),
                "ativo": False,
                "valor": "--",
                "segundos_atras": None
            }
        for chave, info in rt.sensores_atividade.items():
            dt = round(agora - info["ultimo_recebido"], 1)
            ativo = (dt <= 15.0)
            val = info.get("valor")
            val_fmt = f"{val:.1f}" if isinstance(val, float) else str(val)
            nome_rotulo = chave
            unidade = ""
            for m in rt.sensor.perfil.get("medidas", []):
                if m["chave"] == chave:
                    nome_rotulo = m.get("rotulo", chave)
                    unidade = m.get("unidade", "")
                    break
            sensores_status[chave] = {
                "nome": nome_rotulo,
                "unidade": unidade,
                "ativo": ativo,
                "valor": val_fmt,
                "segundos_atras": dt
            }

    usando_http_lan = bool(rt and esp32_conectado and rt.ultima_fonte == "http_lan")
    mqtt_conectado = bool(rt and rt.mqtt and rt.mqtt.conectado)
    mqtt_habilitado = bool(pool_cfg.get("mqtt", {}).get("conectar_ao_entrar", False))
    usando_broker = bool(mqtt_conectado or usando_http_lan)

    return {
        "esp32": {
            "conectado": esp32_conectado,
            "fonte": esp32_fonte,
            "segundos_atras": esp32_segundos
        },
        "serial": {
            "conectado": serial_manager.esta_conectado(),
            "porta": serial_manager.obter_porta()
        },
        "lan_http": {
            "habilitada": lan_habilitada,
            "ativo": bool(lan_habilitada and rt and rt.total_pacotes_http > 0 and esp32_conectado and rt.ultima_fonte == "http_lan"),
            "total_pacotes": rt.total_pacotes_http if rt else 0,
            "ultimo_ip": rt.ultimo_ip_dispositivo if rt else None,
            "ultimo_recebido": rt.ultimo_pacote_http_em if rt else None
        },
        "mqtt_habilitado": mqtt_habilitado,
        "mqtt": rt.mqtt.estado() if rt else {"conectado": False, "erro": "Sem pool"},
        "sql": rt.sql.estado() if rt else {"conectado": False, "erro": "Sem pool", "tipo": "sqlite", "nome_tipo": "SQLite"},
        "flags": flags_resumo,
        "usando_broker": usando_broker,
        "sensores": sensores_status
    }

def background_tasks():
    while True:
        # Serial Manager (compartilhado): cada linha vai só para as pools cujo perfil a aceita
        serial_updated = False
        if serial_manager.esta_conectado():
            linha = serial_manager.ler_linha()
            if linha is not None and runtimes:
                aceita = False
                agora_ser = time.time()
                for pid, rt in list(runtimes.items()):
                    if rt.sensor.processar_linha(linha, avisar=False):
                        aceita = True
                        rt.ultimo_pacote_tempo = agora_ser
                        rt.ultima_fonte = "serial"
                        _publicar_telemetria_valida(pid, rt, "serial", agora_ser)
                if aceita:
                    serial_updated = True
                else:
                    logger.warning("JSON inválido ou incompleto recebido do ESP32 (nenhum perfil de pool compatível).")
        else:
            if config_manager.obter("comunicacao", "reconexao_automatica", True):
                serial_manager.reconectar()
                if serial_manager.esta_conectado():
                    serial_updated = True

        for pid, rt in runtimes.items():
            if serial_updated:
                socketio.emit('update_hardware', get_hardware_state(pid), to=f'dashboard_{pid}')
                
            # Reconexão MQTT individual
            if rt.mqtt.reconectar_se_necessario():
                socketio.emit('update_hardware', get_hardware_state(pid), to=f'dashboard_{pid}')
                
            # Envia logs exclusivos da pool correspondente
            socketio.emit('logs', rt.logger.obter_ultimos(10), to=f'dashboard_{pid}')

        # Transmite status ao vivo de todas as pools para a tela Dispositivos
        socketio.emit('pools_status_update', obter_status_todas_pools())

        interv_str = config_manager.obter("dashboard", "intervalo", "1000 ms")
        try:
            interv_ms = int(interv_str.replace(" ms", "").strip())
        except ValueError:
            interv_ms = 1000
            
        socketio.sleep(max(interv_ms / 1000.0, 0.1))

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    # Se já existir uma conta ADM cadastrada, impede nova criação e manda para o login
    if account_manager.tem_administrador():
        return redirect(url_for('login'))

    tema_atual = config_manager.obter("aparencia", "tema", "Moderno").lower()

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        usuario = request.form.get('usuario', '').strip()
        senha = request.form.get('senha', '')
        confirmar = request.form.get('confirmar_senha', '')

        if not usuario or not senha:
            return render_template('setup.html', erro="Preencha todos os campos obrigatórios.", theme=tema_atual)

        if senha != confirmar:
            return render_template('setup.html', erro="As senhas digitadas não coincidem.", theme=tema_atual)

        sucesso, res = account_manager.criar_administrador_inicial(nome, usuario, senha)
        if sucesso:
            session['logado'] = True
            session['usuario'] = res['usuario']
            session['nome'] = res['nome']
            session['role'] = res['role']
            session['usuario_id'] = res['id']
            return redirect(url_for('pools'))
        return render_template('setup.html', erro=res, theme=tema_atual)

    return render_template('setup.html', theme=tema_atual)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form.get('usuario', '').strip()
        senha = request.form.get('senha', '').strip()
        user = account_manager.autenticar(usuario, senha)
        if user:
            session['logado'] = True
            session['usuario'] = user['usuario']
            session['nome'] = user.get('nome', user['usuario'])
            session['role'] = user.get('role', 'operador')
            session['usuario_id'] = user.get('id')
            return redirect(url_for('pools'))
        return render_template('login.html', theme=config_manager.obter("aparencia", "tema", "Moderno").lower(), erro="Usuário ou senha incorretos.")

    if not account_manager.tem_administrador():
        return redirect(url_for('setup'))

    if session.get('logado'):
        return redirect(url_for('pools'))

    return render_template('login.html', theme=config_manager.obter("aparencia", "tema", "Moderno").lower())

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

import uuid

@app.route('/pools')
@login_required
def pools():
    # Ao voltar para a lista de dispositivos, desmarca a pool ativa
    session.pop('pool_ativo', None)
    session.pop('pool_nome', None)
    pools_lista = config_manager.obter("pools", "lista", [])
    status_map = obter_status_todas_pools()
    
    for p in pools_lista:
        info = status_map.get(p["id"], {})
        p["status_real"] = info.get("status", "ativo" if p.get("ativo", True) else "inativo")
        p["detalhes_status"] = info.get("detalhes", "Ativo" if p.get("ativo", True) else "Inativo")
        p["funcionando"] = info.get("funcionando", False)

    resumo_global = automation_manager.obter_resumo_global()
    return render_template(
        'pools.html',
        theme=config_manager.obter("aparencia", "tema", "Moderno").lower(),
        pools=pools_lista,
        resumo_global=resumo_global
    )

@app.route('/pools/carregar_todas', methods=['GET', 'POST'])
@login_required
def rota_carregar_todas_pools():
    qtd = carregar_todas_pools(ativar_todas=True)
    msg = f"{qtd} dispositivo(s) carregado(s) e ativado(s) em segundo plano com sucesso!"
    return redirect(url_for('pools', msg=msg))

@app.route('/api/pools/carregar_todas', methods=['POST'])
@login_required
def api_carregar_todas_pools():
    qtd = carregar_todas_pools(ativar_todas=True)
    return jsonify({
        "sucesso": True,
        "total_carregadas": qtd,
        "mensagem": f"{qtd} dispositivo(s) carregado(s) com sucesso!"
    })

@app.route('/api/pools/status')
@login_required
def api_pools_status():
    return jsonify(obter_status_todas_pools())

@app.route('/pools/add', methods=['POST'])
@login_required
def add_pool():
    nome = request.form.get('nome', '').strip()
    if nome:
        # Gera ID hexadecimal único de 8 dígitos
        lista_existente = config_manager.obter("pools", "lista", [])
        ids_existentes = {p["id"] for p in lista_existente}
        while True:
            novo_id = '%08X' % random.randint(0, 0xFFFFFFFF)
            if novo_id not in ids_existentes:
                break

        tipo = request.form.get('tipo', 'estufa').strip()
        if tipo not in TIPOS_POOL:
            tipo = 'estufa'

        modo_padrao = config_manager.obter("rede", "modo_padrao", "lan_http")
        nova_pool = {
            "id": novo_id,
            "nome": nome,
            "tipo": tipo,
            "ativo": True,
            "lan_habilitada": True,
            "modo_conexao": modo_padrao,
            "api_token": gerar_token_dispositivo(),
            "mqtt": {"host": "localhost", "porta": "1883", "topico": f"{tipo}/telemetria", "usuario": "", "senha": "", "conectar_ao_entrar": (modo_padrao == "mqtt")},
            "sql": {"tipo": "sqlite", "caminho": f"dados/pools/pool_{novo_id.lower()}.db"}
        }

        pools_sec = config_manager.dados.setdefault("pools", {})
        lista = pools_sec.setdefault("lista", [])
        lista.append(nova_pool)
        config_manager.salvar()
        get_runtime(novo_id)

    return redirect(url_for('pools'))

@app.route('/pools/delete/<pool_id>', methods=['POST'])
@login_required
def delete_pool(pool_id):
    pools_sec = config_manager.dados.get("pools", {})
    lista = pools_sec.get("lista", [])
    
    # Filtra a lista removendo o id correspondente
    nova_lista = [p for p in lista if p["id"] != pool_id]
    
    if len(nova_lista) != len(lista):
        pools_sec["lista"] = nova_lista
        config_manager.salvar()
        
        # Se apagou a pool que estava ativa na sessão, limpa
        if session.get('pool_ativo') == pool_id:
            session.pop('pool_ativo', None)
            session.pop('pool_nome', None)
            
    return redirect(url_for('pools'))


@app.route('/pools/export')
@login_required
def export_pools():
    """Exporta todas as pools (com suas configurações internas) como arquivo JSON."""
    lista = config_manager.obter("pools", "lista", [])
    payload = {
        "square_export_version": "1.0",
        "pools": lista
    }
    conteudo = json.dumps(payload, ensure_ascii=False, indent=4)
    buf = io.BytesIO(conteudo.encode("utf-8"))
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/json",
        as_attachment=True,
        download_name="square_pools_export.json"
    )


@app.route('/pools/import', methods=['POST'])
@login_required
def import_pools():
    """Importa pools de um arquivo JSON. 
    Regras de merge:
    - Pools com ID já existente → IGNORADAS (preserva configuração local).
    - Pools novas (ID inexistente) → ADICIONADAS.
    """
    arquivo = request.files.get('arquivo')
    if not arquivo:
        return redirect(url_for('pools'))

    try:
        conteudo = json.loads(arquivo.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return redirect(url_for('pools'))  # arquivo inválido — ignora silenciosamente

    pools_importadas = conteudo.get("pools", [])
    if not isinstance(pools_importadas, list):
        return redirect(url_for('pools'))

    pools_sec = config_manager.dados.setdefault("pools", {})
    lista_atual = pools_sec.setdefault("lista", [])
    ids_existentes = {p["id"] for p in lista_atual}

    adicionadas = 0
    ignoradas = 0
    for pool in pools_importadas:
        if not isinstance(pool, dict) or "id" not in pool or "nome" not in pool:
            continue
        if pool["id"] in ids_existentes:
            ignoradas += 1  # ID já existe — preserva local
            continue
        # Garante que a pool importada tenha a estrutura mqtt e token LAN/VPN mínimos
        pool.setdefault("mqtt", {"host": "localhost", "porta": "1883", "topico": "estufa/telemetria", "usuario": "", "senha": "", "conectar_ao_entrar": False})
        pool.setdefault("ativo", False)
        pool.setdefault("modo_conexao", config_manager.obter("rede", "modo_padrao", "lan_http"))
        if not pool.get("api_token"):
            pool["api_token"] = gerar_token_dispositivo()
        lista_atual.append(pool)
        ids_existentes.add(pool["id"])
        adicionadas += 1

    config_manager.salvar()

    # Passa um resumo para a página via query string
    return redirect(url_for('pools', importadas=adicionadas, ignoradas=ignoradas))


@app.route('/selecionar_pool/<pool_id>')
@app.route('/pool/<pool_id>')
@login_required
def selecionar_pool(pool_id):
    lista = config_manager.obter("pools", "lista", [])
    pool = next((p for p in lista if p["id"] == pool_id), None)
    if pool:
        session['pool_ativo'] = pool_id
        session['pool_nome'] = pool["nome"]
        get_runtime(pool_id)
        return redirect(url_for('pool_dashboard'))
    return redirect(url_for('pools'))

@app.route('/pools/sair')
@login_required
def sair_pool():
    """Sai do escopo da pool e retorna para a lista geral de dispositivos."""
    session.pop('pool_ativo', None)
    session.pop('pool_nome', None)
    return redirect(url_for('pools'))

def get_pool_ativo():
    """Retorna o dict da pool atualmente ativa na sessão, ou None."""
    pool_id = session.get('pool_ativo')
    if not pool_id:
        return None
    lista = config_manager.obter("pools", "lista", [])
    return next((p for p in lista if p["id"] == pool_id), None)

def salvar_config_pool(pool_id, mqtt_cfg=None, sql_cfg=None):
    """Salva as configurações MQTT/SQL dentro da pool correspondente na lista de pools."""
    lista = config_manager.dados.get("pools", {}).get("lista", [])
    for pool in lista:
        if pool["id"] == pool_id:
            if mqtt_cfg is not None:
                pool["mqtt"] = mqtt_cfg
            if sql_cfg is not None:
                pool["sql"] = sql_cfg
            break
    config_manager.salvar()

# Rota primária da aplicação: sempre redireciona para a aba de dispositivos se logado
@app.route('/')
@login_required
def index():
    return redirect(url_for('pools'))

# Painel de monitoramento do dispositivo ativo (Pool Dashboard)
@app.route('/dashboard')
@app.route('/pool/dashboard')
@login_required
@pool_required
def pool_dashboard():
    pool = get_pool_ativo()
    tipo = normalizar_tipo(pool.get("tipo")) if pool else "estufa"
    perfil = obter_perfil(tipo)
    flags_resumo = automation_manager.obter_resumo_pool(pool["id"]) if pool else {"estado": "ok", "total_ativas": 0, "flags": []}
    return render_template(
        'dashboard.html',
        theme=config_manager.obter("aparencia", "tema", "Moderno").lower(),
        config=config_manager.dados,
        pool_nome=session.get('pool_nome'),
        pool=pool,
        tipo=tipo,
        perfil=perfil,
        flags_resumo=flags_resumo
    )

# 1. Configurações Globais do Site
@app.route('/settings/site')
@login_required
def settings_site():
    portas = serial_manager.listar_portas()
    usuarios = account_manager.obter_usuarios() if session.get('role') == 'adm' else []
    wipe_registrada = account_manager.wipe_chave_registrada()
    rede_info = obter_info_rede(obter_porta_servidor())
    return render_template(
        'settings_site.html',
        theme=config_manager.obter("aparencia", "tema", "Moderno").lower(),
        config=config_manager.dados,
        portas_disponiveis=portas,
        usuarios=usuarios,
        wipe_registrada=wipe_registrada,
        rede_info=rede_info
    )

@app.route('/api/config/site', methods=['POST'])
@login_required
def api_config_site():
    data = request.json or {}
    for secao, valores in data.items():
        if isinstance(valores, dict):
            secao_dict = config_manager.dados.setdefault(secao, {})
            secao_dict.update(valores)
        else:
            config_manager.dados[secao] = valores
    config_manager.salvar()
    socketio.emit('reload_config', config_manager.dados)
    return jsonify({"status": "ok"})

# APIs de Gerenciamento de Contas Interno (Exclusivo ADM)
@app.route('/api/usuarios/criar', methods=['POST'])
@login_required
def api_usuario_criar():
    is_json = request.is_json
    if session.get('role') != 'adm':
        if is_json:
            return jsonify({"sucesso": False, "erro": "Acesso negado."}), 403
        return redirect(url_for('settings_site', erro="Acesso negado. Apenas administradores podem gerenciar contas."))
    
    if is_json:
        data = request.get_json() or {}
        nome = data.get('nome', '')
        usuario = data.get('usuario', '')
        senha = data.get('senha', '')
        role = data.get('role', 'operador')
    else:
        nome = request.form.get('nome', '')
        usuario = request.form.get('usuario', '')
        senha = request.form.get('senha', '')
        role = request.form.get('role', 'operador')

    sucesso, res = account_manager.criar_usuario(nome, usuario, senha, role)
    if is_json:
        if sucesso:
            return jsonify({"sucesso": True, "usuario": res})
        return jsonify({"sucesso": False, "erro": res}), 400

    if sucesso:
        return redirect(url_for('settings_site', msg=f"Usuário '{usuario}' cadastrado com sucesso!"))
    return redirect(url_for('settings_site', erro=res))

@app.route('/api/usuarios/excluir/<usuario_id>', methods=['POST'])
@login_required
def api_usuario_excluir(usuario_id):
    is_json = request.is_json
    if session.get('role') != 'adm':
        if is_json:
            return jsonify({"sucesso": False, "erro": "Acesso negado."}), 403
        return redirect(url_for('settings_site', erro="Acesso negado."))
    sucesso, msg = account_manager.excluir_usuario(usuario_id, id_solicitante=session.get('usuario_id'))
    if is_json:
        return jsonify({"sucesso": sucesso, "mensagem": msg})
    if sucesso:
        return redirect(url_for('settings_site', msg=msg))
    return redirect(url_for('settings_site', erro=msg))

@app.route('/api/usuarios/alterar-senha', methods=['POST'])
@login_required
def api_usuario_alterar_senha():
    is_json = request.is_json
    if session.get('role') != 'adm':
        if is_json:
            return jsonify({"sucesso": False, "erro": "Acesso negado."}), 403
        return redirect(url_for('settings_site', erro="Acesso negado."))
    if is_json:
        data = request.get_json() or {}
        usuario_id = data.get('usuario_id', '')
        nova_senha = data.get('nova_senha', '')
    else:
        usuario_id = request.form.get('usuario_id', '')
        nova_senha = request.form.get('nova_senha', '')
    sucesso, msg = account_manager.alterar_senha(usuario_id, nova_senha)
    if is_json:
        return jsonify({"sucesso": sucesso, "mensagem": msg})
    if sucesso:
        return redirect(url_for('settings_site', msg=msg))
    return redirect(url_for('settings_site', erro=msg))

# 2. Configurações Específicas da Pool
@app.route('/pool/settings')
@login_required
@pool_required
def settings_pool():
    pool = get_pool_ativo()
    tipo = normalizar_tipo(pool.get("tipo")) if pool else "estufa"
    perfil = obter_perfil(tipo)
    automacoes = automation_manager.obter_automacoes(pool["id"]) if pool else []
    flags = automation_manager.obter_flags(pool["id"]) if pool else []
    rede_info = obter_info_rede(obter_porta_servidor())
    return render_template(
        'settings_pool.html',
        theme=config_manager.obter("aparencia", "tema", "Moderno").lower(),
        config=config_manager.dados,
        pool=pool,
        tipo=tipo,
        perfil=perfil,
        automacoes=automacoes,
        flags=flags,
        rede_info=rede_info
    )

@app.route('/pool/settings/salvar', methods=['POST'])
@login_required
@pool_required
def salvar_settings_pool():
    pool_id = session.get('pool_ativo')
    lista = config_manager.dados.get("pools", {}).get("lista", [])
    pool = next((p for p in lista if p["id"] == pool_id), None)
    if not pool:
        return redirect(url_for('pools'))

    pool["nome"] = request.form.get("nome", pool["nome"]).strip()
    pool["tipo"] = request.form.get("tipo", pool.get("tipo", "estufa")).strip()
    pool["ativo"] = request.form.get("ativo") == "on"

    # Preserva configurações MQTT existentes se a aba não enviou campos
    if "mqtt_host" in request.form:
        mqtt_cfg = pool.setdefault("mqtt", {})
        mqtt_cfg["host"] = request.form.get("mqtt_host", "localhost").strip()
        mqtt_cfg["porta"] = request.form.get("mqtt_porta", "1883").strip()
        mqtt_cfg["topico"] = request.form.get("mqtt_topico", f"{pool['tipo']}/telemetria").strip()
        mqtt_cfg["topico_comando"] = request.form.get("mqtt_topico_cmd", f"{pool['tipo']}/comando").strip()
        mqtt_cfg["usuario"] = request.form.get("mqtt_usuario", "").strip()
        mqtt_cfg["senha"] = request.form.get("mqtt_senha", "").strip()
        mqtt_cfg["conectar_ao_entrar"] = request.form.get("mqtt_conectar_ao_entrar") == "on"

    # Configurações completas de Banco de Dados na aba BANCO
    sql_cfg = pool.setdefault("sql", {})
    sql_cfg["tipo"] = request.form.get("sql_tipo", "sqlite").strip()
    sql_cfg["caminho"] = request.form.get("sql_caminho", f"dados/pools/pool_{pool_id.lower()}.db").strip()
    sql_cfg["host"] = request.form.get("sql_host", "localhost").strip()
    
    porta_str = request.form.get("sql_porta", "").strip()
    if porta_str.isdigit():
        sql_cfg["porta"] = int(porta_str)
    else:
        sql_cfg["porta"] = 3306 if sql_cfg["tipo"] == "mysql" else 5432

    sql_cfg["banco"] = request.form.get("sql_banco", f"square_{pool_id.lower()}").strip()
    sql_cfg["usuario"] = request.form.get("sql_usuario", "root").strip()
    senha_form = request.form.get("sql_senha")
    if senha_form is not None:
        sql_cfg["senha"] = senha_form

    config_manager.salvar()
    session['pool_nome'] = pool["nome"]

    rt = runtimes.get(pool_id)
    if rt:
        rt.sensor.definir_tipo(pool["tipo"])
        rt.sql._engine = None
        rt.sql.subtipo_detectado = None
        rt.sql.testar_conexao()
        socketio.emit('update_hardware', get_hardware_state(pool_id), to=f'dashboard_{pool_id}')

    return redirect(url_for('settings_pool', msg="Configurações da pool salvas com sucesso!"))

# Fallback para rota antiga /settings
@app.route('/settings')
@login_required
def settings():
    if session.get('pool_ativo'):
        return redirect(url_for('settings_pool'))
    return redirect(url_for('settings_site'))

# ==========================================
# APIs DE AUTOMAÇÃO E FLAGS (ESTILO WINDOWS SERVER)
# ==========================================

@app.route('/api/pool/<pool_id>/automacoes', methods=['GET'])
@login_required
def api_obter_automacoes(pool_id):
    return jsonify(automation_manager.obter_automacoes(pool_id))

@app.route('/api/pool/<pool_id>/automacoes/adicionar', methods=['POST'])
@login_required
def api_adicionar_automacao(pool_id):
    is_json = request.is_json
    if is_json:
        data = request.get_json() or {}
        nome = data.get('nome', '')
        metrica = data.get('metrica', '')
        condicao = data.get('condicao', '>')
        limite = data.get('limite', 0)
        severidade = data.get('severidade', 'aviso')
        mensagem = data.get('mensagem', '')
    else:
        nome = request.form.get('nome', '')
        metrica = request.form.get('metrica', '')
        condicao = request.form.get('condicao', '>')
        limite = request.form.get('limite', 0)
        severidade = request.form.get('severidade', 'aviso')
        mensagem = request.form.get('mensagem', '')

    sucesso, res = automation_manager.adicionar_automacao(pool_id, nome, metrica, condicao, limite, severidade, mensagem)
    if is_json:
        if sucesso:
            return jsonify({"sucesso": True, "automacao": res})
        return jsonify({"sucesso": False, "erro": res}), 400
    if sucesso:
        return redirect(url_for('settings_pool', msg="Automação criada com sucesso!"))
    return redirect(url_for('settings_pool', erro=res))

@app.route('/api/pool/<pool_id>/automacoes/excluir/<auto_id>', methods=['POST'])
@login_required
def api_excluir_automacao(pool_id, auto_id):
    sucesso, msg = automation_manager.excluir_automacao(pool_id, auto_id)
    if request.is_json:
        return jsonify({"sucesso": sucesso, "mensagem": msg})
    return redirect(url_for('settings_pool', msg=msg if sucesso else None, erro=msg if not sucesso else None))

@app.route('/api/pool/<pool_id>/automacoes/alternar/<auto_id>', methods=['POST'])
@login_required
def api_alternar_automacao(pool_id, auto_id):
    sucesso, res = automation_manager.alternar_automacao(pool_id, auto_id)
    return jsonify({"sucesso": sucesso, "ativo": res})

@app.route('/api/pool/<pool_id>/flags', methods=['GET'])
@login_required
def api_obter_flags_pool(pool_id):
    apenas_ativas = request.args.get('apenas_ativas', 'false').lower() == 'true'
    flags = automation_manager.obter_flags(pool_id, apenas_ativas=apenas_ativas)
    resumo = automation_manager.obter_resumo_pool(pool_id)
    return jsonify({"flags": flags, "resumo": resumo})

@app.route('/api/pool/<pool_id>/flags/reconhecer/<flag_id>', methods=['POST'])
@login_required
def api_reconhecer_flag(pool_id, flag_id):
    sucesso = automation_manager.reconhecer_flag(pool_id, flag_id)
    return jsonify({"sucesso": sucesso})

@app.route('/api/pool/<pool_id>/flags/resolver/<flag_id>', methods=['POST'])
@login_required
def api_resolver_flag(pool_id, flag_id):
    sucesso = automation_manager.resolver_flag(pool_id, flag_id)
    return jsonify({"sucesso": sucesso})

@app.route('/api/pool/<pool_id>/flags/excluir/<flag_id>', methods=['POST'])
@login_required
def api_excluir_flag(pool_id, flag_id):
    sucesso = automation_manager.excluir_flag(pool_id, flag_id)
    return jsonify({"sucesso": sucesso})

@app.route('/api/pool/<pool_id>/flags/limpar_todas', methods=['POST'])
@login_required
def api_limpar_todas_flags(pool_id):
    sucesso = automation_manager.limpar_todas_flags(pool_id)
    return jsonify({"sucesso": sucesso})

@app.route('/api/flags/global', methods=['GET'])
@login_required
def api_flags_global():
    return jsonify(automation_manager.obter_resumo_global())

# ==========================================
# APIs ESPMAP (GERADOR DE FIRMWARE ESP32)
# ==========================================

from managers.espmap_manager import ESPMAPManager

@app.route('/api/pool/<pool_id>/espmap/catalogo', methods=['GET'])
@login_required
def api_espmap_catalogo(pool_id):
    return jsonify(ESPMAPManager.obter_catalogo())

def _gerar_firmware_pool(pool, fonte):
    wifi_ssid = fonte.get("wifi_ssid", "SuaRedeWiFi")
    wifi_pass = fonte.get("wifi_pass", "SuaSenhaWiFi")
    try:
        intervalo = int(fonte.get("intervalo", 2))
    except (TypeError, ValueError):
        intervalo = 2
    linguagem = str(fonte.get("linguagem", "arduino")).lower()
    protocolo = str(fonte.get("protocolo", "lan_http")).lower()
    porta_padrao = obter_porta_servidor()
    server_host = str(fonte.get("server_host") or "").strip() or obter_info_rede(porta_padrao)["ip_lan_principal"]
    try:
        server_port = int(fonte.get("server_port") or porta_padrao)
    except (TypeError, ValueError):
        server_port = porta_padrao

    sensores = fonte.get("sensores")
    if sensores is None and "sensores_json" in fonte:
        try:
            sensores = json.loads(fonte.get("sensores_json", "[]"))
        except Exception:
            sensores = []

    kwargs = dict(
        wifi_ssid=wifi_ssid,
        wifi_pass=wifi_pass,
        sensores=sensores or [],
        intervalo_segundos=intervalo,
        protocolo=protocolo,
        server_host=server_host,
        server_port=server_port,
        api_token=pool.get("api_token", ""),
    )
    if linguagem == "micropython":
        return ESPMAPManager.gerar_codigo_micropython(pool, **kwargs), linguagem
    return ESPMAPManager.gerar_codigo(pool, **kwargs), linguagem

@app.route('/api/pool/<pool_id>/espmap/gerar', methods=['POST'])
@login_required
def api_espmap_gerar(pool_id):
    data = request.get_json() or {}
    pools = config_manager.obter("pools", "lista", [])
    pool = next((p for p in pools if p["id"] == pool_id), None)
    if not pool:
        return jsonify({"sucesso": False, "erro": "Pool não encontrada."}), 404

    codigo, linguagem = _gerar_firmware_pool(pool, data)
    return jsonify({"sucesso": True, "codigo": codigo, "linguagem": linguagem})

@app.route('/api/pool/<pool_id>/espmap/download', methods=['POST'])
@login_required
def api_espmap_download(pool_id):
    pools = config_manager.obter("pools", "lista", [])
    pool = next((p for p in pools if p["id"] == pool_id), None)
    if not pool:
        return jsonify({"sucesso": False, "erro": "Pool não encontrada."}), 404

    codigo, linguagem = _gerar_firmware_pool(pool, request.form)
    if linguagem == "micropython":
        nome_arquivo = f"main_{pool.get('tipo', 'iot')}_{pool_id.lower()}.py"
        mimetype = "text/x-python"
    else:
        nome_arquivo = f"firmware_{pool.get('tipo', 'iot')}_{pool_id.lower()}.ino"
        mimetype = "text/x-c"

    memoria = io.BytesIO()
    memoria.write(codigo.encode('utf-8'))
    memoria.seek(0)
    
    return send_file(
        memoria,
        mimetype=mimetype,
        as_attachment=True,
        download_name=nome_arquivo
    )

# ==========================================
# APIs DE WIPE DA APLICAÇÃO COM SENHA EXCLUSIVA
# ==========================================

@app.route('/api/sistema/wipe', methods=['POST'])
@login_required
def api_sistema_wipe():
    if session.get('role') != 'adm':
        return jsonify({"sucesso": False, "erro": "Acesso negado. Apenas o Administrador Geral pode executar o WIPE."}), 403

    data = request.get_json() or {}
    senha_wipe = data.get("senha_wipe", "").strip()
    if not senha_wipe:
        return jsonify({"sucesso": False, "erro": "A senha exclusiva de WIPE é obrigatória."}), 400

    sucesso, msg = account_manager.executar_wipe(senha_wipe)
    if sucesso:
        session.clear()
        runtimes.clear()
        return jsonify({"sucesso": True, "mensagem": msg})
    return jsonify({"sucesso": False, "erro": msg}), 400

@app.route('/api/sistema/wipe/definir-senha', methods=['POST'])
@login_required
def api_sistema_wipe_definir_senha():
    if session.get('role') != 'adm':
        return jsonify({"sucesso": False, "erro": "Acesso negado. Apenas o Administrador pode configurar a senha de WIPE."}), 403

    data = request.get_json() or {}
    nova_senha = data.get("nova_senha", "").strip()
    senha_atual = data.get("senha_atual", "").strip()
    sucesso, msg = account_manager.definir_senha_wipe(nova_senha, senha_atual=senha_atual)
    return jsonify({"sucesso": sucesso, "mensagem": msg if sucesso else None, "erro": None if sucesso else msg}), (200 if sucesso else 400)

# Banco de dados da Pool
@app.route('/pool/database')
@app.route('/database')
@login_required
@pool_required
def database():
    pool = get_pool_ativo()
    return render_template(
        'database.html',
        theme=config_manager.obter("aparencia", "tema", "Moderno").lower(),
        config=config_manager.dados,
        pool=pool,
        pool_id=session.get('pool_ativo')
    )

@app.route('/api/database/conectar', methods=['POST'])
@login_required
@pool_required
def api_database_conectar():
    data = request.json or {}
    pool_id = session.get('pool_ativo')
    pool = get_pool_ativo()
    sql_cfg = dict(pool.get("sql", {})) if pool else {}

    if data.get('tipo'):    sql_cfg['tipo']    = data['tipo']
    if data.get('caminho'): sql_cfg['caminho'] = data['caminho']
    if data.get('host'):    sql_cfg['host']    = data['host']
    if data.get('porta'):   sql_cfg['porta']   = int(data['porta'])
    if data.get('usuario'): sql_cfg['usuario'] = data['usuario']
    if 'senha' in data:     sql_cfg['senha']   = data['senha']
    if data.get('banco'):   sql_cfg['banco']   = data['banco']

    salvar_config_pool(pool_id, sql_cfg=sql_cfg)

    # Atualiza em memória o runtimes
    rt = get_runtime(pool_id)
    rt.sql._engine = None
    rt.sql.subtipo_detectado = None
    if rt.sql.testar_conexao():
        rt.sql.garantir_tabela_mqtt()

    # Notifica dashboard em tempo real
    socketio.emit('update_hardware', get_hardware_state(pool_id), to=f'dashboard_{pool_id}')

    estado = rt.sql.estado()
    return jsonify({
        "conectado": estado.get("conectado", False),
        "erro": estado.get("erro"),
        "tipo": estado.get("tipo", "sqlite"),
        "nome_tipo": estado.get("nome_tipo", "SQLite")
    })

@app.route('/api/database/status')
@login_required
@pool_required
def api_database_status():
    rt = get_runtime(session.get('pool_ativo'))
    estado = rt.sql.estado() if rt else {"conectado": False, "erro": "Sem runtime", "tipo": "sqlite", "nome_tipo": "SQLite"}
    pool = get_pool_ativo()
    sql_cfg = pool.get("sql", {}) if pool else {}
    return jsonify({
        "conectado": estado.get("conectado", False),
        "erro": estado.get("erro"),
        "tipo": estado.get("tipo", "sqlite"),
        "nome_tipo": estado.get("nome_tipo", "SQLite"),
        "config": sql_cfg
    })

@app.route('/api/database/tables')
@login_required
@pool_required
def db_tables():
    rt = get_runtime(session.get('pool_ativo'))
    rt.sql.garantir_tabela_mqtt()
    if not rt.sql.conectado:
        rt.sql.testar_conexao()
    tabelas = rt.sql.listar_tabelas()
    return jsonify({"tabelas": tabelas, "status": "ok" if rt.sql.conectado else "erro", "erro": rt.sql.ultimo_erro})

@app.route('/api/database/read/<tabela>')
@login_required
@pool_required
def db_read(tabela):
    try:
        rt = get_runtime(session.get('pool_ativo'))
        colunas, linhas = rt.sql.ler_tabela(tabela, limite=200)
        return jsonify({"colunas": colunas, "linhas": linhas, "status": "ok"})
    except Exception as e:
        return jsonify({"status": "erro", "erro": str(e)})

@app.route('/api/config', methods=['POST'])
@login_required
def update_config():
    data = request.json or {}
    for section, values in data.items():
        for key, val in values.items():
            config_manager.definir(section, key, val, salvar=False)
    config_manager.salvar()
    
    # Aplicar configurações na hora
    nova_vel = int(config_manager.obter("comunicacao", "velocidade", "115200"))
    novo_timeout = get_timeout()
    serial_manager.configurar(velocidade=nova_vel, timeout=novo_timeout)
    
    # Enviar configuração atualizada para os clientes via websocket (para telas abertas)
    socketio.emit('reload_config', config_manager.dados)
    
    return jsonify({"status": "ok"})

@app.route('/api/hardware')
@login_required
def api_hardware():
    return jsonify(get_hardware_state(session.get('pool_ativo')))

# ==========================================
# APIs HÍBRIDAS LAN / VPN (SEM BROKER MQTT)
# ==========================================

@app.route('/api/health', methods=['GET'])
def api_health():
    return jsonify({"status": "ok", "versao": "0.2", "modo": "lan_vpn"})

def _extrair_token_requisicao(payload):
    token = request.headers.get("X-API-Key") or ""
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if not token and isinstance(payload, dict):
        token = str(payload.get("token") or "")
    if not token:
        token = request.args.get("token", "")
    return token.strip()

def _localizar_pool_telemetria(pool_id_param, payload, token):
    pools = config_manager.obter("pools", "lista", [])
    alvo_id = (pool_id_param or (payload.get("pool_id") if isinstance(payload, dict) else None) or "").strip()
    if alvo_id:
        return next((p for p in pools if p.get("id") == alvo_id), None)
    if token:
        for p in pools:
            tok_pool = str(p.get("api_token") or "")
            if tok_pool and hmac.compare_digest(token, tok_pool):
                return p
    return None

@app.route('/api/telemetria', methods=['POST'])
@app.route('/api/telemetria/<pool_id>', methods=['POST'])
def api_telemetria(pool_id=None):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "erro": "Corpo JSON inválido ou ausente."}), 400

    token = _extrair_token_requisicao(payload)
    pool = _localizar_pool_telemetria(pool_id, payload, token)
    if not pool:
        if token and config_manager.obter("rede", "exigir_token_telemetria", True) and not pool_id and not payload.get("pool_id"):
            return jsonify({"ok": False, "erro": "Token de dispositivo inválido ou ausente (header X-API-Key)."}), 401
        return jsonify({"ok": False, "erro": "Pool não encontrada."}), 404

    if not pool.get("lan_habilitada", True):
        return jsonify({"ok": False, "erro": "LAN Direta (HTTP) está desligada nesta pool."}), 403

    if config_manager.obter("rede", "exigir_token_telemetria", True):
        token_esperado = str(pool.get("api_token") or "")
        if not token or not token_esperado or not hmac.compare_digest(token, token_esperado):
            return jsonify({"ok": False, "erro": "Token de dispositivo inválido ou ausente (header X-API-Key)."}), 401

    payload_limpo = {k: v for k, v in payload.items() if k != "token"}
    payload_limpo.setdefault("pool_id", pool["id"])
    aceito, comandos = processar_telemetria_lan(pool["id"], payload_limpo, ip_origem=request.remote_addr)
    return jsonify({
        "ok": True,
        "aceito": aceito,
        "pool_id": pool["id"],
        "recebido_em": time.strftime("%H:%M:%S"),
        "comandos": comandos,
    })

@app.route('/api/pool/<pool_id>/comando', methods=['POST'])
@login_required
def api_pool_enfileirar_comando(pool_id):
    pool = next((p for p in config_manager.obter("pools", "lista", []) if p["id"] == pool_id), None)
    if not pool:
        return jsonify({"sucesso": False, "erro": "Pool não encontrada."}), 404
    data = request.get_json(silent=True) or {}
    acao = str(data.get("acao") or "").strip()
    if not acao:
        return jsonify({"sucesso": False, "erro": "Informe a ação do comando."}), 400
    valor = data.get("valor")

    rt = get_runtime(pool_id)
    item = rt.enfileirar_comando(acao, valor=valor, origem=session.get("usuario", "painel"))
    rt.logger.info(f"Comando enfileirado para o ESP32: {acao}={valor}")

    # Se MQTT também estiver ativo nesta pool, publica lá também
    if rt.mqtt and rt.mqtt.conectado:
        topico_cmd = pool.get("mqtt", {}).get("topico_comando")
        rt.mqtt.publicar(json.dumps(item, ensure_ascii=False), topico=topico_cmd)

    return jsonify({"sucesso": True, "comando": item, "pendentes": len(rt.comandos_pendentes)})

def _montar_info_lan_pool(pool_id):
    pool = next((p for p in config_manager.obter("pools", "lista", []) if p["id"] == pool_id), None)
    if not pool:
        return None
    garantir_tokens_pools()
    rt = get_runtime(pool_id)
    rede = obter_info_rede(obter_porta_servidor())
    agora = time.time()
    lan_habilitada = bool(pool.get("lan_habilitada", True))
    ativo_http = bool(
        lan_habilitada
        and rt and rt.ultimo_pacote_tempo > 0
        and (agora - rt.ultimo_pacote_tempo) <= 15.0
        and rt.ultima_fonte == "http_lan"
    )
    return {
        "sucesso": True,
        "pool_id": pool_id,
        "pool_nome": pool.get("nome", "Dispositivo"),
        "modo_conexao": pool.get("modo_conexao", "lan_http"),
        "lan_habilitada": lan_habilitada,
        "ativo": ativo_http,
        "api_token": pool.get("api_token", ""),
        "url_telemetria": rede["endpoint_telemetria"],
        "url_telemetria_pool": f"{rede['endpoint_telemetria']}/{pool_id}",
        "ultimo_ip": rt.ultimo_ip_dispositivo if rt else None,
        "total_pacotes": rt.total_pacotes_http if rt else 0,
        "ultimo_recebido": rt.ultimo_pacote_http_em if rt else None,
        "ultimo_payload": rt.ultimo_payload_http if rt else None,
        "pendentes": len(rt.comandos_pendentes) if rt else 0,
        "mqtt_conectado": bool(rt and rt.mqtt and rt.mqtt.conectado),
        "mqtt_habilitado": bool(pool.get("mqtt", {}).get("conectar_ao_entrar", False)),
        "rede": rede,
        "config_rede": config_manager.obter_secao("rede"),
    }

@app.route('/api/pool/<pool_id>/lan/info', methods=['GET'])
@login_required
def api_pool_lan_info(pool_id):
    info = _montar_info_lan_pool(pool_id)
    if not info:
        return jsonify({"sucesso": False, "erro": "Pool não encontrada."}), 404
    return jsonify(info)

@app.route('/api/lan/status', methods=['GET'])
@login_required
@pool_required
def api_lan_status():
    pool_id = session.get('pool_ativo')
    info = _montar_info_lan_pool(pool_id)
    if not info:
        return jsonify({"sucesso": False, "erro": "Pool ativa não encontrada."}), 404
    return jsonify(info)

@app.route('/api/lan/ativar', methods=['POST'])
@login_required
@pool_required
def api_lan_ativar():
    pool_id = session.get('pool_ativo')
    lista = config_manager.obter("pools", "lista", [])
    pool = next((p for p in lista if p.get("id") == pool_id), None)
    if not pool:
        return jsonify({"sucesso": False, "erro": "Pool não encontrada."}), 404

    pool["lan_habilitada"] = True
    pool["modo_conexao"] = "lan_http"
    mqtt_cfg = pool.setdefault("mqtt", {})
    mqtt_cfg["conectar_ao_entrar"] = False
    if not pool.get("api_token"):
        pool["api_token"] = gerar_token_dispositivo()
    config_manager.salvar()

    rt = get_runtime(pool_id)
    if rt:
        if rt.mqtt and rt.mqtt.conectado:
            rt.mqtt.desconectar()
        rt.logger.info("LAN Direta (HTTP) ativada nesta pool.")
        socketio.emit('update_hardware', get_hardware_state(pool_id), to=f'dashboard_{pool_id}')
    socketio.emit('pools_status_update', obter_status_todas_pools())

    return jsonify({"sucesso": True, "lan_habilitada": True, "mensagem": "LAN Direta (HTTP) ativada e Broker MQTT desligado."})

@app.route('/api/lan/desligar', methods=['POST'])
@login_required
@pool_required
def api_lan_desligar():
    pool_id = session.get('pool_ativo')
    lista = config_manager.obter("pools", "lista", [])
    pool = next((p for p in lista if p.get("id") == pool_id), None)
    if not pool:
        return jsonify({"sucesso": False, "erro": "Pool não encontrada."}), 404

    pool["lan_habilitada"] = False
    config_manager.salvar()

    rt = runtimes.get(pool_id)
    if rt:
        if rt.ultima_fonte == "http_lan":
            rt.ultimo_pacote_tempo = 0.0
            rt.ultima_fonte = None
        rt.logger.info("LAN Direta (HTTP) desligada nesta pool.")
        socketio.emit('update_hardware', get_hardware_state(pool_id), to=f'dashboard_{pool_id}')
    socketio.emit('pools_status_update', obter_status_todas_pools())

    return jsonify({"sucesso": True, "lan_habilitada": False, "mensagem": "LAN Direta (HTTP) desligada nesta pool."})

@app.route('/api/pool/<pool_id>/lan/regenerar-token', methods=['POST'])
@login_required
def api_pool_lan_regenerar_token(pool_id):
    lista = config_manager.obter("pools", "lista", [])
    pool = next((p for p in lista if p["id"] == pool_id), None)
    if not pool:
        return jsonify({"sucesso": False, "erro": "Pool não encontrada."}), 404
    novo_token = gerar_token_dispositivo()
    pool["api_token"] = novo_token
    config_manager.salvar()
    return jsonify({"sucesso": True, "api_token": novo_token})

@app.route('/api/pool/<pool_id>/lan/testar', methods=['POST'])
@login_required
def api_pool_lan_testar(pool_id):
    pool = next((p for p in config_manager.obter("pools", "lista", []) if p["id"] == pool_id), None)
    if not pool:
        return jsonify({"sucesso": False, "erro": "Pool não encontrada."}), 404
    if not pool.get("lan_habilitada", True):
        return jsonify({"sucesso": False, "erro": "A LAN Direta está desligada nesta pool. Ative a LAN antes de testar."}), 400
    tipo = normalizar_tipo(pool.get("tipo"))
    perfil = obter_perfil(tipo)
    payload_teste = {
        "pool_id": pool_id,
        "dispositivo": pool.get("nome", "Dispositivo Teste"),
        "tipo": tipo,
        "origem_teste": "lan_http",
    }
    for m in perfil.get("medidas", []):
        v_min = float(m.get("min", 0))
        v_max = float(m.get("max", 100))
        payload_teste[m["chave"]] = round((v_min + v_max) / 2.0, 2)
    aceito, comandos = processar_telemetria_lan(pool_id, payload_teste, ip_origem=request.remote_addr)
    return jsonify({"sucesso": True, "aceito": aceito, "payload": payload_teste, "comandos": comandos})

@app.route('/api/rede/info', methods=['GET'])
@login_required
def api_rede_info():
    rede = obter_info_rede(obter_porta_servidor())
    return jsonify({
        "sucesso": True,
        "rede": rede,
        "config_rede": config_manager.obter_secao("rede"),
    })

@app.route('/api/mqtt/status')
@login_required
@pool_required
def api_mqtt_status():
    pool_id = session.get('pool_ativo')
    rt = get_runtime(pool_id)
    pool = get_pool_ativo()
    mqtt_cfg = pool.get("mqtt", {}) if pool else {}
    tipo = pool.get("tipo", "estufa") if pool else "estufa"
    estado = rt.mqtt.estado() if rt else {"conectado": False, "erro": "Sem pool"}
    return jsonify({
        "conectado": estado.get("conectado", False),
        "conectado_em": estado.get("conectado_em"),
        "total_mensagens": estado.get("total_mensagens", 0),
        "ultima_mensagem": estado.get("ultima_mensagem"),
        "erro": estado.get("erro"),
        "pool_id": pool_id,
        "pool_nome": pool.get("nome", "Dispositivo") if pool else "",
        "config": {
            "host": mqtt_cfg.get("host", "localhost"),
            "porta": mqtt_cfg.get("porta", "1883"),
            "topico": mqtt_cfg.get("topico", f"{tipo}/telemetria"),
            "topico_padrao": f"{tipo}/telemetria",
            "topico_cmd": mqtt_cfg.get("topico_comando", f"{tipo}/comando"),
            "usuario": mqtt_cfg.get("usuario", ""),
            "conectar_ao_entrar": mqtt_cfg.get("conectar_ao_entrar", False)
        }
    })

@app.route('/api/mqtt/testar', methods=['POST'])
@login_required
def api_mqtt_testar():
    data = request.json or {}
    host = data.get("host", "localhost").strip()
    porta = data.get("porta", 1883)
    sucesso, msg, latencia = MQTTManager.testar_broker(host, porta)
    return jsonify({
        "sucesso": sucesso,
        "mensagem": msg,
        "latencia_ms": latencia
    })

@app.route('/api/mqtt/publicar-teste', methods=['POST'])
@login_required
@pool_required
def api_mqtt_publicar_teste():
    pool_id = session.get('pool_ativo')
    rt = get_runtime(pool_id)
    if not rt or not rt.mqtt.conectado:
        return jsonify({"sucesso": False, "erro": "O MQTT não está conectado nesta pool."}), 400
    
    data = request.json or {}
    topico = data.get("topico")
    import time
    mensagem = data.get("mensagem", json.dumps({"origem": "square_panel", "tipo": "ping_teste", "ts": int(time.time())}))
    sucesso = rt.mqtt.publicar(mensagem, topico=topico)
    return jsonify({"sucesso": sucesso, "mensagem": "Mensagem de teste publicada com sucesso!" if sucesso else "Falha ao publicar."})

@app.route('/api/mqtt/conectar', methods=['POST'])
@login_required
@pool_required
def api_mqtt_conectar():
    data = request.json or {}
    pool_id = session.get('pool_ativo')

    pool = get_pool_ativo()
    mqtt_cfg = dict(pool.get("mqtt", {})) if pool else {}

    if data.get('host'):          mqtt_cfg['host']    = data['host'].strip()
    if data.get('porta'):         mqtt_cfg['porta']   = str(data['porta']).strip()
    if data.get('topico_telemetria'): mqtt_cfg['topico'] = data['topico_telemetria'].strip()
    if data.get('topico_cmd'):    mqtt_cfg['topico_comando'] = data['topico_cmd'].strip()
    if data.get('usuario') is not None: mqtt_cfg['usuario'] = data['usuario'].strip()
    if data.get('senha')   is not None: mqtt_cfg['senha']   = data['senha'].strip()
    
    if "conectar_ao_entrar" in data:
        mqtt_cfg['conectar_ao_entrar'] = bool(data["conectar_ao_entrar"])
    else:
        mqtt_cfg['conectar_ao_entrar'] = True

    if pool:
        pool["modo_conexao"] = "mqtt"
    salvar_config_pool(pool_id, mqtt_cfg=mqtt_cfg)

    rt = get_runtime(pool_id)
    if rt:
        rt.mqtt.desconectar()
        rt.mqtt.conectar()
        import time; time.sleep(1.2)
        estado = rt.mqtt.estado()
        socketio.emit('update_hardware', get_hardware_state(pool_id), to=f'dashboard_{pool_id}')
        return jsonify({"conectado": estado.get("conectado", False), "erro": estado.get("erro")})
    return jsonify({"conectado": False, "erro": "Runtime não encontrado"})

@app.route('/api/mqtt/desconectar', methods=['POST'])
@login_required
@pool_required
def api_mqtt_desconectar():
    pool_id = session.get('pool_ativo')
    pool = get_pool_ativo()
    if pool:
        mqtt_cfg = dict(pool.get("mqtt", {}))
        mqtt_cfg['conectar_ao_entrar'] = False
        salvar_config_pool(pool_id, mqtt_cfg=mqtt_cfg)
        
    rt = get_runtime(pool_id)
    if rt:
        rt.mqtt.desconectar()
        socketio.emit('update_hardware', get_hardware_state(pool_id), to=f'dashboard_{pool_id}')
        estado = rt.mqtt.estado()
        return jsonify({"conectado": estado.get("conectado", False), "erro": estado.get("erro")})
    return jsonify({"conectado": False, "erro": "Runtime não encontrado"})

@socketio.on('connect')
def handle_connect(auth=None):
    from flask_socketio import emit
    pool_id = session.get('pool_ativo') if has_request_context() else None
    emit('update_hardware', get_hardware_state(pool_id))
    rt = get_runtime(pool_id) if pool_id else None
    if rt:
        dados = rt.sensor.obter_dados()
        if dados:
            emit('sensor_data', dados.para_dict())

@socketio.on('join_dashboard')
def handle_join_dashboard():
    """Cliente entra na sala 'dashboard' da sua pool."""
    from flask_socketio import join_room, emit
    pool_id = session.get('pool_ativo')
    if pool_id:
        join_room(f'dashboard_{pool_id}')
        emit('update_hardware', get_hardware_state(pool_id))
        rt = get_runtime(pool_id)
        logs_pool = rt.logger.obter_ultimos(10) if rt else logger.obter_ultimos(10)
        emit('logs', logs_pool)

@socketio.on('leave_dashboard')
def handle_leave_dashboard():
    from flask_socketio import leave_room
    pool_id = session.get('pool_ativo')
    if pool_id:
        leave_room(f'dashboard_{pool_id}')

def _imprimir_banner_rede(porta):
    info = obter_info_rede(porta)
    print("\n" + "=" * 64)
    print("  SQUARE EXTREME 0.2 — SERVIDOR HÍBRIDO (LAN + VPN SEM BROKER)")
    print("=" * 64)
    print(f"  Host Local      : {info['url_local']}")
    for item in info['interfaces_lan']:
        print(f"  Rede LAN        : {item['url']}  ({item['interface']})")
    if info['interfaces_vpn']:
        for item in info['interfaces_vpn']:
            print(f"  Rede VPN        : {item['url']}  ({item['interface']})")
    else:
        print("  Rede VPN        : Nenhuma interface VPN ativa detectada (Tailscale/WireGuard)")
    print(f"  Endpoint ESP32  : POST {info['endpoint_telemetria']}")
    print("=" * 64 + "\n")

if __name__ == '__main__':
    # Inicialização da porta serial padrão (compartilhada)
    if config_manager.obter("sistema", "iniciar_conectado", True):
        serial_manager.conectar()

    host_bind = (os.environ.get("SQUARE_HOST") or config_manager.obter("rede", "host", "0.0.0.0")).strip()
    porta_bind = obter_porta_servidor()
    debug_env = os.environ.get("SQUARE_DEBUG")
    debug_bind = (debug_env == "1") if debug_env is not None else bool(config_manager.obter("rede", "debug", False))

    logger.info(f"Aplicação Web Flask iniciada em {host_bind}:{porta_bind} (modo LAN/VPN).")
    _imprimir_banner_rede(porta_bind)

    # Inicia thread em background
    socketio.start_background_task(background_tasks)

    # Inicia servidor
    socketio.run(app, host=host_bind, port=porta_bind, debug=debug_bind, use_reloader=False)
