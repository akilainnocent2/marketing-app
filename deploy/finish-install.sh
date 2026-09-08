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
