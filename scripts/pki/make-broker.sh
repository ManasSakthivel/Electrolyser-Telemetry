#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.."; pwd)"
CADIR="$ROOT/certs/ca"
BDIR="$ROOT/certs/broker"
mkdir -p "$BDIR"
openssl genrsa -out "$BDIR/broker.key" 4096
openssl req -new -key "$BDIR/broker.key" -out "$BDIR/broker.csr" \
  -subj "/C=IN/O=Electrolyser/CN=broker.local"
openssl x509 -req -in "$BDIR/broker.csr" -CA "$CADIR/ca.crt" -CAkey "$CADIR/ca.key" -CAcreateserial \
  -out "$BDIR/broker.crt" -days 825 -sha256 -extfile <(printf "subjectAltName=DNS:broker,IP:127.0.0.1")
echo "Broker certs ready at certs/broker"

