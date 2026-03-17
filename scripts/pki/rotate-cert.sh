#!/usr/bin/env bash
set -euo pipefail

# Rotate a client certificate
# Usage: ./rotate-cert.sh <COMMON_NAME|all>

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <COMMON_NAME|all>"
    exit 1
fi

TARGET="$1"
ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
PKI="$ROOT/scripts/pki"
CLIENTS_ROOT="$ROOT/certs/clients"

rotate_one() {
    local CN="$1"
    local CLIENT_DIR="$CLIENTS_ROOT/$CN"

    if [ ! -d "$CLIENT_DIR" ]; then
        echo "Error: Client directory $CLIENT_DIR does not exist."
        return 1
    fi

    echo "Rotating certificate for $CN..."

    # Backup existing certs
    local BACKUP_DIR="$CLIENT_DIR/backup_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    mv "$CLIENT_DIR"/*.crt "$CLIENT_DIR"/*.key "$CLIENT_DIR"/*.csr "$BACKUP_DIR/" 2>/dev/null || true
    echo "  Backed up old certs to $BACKUP_DIR"

    # Generate new cert using existing make-client.sh logic
    "$PKI/make-client.sh" "$CN"
    echo "  Rotation complete for $CN"
}

if [ "$TARGET" == "all" ]; then
    echo "Rotating ALL client certificates..."
    for d in "$CLIENTS_ROOT"/*; do
        if [ -d "$d" ]; then
            CN=$(basename "$d")
            rotate_one "$CN"
        fi
    done
else
    rotate_one "$TARGET"
fi
