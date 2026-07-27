#!/usr/bin/env bash
set -euo pipefail
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <client-cn>"; exit 1
fi
CN="$1"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.."; pwd)"
CADIR="$ROOT/certs/ca"
CDIR="$ROOT/certs/clients/$CN"
mkdir -p "$CDIR"
openssl genrsa -out "$CDIR/client.key" 4096
openssl req -new -key "$CDIR/client.key" -out "$CDIR/client.csr" -subj "/C=IN/O=Electrolyser/CN=$CN"
openssl x509 -req -in "$CDIR/client.csr" -CA "$CADIR/ca.crt" -CAkey "$CADIR/ca.key" -CAcreateserial \
  -out "$CDIR/client.crt" -days 825 -sha256
echo "Client certs at certs/clients/$CN"

