#!/usr/bin/env bash
set -euo pipefail
# Existing host only. This project is separate from the application Compose project.
bundle=/home/ubuntu/harbinger-package/monitoring-bundle.tar.gz
trap 'rm -f "$bundle"' EXIT
root=/opt/harbinger-monitoring
test_id="$1"
[[ "$test_id" =~ ^[A-Za-z0-9_-]{1,80}$ ]] || exit 2
test -d /opt/harbinger/current
test "$(df --output=avail -k /opt | tail -1)" -gt 524288
release="$root/releases/$test_id"
test ! -e "$release"
previous=$(readlink -f "$root/current" 2>/dev/null || true)
complete=0
finish() {
  rm -f "$bundle"
  if [ "$complete" -ne 1 ]; then
    if [ -n "$previous" ] && [ -f "$previous/compose.yml" ]; then
      docker compose -p harbinger-monitoring -f "$previous/compose.yml" up -d
    elif [ -f "$release/compose.yml" ]; then
      docker compose -p harbinger-monitoring -f "$release/compose.yml" down
    fi
    # Do not leave a failed deployment's credentials in a historical release.
    rm -f "$release/config/smtp-password" "$release/config/alertmanager.yml"
  fi
}
trap finish EXIT
install -d -m 0750 "$root" "$root/releases" "$release"
tar --no-same-owner -xzf "$bundle" -C "$release"
chown -R root:65534 "$release/config"
chmod 0750 "$release/config"
chmod 0640 "$release/config/"*
install -d -o 65534 -g 65534 -m 0750 "$root/data/prometheus" "$root/data/alertmanager"
docker compose -p harbinger-monitoring -f "$release/compose.yml" pull --quiet
docker compose -p harbinger-monitoring -f "$release/compose.yml" run --rm --no-deps --entrypoint /bin/promtool prometheus check config /etc/hbmonitor/prometheus.yml
# amtool can echo recipient details; don't forward its output to public workflow logs.
docker compose -p harbinger-monitoring -f "$release/compose.yml" run --rm --no-deps --entrypoint /bin/amtool alertmanager check-config /etc/hbmonitor/alertmanager.yml >/dev/null 2>&1
docker compose -p harbinger-monitoring -f "$release/compose.yml" up -d
for attempt in $(seq 1 60); do
  if curl --fail --silent http://127.0.0.1:19090/-/ready >/dev/null && curl --fail --silent http://127.0.0.1:19093/-/ready >/dev/null; then break; fi
  sleep 2
done
python3 "$release/external_alerts.py" --release "$release" --out "$root/result.json"
ln -sfn "$release" "$root/current"
complete=1
if [ -n "$previous" ] && [ "$previous" != "$release" ]; then
  rm -f "$previous/config/smtp-password" "$previous/config/alertmanager.yml"
fi
