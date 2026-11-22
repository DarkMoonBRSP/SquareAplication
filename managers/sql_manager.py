"""Acesso ao banco de dados (SQLite, MySQL, PostgreSQL) usando SQLAlchemy."""
import time
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


class SQLManager:
    def __init__(self, config_manager, pool_id, logger=None):
        self.config = config_manager
        self.pool_id = pool_id
        self.logger = logger
        self.conectado = False
        self.ultimo_erro = None
        self.subtipo_detectado = None
        self.ultima_verificacao = 0.0
        self.intervalo_verificacao = 5.0
        self._engine = None

    def _obter_tipo_config(self):
        lista = self.config.obter("pools", "lista", [])
        pool = next((p for p in lista if p.get("id") == self.pool_id), {})
        return str(pool.get("sql", {}).get("tipo", "sqlite")).lower().strip()

    def obter_nome_tipo(self):
        if getattr(self, "subtipo_detectado", None) and self.conectado:
            return self.subtipo_detectado
        
        tipo_cfg = self._obter_tipo_config()
        if tipo_cfg == "sqlite":
            return "SQLite"
        elif tipo_cfg in ("postgresql", "postgres", "postgree"):
            return "PostgreSQL"
        elif "maria" in tipo_cfg:
            return "MariaDB"
        elif tipo_cfg == "mysql":
            return "MySQL / MariaDB"
        return tipo_cfg.upper() if tipo_cfg else "SQL"

    def _get_engine(self):
        # Lê a configuração de sql diretamente da pool correta
        lista = self.config.obter("pools", "lista", [])
        pool = next((p for p in lista if p.get("id") == self.pool_id), {})
        sql_cfg = pool.get("sql", {})
        
        tipo = self._obter_tipo_config()
        
        if tipo == "sqlite":
            caminho_padrao = f"dados/pools/pool_{str(self.pool_id).lower()}.db" if self.pool_id else "dados/geral.db"
            caminho_str = sql_cfg.get("caminho") or caminho_padrao
            valor = Path(caminho_str)
            if not valor.is_absolute():
                valor = Path(__file__).resolve().parent.parent / valor
            
            valor.parent.mkdir(parents=True, exist_ok=True)
            if not valor.is_file():
                open(valor, 'a').close()
            
            uri = f"sqlite:///{valor.as_posix()}"
        
        elif tipo in ("mysql", "mariadb"):
            host = sql_cfg.get("host", "localhost")
            porta = sql_cfg.get("porta", 3306)
            usuario = sql_cfg.get("usuario", "root")
            senha = sql_cfg.get("senha", "")
            banco = sql_cfg.get("banco", "square")
            uri = f"mysql+pymysql://{usuario}:{senha}@{host}:{porta}/{banco}"
            
        elif tipo in ("postgresql", "postgres", "postgree"):
            host = sql_cfg.get("host", "localhost")
            porta = sql_cfg.get("porta", 5432)
            usuario = sql_cfg.get("usuario", "postgres")
            senha = sql_cfg.get("senha", "")
            banco = sql_cfg.get("banco", "square")
            uri = f"postgresql+pg8000://{usuario}:{senha}@{host}:{porta}/{banco}"
            
        else:
            raise ValueError(f"Tipo de banco não suportado: {tipo}")

        if not self._engine or str(self._engine.url) != uri:
            self._engine = create_engine(uri, pool_pre_ping=True)
            
        return self._engine

    def testar_conexao(self):
        try:
            engine = self._get_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                
                # Identifica tipo exato do motor conectado
                tipo_cfg = self._obter_tipo_config()
                if engine.dialect.name == 'sqlite':
                    self.subtipo_detectado = "SQLite"
                elif engine.dialect.name == 'postgresql':
                    self.subtipo_detectado = "PostgreSQL"
                elif engine.dialect.name == 'mysql':
                    try:
                        v = str(conn.execute(text("SELECT VERSION()")).scalar() or "").lower()
                        if "mariadb" in v:
                            self.subtipo_detectado = "MariaDB"
                        else:
                            self.subtipo_detectado = "MySQL"
                    except Exception:
                        self.subtipo_detectado = "MariaDB" if "maria" in tipo_cfg else "MySQL"
                else:
                    self.subtipo_detectado = engine.dialect.name.capitalize()

            self.conectado, self.ultimo_erro = True, None
            return True
        except SQLAlchemyError as erro:
            self.conectado, self.ultimo_erro = False, str(erro)
            return False
        except Exception as erro:
            self.conectado, self.ultimo_erro = False, str(erro)
            return False

    def verificar_se_necessario(self):
        agora = time.monotonic()
        if agora - self.ultima_verificacao < self.intervalo_verificacao:
            return self.conectado
        self.ultima_verificacao = agora
        return self.testar_conexao()

    def listar_tabelas(self):
        try:
            engine = self._get_engine()
            with engine.connect() as conn:
                if engine.dialect.name == 'sqlite':
                    res = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"))
                elif engine.dialect.name == 'mysql':
                    res = conn.execute(text("SHOW TABLES"))
                elif engine.dialect.name == 'postgresql':
                    res = conn.execute(text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname != 'pg_catalog' AND schemaname != 'information_schema'"))
                else:
                    return []
                linhas = res.fetchall()
            self.conectado, self.ultimo_erro = True, None
            return [linha[0] for linha in linhas]
        except SQLAlchemyError as erro:
            self.conectado, self.ultimo_erro = False, str(erro)
            return []

    def ler_tabela(self, tabela, limite=200):
        tabelas = self.listar_tabelas()
        if tabela not in tabelas:
            raise ValueError("Tabela não permitida")
        try:
            engine = self._get_engine()
            with engine.connect() as conn:
                # Segurança: tabela validada contra listagem do banco
                lim = max(1, min(int(limite), 1000))
                if engine.dialect.name == 'mysql':
                    cursor = conn.execute(text(f'SELECT * FROM `{tabela}` LIMIT {lim}'))
                else:
                    cursor = conn.execute(text(f'SELECT * FROM "{tabela}" LIMIT {lim}'))
                
                colunas = list(cursor.keys())
                linhas = [list(row) for row in cursor.fetchall()]
                
            self.conectado, self.ultimo_erro = True, None
            return colunas, linhas
        except SQLAlchemyError as erro:
            self.conectado, self.ultimo_erro = False, str(erro)
            raise

    def executar(self, query, params=None):
        engine = self._get_engine()
        with engine.begin() as conn:
            if params:
                res = conn.execute(text(query), params)
            else:
                res = conn.execute(text(query))
            return res

    def garantir_tabela_mqtt(self):
        engine = self._get_engine()
        
        if engine.dialect.name == 'sqlite':
            sql = """
            CREATE TABLE IF NOT EXISTS mqtt_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topico TEXT NOT NULL,
                payload TEXT NOT NULL,
                recebido_em TEXT NOT NULL
            )
            """
        elif engine.dialect.name == 'mysql':
            sql = """
            CREATE TABLE IF NOT EXISTS mqtt_messages (
                id INT AUTO_INCREMENT PRIMARY KEY,
                topico VARCHAR(255) NOT NULL,
                payload TEXT NOT NULL,
                recebido_em VARCHAR(255) NOT NULL
            )
            """
        elif engine.dialect.name == 'postgresql':
            sql = """
            CREATE TABLE IF NOT EXISTS mqtt_messages (
                id SERIAL PRIMARY KEY,
                topico TEXT NOT NULL,
                payload TEXT NOT NULL,
                recebido_em TEXT NOT NULL
            )
            """
        else:
            return False
            
        self.executar(sql)
        return True

    def estado(self):
        self.verificar_se_necessario()
        tipo_cfg = self._obter_tipo_config()
        nome_tipo = self.obter_nome_tipo()
        return {
            "conectado": self.conectado,
            "erro": self.ultimo_erro,
            "tipo": tipo_cfg,
            "nome_tipo": nome_tipo
        }
