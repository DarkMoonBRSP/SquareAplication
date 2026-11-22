document.addEventListener("DOMContentLoaded", () => {
    const socket = io();

    // Carrega a configuração do perfil ativo da pool (se fornecido na página)
    let perfilConfig = null;
    const perfilEl = document.getElementById('perfil-config-json');
    if (perfilEl) {
        try {
            perfilConfig = JSON.parse(perfilEl.textContent);
        } catch(e) {
            console.error("Erro ao carregar perfilConfig:", e);
        }
    }

    // Helper para cores do Chart.js de acordo com o tema ativo
    function obterCoresTemaGrafico() {
        if (document.body.classList.contains('theme-industrial')) {
            return {
                border: '#ff9800',
                background: 'rgba(255, 152, 0, 0.18)',
                grid: 'rgba(255, 152, 0, 0.15)',
                ticks: '#ffaa00'
            };
        } else if (document.body.classList.contains('theme-claro')) {
            return {
                border: '#5b5fc7',
                background: 'rgba(91, 95, 199, 0.15)',
                grid: 'rgba(0, 0, 0, 0.08)',
                ticks: '#605e5c'
            };
        }
        // Moderno (Escuro Tecnológico)
        return {
            border: '#00e676',
            background: 'rgba(0, 230, 118, 0.14)',
            grid: 'rgba(255, 255, 255, 0.08)',
            ticks: '#8b949e'
        };
    }

    // Configuração do Chart.js
    const ctx = document.getElementById('graficoSensores');
    let chart;
    try {
        if (ctx) {
            const sensorSelectInit = document.getElementById('grafico-sensor');
            const labelInicial = (sensorSelectInit && sensorSelectInit.options[sensorSelectInit.selectedIndex]) 
                ? sensorSelectInit.options[sensorSelectInit.selectedIndex].text 
                : 'Medição';

            const coresGrafico = obterCoresTemaGrafico();

            chart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: labelInicial,
                        data: [],
                        borderColor: coresGrafico.border,
                        backgroundColor: coresGrafico.background,
                        tension: 0.2,
                        fill: true
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    scales: {
                        x: {
                            type: 'time',
                            time: { unit: 'second', tooltipFormat: 'HH:mm:ss', displayFormats: { second: 'HH:mm:ss' } },
                            grid: { color: coresGrafico.grid },
                            ticks: { color: coresGrafico.ticks }
                        },
                        y: { 
                            beginAtZero: true,
                            grid: { color: coresGrafico.grid },
                            ticks: { color: coresGrafico.ticks }
                        }
                    }
                }
            });

            if (sensorSelectInit) {
                sensorSelectInit.addEventListener('change', (e) => {
                    chart.data.datasets[0].label = e.target.options[e.target.selectedIndex].text;
                    chart.data.datasets[0].data = []; // limpa histórico ao trocar
                    chart.update();
                });
            }
        }
    } catch(err) {
        console.error("Erro ao inicializar Chart.js:", err);
    }

    let maxPoints = 60;
    let autoUpdate = true;

    socket.on('sensor_data', (dados) => {
        if (!dados) return;

        // Atualiza status de telemetria recebida no card de status
        const hwDadosStatus = document.getElementById('hw-dados-status');
        if (hwDadosStatus) {
            hwDadosStatus.innerHTML = '<i class="bi bi-circle-fill me-1" style="font-size: 0.45rem;"></i> Conectado';
            hwDadosStatus.className = 'badge bg-success';
        }
        const hwDadosHora = document.getElementById('hw-dados-hora');
        if (hwDadosHora) {
            const agora = new Date();
            hwDadosHora.innerText = agora.toLocaleTimeString();
        }

        // 1. Atualiza medições com base no perfil ativo
        if (perfilConfig && Array.isArray(perfilConfig.medidas)) {
            perfilConfig.medidas.forEach(med => {
                const el = document.getElementById('val-' + med.chave);
                if (el && dados[med.chave] !== undefined && dados[med.chave] !== null) {
                    const raw = dados[med.chave];
                    const formatado = typeof raw === 'number' 
                        ? (Number.isInteger(raw) ? raw : raw.toFixed(1))
                        : raw;
                    el.innerText = `${formatado} ${med.unidade || ''}`.trim();
                }
            });
        }

        // Suporte dinâmico para múltiplos sensores ESP32 (ESPMAP)
        const selectSensor = document.getElementById('grafico-sensor');
        const containerExtras = document.getElementById('container-sensores-extras');

        for (const [chave, valor] of Object.entries(dados)) {
            if (chave === 'extras' || chave === 'pool_id' || chave === 'dispositivo' || chave === 'tipo' || chave === 'uptime_seg') continue;

            if (typeof valor === 'number') {
                // 1. Adiciona dinamicamente ao seletor de métrica do gráfico se for sensor novo
                if (selectSensor && !selectSensor.querySelector(`option[value="${chave}"]`)) {
                    const opt = document.createElement('option');
                    opt.value = chave;
                    opt.text = chave.replace(/_/g, ' ').toUpperCase();
                    selectSensor.appendChild(opt);
                }

                // 2. Cria indicador visual dinâmico no painel de medições se for sensor extra
                let el = document.getElementById('val-' + chave);
                if (!el && containerExtras) {
                    const div = document.createElement('div');
                    div.className = 'd-flex justify-content-between mb-3 fs-5';
                    div.innerHTML = `
                        <span><i class="bi bi-activity text-info"></i> ${chave.replace(/_/g, ' ')}</span>
                        <span class="fw-bold text-info" id="val-${chave}">--</span>
                    `;
                    containerExtras.appendChild(div);
                    el = document.getElementById('val-' + chave);
                }

                if (el) {
                    const formatado = Number.isInteger(valor) ? valor : valor.toFixed(1);
                    const unidade = el.getAttribute('data-unidade') || '';
                    el.innerText = `${formatado} ${unidade}`.trim();
                }
            } else if (typeof valor !== 'object') {
                const el = document.getElementById('val-' + chave);
                if (el) el.innerText = valor;
            }
        }

        // 2. Atualiza Indicador Gráfico Especial (Lixeira / Reservatório)
        if (perfilConfig && perfilConfig.indicador) {
            const ind = perfilConfig.indicador;
            const val = dados[ind.chave];
            if (val !== undefined && val !== null) {
                const num = parseFloat(val);
                const barra = document.getElementById('indicador-barra');
                const badge = document.getElementById('indicador-status-badge');
                if (barra && !isNaN(num)) {
                    const pct = Math.max(0, Math.min(100, Math.round(num)));
                    barra.style.width = pct + '%';
                    barra.innerText = pct + '%';

                    if (Array.isArray(ind.faixas) && ind.faixas.length > 0) {
                        let faixaEscolhida = ind.faixas[ind.faixas.length - 1];
                        for (const f of ind.faixas) {
                            if (num <= f.ate) {
                                faixaEscolhida = f;
                                break;
                            }
                        }

                        const cores = ['bg-info', 'bg-success', 'bg-warning', 'bg-danger', 'bg-secondary'];
                        cores.forEach(c => {
                            barra.classList.remove(c);
                            if (badge) badge.classList.remove(c);
                        });

                        const classeCor = 'bg-' + faixaEscolhida.cor;
                        barra.classList.add(classeCor);
                        if (badge) {
                            badge.classList.add(classeCor);
                            badge.innerText = faixaEscolhida.texto;
                            if (faixaEscolhida.cor === 'warning') {
                                badge.classList.add('text-dark');
                            } else {
                                badge.classList.remove('text-dark');
                            }
                        }
                    }
                }
            }
        }

        // 3. Atualiza Estados / Atuadores pré-definidos do perfil (ex: Bomba)
        if (perfilConfig && Array.isArray(perfilConfig.estados)) {
            perfilConfig.estados.forEach(est => {
                const el = document.getElementById('estado-' + est.chave);
                if (el) {
                    const rawVal = dados[est.chave] !== undefined 
                        ? dados[est.chave] 
                        : (dados.extras ? dados.extras[est.chave] : undefined);
                    if (rawVal !== undefined) {
                        const ativo = Boolean(rawVal);
                        el.className = 'badge fs-6 ' + (ativo ? 'bg-success' : 'bg-secondary');
                        el.innerText = ativo ? 'Ligado' : 'Desligado';
                    }
                }
            });
        }

        // 4. Atualiza Atuadores adicionais genéricos em dados.extras.atuadores
        if (dados.extras && dados.extras.atuadores && Object.keys(dados.extras.atuadores).length > 0) {
            const painel = document.getElementById('panel-atuadores');
            const container = document.getElementById('atuadores-container');
            if (painel && container) {
                painel.style.display = 'block';
                let html = '';
                for (const [nome, estado] of Object.entries(dados.extras.atuadores)) {
                    const cor = estado ? 'success' : 'secondary';
                    const icone = estado ? 'check-circle' : 'x-circle';
                    html += `<div class="badge bg-${cor} fs-6 p-2"><i class="bi bi-${icone}"></i> ${nome.toUpperCase()}</div>`;
                }
                container.innerHTML = html;
            }
        }

        // 5. Status geral de dados
        const hwDados = document.getElementById('hw-dados-status');
        if (hwDados) {
            hwDados.innerHTML = `<i class="bi bi-circle-fill" style="font-size: 0.5rem;"></i> Conectado`;
            hwDados.className = "text-success";
        }

        // 6. Atualiza gráfico temporal (somente desenha em primeiro plano para poupar recursos)
        if (chart && autoUpdate) {
            const time = new Date();
            const sensorSelect = document.getElementById('grafico-sensor');
            if (sensorSelect) {
                const prop = sensorSelect.value;
                if (dados[prop] !== undefined && dados[prop] !== null) {
                    chart.data.labels.push(time);
                    chart.data.datasets[0].data.push(dados[prop]);

                    while (chart.data.labels.length > maxPoints) {
                        chart.data.labels.shift();
                        chart.data.datasets[0].data.shift();
                    }
                    if (!document.hidden) {
                        chart.update('none');
                    }
                }
            }
        }
    });

    // Ao voltar para o primeiro plano, redesenha o gráfico
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden && chart && autoUpdate) {
            chart.update();
        }
    });

    // Atualização em tempo real de configurações
    socket.on('reload_config', (config) => {
        if (!config) return;

        if (config.aparencia) {
            const tema = config.aparencia.tema ? config.aparencia.tema.toLowerCase() : 'moderno';
            document.documentElement.setAttribute('data-bs-theme', (tema === 'moderno' || tema === 'industrial') ? 'dark' : 'light');
            document.body.className = 'theme-' + tema;
            
            if (chart) {
                const coresGrafico = obterCoresTemaGrafico();
                chart.data.datasets[0].borderColor = coresGrafico.border;
                chart.data.datasets[0].backgroundColor = coresGrafico.background;
                if (chart.options.scales.x.grid) chart.options.scales.x.grid.color = coresGrafico.grid;
                if (chart.options.scales.y.grid) chart.options.scales.y.grid.color = coresGrafico.grid;
                if (chart.options.scales.x.ticks) chart.options.scales.x.ticks.color = coresGrafico.ticks;
                if (chart.options.scales.y.ticks) chart.options.scales.y.ticks.color = coresGrafico.ticks;
                chart.update();
            }
            
            if (config.aparencia.escala) {
                document.body.style.zoom = config.aparencia.escala;
            }
            
            if (config.aparencia.animacoes === false) {
                document.body.classList.add('no-animations');
            } else {
                document.body.classList.remove('no-animations');
            }
        }
        
        if (config.dashboard && config.dashboard.pontos_grafico) {
            maxPoints = parseInt(config.dashboard.pontos_grafico) || 60;
        }

        if (config.graficos && chart) {
            if (config.graficos.exibir_grade !== undefined) {
                chart.options.scales.x.grid.display = config.graficos.exibir_grade;
                chart.options.scales.y.grid.display = config.graficos.exibir_grade;
            }
            if (config.graficos.exibir_legenda !== undefined) {
                chart.options.plugins.legend.display = config.graficos.exibir_legenda;
            }
            if (config.graficos.atualizacao_automatica !== undefined) {
                autoUpdate = config.graficos.atualizacao_automatica;
            }
            chart.update();
        }
    });

    // Ao conectar via socket, entra na sala 'dashboard' da sua pool
    socket.on('connect', () => {
        socket.emit('join_dashboard');
    });

    window.addEventListener('beforeunload', () => {
        socket.emit('leave_dashboard');
    });

    socket.on('update_hardware', (hardware) => {
        if (!hardware) return;

        const hwSerial = document.getElementById('hw-serial-status');
        const hwEsp32 = document.getElementById('hw-esp32-status');
        const hwPorta = document.getElementById('hw-serial-porta');
        const hwLan = document.getElementById('hw-lan-status');
        const hwMqtt = document.getElementById('hw-mqtt-status');
        const hwSql = document.getElementById('hw-sql-status');
        const rowSerial = document.getElementById('row-hw-serial');

        // 1. ESP32 (Atividade validada via LAN HTTP, broker ou serial)
        if (hwEsp32 && hardware.esp32) {
            if (hardware.esp32.conectado) {
                const fonte = hardware.esp32.fonte === 'http_lan'
                    ? 'LAN HTTP'
                    : (hardware.esp32.fonte === 'mqtt' ? 'Broker' : 'USB');
                hwEsp32.innerHTML = `<i class="bi bi-circle-fill me-1" style="font-size: 0.45rem;"></i> Conectado (${fonte})`;
                hwEsp32.className = "badge bg-success";
            } else {
                hwEsp32.innerHTML = `<i class="bi bi-circle-fill me-1" style="font-size: 0.45rem;"></i> Desconectado`;
                hwEsp32.className = "badge bg-secondary";
            }
        }

        // 2. Ocultar USB Serial se conexão for via Rede (LAN HTTP ou Broker MQTT)
        if (rowSerial) {
            if (hardware.usando_broker || (hardware.lan_http && hardware.lan_http.ativo) || (hardware.mqtt && hardware.mqtt.conectado)) {
                rowSerial.classList.add('d-none');
            } else {
                rowSerial.classList.remove('d-none');
            }
        }
        
        if (hwSerial && hardware.serial) {
            if (hardware.serial.conectado) {
                hwSerial.innerHTML = `<i class="bi bi-circle-fill me-1" style="font-size: 0.45rem;"></i> Conectado`;
                hwSerial.className = "badge bg-success";
                if (hwPorta) hwPorta.innerText = hardware.serial.porta || '--';
            } else {
                hwSerial.innerHTML = `<i class="bi bi-circle-fill me-1" style="font-size: 0.45rem;"></i> Desconectado`;
                hwSerial.className = "badge bg-secondary";
                if (hwPorta) hwPorta.innerText = "--";
            }
        }

        if (hwLan && hardware.lan_http) {
            if (hardware.lan_http.habilitada === false) {
                hwLan.innerHTML = `<i class="bi bi-slash-circle me-1"></i> Desligada`;
                hwLan.className = "badge bg-secondary";
                hwLan.title = "LAN Direta desligada manualmente nesta pool";
            } else if (hardware.lan_http.ativo) {
                const ipOrigem = hardware.lan_http.ultimo_ip || 'LAN';
                hwLan.innerHTML = `<i class="bi bi-circle-fill me-1" style="font-size: 0.45rem;"></i> Ativo (${ipOrigem})`;
                hwLan.className = "badge bg-success";
                hwLan.title = `Pacotes HTTP recebidos: ${hardware.lan_http.total_pacotes || 0} | Último: ${hardware.lan_http.ultimo_recebido || '--'}`;
            } else if ((hardware.lan_http.total_pacotes || 0) > 0) {
                hwLan.innerHTML = `<i class="bi bi-circle-fill me-1" style="font-size: 0.45rem;"></i> Ocioso`;
                hwLan.className = "badge bg-warning text-dark";
                hwLan.title = `Pacotes HTTP recebidos: ${hardware.lan_http.total_pacotes} | Último: ${hardware.lan_http.ultimo_recebido || '--'}`;
            } else {
                hwLan.innerHTML = `<i class="bi bi-circle-fill me-1" style="font-size: 0.45rem;"></i> Aguardando POST`;
                hwLan.className = "badge bg-secondary";
                hwLan.title = "Pronto para receber POST /api/telemetria via LAN ou VPN";
            }
        }

        if (hwMqtt && hardware.mqtt) {
            if (hardware.mqtt.conectado) {
                hwMqtt.innerHTML = `<i class="bi bi-circle-fill me-1" style="font-size: 0.45rem;"></i> Conectado`;
                hwMqtt.className = "badge bg-success";
            } else if (hardware.mqtt_habilitado === false) {
                hwMqtt.innerHTML = `<i class="bi bi-circle-fill me-1" style="font-size: 0.45rem;"></i> Opcional / Desligado`;
                hwMqtt.className = "badge bg-secondary";
            } else {
                hwMqtt.innerHTML = `<i class="bi bi-circle-fill me-1" style="font-size: 0.45rem;"></i> Erro`;
                hwMqtt.className = "badge bg-danger";
            }
        }

        if (hwSql && hardware.sql) {
            const rawTipo = (hardware.sql.tipo || '').toLowerCase();
            const nomeBanco = hardware.sql.nome_tipo || (
                rawTipo === 'sqlite' ? 'SQLite' :
                (rawTipo === 'postgresql' || rawTipo === 'postgres' || rawTipo === 'postgree') ? 'PostgreSQL' :
                rawTipo === 'mariadb' ? 'MariaDB' :
                rawTipo === 'mysql' ? 'MySQL' :
                (hardware.sql.tipo ? hardware.sql.tipo.toUpperCase() : 'SQL')
            );

            if (hardware.sql.conectado) {
                hwSql.innerHTML = `<i class="bi bi-database-check me-1"></i> ${nomeBanco} Ativo`;
                hwSql.className = "badge bg-success";
                hwSql.title = `${nomeBanco} conectado com sucesso`;
            } else {
                hwSql.innerHTML = `<i class="bi bi-x-circle me-1"></i> ${nomeBanco} Erro`;
                hwSql.className = "badge bg-danger";
                hwSql.title = hardware.sql.erro || `${nomeBanco} desconectado`;
            }
        }

        // 3. Atividade individual dos sensores (via Broker ou telemetria)
        if (hardware.sensores) {
            let ativosCount = 0;
            const container = document.getElementById('container-status-sensores');
            for (const [chave, info] of Object.entries(hardware.sensores)) {
                if (info.ativo) ativosCount++;
                
                let badge = document.getElementById(`badge-sensor-${chave}`);
                let row = document.getElementById(`sensor-status-row-${chave}`);
                
                if (!row && container) {
                    row = document.createElement('div');
                    row.id = `sensor-status-row-${chave}`;
                    row.className = 'd-flex justify-content-between align-items-center p-1 rounded bg-dark border border-secondary-subtle small';
                    row.innerHTML = `
                        <span class="text-light" style="font-size: 0.75rem;"><i class="bi bi-activity text-info me-1"></i> ${info.nome}</span>
                        <span class="badge bg-secondary" id="badge-sensor-${chave}" style="font-size: 0.65rem;"><i class="bi bi-circle-fill me-1" style="font-size: 0.4rem;"></i> Aguardando</span>
                    `;
                    container.appendChild(row);
                    badge = document.getElementById(`badge-sensor-${chave}`);
                }
                
                if (badge) {
                    if (info.ativo) {
                        badge.className = 'badge bg-success';
                        badge.innerHTML = `<i class="bi bi-circle-fill me-1" style="font-size: 0.4rem;"></i> Ativo (${info.valor}${info.unidade ? ' ' + info.unidade : ''})`;
                    } else {
                        badge.className = 'badge bg-secondary';
                        const label = info.segundos_atras !== null ? `Inativo (${info.segundos_atras}s)` : 'Aguardando';
                        badge.innerHTML = `<i class="bi bi-circle-fill me-1" style="font-size: 0.4rem;"></i> ${label}`;
                    }
                }
            }
            const countBadge = document.getElementById('hw-sensores-ativos-count');
            if (countBadge) {
                countBadge.innerText = `${ativosCount} ativos`;
                countBadge.className = ativosCount > 0 ? 'badge bg-success' : 'badge bg-secondary';
            }
        }

        // Atualização de Flags de Integridade (Estilo Windows Server)
        if (hardware.flags) {
            const healthBadge = document.getElementById('hw-health-badge');
            const flagsCount = document.getElementById('hw-flags-count');
            const flagsEmpty = document.getElementById('hw-flags-empty');
            const flagsContainer = document.getElementById('hw-flags-container');

            if (flagsCount) flagsCount.innerText = hardware.flags.total_ativas || 0;
            if (healthBadge) {
                if (hardware.flags.estado === 'critico') {
                    healthBadge.className = 'badge bg-danger';
                    healthBadge.innerHTML = '<i class="bi bi-exclamation-octagon-fill"></i> Crítico';
                } else if (hardware.flags.estado === 'aviso') {
                    healthBadge.className = 'badge bg-warning text-dark';
                    healthBadge.innerHTML = '<i class="bi bi-exclamation-triangle-fill"></i> Atenção';
                } else {
                    healthBadge.className = 'badge bg-success';
                    healthBadge.innerHTML = '<i class="bi bi-shield-check"></i> Operacional';
                }
            }

            if (flagsEmpty && flagsContainer) {
                const ativas = (hardware.flags.flags || []).filter(f => f.ativa);
                if (ativas.length === 0) {
                    flagsEmpty.classList.remove('d-none');
                    flagsContainer.innerHTML = '';
                } else {
                    flagsEmpty.classList.add('d-none');
                    let html = '';
                    ativas.forEach(f => {
                        const bClass = f.severidade === 'critico' ? 'bg-danger' : (f.severidade === 'aviso' ? 'bg-warning text-dark' : 'bg-info');
                        const bBorder = f.severidade === 'critico' ? 'border-danger' : (f.severidade === 'aviso' ? 'border-warning' : 'border-info');
                        html += `
                            <div class="p-2 rounded bg-dark border ${bBorder} d-flex justify-content-between align-items-center" id="card-flag-${f.id}">
                                <div>
                                    <div class="d-flex align-items-center gap-1">
                                        <span class="badge ${bClass}" style="font-size: 0.65rem;">${f.severidade.toUpperCase()}</span>
                                        <strong class="text-white small">${f.titulo}</strong>
                                    </div>
                                    <small class="text-light d-block mt-1" style="font-size: 0.75rem;">${f.mensagem}</small>
                                    <small class="text-muted" style="font-size: 0.7rem;"><i class="bi bi-clock"></i> ${f.criada_em}</small>
                                </div>
                                <button class="btn btn-sm btn-outline-secondary py-0 px-1" onclick="resolverFlagDashboard('${hardware.flags.pool_id || ''}', '${f.id}')" title="Reconhecer / Resolver">
                                    <i class="bi bi-check-lg text-success"></i>
                                </button>
                            </div>
                        `;
                    });
                    flagsContainer.innerHTML = html;
                }
            }
        }
    });

    // Funções globais para resolver flags a partir do dashboard
    window.resolverFlagDashboard = function(poolId, flagId) {
        if (!poolId || !flagId) return;
        fetch(`/api/pool/${poolId}/flags/resolver/${flagId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        })
        .then(r => r.json())
        .then(() => {
            const card = document.getElementById(`card-flag-${flagId}`);
            if (card) card.remove();
            const container = document.getElementById('hw-flags-container');
            const empty = document.getElementById('hw-flags-empty');
            const count = document.getElementById('hw-flags-count');
            if (container && container.children.length === 0 && empty) {
                empty.classList.remove('d-none');
            }
            if (count) {
                const current = parseInt(count.innerText) || 1;
                count.innerText = Math.max(0, current - 1);
            }
        });
    };

    socket.on('logs', (linhas) => {
        const lista = document.getElementById('lista-logs');
        if (lista && Array.isArray(linhas)) {
            lista.innerHTML = '';
            linhas.forEach(linha => {
                const li = document.createElement('li');
                li.innerText = linha;
                lista.appendChild(li);
            });
        }
    });
});
