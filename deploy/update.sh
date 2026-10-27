#!/usr/bin/env bash
# Update EVE Reaction Ding to the newest version from git and restart the service.
#
#   sudo ./deploy/update.sh            # update if there is something new
#   sudo ./deploy/update.sh --force    # reinstall and restart even without changes
#   sudo ./deploy/update.sh --check    # only show whether an update is available
#
# Steps: git fetch -> fast-forward to origin/<branch> -> install Python packages -> run the
# unit tests -> restart the service -> check that the web interface answers.
# If the tests or the check fail, the previous version is restored automatically.
# Your data (settings, plans, database) is not touched.
set -euo pipefail

SERVICE=eve-reaction-ding
CONFIG="${EVE_RD_CONFIG:-/etc/$SERVICE.env}"   # override for testing
FORCE=0
CHECK_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --check) CHECK_ONLY=1 ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done
[ "$(id -u)" -eq 0 ] || { echo "Please run with sudo: sudo $0 $*" >&2; exit 1; }
[ -f "$CONFIG" ] || { echo "$CONFIG not found - run deploy/install.sh first." >&2; exit 1; }
# shellcheck disable=SC1090
. "$CONFIG"
: "${APP_DIR:?}" "${BRANCH:?}" "${VENV:?}" "${REPO_OWNER:?}" "${PORT:=8765}"

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
# git runs as the owner of the clone (their SSH key / credentials, no "dubious ownership")
g() { runuser -u "$REPO_OWNER" -- git -C "$APP_DIR" "$@"; }

exec 9>"/run/$SERVICE-update.lock"
flock -n 9 || { log "Another update is running."; exit 0; }

if [ -n "$(g status --porcelain --untracked-files=no)" ]; then
  log "There are local changes in $APP_DIR - not updating. See: git -C $APP_DIR status"
  exit 1
fi

log "Fetching $BRANCH"
g fetch --quiet origin "$BRANCH"
OLD="$(g rev-parse HEAD)"
NEW="$(g rev-parse "origin/$BRANCH")"

if [ "$OLD" = "$NEW" ] && [ "$FORCE" = 0 ]; then
  log "Already up to date ($(g log -1 --format='%h %s'))."
  exit 0
fi
if [ "$OLD" != "$NEW" ]; then
  log "Update available: $(g rev-list --count "$OLD..$NEW") new commit(s)"
  g log --format='   %h %s' "$OLD..$NEW"
fi
[ "$CHECK_ONLY" = 1 ] && exit 0

healthy() {   # the service runs and the web interface answers with the version that is checked out
  local want
  want="$(g rev-parse --short=7 HEAD)"
  for _ in $(seq 1 40); do
    if systemctl is-active --quiet "$SERVICE" \
       && curl -fs "http://127.0.0.1:$PORT/api/meta" | grep -q "\"version\": \"$want\""; then
      return 0
    fi
    sleep 1
  done
  return 1
}
install_and_test() {
  local out
  "$VENV/bin/pip" install -q --disable-pip-version-check -r "$APP_DIR/requirements.txt" || return 1
  if ! out="$(cd "$APP_DIR" && runuser -u "$REPO_OWNER" -- env PYTHONDONTWRITEBYTECODE=1 \
                "$VENV/bin/python" -m unittest discover -s tests 2>&1)"; then
    printf '%s\n' "$out" | tail -20
    log "Tests failed."
    return 1
  fi
  log "Tests passed ($(printf '%s\n' "$out" | grep -o 'Ran [0-9]* tests' || echo ok))."
}
rollback() {
  log "Something went wrong - going back to $(g log -1 --format='%h' "$OLD")"
  g reset --quiet --hard "$OLD"
  "$VENV/bin/pip" install -q --disable-pip-version-check -r "$APP_DIR/requirements.txt" || true
  systemctl restart "$SERVICE"
  healthy && log "Previous version is running again." || log "Previous version does not answer either - see: journalctl -u $SERVICE -n 50"
  exit 1
}

if [ "$OLD" != "$NEW" ]; then
  g merge --quiet --ff-only "origin/$BRANCH" || {
    log "Cannot fast-forward (history was rewritten?). Fix by hand: git -C $APP_DIR reset --hard origin/$BRANCH"
    exit 1
  }
fi

log "Installing packages and running tests"
install_and_test || rollback

log "Restarting $SERVICE"
systemctl restart "$SERVICE"
if healthy; then
  log "Done - running $(g log -1 --format='%h %s')"
else
  log "The web interface does not answer after the update."
  rollback
fi
