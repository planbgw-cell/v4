#!/bin/bash
# Run as root once: sudo bash /home/flairy/v4/install-system-packages-as-root.sh
# Installs: python3-venv (optional recreate), ffmpeg/mesa/vainfo from apt, Docker CE, flairy-db.

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y ca-certificates curl gnupg python3.13-venv ffmpeg mesa-va-drivers mesa-vdpau-drivers vainfo

# Optional: remove Ubuntu docker.io if present (avoids conflicts with docker-ce)
apt-get remove -y docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc 2>/dev/null || true

install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -qq
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable --now docker

usermod -aG docker flairy || true

install -d -o 999 -g 999 -m 0700 /home/flairy/db_data
chown -R 999:999 /home/flairy/db_data

PGPASS_FILE=/home/flairy/v4/postgres_password_flairy_v4.txt
if [[ ! -f "${PGPASS_FILE}" ]]; then
  install -d -m 0755 /home/flairy/v4
  openssl rand -base64 32 | tr -d '\n' > "${PGPASS_FILE}"
  chmod 600 "${PGPASS_FILE}"
  chown flairy:flairy "${PGPASS_FILE}"
fi
PGPASS=$(tr -d '\n' < "${PGPASS_FILE}")

if ! docker ps -a --format '{{.Names}}' | grep -qx flairy-db; then
  docker pull postgres:16
  docker run -d --name flairy-db --restart always \
    -e POSTGRES_USER=flairy_admin \
    -e POSTGRES_DB=flairy_v4 \
    -e "POSTGRES_PASSWORD=${PGPASS}" \
    -p 5432:5432 \
    -v /home/flairy/db_data:/var/lib/postgresql/data \
    postgres:16
  echo "PostgreSQL container started. Password: ${PGPASS_FILE} (owner flairy, mode 600)."
else
  echo "Container flairy-db already exists; skipping docker run."
fi

echo "Done. flairy must re-login for docker group. Optional: rm -rf /home/flairy/v4/venv && sudo -u flairy python3 -m venv /home/flairy/v4/venv --prompt flairy-v4 && get-pip as flairy if desired."
