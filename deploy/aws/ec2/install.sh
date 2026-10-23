#!/usr/bin/env bash
set -Eeuo pipefail
umask 022
release_sha=${1:?immutable source SHA required}
public_ip=${2:?public IPv4 required}
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]]
python3 -c 'import ipaddress,sys; assert ipaddress.IPv4Address(sys.argv[1]).is_global' "$public_ip"
package=/home/ubuntu/harbinger-package
root=/opt/harbinger
release="$root/releases/$release_sha"
pending="$root/pending-deployment"
# A prior interrupted invocation keeps its rollback snapshot until restored.
if [[ -f "$pending/rollback.sh" ]]; then
    bash "$pending/rollback.sh"
fi
previous=$(readlink -f "$root/current" 2>/dev/null || true)
mkdir -p "$pending"
printf '%s\n' "$previous" > "$pending/previous"
if [[ -f /etc/nginx/sites-available/harbinger ]]; then
    cp /etc/nginx/sites-available/harbinger "$pending/nginx"
fi
cat > "$pending/rollback.sh" <<'ROLLBACK'
#!/usr/bin/env bash
set -Eeuo pipefail
pending=/opt/harbinger/pending-deployment
previous=$(cat "$pending/previous")
if [[ -n "$previous" ]]; then
    ln -sfn "$previous" /opt/harbinger/current
    docker compose -p harbinger --env-file "$previous/.env" -f "$previous/compose.yml" up -d --wait --wait-timeout 180
else
    docker stop harbinger-api || true
fi
if [[ -f "$pending/nginx" ]]; then
    cp "$pending/nginx" /etc/nginx/sites-available/harbinger
    nginx -t
    systemctl reload nginx
fi
rm -rf "$pending"
ROLLBACK
rollback() {
    local status=$?
    trap - ERR
    bash "$pending/rollback.sh" || true
    exit "$status"
}
trap rollback ERR
exec > >(tee -a /var/log/harbinger-deploy.log) 2>&1
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends docker.io docker-compose-v2 nginx python3-venv curl ca-certificates openssl
systemctl enable --now docker nginx
mkdir -p "$release/runtime" /var/www/harbinger-acme/.well-known/acme-challenge
docker load -i "$package/image.tar.gz"
tar -xzf "$package/runtime.tar.gz" -C "$release/runtime"
chmod -R a+rX "$release/runtime"
cp "$package/compose.yml" "$release/compose.yml"
cp "$package/deployment.json" "$release/deployment.json"
printf 'HARBINGER_RELEASE=%s\n' "$release_sha" > "$release/.env"
ln -sfn "$release" "$root/current"
docker compose -p harbinger --env-file "$release/.env" -f "$release/compose.yml" up -d --wait --wait-timeout 180
curl --fail --silent --show-error http://127.0.0.1:8000/health

cat > /etc/nginx/conf.d/harbinger-limits.conf <<'NGINX'
limit_req_zone $binary_remote_addr zone=harbinger_requests:10m rate=15r/s;
limit_conn_zone $binary_remote_addr zone=harbinger_connections:10m;
log_format harbinger '$remote_addr [$time_local] $request_method $status $body_bytes_sent $request_time';
NGINX
cat > /etc/nginx/sites-available/harbinger <<NGINX
server {
    listen 80 default_server;
    server_name $public_ip;
    access_log /var/log/nginx/harbinger-access.log harbinger;
    location /.well-known/acme-challenge/ { root /var/www/harbinger-acme; }
    location / { return 503; }
}
NGINX
rm -f /etc/nginx/sites-enabled/default
ln -sfn /etc/nginx/sites-available/harbinger /etc/nginx/sites-enabled/harbinger
nginx -t
systemctl reload nginx
if [[ ! -x "$root/certbot/bin/certbot" ]]; then
    python3 -m venv "$root/certbot"
fi
"$root/certbot/bin/pip" install --disable-pip-version-check 'certbot==5.8.0'
cert_args=(certonly --non-interactive --agree-tos --register-unsafely-without-email
    --preferred-profile shortlived --webroot --webroot-path /var/www/harbinger-acme
    --ip-address "$public_ip" --cert-name harbinger)
if [[ -f /etc/letsencrypt/live/harbinger/fullchain.pem ]]; then
    if ! openssl x509 -in /etc/letsencrypt/live/harbinger/fullchain.pem -checkip "$public_ip" -noout; then
        cert_args+=(--force-renewal)
    fi
fi
"$root/certbot/bin/certbot" "${cert_args[@]}"
cat > /etc/nginx/sites-available/harbinger <<NGINX
server {
    listen 80 default_server;
    server_name $public_ip;
    access_log /var/log/nginx/harbinger-access.log harbinger;
    location /.well-known/acme-challenge/ { root /var/www/harbinger-acme; }
    location / { return 308 https://$public_ip\$request_uri; }
}
server {
    listen 443 ssl default_server;
    server_name $public_ip;
    ssl_certificate /etc/letsencrypt/live/harbinger/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/harbinger/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    access_log /var/log/nginx/harbinger-access.log harbinger;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy no-referrer always;
    add_header Cache-Control no-store always;
    client_max_body_size 5m;
    client_body_timeout 20s;
    limit_req zone=harbinger_requests burst=40 nodelay;
    limit_req_status 429;
    limit_conn harbinger_connections 10;
    location = / { return 302 /console/; }
    location = /deployment.json { alias $root/current/deployment.json; }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $public_ip;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_read_timeout 120s;
    }
}
NGINX
nginx -t
systemctl reload nginx

cat > /etc/systemd/system/harbinger.service <<'UNIT'
[Unit]
Description=Harbinger synthetic-trained analysis API
Requires=docker.service
After=docker.service network-online.target
[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/harbinger/current
ExecStart=/usr/bin/docker compose -p harbinger up -d --wait --wait-timeout 180
ExecStop=/usr/bin/docker compose -p harbinger stop
TimeoutStartSec=240
[Install]
WantedBy=multi-user.target
UNIT
cat > /usr/local/sbin/harbinger-reload-nginx <<'HOOK'
#!/bin/sh
set -eu
/usr/sbin/nginx -t
/usr/bin/systemctl reload nginx
HOOK
chmod 755 /usr/local/sbin/harbinger-reload-nginx
cat > /etc/systemd/system/harbinger-cert-renew.service <<'UNIT'
[Unit]
Description=Renew Harbinger short-lived IP TLS certificate
After=network-online.target nginx.service
[Service]
Type=oneshot
ExecStart=/opt/harbinger/certbot/bin/certbot renew --quiet --deploy-hook /usr/local/sbin/harbinger-reload-nginx
UNIT
cat > /etc/systemd/system/harbinger-cert-renew.timer <<'UNIT'
[Unit]
Description=Check Harbinger IP certificate renewal every six hours
[Timer]
OnCalendar=*-*-* 00,06,12,18:00:00
RandomizedDelaySec=900
Persistent=true
[Install]
WantedBy=timers.target
UNIT
cat > /etc/logrotate.d/harbinger <<'LOGROTATE'
/var/log/harbinger-deploy.log {
    daily
    rotate 7
    size 10M
    compress
    missingok
    notifempty
    copytruncate
}
LOGROTATE
systemctl daemon-reload
systemctl enable --now harbinger.service harbinger-cert-renew.timer
curl --fail --silent --show-error "https://$public_ip/health"
rm -f "$package/image.tar.gz" "$package/runtime.tar.gz"
trap - ERR
printf '\nRelease installed; final verification pending: https://%s/console/\n' "$public_ip"
