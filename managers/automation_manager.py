"""
Automation and Flags Manager - ExtremeSquare 0.1
Inspirado em gerenciamento de eventos e integridade estilo Windows Server.
Gerencia regras de automação por pool e geração de flags de alerta (Info, Aviso, Crítico).
"""

import os
import json
import uuid
from datetime import datetime

class AutomationManager:
    def __init__(self, config_manager, logger=None):
        self.config_manager = config_manager
        self.logger = logger
        self._pasta_dados = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dados", "pools")
        os.makedirs(self._pasta_dados, exist_ok=True)
        # Rastreia último estado de disparo para evitar repetições desnecessárias (debounce)
        self._estado_disparos = {}

    def _caminho_flags(self, pool_id):
        return os.path.join(self._pasta_dados, f"flags_{str(pool_id).lower()}.json")

    def obter_automacoes(self, pool_id):
        """Retorna a lista de regras de automação da pool especificada."""
        pools = self.config_manager.obter("pools", "lista", [])
        pool = next((p for p in pools if p["id"] == pool_id), None)
        if pool and "automacoes" in pool:
            return pool["automacoes"]
        return []

    def salvar_automacoes(self, pool_id, automacoes):
        """Salva a lista de automações para uma pool."""
        pools = self.config_manager.dados.get("pools", {}).get("lista", [])
        for p in pools:
            if p["id"] == pool_id:
                p["automacoes"] = automacoes
                break
        self.config_manager.salvar()

    def adicionar_automacao(self, pool_id, nome, metrica, condicao, limite, severidade="aviso", mensagem=""):
        """Adiciona uma nova regra de automação à pool."""
        try:
            limite_num = float(limite)
        except (ValueError, TypeError):
            return False, "O limite deve ser um número válido."

        if condicao not in (">", "<", ">=", "<=", "==", "!="):
            return False, "Condição de comparação inválida."

        if severidade not in ("info", "aviso", "critico"):
            severidade = "aviso"

        automacoes = self.obter_automacoes(pool_id)
        nova_regra = {
            "id": f"auto_{uuid.uuid4().hex[:8]}",
            "nome": nome.strip() or f"Alerta {metrica} {condicao} {limite}",
            "metrica": metrica.strip(),
            "condicao": condicao,
            "limite": limite_num,
            "severidade": severidade,
            "mensagem": mensagem.strip(),
            "ativo": True,
            "criado_em": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        }
        automacoes.append(nova_regra)
        self.salvar_automacoes(pool_id, automacoes)
        if self.logger:
            self.logger.info(f"[Pool {pool_id}] Nova automação criada: {nova_regra['nome']}")
        return True, nova_regra

    def excluir_automacao(self, pool_id, auto_id):
        """Exclui uma regra de automação da pool."""
        automacoes = self.obter_automacoes(pool_id)
        novas = [a for a in automacoes if a["id"] != auto_id]
        if len(novas) != len(automacoes):
            self.salvar_automacoes(pool_id, novas)
            return True, "Automação excluída com sucesso."
        return False, "Automação não encontrada."

    def alternar_automacao(self, pool_id, auto_id, ativo=None):
        """Ativa ou desativa uma regra."""
        automacoes = self.obter_automacoes(pool_id)
        for a in automacoes:
            if a["id"] == auto_id:
                a["ativo"] = not a["ativo"] if ativo is None else bool(ativo)
                self.salvar_automacoes(pool_id, automacoes)
                return True, a["ativo"]
        return False, "Automação não encontrada."

    # --- GERENCIAMENTO DE FLAGS (Estilo Windows Server) ---

    def carregar_flags(self, pool_id):
        """Lê as flags salvas no arquivo isolado da pool."""
        caminho = self._caminho_flags(pool_id)
        if not os.path.exists(caminho):
            return []
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            if self.logger:
                self.logger.error(f"Erro ao carregar flags da pool {pool_id}: {e}")
            return []

    def salvar_flags(self, pool_id, flags):
        """Salva a lista de flags da pool."""
        caminho = self._caminho_flags(pool_id)
        try:
            with open(caminho, "w", encoding="utf-8") as f:
                json.dump(flags, f, indent=4, ensure_ascii=False)
        except Exception as e:
            if self.logger:
                self.logger.error(f"Erro ao salvar flags da pool {pool_id}: {e}")

    def obter_flags(self, pool_id, apenas_ativas=False):
        """Retorna todas as flags ou apenas as ativas."""
        flags = self.carregar_flags(pool_id)
        if apenas_ativas:
            return [f for f in flags if f.get("ativa", True)]
        return flags

    def criar_flag(self, pool_id, severidade, titulo, mensagem, auto_id=None, valor_atual=None):
        """Gera uma nova flag na pool."""
        flags = self.carregar_flags(pool_id)
        
        # Se já existe uma flag idêntica ativa para essa mesma automação, apenas atualiza timestamp e valor
        if auto_id:
            for f in flags:
                if f.get("auto_id") == auto_id and f.get("ativa", True):
                    f["atualizado_em"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                    f["valor_atual"] = valor_atual
                    f["ocorrencias"] = f.get("ocorrencias", 1) + 1
                    self.salvar_flags(pool_id, flags)
                    return f

        nova_flag = {
            "id": f"flg_{uuid.uuid4().hex[:8]}",
            "pool_id": pool_id,
            "auto_id": auto_id,
            "severidade": severidade,  # 'info', 'aviso', 'critico'
            "titulo": titulo,
            "mensagem": mensagem,
            "valor_atual": valor_atual,
            "criada_em": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "atualizado_em": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "ativa": True,
            "reconhecida": False,
            "ocorrencias": 1
        }
        flags.insert(0, nova_flag)  # Mais recentes primeiro
        # Limita histórico de flags em 100 por pool para performance
        if len(flags) > 100:
            flags = flags[:100]
        self.salvar_flags(pool_id, flags)

        if self.logger:
            self.logger.info(f"[FLAG {severidade.upper()}] Pool {pool_id}: {titulo} - {mensagem}")
        return nova_flag

    def reconhecer_flag(self, pool_id, flag_id):
        """Marca a flag como reconhecida pelo operador."""
        flags = self.carregar_flags(pool_id)
        for f in flags:
            if f["id"] == flag_id:
                f["reconhecida"] = True
                f["reconhecida_em"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                self.salvar_flags(pool_id, flags)
                return True
        return False

    def resolver_flag(self, pool_id, flag_id):
        """Marca uma flag como resolvida / inativa."""
        flags = self.carregar_flags(pool_id)
        for f in flags:
            if f["id"] == flag_id:
                f["ativa"] = False
                f["resolvida_em"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                self.salvar_flags(pool_id, flags)
                return True
        return False

    def excluir_flag(self, pool_id, flag_id):
        """Remove a flag do histórico."""
        flags = self.carregar_flags(pool_id)
        novas = [f for f in flags if f["id"] != flag_id]
        if len(novas) != len(flags):
            self.salvar_flags(pool_id, novas)
            return True
        return False

    def limpar_todas_flags(self, pool_id):
        """Exclui todas as flags da pool."""
        self.salvar_flags(pool_id, [])
        return True

    # --- AVALIAÇÃO DE AUTOMAÇÕES VIA TELEMETRIA ---

    def testar_condicao(self, valor, condicao, limite):
        try:
            val = float(valor)
            lim = float(limite)
            if condicao == ">":
                return val > lim
            elif condicao == "<":
                return val < lim
            elif condicao == ">=":
                return val >= lim
            elif condicao == "<=":
                return val <= lim
            elif condicao == "==":
                return val == lim
            elif condicao == "!=":
                return val != lim
        except (ValueError, TypeError):
            return False
        return False

    def processar_telemetria(self, pool_id, dados_dict, socketio=None):
        """
        Avalia as regras de automação contra os dados recebidos.
        Gera e emite flags quando as condições são satisfeitas.
        """
        if not dados_dict or not isinstance(dados_dict, dict):
            return []

        automacoes = self.obter_automacoes(pool_id)
        if not automacoes:
            return []

        flags_geradas = []

        for regra in automacoes:
            if not regra.get("ativo", True):
                continue

            metrica = regra.get("metrica")
            if not metrica:
                continue

            # Busca valor da métrica direta ou dentro de extras
            valor = dados_dict.get(metrica)
            if valor is None and "extras" in dados_dict and isinstance(dados_dict["extras"], dict):
                valor = dados_dict["extras"].get(metrica)

            if valor is None:
                continue

            condicao = regra.get("condicao", ">")
            limite = regra.get("limite", 0)

            disparou = self.testar_condicao(valor, condicao, limite)
            chave_estado = f"{pool_id}_{regra['id']}"

            if disparou:
                # Gera ou atualiza Flag
                severidade = regra.get("severidade", "aviso")
                titulo = regra.get("nome") or f"Alerta de {metrica}"
                
                msg_custom = regra.get("mensagem")
                if msg_custom:
                    msg = msg_custom.replace("{valor}", str(valor)).replace("{limite}", str(limite)).replace("{metrica}", str(metrica))
                else:
                    msg = f"A métrica '{metrica}' atingiu {valor} ({condicao} {limite})"

                flag = self.criar_flag(
                    pool_id=pool_id,
                    severidade=severidade,
                    titulo=titulo,
                    mensagem=msg,
                    auto_id=regra["id"],
                    valor_atual=valor
                )
                flags_geradas.append(flag)

                # Se acabou de disparar (transição de falso para verdadeiro)
                if not self._estado_disparos.get(chave_estado, False):
                    self._estado_disparos[chave_estado] = True
                    if socketio:
                        socketio.emit("nova_flag", flag, to=f"dashboard_{pool_id}")
                        socketio.emit("alerta_global", {
                            "pool_id": pool_id,
                            "flag": flag,
                            "resumo": self.obter_resumo_global()
                        })
            else:
                # Normalizou: se estava disparado, marca como resolvido
                if self._estado_disparos.get(chave_estado, False):
                    self._estado_disparos[chave_estado] = False
                    # Auto-resolve a flag ativa dessa regra
                    flags = self.carregar_flags(pool_id)
                    alterou = False
                    for f in flags:
                        if f.get("auto_id") == regra["id"] and f.get("ativa", True):
                            f["ativa"] = False
                            f["resolvida_em"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                            alterou = True
                    if alterou:
                        self.salvar_flags(pool_id, flags)
                        if socketio:
                            socketio.emit("flag_resolvida", {"pool_id": pool_id, "auto_id": regra["id"]}, to=f"dashboard_{pool_id}")
                            socketio.emit("alerta_global", {
                                "pool_id": pool_id,
                                "resumo": self.obter_resumo_global()
                            })

        return flags_geradas

    # --- RESUMO ESTILO WINDOWS SERVER (Server Manager) ---

    def obter_resumo_pool(self, pool_id):
        """Retorna o estado de integridade de uma pool específica."""
        flags = self.obter_flags(pool_id, apenas_ativas=True)
        criticos = sum(1 for f in flags if f.get("severidade") == "critico")
        avisos = sum(1 for f in flags if f.get("severidade") == "aviso")
        infos = sum(1 for f in flags if f.get("severidade") == "info")

        if criticos > 0:
            estado = "critico"  # 🔴
            rotulo = "Crítico"
        elif avisos > 0:
            estado = "aviso"    # 🟡
            rotulo = "Atenção"
        else:
            estado = "ok"       # 🟢
            rotulo = "Operacional"

        return {
            "pool_id": pool_id,
            "estado": estado,
            "rotulo": rotulo,
            "total_ativas": len(flags),
            "criticos": criticos,
            "avisos": avisos,
            "infos": infos,
            "flags": flags
        }

    def obter_resumo_global(self):
        """
        Retorna o painel geral de integridade de todas as pools (Server Manager style).
        """
        pools = self.config_manager.obter("pools", "lista", [])
        total_pools = len(pools)
        pools_ok = 0
        pools_aviso = 0
        pools_critico = 0
        total_flags_ativas = 0
        todas_flags_recentes = []

        resumo_por_pool = {}
        for p in pools:
            pid = p["id"]
            resumo = self.obter_resumo_pool(pid)
            resumo_por_pool[pid] = resumo
            total_flags_ativas += resumo["total_ativas"]
            if resumo["estado"] == "critico":
                pools_critico += 1
            elif resumo["estado"] == "aviso":
                pools_aviso += 1
            else:
                pools_ok += 1

            for f in resumo["flags"]:
                f_com_pool = dict(f)
                f_com_pool["pool_nome"] = p.get("nome", pid)
                todas_flags_recentes.append(f_com_pool)

        # Ordena as flags por data/hora mais recente
        todas_flags_recentes.sort(key=lambda x: x.get("atualizado_em", x.get("criada_em", "")), reverse=True)

        return {
            "total_pools": total_pools,
            "pools_ok": pools_ok,
            "pools_aviso": pools_aviso,
            "pools_critico": pools_critico,
            "total_flags_ativas": total_flags_ativas,
            "resumo_por_pool": resumo_por_pool,
            "flags_recentes": todas_flags_recentes[:15]
        }
