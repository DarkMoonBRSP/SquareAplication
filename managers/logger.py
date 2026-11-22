from datetime import datetime
from pathlib import Path


class Logger:
    def __init__(self, config_manager=None, pool_id=None):
        raiz = Path(__file__).resolve().parent.parent
        self.config = config_manager
        self.pool_id = pool_id
        if self.pool_id:
            self.pasta_logs = raiz / "logs" / "pools"
            self.pasta_logs.mkdir(parents=True, exist_ok=True)
            self.arquivo = self.pasta_logs / f"pool_{str(pool_id).lower()}.log"
        else:
            self.pasta_logs = raiz / "logs"
            self.pasta_logs.mkdir(parents=True, exist_ok=True)
            self.arquivo = self.pasta_logs / "sistema.log"
        self.registros = []
        self.carregar_logs()

    def _ativado(self):
        return self.config is None or self.config.obter("logs", "ativados", True)

    def _salvar_arquivo(self):
        return self.config is None or self.config.obter("logs", "salvar_arquivo", True)

    def carregar_logs(self):
        if not self.arquivo.exists():
            return
        try:
            with self.arquivo.open("r", encoding="utf-8") as arquivo:
                self.registros = [linha.strip() for linha in arquivo if linha.strip()]
            self._limitar_registros()
        except OSError:
            self.registros = []

    def registrar(self, mensagem, nivel="INFO"):
        if not self._ativado():
            return None
        horario = datetime.now().strftime("%H:%M:%S")
        registro = f"[{horario}] [{nivel}] {mensagem}"
        self.registros.append(registro)
        self._limitar_registros()
        if self._salvar_arquivo():
            try:
                with self.arquivo.open("a", encoding="utf-8") as arquivo:
                    arquivo.write(registro + "\n")
            except OSError:
                pass
        return registro

    def _limitar_registros(self):
        try:
            limite = int(self.config.obter("logs", "limite_registros", "20")) if self.config else 20
        except (TypeError, ValueError):
            limite = 20
        limite = max(1, limite)
        if len(self.registros) > limite:
            self.registros = self.registros[-limite:]

    def info(self, mensagem):
        return self.registrar(mensagem, "INFO")

    def warning(self, mensagem):
        return self.registrar(mensagem, "WARNING")

    def error(self, mensagem):
        return self.registrar(mensagem, "ERROR")

    def obter_registros(self):
        return self.registros.copy()

    def obter_ultimos(self, quantidade=20):
        return self.registros[-max(1, quantidade):]

    def limpar(self):
        self.registros.clear()
        if self._salvar_arquivo():
            try:
                self.arquivo.write_text("", encoding="utf-8")
                return True
            except OSError:
                return False
        return True
