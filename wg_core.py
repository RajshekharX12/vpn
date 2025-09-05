#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import ipaddress
import json
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple, Optional

WG_DIR = Path("/etc/wireguard")
CLIENTS_DIR = WG_DIR / "clients"
STATE_DIR = WG_DIR / "state"
STATE_FILE = STATE_DIR / "bot_state.json"

WG_IFACE = "wg0"
DEFAULT_PORT = 51820
DEFAULT_DNS = ["1.1.1.1", "8.8.8.8"]
SUBNET_CIDR = "10.8.0.0/24"  # server .1, clients /32

def ensure_root():
    if os.geteuid() != 0:
        raise SystemExit("Run as root (sudo)")

def ensure_paths():
    CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        STATE_FILE.write_text(json.dumps({
            "owner_id": None,
            "owner_username": "",
            "steps": {},
            "peers": {},
            "last_ip": ""
        }, indent=2))

def run(cmd: str) -> Tuple[int, str, str]:
    p = subprocess.run(shlex.split(cmd), text=True, capture_output=True)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()

def state_get() -> dict:
    return json.loads(STATE_FILE.read_text())

def state_set(data: dict):
    STATE_FILE.write_text(json.dumps(data, indent=2))

def get_owner_id() -> Optional[int]:
    return state_get().get("owner_id")

def set_owner_id(uid: int, uname: str):
    st = state_get()
    st["owner_id"] = uid
    st["owner_username"] = uname
    state_set(st)

def _default_iface() -> str:
    rc, out, _ = run("ip route get 1.1.1.1")
    m = re.search(r" dev\s+(\S+)", out)
    return m.group(1) if m else "eth0"

def endpoint_guess() -> str:
    rc, ip, _ = run("bash -lc \"curl -4s https://ifconfig.me || true\"")
    if not ip:
        rc, out, _ = run("ip route get 1.1.1.1")
        m = re.search(r"src\s+([0-9.]+)", out)
        ip = m.group(1) if m else "0.0.0.0"
    return f"{ip}:{DEFAULT_PORT}"

def server_public_key() -> str:
    keyfile = WG_DIR / "server_public.key"
    if keyfile.exists():
        return keyfile.read_text().strip()
    rc, out, _ = run(f"wg show {WG_IFACE} public-key")
    return out.strip() if rc == 0 and out else ""

def is_wireguard_ready() -> bool:
    if not (WG_DIR / f"{WG_IFACE}.conf").exists():
        return False
    rc, _, _ = run(f"wg show {WG_IFACE}")
    return rc == 0

def install_wireguard_quick() -> Tuple[bool, str]:
    # Install packages (noninteractive to avoid prompts)
    rc, _, err = run("bash -lc 'export DEBIAN_FRONTEND=noninteractive; apt update && apt install -y wireguard qrencode iptables-persistent'")
    if rc != 0:
        return False, f"apt install failed: {err}"

    # Enable IP forwarding
    run("bash -lc \"sed -i 's/^#\\?net.ipv4.ip_forward.*/net.ipv4.ip_forward=1/' /etc/sysctl.conf\"")
    rc, _, err = run("sysctl -p")
    if rc != 0:
        return False, f"sysctl failed: {err}"

    conf_path = WG_DIR / f"{WG_IFACE}.conf"
    if not conf_path.exists():
        # Generate server keys
        rc, priv, e1 = run("wg genkey")
        if rc != 0:
            return False, f"wg genkey failed: {e1}"
        rc, pub, e2 = run(f"bash -lc \"echo '{priv.strip()}' | wg pubkey\"")
        if rc != 0:
            return False, f"wg pubkey failed: {e2}"

        (WG_DIR / "server_private.key").write_text(priv.strip())
        (WG_DIR / "server_public.key").write_text(pub.strip())
        os.chmod(WG_DIR / "server_private.key", 0o600)

        iface = _default_iface()
        post_up = (
            f"iptables -t nat -A POSTROUTING -o {iface} -j MASQUERADE; "
            "iptables -A FORWARD -i wg0 -j ACCEPT; "
            "iptables -A FORWARD -o wg0 -j ACCEPT"
        )
        post_down = post_up.replace("-A", "-D")

        # Server address .1/24
        server_ip = str(list(ipaddress.ip_network(SUBNET_CIDR).hosts())[0])  # .1
        conf_path.write_text(
            "[Interface]\n"
            f"Address = {server_ip}/24\n"
            f"ListenPort = {DEFAULT_PORT}\n"
            f"PrivateKey = {priv.strip()}\n"
            "SaveConfig = true\n"
            f"PostUp = {post_up}\n"
            f"PostDown = {post_down}\n"
        )

    # Enable and start the interface
    run(f"systemctl enable wg-quick@{WG_IFACE}")
    rc, _, err = run(f"systemctl start wg-quick@{WG_IFACE}")
    if rc != 0:
        return False, f"Failed to start wg-quick@{WG_IFACE}: {err}"

    ep = endpoint_guess()
    pub = server_public_key()
    return True, (
        "WireGuard ready.\n"
        f"<b>Server pubkey:</b> <code>{pub}</code>\n"
        f"<b>Endpoint:</b> <code>{ep}</code>"
    )

def _gen_keypair() -> Tuple[str, str]:
    rc, priv, e1 = run("wg genkey")
    if rc != 0:
        raise RuntimeError(f"wg genkey failed: {e1}")
    rc, pub, e2 = run(f"bash -lc \"echo '{priv.strip()}' | wg pubkey\"")
    if rc != 0:
        raise RuntimeError(f"wg pubkey failed: {e2}")
    return priv.strip(), pub.strip()

