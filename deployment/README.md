# Deployment Guide

For application installation and systemd service setup, follow
[Installing as a systemd service](../README.md#installing-as-a-systemd-service)
in the top-level README. That section also covers standalone access and logging.
See [Configuration](../README.md#configuration) for environment variables and
Hub discovery, and [Security](../README.md#security) for deployment assumptions.

This guide covers optional nginx integration and maintenance of an installed service.

## Optional nginx reverse proxy

After installing the app, add the location block from
[nginx-harmony.conf](nginx-harmony.conf) inside your nginx site's existing
`server` block. The file is a location snippet, not a complete site configuration.
Match its location prefix to the app's `URL_PREFIX`, and its upstream port to
the service's listening port.

Validate and reload nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Access the app through your nginx hostname at the configured location prefix.

### Additional ingress proxy

If another nginx proxies to this server, pass the original client information:

```nginx
# Inside the ingress server block; replace the backend address.
location /harmony {
    proxy_pass http://192.168.1.100;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
}
```

If the backend nginx uses client-IP restrictions, configure the real-IP directives
in [nginx-harmony.conf](nginx-harmony.conf), trusting only your ingress proxy's
address. Forwarded headers alone do not enable client-IP restrictions.

## Changing an installed service

The supplied [service unit](harmony-web.service) is the reference for Gunicorn
options. Edit the installed copy at `/etc/systemd/system/harmony-web.service`.
Keep one worker so request threads share a Hub connection.

After changing the installed unit:

```bash
sudo systemctl daemon-reload
sudo systemctl restart harmony-web
```

When changing the URL prefix or listening port, update the nginx location or
upstream to match, then validate and reload nginx as above.

## Updating

From the installed checkout:

```bash
cd /var/lib/harmony-web
sudo git pull
```

If dependencies changed, repeat the dependency installation command in the
[top-level installation instructions](../README.md#installing-as-a-systemd-service).
If the supplied unit changed, review and apply its changes to the installed unit,
then use the reload and restart steps above. Otherwise, restart the app:

```bash
sudo systemctl restart harmony-web
```

## Troubleshooting nginx

For a 502 response, use the service status and journal commands in the
[top-level installation instructions](../README.md#installing-as-a-systemd-service).
Check that nginx's upstream address matches the running service, and inspect
`/var/log/nginx/error.log`.

For image-cache permission errors, check the cache ownership and service account
against the same installation instructions.
