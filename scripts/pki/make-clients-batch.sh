#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
PKI="$ROOT/scripts/pki"
CLIENTS_DIR="$ROOT/certs/clients"

# electrolyser list & sensor list (matches our design)
electrolysers=(EL1 EL2)

# sensors per electrolyser
sensors_common=(
  "cell_1_voltage"
  "cell_2_voltage"
  "cell_3_voltage"
  "cell_4_voltage"
  "cell_5_voltage"
  "stack_current"
  "stack_temperature"
  "stack_pressure"
  "h2_flow_rate"
  "o2_flow_rate"
  "tank_pressure"
  "water_flow"
)

# plant-level irradiance sensors
irradiance=(irradiance_1 irradiance_2)

echo "Creating client certs..."

# ensure CA exists
"$PKI/make-ca.sh"

# create per-electrolyser sensors
for el in "${electrolysers[@]}"; do
  for s in "${sensors_common[@]}"; do
    CN="sensor-${el}-${s}"
    echo "Creating: $CN"
    "$PKI/make-client.sh" "$CN"
  done
done

# irradiance sensors
for r in "${irradiance[@]}"; do
  CN="sensor-plant-A-${r}"
  echo "Creating: $CN"
  "$PKI/make-client.sh" "$CN"
done

echo "Created client certs under certs/clients/"
