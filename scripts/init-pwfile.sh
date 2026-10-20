#!/usr/bin/env bash
# scripts/init-pwfile.sh
# ======================
# Initialise the Mosquitto password file with the WebSocket viewer credential.
# Must be run AFTER 'docker compose up -d mosquitto' (requires the mosquitto
# container to be running so we can use its mosquitto_passwd binary).
#
# Usage:
#   MQTT_WS_USER=ws_viewer MQTT_WS_PASS=<your-secret> ./scripts/init-pwfile.sh
#
# Or source .env first:
#   set -a; source .env; set +a
#   ./scripts/init-pwfile.sh
set -euo pipefail

MQTT_WS_USER="${MQTT_WS_USER:-}"
MQTT_WS_PASS="${MQTT_WS_PASS:-}"

if [[ -z "$MQTT_WS_USER" || -z "$MQTT_WS_PASS" ]]; then
  echo "ERROR: MQTT_WS_USER and MQTT_WS_PASS must be set." >&2
  echo "  Source .env or export them before running this script." >&2
  exit 1
fi

# Use the running mosquitto container's mosquitto_passwd binary so the hash
# format matches the broker's expectation exactly.
docker exec mosquitto mosquitto_passwd -b /mosquitto/config/pwfile "$MQTT_WS_USER" "$MQTT_WS_PASS"
# mosquitto_passwd can rewrite the file with looser modes; the broker warns on world-readable pwfiles.
chmod 600 "$(dirname "$0")/../mosquitto/conf/pwfile"
echo "Password entry for '${MQTT_WS_USER}' written to mosquitto/conf/pwfile."
echo "Send SIGHUP to reload: docker exec mosquitto kill -HUP 1"
docker exec mosquitto kill -HUP 1
echo "Broker configuration reloaded."
