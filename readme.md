# ExtremeSquare 0.2 (SQUARE) — Plataforma IoT LAN / VPN

Aplicação web em **Python (Flask + Flask-SocketIO)** para monitoramento e automação de dispositivos IoT (placas ESP32) em tempo real, organizada por **Pools** independentes.

Projetada para operar de forma **híbrida**: funciona integralmente na rede privada local (**LAN**, mesmo sem acesso à internet) e aceita acesso remoto seguro por **VPN** (Tailscale, WireGuard, ZeroTier) — sem exigir broker MQTT obrigatório.

---

## Principais Recursos

- **Pools multi-aplicação (`models/perfis.py`):** suporta 5 perfis com métricas, unidades e barras de nível dedicadas:
  - `estufa` (Estufa Inteligente)
  - `lixeira` (Lixeira Inteligente)
  - `reservatorio` (Nível de Reservatório)
  - `energia` (Medidor de Energia Elétrica)
  - `consumo_agua` (Consumo de Água / Hidrômetro)
- **Comunicação Direta LAN / VPN sem Broker (`POST /api/telemetria`):**
  - Cada pool possui token `api_token` exclusivo enviado no header `X-API-Key`.
  - Comandos remotos enfileirados em `POST /api/pool/<id>/comando` são entregues ao ESP32 na resposta JSON (`comandos[]`) do próximo `POST`.
  - Pode ser ligada ou desligada por pool (`POST /api/lan/ativar` e `POST /api/lan/desligar`).
- **Suporte opcional a Broker MQTT e USB/Serial:** mantendo `paho-mqtt` e `pyserial` para quem preferir broker ou bancada USB.
- **Interface 100% Offline-Ready (`static/vendor/`):** Bootstrap 5, Bootstrap Icons, Socket.IO e Chart.js + Luxon servidos localmente sem CDNs externas.
- **Descoberta automática de IPs (`managers/network_manager.py`):** lista URLs da LAN e de interfaces VPN ativas na aba **Rede LAN & VPN** e na janela unificada **MQTT / LAN**.
- **Banco de Dados isolado por pool (`managers/sql_manager.py`):** SQLAlchemy compatível com SQLite (padrão), MySQL / MariaDB e PostgreSQL.
- **ESPMAP (`managers/espmap_manager.py`):** gerador de firmware para ESP32 em **Arduino C++ (`.ino`)** e **MicroPython (`main.py`)** nos modos `lan_http` e `mqtt`.
- **Automações, Flags e Segurança:** regras condicionais por grandeza, flags de alerta por severidade, contas com perfis (`adm` / `operador`), setup inicial (`/setup`), `secret.key` dinâmica e Zona de **WIPE** protegida por senha exclusiva.
- **3 Temas Visuais:** **Moderno**, **Industrial** (alto contraste âmbar) e **Claro** (inspirado no Teams/Fluent).

---

## Arquitetura do Projeto

```text
app.py                              Servidor Flask, rotas, APIs LAN/VPN e SocketIO
managers/
  account_manager.py                Contas de usuário (RBAC), hashes e WIPE
  automation_manager.py             Regras condicionais e flags de integridade
  config_manager.py                 Configurações persistentes em JSON
  espmap_manager.py                 Gerador de firmware ESP32 (Arduino / MicroPython)
  logger.py                         Logs por sistema e isolados por pool
  mqtt_manager.py                   Cliente MQTT assíncrono opcional
  network_manager.py                Descoberta LAN/VPN, tokens e secret.key
  sensor_manager.py                 Validação JSON (Serial, MQTT e HTTP LAN)
  serial_manager.py                 Comunicação USB/Serial
  sql_manager.py                    Conexão SQLite, MySQL/MariaDB e PostgreSQL
models/
  perfis.py                         Perfis e medidas por tipo de aplicação
  sensor_data.py                    Estrutura de dados das leituras
templates/                          Páginas Jinja2 (dashboard, pools, database, settings)
static/
  css/style.css                     Estilos dos 3 temas
  js/app.js                         WebSockets, gráficos Chart.js e status ao vivo
  vendor/                           Bibliotecas frontend locais (offline)
simuladores/                        Simuladores MQTT por aplicação
simulador_lan_http.py               Simulador standalone LAN HTTP (sem dependências externas)
```

---

## Instalação e Execução

1. Instale as dependências (ou execute `instalar_dependencias.bat`):
   ```bash
   pip install -r requirements.txt
   ```
2. Inicie o servidor:
   - **Modo interativo (com URLs no terminal):** execute `iniciar_aplicacao.bat` ou:
     ```bash
     python app.py
     ```
   - **Modo segundo plano (sem janela aberta):** execute `iniciar_servidor_segundo_plano.bat` (e `parar_servidor.bat` para encerrar).
3. Na primeira execução, acesse `http://localhost:5000` (ou `http://<IP-LAN>:5000`) para cadastrar a conta **Administrador** inicial em `/setup`.

### Simulador LAN sem Broker (para testes)

```bash
python simulador_lan_http.py --pool-id <ID_DA_POOL> --token <TOKEN> --host <IP_LAN> --tipo estufa
```
