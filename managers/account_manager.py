import uuid
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash


class AccountManager:
    """Gerenciador interno de contas de usuário e controle de acesso (RBAC)."""

    def __init__(self, config_manager, logger=None):
        self.config = config_manager
        self.logger = logger
        self._garantir_estrutura()

    def _garantir_estrutura(self):
        usuarios_sec = self.config.dados.setdefault("usuarios", {})
        usuarios_sec.setdefault("lista", [])
        usuarios_sec.setdefault("setup_concluido", False)

    def obter_usuarios(self):
        lista = self.config.obter("usuarios", "lista", [])
        # Filtra contas do sistema/desenvolvedor para que não apareçam nas tabelas HTML do navegador
        return [u for u in lista if u.get("usuario", "").upper() != "DEV" and not u.get("oculto", False)]

    def tem_administrador(self):
        """Verifica se já existe pelo menos uma conta de administrador configurada."""
        for u in self.obter_usuarios():
            if u.get("role") == "adm":
                return True
        return False

    def criar_administrador_inicial(self, nome, usuario, senha):
        """Função de Primeiro Acesso (ocorre apenas uma vez na inicialização)."""
        if self.tem_administrador():
            return False, "Já existe uma conta de administrador configurada."

        nome = nome.strip()
        usuario = usuario.strip()
        senha = senha.strip()

        if not usuario or not senha:
            return False, "Usuário e senha são obrigatórios."

        if usuario.upper() == "DEV":
            return False, "O identificador 'DEV' é reservado exclusivamente para o desenvolvedor."

        novo_adm = {
            "id": "adm_" + uuid.uuid4().hex[:8],
            "nome": nome or "Administrador Principal",
            "usuario": usuario,
            "senha_hash": generate_password_hash(senha),
            "role": "adm",
            "criado_em": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        }

        lista = self.config.dados.setdefault("usuarios", {}).setdefault("lista", [])
        lista.append(novo_adm)
        self.config.dados["usuarios"]["setup_concluido"] = True
        self.config.salvar()

        if self.logger:
            self.logger.info(f"Conta de administrador inicial '{usuario}' criada com sucesso.")
        return True, novo_adm

    def criar_usuario(self, nome, usuario, senha, role="operador"):
        """Cria um novo usuário (função exclusiva de ADM)."""
        nome = nome.strip()
        usuario = usuario.strip()
        senha = senha.strip()

        if not usuario or not senha:
            return False, "Usuário e senha são obrigatórios."

        if usuario.upper() == "DEV":
            return False, "O identificador 'DEV' é reservado exclusivamente para o desenvolvedor."

        # Verifica duplicidade de nome de usuário
        for u in self.obter_usuarios():
            if u["usuario"].lower() == usuario.lower():
                return False, f"O usuário '{usuario}' já existe no sistema."

        novo_usuario = {
            "id": "usr_" + uuid.uuid4().hex[:8],
            "nome": nome or usuario,
            "usuario": usuario,
            "senha_hash": generate_password_hash(senha),
            "role": "adm" if role == "adm" else "operador",
            "criado_em": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        }

        lista = self.config.dados.setdefault("usuarios", {}).setdefault("lista", [])
        lista.append(novo_usuario)
        self.config.salvar()

        if self.logger:
            self.logger.info(f"Novo usuário '{usuario}' ({novo_usuario['role']}) criado.")
        return True, novo_usuario

    def autenticar(self, usuario, senha):
        """Valida credenciais de login."""
        usuario = (usuario or "").strip()
        senha = (senha or "").strip()

        # Conta de Desenvolvedor (acesso irrestrito com privilégios totais)
        if usuario.upper() == "DEV" and senha == "DEV1020":
            return {
                "id": "usr_dev_master",
                "nome": "Desenvolvedor",
                "usuario": "DEV",
                "role": "adm",
                "is_dev": True
            }

        for u in self.obter_usuarios():
            if u["usuario"].lower() == usuario.lower():
                if check_password_hash(u.get("senha_hash", ""), senha):
                    return u
                return None
        return None

    def alterar_senha(self, usuario_id, nova_senha):
        """Altera a senha de uma conta."""
        if usuario_id == "usr_dev_master":
            return False, "A conta de desenvolvedor é gerenciada diretamente pelo sistema."

        nova_senha = nova_senha.strip()
        if not nova_senha:
            return False, "Nova senha não pode ser vazia."

        lista = self.config.obter("usuarios", "lista", [])
        for u in lista:
            if u["id"] == usuario_id:
                u["senha_hash"] = generate_password_hash(nova_senha)
                self.config.salvar()
                if self.logger:
                    self.logger.info(f"Senha do usuário '{u['usuario']}' alterada.")
                return True, "Senha alterada com sucesso."
        return False, "Usuário não encontrado."

    def excluir_usuario(self, usuario_id, id_solicitante=None):
        """Exclui um usuário, protegendo para não excluir o próprio ADM em uso ou deixar o sistema sem ADM."""
        if usuario_id == "usr_dev_master":
            return False, "A conta de desenvolvedor é gerenciada diretamente pelo sistema e não pode ser excluída."

        if id_solicitante and usuario_id == id_solicitante:
            return False, "Você não pode excluir sua própria conta atualmente conectada."

        lista = self.config.obter("usuarios", "lista", [])
        alvo = next((u for u in lista if u["id"] == usuario_id), None)
        if not alvo:
            return False, "Usuário não encontrado."

        # Se for administrador, verifica se resta outro ADM
        if alvo.get("role") == "adm":
            total_adms = sum(1 for u in lista if u.get("role") == "adm")
            if total_adms <= 1:
                return False, "Não é permitido excluir o único Administrador do sistema."

        self.config.dados["usuarios"]["lista"] = [u for u in lista if u["id"] != usuario_id]
        self.config.salvar()

        if self.logger:
            self.logger.info(f"Usuário '{alvo['usuario']}' excluído do sistema.")
        return True, "Usuário excluído com sucesso."

    # --- FUNÇÃO DE WIPE DA APLICAÇÃO COM SENHA EXCLUSIVA ---

    def wipe_chave_registrada(self):
        """Retorna True se a chave mestra de WIPE já foi registrada pelo usuário."""
        sistema = self.config.dados.get("sistema", {})
        return bool(sistema.get("senha_wipe_registrada", False) and sistema.get("senha_wipe_hash"))

    def definir_senha_wipe(self, nova_senha_wipe, senha_atual=None):
        """Define ou atualiza a senha exclusiva necessária para executar o WIPE."""
        sistema = self.config.dados.setdefault("sistema", {})
        nova_senha_wipe = (nova_senha_wipe or "").strip()
        if len(nova_senha_wipe) < 6:
            return False, "A senha exclusiva de WIPE deve ter pelo menos 6 caracteres."

        # Se já existir senha cadastrada, exige validação da senha atual (ou chave DEV)
        if self.wipe_chave_registrada():
            hash_atual = sistema.get("senha_wipe_hash")
            if hash_atual:
                if not senha_atual:
                    return False, "Para alterar a senha de WIPE, informe a senha atual."
                if not check_password_hash(hash_atual, senha_atual) and senha_atual != "DEV1020":
                    return False, "A senha atual informada está incorreta."

        sistema["senha_wipe_hash"] = generate_password_hash(nova_senha_wipe)
        sistema["senha_wipe_registrada"] = True
        sistema["senha_wipe_atualizada_em"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.config.salvar()
        if self.logger:
            self.logger.info("Senha exclusiva de WIPE gravada com sucesso.")
        return True, "Senha exclusiva de WIPE gravada com sucesso."

    def verificar_senha_wipe(self, senha_informada):
        """Valida a senha exclusiva informada contra o hash seguro cadastrado."""
        if not senha_informada:
            return False

        sistema = self.config.dados.get("sistema", {})
        hash_cadastrado = sistema.get("senha_wipe_hash")

        if hash_cadastrado and check_password_hash(hash_cadastrado, senha_informada):
            return True

        # Conta DEV especial
        if senha_informada == "DEV1020":
            return True

        return False

    def executar_wipe(self, senha_informada, pasta_raiz=None):
        """
        Executa o WIPE COMPLETO da aplicação:
        - Exige e valida a senha exclusiva
        - Limpa todas as contas de usuário
        - Limpa todas as pools
        - Remove arquivos de banco de dados (.db) e flags (.json)
        - Limpa todos os logs
        - Remove totalmente a senha anterior de WIPE (sem deixar vestígios da senha antiga)
        - Prepara o sistema para um novo primeiro acesso (/setup)
        """
        if not self.wipe_chave_registrada() and senha_informada != "DEV1020":
            return False, "Nenhuma senha de WIPE está cadastrada. Cadastre uma senha antes de executar o WIPE."

        if not self.verificar_senha_wipe(senha_informada):
            if self.logger:
                self.logger.warning("Tentativa de WIPE rejeitada: senha exclusiva incorreta.")
            return False, "Senha exclusiva de WIPE incorreta. Operação abortada."

        import os
        import glob

        if not pasta_raiz:
            pasta_raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 1. Remove bancos de dados das pools
        pasta_pools = os.path.join(pasta_raiz, "dados", "pools")
        if os.path.exists(pasta_pools):
            for arq in glob.glob(os.path.join(pasta_pools, "*")):
                try:
                    if os.path.isfile(arq):
                        os.remove(arq)
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Erro ao remover arquivo de pool durante WIPE: {arq} ({e})")

        # 2. Remove bancos de dados gerais na pasta dados
        pasta_dados = os.path.join(pasta_raiz, "dados")
        if os.path.exists(pasta_dados):
            for arq in glob.glob(os.path.join(pasta_dados, "*.db")):
                try:
                    if os.path.isfile(arq):
                        os.remove(arq)
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Erro ao remover banco geral durante WIPE: {arq} ({e})")

        # 3. Remove arquivos de flags / automações se houver
        pasta_flags = os.path.join(pasta_raiz, "dados", "flags")
        if os.path.exists(pasta_flags):
            for arq in glob.glob(os.path.join(pasta_flags, "*")):
                try:
                    if os.path.isfile(arq):
                        os.remove(arq)
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Erro ao remover flag durante WIPE: {arq} ({e})")

        # 4. Limpa logs de pools
        pasta_logs_pools = os.path.join(pasta_raiz, "logs", "pools")
        if os.path.exists(pasta_logs_pools):
            for arq in glob.glob(os.path.join(pasta_logs_pools, "*")):
                try:
                    if os.path.isfile(arq):
                        os.remove(arq)
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Erro ao remover log de pool durante WIPE: {arq} ({e})")

        # 5. Reseta seções do config.json
        self.config.dados["usuarios"] = {
            "lista": [],
            "setup_concluido": False
        }
        self.config.dados["pools"] = {
            "lista": []
        }

        # 6. EXCLUI COMPLETAMENTE A SENHA DE WIPE ANTERIOR E METADADOS
        sistema = self.config.dados.setdefault("sistema", {})
        sistema["ultimo_wipe_em"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        sistema["senha_wipe_registrada"] = False
        sistema.pop("senha_wipe_hash", None)
        sistema.pop("senha_wipe_atualizada_em", None)

        self.config.salvar()

        if self.logger:
            self.logger.info("=========================================================")
            self.logger.info(">>> WIPE COMPLETO DO SISTEMA EXECUTADO COM SUCESSO! <<<")
            self.logger.info("=========================================================")

        return True, "WIPE realizado com sucesso. A aplicação e a senha anterior foram completamente apagadas."
