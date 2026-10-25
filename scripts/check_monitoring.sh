#!/usr/bin/env bash
set -euo pipefail
# Match the Compose image. Verify bytes before executing a downloaded binary.
monitoring_tmp=$(mktemp -d)
trap 'rm -rf "$monitoring_tmp"' EXIT
archive="$monitoring_tmp/prometheus.tar.gz"
curl --fail --location --retry 2 --max-time 120 \
  https://github.com/prometheus/prometheus/releases/download/v2.54.1/prometheus-2.54.1.linux-amd64.tar.gz \
  --output "$archive"
printf '%s  %s\n' 31715ef65e8a898d0f97c8c08c03b6b9afe485ac84e1698bcfec90fc6e62924f "$archive" | sha256sum --check --status
tar --no-same-owner -xzf "$archive" -C "$monitoring_tmp" --strip-components=1 prometheus-2.54.1.linux-amd64/promtool
"$monitoring_tmp/promtool" check rules deploy/monitoring/rules.yml
"$monitoring_tmp/promtool" test rules deploy/monitoring/rules.test.yml
"$monitoring_tmp/promtool" check config deploy/monitoring/prometheus.yml
