#!/usr/bin/env bash
# One-time setup of EVE Reaction Ding as a service on a Linux server / VM.
#
#   git clone https://github.com/GamingToastEVE/EVEOnlineReactionDing.git
#   cd EVEOnlineReactionDing
#   sudo ./deploy/install.sh                      # service on port 8765
#   sudo ./deploy/install.sh --mariadb --auto-update daily --port 8080
#
# Options:
#   --port N               port of the web interface (default 8765)
#   --host ADDR            listen address (default 0.0.0.0 = reachable in the network)
#   --branch NAME          git branch for updates (default: the branch checked out now)
#   --mariadb              install MariaDB and create a database + user for the program
#   --auto-update WHEN     check for updates automatically: hourly, daily or weekly
#
# Works on Debian/Ubuntu (apt), Fedora/RHEL/Rocky/Alma (dnf), openSUSE (zypper) and Arch (pacman).
# Running it again is safe: it only updates the configuration.
set -euo pipefail

SERVICE=eve-reaction-ding
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV=/opt/$SERVICE/venv
DATA_HOME=/var/lib/$SERVICE
CONFIG=/etc/$SERVICE.env
RUN_USER=evereaction
PORT=8765
HOST=0.0.0.0
BRANCH=""
WITH_MARIADB=0
AUTO_UPDATE=""

usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --mariadb) WITH_MARIADB=1; shift ;;
    --auto-update) AUTO_UPDATE="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown option: $1" >&2; usage 2 ;;
  esac
done
case "$AUTO_UPDATE" in ""|hourly|daily|weekly) ;; *) echo "--auto-update must be hourly, daily or weekly" >&2; exit 2 ;; esac
[ "$(id -u)" -eq 0 ] || { echo "Please run with sudo: sudo $0 $*" >&2; exit 1; }
command -v systemctl >/dev/null || { echo "This script needs systemd (systemctl)." >&2; exit 1; }

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
REPO_OWNER="$(stat -c %U "$APP_DIR")"
OWNER_HOME="$(getent passwd "$REPO_OWNER" | cut -d: -f6)"
git_owner() { runuser -u "$REPO_OWNER" -- env HOME="$OWNER_HOME" git -C "$APP_DIR" "$@"; }
[ -n "$BRANCH" ] || BRANCH="$(git_owner rev-parse --abbrev-ref HEAD)"

# --- packages ----------------------------------------------------------------
say "Installing system packages"
if command -v apt-get >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q
  apt-get install -y -q python3 python3-venv python3-pip git curl
  [ "$WITH_MARIADB" = 1 ] && apt-get install -y -q mariadb-server
elif command -v dnf >/dev/null; then
  dnf install -y python3 python3-pip git curl
  [ "$WITH_MARIADB" = 1 ] && dnf install -y mariadb-server
elif command -v zypper >/dev/null; then
  zypper --non-interactive install python3 python3-pip git curl
  [ "$WITH_MARIADB" = 1 ] && zypper --non-interactive install mariadb
elif command -v pacman >/dev/null; then
  pacman -Sy --noconfirm --needed python python-pip git curl
  [ "$WITH_MARIADB" = 1 ] && pacman -S --noconfirm --needed mariadb
else
  echo "Unknown package manager - please install python3 (with venv), git and curl yourself." >&2
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' \
  || { echo "Python 3.9 or newer is needed (found $(python3 -V))." >&2; exit 1; }

# --- service user, folders, python environment ----------------------------------
say "Creating user '$RUN_USER', data folder and Python environment"
id "$RUN_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DATA_HOME" --create-home --shell /usr/sbin/nologin "$RUN_USER"
mkdir -p "$DATA_HOME/data" "$(dirname "$VENV")"
chown -R "$RUN_USER:" "$DATA_HOME"
chmod 750 "$DATA_HOME"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --disable-pip-version-check --upgrade pip
"$VENV/bin/pip" install -q --disable-pip-version-check -r "$APP_DIR/requirements.txt"
# the service user must be able to read the program files
runuser -u "$RUN_USER" -- test -r "$APP_DIR/reactionding/server.py" \
  || { echo "User $RUN_USER cannot read $APP_DIR - clone the repo to a readable place (e.g. /opt)." >&2; exit 1; }

