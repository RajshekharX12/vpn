import subprocess

def generate_keys():
    private = subprocess.check_output("wg genkey", shell=True).decode().strip()
    public = subprocess.check_output(f"echo {private} | wg pubkey", shell=True).decode().strip()
    return private, public


def generate_config(server, private_key, address):

    config = f"""
[Interface]
PrivateKey = {private_key}
Address = {address}/32
DNS = 1.1.1.1

[Peer]
PublicKey = {server['public_key']}
Endpoint = {server['ip']}:{server['port']}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
"""

    return config
