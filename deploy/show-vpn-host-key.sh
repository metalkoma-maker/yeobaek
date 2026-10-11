#!/usr/bin/env bash
# Read-only: print the existing OpenSSH public host key for the VPN address.
set -euo pipefail
vpn_address="$(tailscale ip -4)"
python3 - "$vpn_address" <<'PY'
import ipaddress, sys
if ipaddress.ip_address(sys.argv[1]) not in ipaddress.ip_network('100.64.0.0/10'):
    raise SystemExit('Tailscale IPv4 required')
PY
echo 'DEPLOY_HOST:'
printf '%s\n' "$vpn_address"
echo 'DEPLOY_KNOWN_HOSTS (public host key):'
awk -v target="$vpn_address" '{print target " " $1 " " $2}' /etc/ssh/ssh_host_ed25519_key.pub
echo 'Public host-key fingerprint:'
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
