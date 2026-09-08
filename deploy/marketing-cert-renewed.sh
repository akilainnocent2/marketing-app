#!/bin/sh
set -eu
if [ "${RENEWED_LINEAGE:-}" = /etc/letsencrypt/live/marketing.britishschool.ac.tz ]; then
    /usr/sbin/nginx -t
    /usr/bin/systemctl reload nginx
fi
