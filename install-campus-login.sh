#!/bin/bash
# Install the campus portal auto-login on Fedora as a quiet boot-time service:
# whenever the Wi-Fi is on Tsinglan-School (connection name or SSID) and the
# portal is in the way, log in -- outside FlClash's TUN, see campus-login.py.
#
#   sudo bash install-campus-login.sh [CRED_JSON]
#
# CRED_JSON defaults to the invoking user's ~/.campus-login ({"user","password"},
# what `campus-login.py -u U -p P --save` writes). It is copied to
# /etc/campus-login.json, root-only, because the service runs as root.
# Logs (only logins and failures): journalctl -u campus-login
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }

here=$(cd "$(dirname "$0")" && pwd)
user_home=$(getent passwd "${SUDO_USER:-root}" | cut -d: -f6)
cred=${1:-$user_home/.campus-login}
network=${CAMPUS_NETWORK:-Tsinglan-School}
iface=${CAMPUS_IFACE:-wlp0s20f3}

install -m 755 "$here/campus-login.py" /usr/local/sbin/campus-login
if [ -f "$cred" ]; then
    install -m 600 -o root -g root "$cred" /etc/campus-login.json
else
    echo "warning: $cred not found; create /etc/campus-login.json before it can log in" >&2
fi

# The first version was a NetworkManager dispatcher hook. Its scripts run in a
# confined SELinux domain that may not be allowed to run curl and talk to the
# portal; a systemd service started from bin_t runs unconfined.
rm -f /etc/NetworkManager/dispatcher.d/90-campus-login

cat > /etc/systemd/system/campus-login.service <<EOF
[Unit]
Description=Campus portal auto-login on $network
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
ExecStart=/usr/local/sbin/campus-login --watch "$network" -i $iface --cred /etc/campus-login.json
Restart=always
RestartSec=10
Nice=10

[Install]
WantedBy=multi-user.target
EOF
restorecon -F /usr/local/sbin/campus-login /etc/campus-login.json \
    /etc/systemd/system/campus-login.service 2>/dev/null || true
systemctl daemon-reload
systemctl enable --now campus-login.service
systemctl restart campus-login.service

systemctl --no-pager --lines=0 status campus-login.service | head -4
echo "logs: journalctl -u campus-login"
