#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 022

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SOURCE_DIR="$PROJECT_DIR/deploy/certs"
ROOT_SOURCE="$SOURCE_DIR/Russian_Trusted_Root_CA.crt"
SUB_SOURCE="$SOURCE_DIR/Russian_Trusted_Sub_CA.crt"
ROOT_TARGET="/usr/local/share/ca-certificates/happyfox_russian_trusted_root_ca.crt"
SUB_TARGET="/usr/local/share/ca-certificates/happyfox_russian_trusted_sub_ca.crt"

for tool in openssl install update-ca-certificates; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "Required CA installation tool is missing: $tool" >&2
    exit 1
  }
done

[[ -s "$ROOT_SOURCE" && -s "$SUB_SOURCE" ]] || {
  echo "Russian Trusted CA files are missing from deploy/certs" >&2
  exit 1
}

root_subject="$(openssl x509 -in "$ROOT_SOURCE" -noout -subject)"
sub_subject="$(openssl x509 -in "$SUB_SOURCE" -noout -subject)"
[[ "$root_subject" == *"Russian Trusted Root CA"* ]] || {
  echo "Unexpected Russian Trusted Root CA subject" >&2
  exit 1
}
[[ "$sub_subject" == *"Russian Trusted Sub CA"* ]] || {
  echo "Unexpected Russian Trusted Sub CA subject" >&2
  exit 1
}

# Fail closed if the version-controlled issuing certificate is not chained to
# the version-controlled Ministry root. Never bypass TLS verification for MAX.
openssl verify -CAfile "$ROOT_SOURCE" "$SUB_SOURCE" >/dev/null

install -m 0644 "$ROOT_SOURCE" "$ROOT_TARGET"
install -m 0644 "$SUB_SOURCE" "$SUB_TARGET"
update-ca-certificates >/dev/null

# Verify that the system bundle produced by update-ca-certificates now trusts
# the same issuing CA that MAX presents in its Russian PKI chain.
openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt "$SUB_SOURCE" >/dev/null

echo "[happyfox-ca] Russian Trusted Root/Sub CA installed"
