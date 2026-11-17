#!/usr/bin/env bash
# Rendered by cloudshell_deploy.py; no AWS credentials are embedded.
set -Eeuo pipefail
exec > >(tee -a /var/log/harbinger-bootstrap.log /dev/console) 2>&1
trap 'echo HARBINGER_BOOTSTRAP_FAILED; /usr/sbin/poweroff' ERR
mkdir -p /opt/harbinger-bootstrap
# Stop after the initial 24-hour review window, including across reboots.
cat > /etc/systemd/system/harbinger-review-stop.service <<'UNIT'
[Unit]
Description=Stop Harbinger after the initial review window
[Service]
Type=oneshot
ExecStart=/usr/sbin/poweroff
UNIT
cat > /etc/systemd/system/harbinger-review-stop.timer <<'UNIT'
[Unit]
Description=Bound initial Harbinger review hosting to 24 hours
[Timer]
OnCalendar=@@STOP_AT@@
Persistent=true
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now harbinger-review-stop.timer
cat > /opt/harbinger-bootstrap/build.sh <<'BUILD'
#!/usr/bin/env bash
set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
release=@@SOURCE_SHA@@
apt-get update
apt-get install -y --no-install-recommends git docker.io docker-buildx docker-compose-v2 curl ca-certificates python3
systemctl enable --now docker
mkdir -p /opt/harbinger-source
cd /opt/harbinger-source
git init
git remote add origin https://github.com/sokldjs554/harbinger.git
git fetch --depth=1 origin "$release"
git checkout --detach FETCH_HEAD
test "$(git rev-parse HEAD)" = "$release"
package=/home/ubuntu/harbinger-package
mkdir -p "$package/runtime"
DOCKER_BUILDKIT=1 docker build -t "harbinger:$release" .
docker run --rm --user 0:0 --memory 3g -v "$package/runtime:/runtime" "harbinger:$release" harbinger synth --out /runtime/data --scale 1 --months 36 --seed 20260101
docker run --rm --user 0:0 --memory 3g -v "$package/runtime:/runtime" "harbinger:$release" harbinger features --data /runtime/data
docker run --rm --user 0:0 --memory 3g -v "$package/runtime:/runtime" "harbinger:$release" harbinger eval --data /runtime/data --models /runtime/models --artifacts /runtime/artifacts --seed 20260101 --skip-loso
python3 - "$release" <<'PY'
import json, sys
from pathlib import Path
p = Path('/home/ubuntu/harbinger-package')
metrics = json.loads((p / 'runtime/artifacts/metrics.json').read_text())
(p / 'deployment.json').write_text(json.dumps({
    'commit': sys.argv[1], 'region': 'ap-southeast-2', 'synthetic': True,
    'scale': 1, 'months': 36, 'seed': 20260101,
    'model_version': metrics['bundle_version'], 'bootstrap_completed': False,
    'review_stop_at_utc': '@@STOP_AT@@',
    'note': 'Built on EC2 from verified source; historical experiment metrics unchanged.'
}))
PY
docker save "harbinger:$release" | gzip -1 > "$package/image.tar.gz"
tar -czf "$package/runtime.tar.gz" -C "$package/runtime" .
cp deploy/aws/ec2/install.sh deploy/aws/ec2/compose.yml "$package/"
metadata_token=$(curl --fail --silent --show-error --max-time 10 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token)
public_ip=$(curl --fail --silent --show-error --max-time 10 -H "X-aws-ec2-metadata-token: $metadata_token" http://169.254.169.254/latest/meta-data/public-ipv4)
unset metadata_token
bash "$package/install.sh" "$release" "$public_ip"
/opt/harbinger/certbot/bin/certbot renew --dry-run --run-deploy-hooks --deploy-hook /usr/local/sbin/harbinger-reload-nginx
systemctl is-active docker harbinger harbinger-cert-renew.timer harbinger-review-stop.timer
curl --fail --silent --show-error "https://$public_ip/health"
python3 - <<'PY'
import json, os
from pathlib import Path
p = Path('/opt/harbinger/current/deployment.json')
d = json.loads(p.read_text())
d.update(bootstrap_completed=True, renewal_dry_run=True)
temporary = p.with_suffix('.tmp')
temporary.write_text(json.dumps(d))
os.replace(temporary, p)
PY
rm -rf /opt/harbinger/pending-deployment
echo "HARBINGER_BOOTSTRAP_OK https://$public_ip/console/"
BUILD
# A failed or stalled first deployment shuts down this newly created host.
timeout --signal=TERM --kill-after=30s 55m bash /opt/harbinger-bootstrap/build.sh
trap - ERR
