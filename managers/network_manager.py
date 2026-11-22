"""Descoberta de interfaces de rede (LAN / VPN) e gerenciamento de chave secreta.

Não depende de bibliotecas externas nem de acesso à internet para detectar
os endereços privados da máquina (LAN e VPN como Tailscale / WireGuard / ZeroTier).
"""
import ipaddress
import os
import platform
import re
import secrets
import socket
import subprocess
from pathlib import Path

_REDE_CGNAT_TAILSCALE = ipaddress.ip_network("100.64.0.0/10")
_TERMOS_VPN = ("tailscale", "wireguard", "wg", "zerotier", "openvpn", "tap", "tun", "vpn", "nordlynx", "hamachi")
_TERMOS_IGNORAR = ("loopback", "vethernet", "vmware", "virtualbox", "docker", "wsl", "hyper-v")


def obter_ou_criar_secret_key(caminho_arquivo=None):
    """Retorna a chave secreta da variável de ambiente ou de config/secret.key."""
    env_key = os.environ.get("SQUARE_SECRET_KEY", "").strip()
    if env_key:
        return env_key

    if caminho_arquivo is None:
        caminho_arquivo = Path(__file__).resolve().parent.parent / "config" / "secret.key"
    else:
        caminho_arquivo = Path(caminho_arquivo)

    try:
        if caminho_arquivo.is_file():
            chave = caminho_arquivo.read_text(encoding="utf-8").strip()
            if len(chave) >= 32:
                return chave
        caminho_arquivo.parent.mkdir(parents=True, exist_ok=True)
        chave = secrets.token_hex(32)
        caminho_arquivo.write_text(chave, encoding="utf-8")
        return chave
    except OSError:
        return secrets.token_hex(32)


def gerar_token_dispositivo():
    """Gera um token seguro de 32 caracteres hexadecimais para autenticação de ESP32 via LAN/VPN."""
    return secrets.token_hex(16)


def _ip_rota_padrao():
    """Obtém o IPv4 da interface usada para a rota padrão sem enviar nenhum pacote real."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # connect() em socket UDP não transmite pacotes na rede; apenas consulta a tabela de rotas do SO.
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
            return ip
    except OSError:
        pass
    finally:
        s.close()
    return None


def _coletar_interfaces_windows():
    """Lê adaptadores e IPs IPv4 via ipconfig (somente Windows)."""
    resultados = []
    try:
        out = subprocess.check_output(
            ["ipconfig"],
            stderr=subprocess.DEVNULL,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        texto = out.decode("cp850", errors="ignore")
    except Exception:
        return resultados

    adaptador_atual = ""
    for linha in texto.splitlines():
        if linha and not linha.startswith(" ") and linha.strip().endswith(":"):
            adaptador_atual = linha.strip().rstrip(":")
            continue
        m = re.search(r"IPv4[^:]*:\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", linha)
        if m:
            ip = m.group(1).strip()
            resultados.append((adaptador_atual, ip))
    return resultados


def _coletar_interfaces_generico():
    """Fallback multiplataforma via getaddrinfo."""
    resultados = []
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        vistos = set()
        for info in infos:
            ip = info[4][0]
            if ip not in vistos:
                vistos.add(ip)
                resultados.append(("Interface Local", ip))
    except OSError:
        pass
    return resultados


def _classificar_ip(ip_str, nome_adaptador=""):
    """Classifica um IPv4 como 'vpn', 'lan' ou None (ignorar)."""
    try:
        obj = ipaddress.ip_address(ip_str)
    except ValueError:
        return None

    if obj.is_loopback or obj.is_link_local or obj.is_multicast or obj.is_unspecified:
        return None

    nome_low = (nome_adaptador or "").lower()
    if any(t in nome_low for t in _TERMOS_VPN) or obj in _REDE_CGNAT_TAILSCALE:
        return "vpn"

    if any(t in nome_low for t in _TERMOS_IGNORAR):
        return None

    if obj.is_private:
        return "lan"

    return None


def obter_info_rede(porta=5000):
    """Retorna informações estruturadas dos endereços LAN e VPN do servidor SQUARE."""
    try:
        porta = int(porta)
    except (TypeError, ValueError):
        porta = 5000

    hostname = socket.gethostname()
    ip_padrao = _ip_rota_padrao()

    if platform.system().lower() == "windows":
        brutos = _coletar_interfaces_windows() or _coletar_interfaces_generico()
    else:
        brutos = _coletar_interfaces_generico()

    ips_lan = []
    ips_vpn = []
    vistos_lan = set()
    vistos_vpn = set()

    for adaptador, ip in brutos:
        cat = _classificar_ip(ip, adaptador)
        if cat == "vpn" and ip not in vistos_vpn:
            vistos_vpn.add(ip)
            ips_vpn.append({"ip": ip, "interface": adaptador or "VPN", "url": f"http://{ip}:{porta}"})
        elif cat == "lan" and ip not in vistos_lan:
            vistos_lan.add(ip)
            ips_lan.append({"ip": ip, "interface": adaptador or "LAN", "url": f"http://{ip}:{porta}"})

    # Garante que o IP da rota padrão apareça em primeiro na lista LAN (se não for VPN)
    if ip_padrao:
        cat_padrao = _classificar_ip(ip_padrao, "")
        if cat_padrao == "vpn" and ip_padrao not in vistos_vpn:
            ips_vpn.insert(0, {"ip": ip_padrao, "interface": "VPN", "url": f"http://{ip_padrao}:{porta}"})
        elif cat_padrao == "lan":
            ips_lan = [item for item in ips_lan if item["ip"] != ip_padrao]
            ips_lan.insert(0, {"ip": ip_padrao, "interface": "LAN Principal", "url": f"http://{ip_padrao}:{porta}"})

    ip_lan_principal = ips_lan[0]["ip"] if ips_lan else (ip_padrao or "127.0.0.1")
    url_lan_principal = f"http://{ip_lan_principal}:{porta}"

    return {
        "hostname": hostname,
        "porta": porta,
        "url_local": f"http://localhost:{porta}",
        "ip_lan_principal": ip_lan_principal,
        "url_lan_principal": url_lan_principal,
        "endpoint_telemetria": f"{url_lan_principal}/api/telemetria",
        "interfaces_lan": ips_lan,
        "interfaces_vpn": ips_vpn,
        "vpn_detectada": len(ips_vpn) > 0,
    }
