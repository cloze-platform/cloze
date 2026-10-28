#!/bin/sh
# Self-signed certificate for the load balancer -> container hop. The ALB
# encrypts to its targets but doesn't verify their certificates.
set -e
mkdir -p /tmp/tls
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=cloze" \
  -keyout /tmp/tls/key.pem -out /tmp/tls/cert.pem 2> /dev/null
exec "$@"
