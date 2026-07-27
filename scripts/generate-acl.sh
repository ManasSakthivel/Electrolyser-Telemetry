#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")"/.. && pwd)"
ACLFILE="$ROOT/mosquitto/conf/aclfile"

# Backup current ACL
# Backup current ACL if it exists
if [ -f "$ACLFILE" ]; then
  cp "$ACLFILE" "$ACLFILE.bak.$(date +%s)"
fi

echo "# Auto-generated ACL entries - keep above this line" >> "$ACLFILE"
echo "# Generated at: $(date -u)" >> "$ACLFILE"

# per-electrolyser sensors
electrolysers=(EL1 EL2)
sensors_common=(
  "cell_1_voltage:cell/1/voltage"
  "cell_2_voltage:cell/2/voltage"
  "cell_3_voltage:cell/3/voltage"
  "cell_4_voltage:cell/4/voltage"
  "cell_5_voltage:cell/5/voltage"
  "stack_current:stack/current"
  "stack_temperature:stack/temperature"
  "stack_pressure:stack/pressure"
  "h2_flow_rate:h2/flow_rate"
  "o2_flow_rate:o2/flow_rate"
  "tank_pressure:tank/pressure"
  "water_flow:water_flow"
)

for el in "${electrolysers[@]}"; do
  for entry in "${sensors_common[@]}"; do
    IFS=":" read -r s path <<< "$entry"
    CN="sensor-${el}-${s}"
    topic="electrolyser/plant-A/${el}/${path}"
    cat >> "$ACLFILE" <<EOF
user ${CN}
topic write ${topic}
EOF
  done
done

# irradiance sensors
for i in 1 2; do
  CN="sensor-plant-A-irradiance_${i}"
  topic="electrolyser/plant-A/irradiance/${i}"
  cat >> "$ACLFILE" <<EOF
user ${CN}
topic write ${topic}
EOF
done

# keep telegraf & monitor read access
cat >> "$ACLFILE" <<'EOF'

# monitoring / telegraf read access
user telegraf-subscriber
topic read electrolyser/plant-A/#

user monitor-local
topic read electrolyser/#
EOF

chmod 700 "$ACLFILE"
echo "ACL generation complete; file: $ACLFILE"