# --- configuration ---------------------------------------------------------------
say "Writing $CONFIG"
cat > "$CONFIG" <<EOF
# EVE Reaction Ding - read by the systemd service. Change and run: sudo systemctl restart $SERVICE
HOST=$HOST
PORT=$PORT
EVE_REACTION_DING_DATA=$DATA_HOME/data
# used by deploy/update.sh
APP_DIR=$APP_DIR
BRANCH=$BRANCH
VENV=$VENV
REPO_OWNER=$REPO_OWNER
EOF

# --- MariaDB (optional) --------------------------------------------------------------
if [ "$WITH_MARIADB" = 1 ]; then
  say "Setting up MariaDB"
  systemctl enable --now mariadb 2>/dev/null || systemctl enable --now mysqld
  DB_JSON="$DATA_HOME/data/database.json"
  if [ -f "$DB_JSON" ]; then
    echo "$DB_JSON exists - keeping the existing database login."
  else
    DB_PASS="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)"
    mysql -u root <<SQL
CREATE DATABASE IF NOT EXISTS eve_reaction_ding CHARACTER SET utf8mb4;
CREATE USER IF NOT EXISTS 'evereaction'@'localhost' IDENTIFIED BY '$DB_PASS';
ALTER USER 'evereaction'@'localhost' IDENTIFIED BY '$DB_PASS';
GRANT ALL PRIVILEGES ON eve_reaction_ding.* TO 'evereaction'@'localhost';
FLUSH PRIVILEGES;
SQL
    cat > "$DB_JSON" <<EOF
{
  "enabled": true,
  "host": "127.0.0.1",
  "port": 3306,
  "user": "evereaction",
  "password": "$DB_PASS",
  "database": "eve_reaction_ding"
}
EOF
    chown "$RUN_USER:" "$DB_JSON"; chmod 600 "$DB_JSON"
    echo "Database 'eve_reaction_ding' and user 'evereaction' created (login in $DB_JSON)."
  fi
fi

# --- systemd service --------------------------------------------------------------
say "Installing systemd service '$SERVICE'"
cat > /etc/systemd/system/$SERVICE.service <<EOF
[Unit]
Description=EVE Reaction Ding (EVE Online reactions calculator and planner)
After=network-online.target mariadb.service mysqld.service
Wants=network-online.target

[Service]
User=$RUN_USER
Group=$RUN_USER
EnvironmentFile=$CONFIG
Environment=HOME=$DATA_HOME PYTHONUNBUFFERED=1
WorkingDirectory=$APP_DIR
ExecStart=$VENV/bin/python -m reactionding serve
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$DATA_HOME
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

if [ -n "$AUTO_UPDATE" ]; then
  say "Automatic updates: $AUTO_UPDATE"
  cat > /etc/systemd/system/$SERVICE-update.service <<EOF
[Unit]
Description=Update EVE Reaction Ding from git
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$APP_DIR/deploy/update.sh
EOF
  cat > /etc/systemd/system/$SERVICE-update.timer <<EOF
[Unit]
Description=Check for EVE Reaction Ding updates ($AUTO_UPDATE)

[Timer]
OnCalendar=$AUTO_UPDATE
RandomizedDelaySec=15min
Persistent=true

[Install]
WantedBy=timers.target
EOF
fi

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"
[ -n "$AUTO_UPDATE" ] && systemctl enable --now "$SERVICE-update.timer" >/dev/null

# --- check -------------------------------------------------------------------------
say "Waiting for the web interface"
for _ in $(seq 1 40); do
  curl -fs -o /dev/null "http://127.0.0.1:$PORT/api/meta" && break
  sleep 1
done
if curl -fs -o /dev/null "http://127.0.0.1:$PORT/api/meta"; then
  IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo "Running: http://${IP:-<server-ip>}:$PORT/"
  echo
  echo "  status:   systemctl status $SERVICE"
  echo "  log:      journalctl -u $SERVICE -f"
  echo "  update:   sudo $APP_DIR/deploy/update.sh"
  echo "  settings: $CONFIG"
  echo "  data:     $DATA_HOME/data"
  [ -n "$AUTO_UPDATE" ] && echo "  auto-update: systemctl list-timers $SERVICE-update.timer"
  echo
  echo "Note: there is no login - only open the port in your own network or put a reverse proxy with a password in front."
else
  echo "The service did not answer on port $PORT. Look at: journalctl -u $SERVICE -n 50" >&2
  exit 1
fi
