from dataclasses import dataclass, field
from typing import Any


@dataclass
class SensorData:
    # Medições numéricas definidas pelo perfil da pool (ex.: {"temperatura": 25.1})
    valores: dict[str, float] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def atuadores(self):
        return self.extras.get("atuadores", {})

    @property
    def sistema(self):
        return self.extras.get("sistema", {})

    def para_dict(self):
        """Formato enviado ao dashboard: medições no nível raiz + extras numéricos diretos."""
        res = dict(self.valores)
        for k, v in self.extras.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                res[k] = v
        res["extras"] = self.extras
        return res
