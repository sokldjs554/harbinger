#!/usr/bin/env bash
set -euo pipefail
# The reviewed implicit TLS implementation; checksum from the official release.
monitoring_tmp=$(mktemp -d)
trap 'rm -rf "$monitoring_tmp"' EXIT
archive="$monitoring_tmp/alertmanager.tar.gz"
curl --fail --location --retry 2 --max-time 120 \
  https://github.com/prometheus/alertmanager/releases/download/v0.33.0/alertmanager-0.33.0.linux-amd64.tar.gz \
  --output "$archive"
printf '%s  %s\n' 8ce11c42e8a6dfbbf93a59c0b193cb1329210b36d0c7ef3df7b745608675a1d1 "$archive" | sha256sum --check --status
tar --no-same-owner -xzf "$archive" -C "$monitoring_tmp" --strip-components=1 alertmanager-0.33.0.linux-amd64/amtool alertmanager-0.33.0.linux-amd64/alertmanager
mkdir -p "$1"
cp "$monitoring_tmp/alertmanager" "$monitoring_tmp/amtool" "$1/"
"$1/alertmanager" --version