def _used_ips() -> set:
    used = set()
    # Reserved server .1
    used.add(str(list(ipaddress.ip_network(SUBNET_CIDR).hosts())[0]))
    # From wg live
    rc, out, _ = run(f"wg show {WG_IFACE} allowed-ips")
    if rc == 0 and out:
        for line in out.splitlines():
            parts = line.split()
            if parts:
                ipcidr = parts[-1]
                try:
                    used.add(str(ipaddress.ip_interface(ipcidr).ip))
                except Exception:
                    pass
    # From saved client files
    for f in CLIENTS_DIR.glob("*.conf"):
        text = f.read_text()
        m = re.search(r"^Address\s*=\s*([0-9\.]+)/\d+", text, re.MULTILINE)
        if m:
            used.add(m.group(1))
    return used

def _next_free_ip() -> str:
    net = ipaddress.ip_network(SUBNET_CIDR)
    used = _used_ips()
    for host in net.hosts():
        ip = str(host)
        if ip not in used:
            return ip
    raise RuntimeError("No free IPs left in subnet")

def _client_conf_text(priv_key: str, ip: str) -> str:
    dns_line = f"DNS = {', '.join(DEFAULT_DNS)}" if DEFAULT_DNS else ""
    ep = endpoint_guess()
    pub = server_public_key()
    lines = [
        "[Interface]",
        f"PrivateKey = {priv_key}",
        f"Address = {ip}/32",
        dns_line,
        "",
        "[Peer]",
        f"PublicKey = {pub}",
        "AllowedIPs = 0.0.0.0/0, ::/0",
        f"Endpoint = {ep}",
        "PersistentKeepalive = 25",
        ""
    ]
    return "\n".join([ln for ln in lines if ln != ""])

def add_peer(name: str) -> Tuple[str, str, Path]:
    if not is_wireguard_ready():
        raise RuntimeError("WireGuard not ready. Run Install/Check first.")
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:32]
    cpath = CLIENTS_DIR / f"{safe}.conf"
    if cpath.exists():
        raise RuntimeError("Peer name already exists.")

    priv, pub = _gen_keypair()
    ip = _next_free_ip()
    ip_cidr = f"{ip}/32"

    # Add to live wg
    rc, _, err = run(f"wg set {WG_IFACE} peer {pub} allowed-ips {ip_cidr}")
    if rc != 0:
        raise RuntimeError(f"wg set failed: {err}")

    # Append to wg0.conf for persistence
    conf_path = WG_DIR / f"{WG_IFACE}.conf"
    with conf_path.open("a") as f:
        f.write(f"\n# {safe}\n[Peer]\nPublicKey = {pub}\nAllowedIPs = {ip_cidr}\n")

    # Save client file
    cpath.write_text(_client_conf_text(priv, ip))
    os.chmod(cpath, 0o600)

    # Persist live config
    run(f"wg-quick save {WG_IFACE}")

    # Update state
    st = state_get()
    st.setdefault("peers", {})
    st["peers"][safe] = {"pub": pub, "ip": ip}
    st["last_ip"] = ip
    state_set(st)

    return safe, ip, cpath

def get_peer_conf_path(name: str) -> Optional[Path]:
    cpath = CLIENTS_DIR / f"{name}.conf"
    return cpath if cpath.exists() else None

def make_qr_png(conf_path: Path) -> bytes:
    # qrencode -> PNG
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        png_path = tf.name
    rc, _, err = run(f"bash -lc \"qrencode -t PNG -o {shlex.quote(png_path)} < {shlex.quote(str(conf_path))}\"")
    if rc != 0:
        raise RuntimeError(f"qrencode failed: {err}")
    data = Path(png_path).read_bytes()
    try:
        os.unlink(png_path)
    except Exception:
        pass
    return data

def revoke_peer(name: str) -> Tuple[bool, str]:
    st = state_get()
    peer = st.get("peers", {}).get(name)
    if not peer:
        return False, "Peer not found."

    pub = peer["pub"]

    # Remove from live
    run(f"wg set {WG_IFACE} peer {pub} remove")

    # Remove from wg0.conf
    conf_path = WG_DIR / f"{WG_IFACE}.conf"
    conf_txt = conf_path.read_text()
    pattern = rf"(?m)^# {re.escape(name)}\n\[Peer\]\nPublicKey = {re.escape(pub)}\nAllowedIPs = [^\n]+\n?"
    conf_txt = re.sub(pattern, "", conf_txt)
    conf_path.write_text(conf_txt)

    # Delete client file
    try:
        (CLIENTS_DIR / f"{name}.conf").unlink()
    except Exception:
        pass

    # Update state
    st["peers"].pop(name, None)
    state_set(st)

    run(f"wg-quick save {WG_IFACE}")
    return True, "Peer revoked."

def list_peers_text() -> str:
    st = state_get()
    peers = st.get("peers", {})
    if not peers:
        return "No peers yet."
    lines = []
    for n, p in peers.items():
        lines.append(f"• <b>{n}</b> — {p['ip']}  (<code>{p['pub'][:12]}…</code>)")
    return "\n".join(lines)

def wg_restart() -> Tuple[bool, str]:
    run(f"wg-quick save {WG_IFACE}")
    rc1, _, e1 = run(f"wg-quick down {WG_IFACE}")
    rc2, _, e2 = run(f"wg-quick up {WG_IFACE}")
    if rc2 == 0:
        return True, "WireGuard restarted."
    return False, f"Restart error: {e1 or ''} {e2 or ''}".strip()

def wg_stats_preformatted() -> str:
    rc, out, err = run(f"wg show {WG_IFACE}")
    if rc != 0:
        return f"❌ {err or 'wg show failed'}"
    # Wrap in <pre> for monospace
    return f"<pre>{out}</pre>"
