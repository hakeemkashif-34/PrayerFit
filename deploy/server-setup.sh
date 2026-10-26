#!/usr/bin/env bash
# Sets up a fresh Ubuntu 24.04 server for PrayerFit. Run it once, from the
# repo folder, with sudo:
#   sudo deploy/server-setup.sh
# Running it again is safe. Each step checks before it changes anything.
#
# What it does:
#   1. Updates Ubuntu and installs Docker from Docker's own apt repo.
#   2. Adds a 2 GB swap file. The VM has 1 GB of RAM, and building the
#      website needs more than that for a minute.
#   3. Sets the clock to Toronto time, so cron times below are local.
#   4. Turns on the ufw firewall: only SSH, 80, and 443 in.
#   5. SSH: keys only, no passwords, no root login.
#   6. Installs security updates every day by itself, and reboots at
#      4:30 am if an update needs it. The containers start again by themselves.
#   7. Backs up the database every day at 3:30 am (deploy/backup.sh).
#   8. Adds a "dc" shortcut for the long docker compose command.

set -euo pipefail

if [[ $EUID -ne 0 || -z "${SUDO_USER:-}" ]]; then
  echo "Run this with sudo from your own user: sudo deploy/server-setup.sh" >&2
  exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="$SUDO_USER"
export DEBIAN_FRONTEND=noninteractive

echo "==> 1. Updating Ubuntu and installing Docker"
apt-get update -q
apt-get upgrade -y -q
apt-get install -y -q ca-certificates curl gnupg ufw unattended-upgrades
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck source=/dev/null  # Ubuntu's own file, only on the server.
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
# Lets you run docker without sudo. Takes effect after you log out and back in.
usermod -aG docker "$APP_USER"

echo "==> 2. Swap file"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
fi
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab

echo "==> 3. Time zone"
timedatectl set-timezone America/Toronto

echo "==> 4. Firewall (ufw)"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

echo "==> 5. SSH: keys only"
# sshd uses the first value it reads, and files load in name order, so
# "10-" comes before Azure's own 50-cloudimg-settings.conf.
cat > /etc/ssh/sshd_config.d/10-prayerfit.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
CONF
# Check the config before reloading, so a typo can't lock you out.
sshd -t
systemctl reload ssh

echo "==> 6. Automatic security updates"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF
cat > /etc/apt/apt.conf.d/52prayerfit-upgrades <<'CONF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:30";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
CONF
systemctl enable --now unattended-upgrades

echo "==> 7. Daily database backup"
chmod +x "$REPO_DIR/deploy/backup.sh" "$REPO_DIR/deploy/update.sh"
cat > /etc/cron.d/prayerfit-backup <<CONF
# Back up the PrayerFit database every day at 3:30 am Toronto time.
30 3 * * * $APP_USER $REPO_DIR/deploy/backup.sh >> /home/$APP_USER/prayerfit-backups.log 2>&1
CONF
chmod 644 /etc/cron.d/prayerfit-backup

echo "==> 8. The dc shortcut"
BASHRC="/home/$APP_USER/.bashrc"
grep -q '^alias dc=' "$BASHRC" || \
  echo "alias dc='docker compose -f $REPO_DIR/docker-compose.yml -f $REPO_DIR/docker-compose.prod.yml'" >> "$BASHRC"

echo
echo "Done. Log out and back in so docker works without sudo, then:"
echo "  cd $REPO_DIR && cp deploy/production.env.example .env && chmod 600 .env && nano .env"
echo "  deploy/update.sh"
