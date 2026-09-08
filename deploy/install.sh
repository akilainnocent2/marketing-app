#!/bin/bash
set -euo pipefail
cd /root/myapps/marketing-app
# Scope guard: this initial installer refuses to overwrite an existing deployment.
test ! -e /etc/systemd/system/marketing.service
test ! -e /etc/nginx/sites-available/marketing
test ! -e /etc/marketing/marketing.env
test -z "$(runuser -u postgres -- psql -X -d postgres -Atc "SELECT datname FROM pg_database WHERE datname='marketing'")"
test -z "$(runuser -u postgres -- psql -X -d postgres -Atc "SELECT rolname FROM pg_roles WHERE rolname='marketing'")"
runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -d postgres <<'SQL'
CREATE ROLE marketing LOGIN PASSWORD 'marketing_app' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE DATABASE marketing OWNER marketing;
REVOKE ALL ON DATABASE marketing FROM PUBLIC;
SQL
install -d -m 700 /etc/marketing
install -m 600 deploy/marketing.env /etc/marketing/marketing.env
install -d -m 755 /var/www/marketing/static /var/www/marketing/acme
set -a
source /etc/marketing/marketing.env
set +a
.venv/bin/python manage.py check --deploy --fail-level WARNING
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py initialize
.venv/bin/python manage.py import_locations
.venv/bin/python manage.py collectstatic --noinput
chmod -R a+rX /var/www/marketing/static
install -m 644 deploy/marketing.service /etc/systemd/system/marketing.service
systemctl daemon-reload
systemctl enable --now marketing.service
install -m 644 deploy/marketing-http.conf /etc/nginx/sites-available/marketing
ln -s /etc/nginx/sites-available/marketing /etc/nginx/sites-enabled/marketing
nginx -t
systemctl reload nginx
certbot certonly --webroot -w /var/www/marketing/acme -d marketing.britishschool.ac.tz --cert-name marketing.britishschool.ac.tz --non-interactive --agree-tos --register-unsafely-without-email
cat deploy/marketing-http.conf deploy/marketing-https.conf > /etc/nginx/sites-available/marketing
nginx -t
systemctl reload nginx
systemctl is-active marketing.service
