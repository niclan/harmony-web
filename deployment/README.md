# Deployment Guide

This directory contains configuration files for deploying Harmony Hub Web Controller on a server with nginx and systemd.

The application runs using **gunicorn** (a production-grade WSGI server) behind nginx as a reverse proxy.

## Prerequisites

- Ubuntu/Debian Linux server
- nginx installed
- Python 3.11+ installed
- sudo/root access

## Installation Steps

### 1. Clone and Setup Application

```bash
# Clone repository to /var/lib
sudo git clone <repository-url> /var/lib/harmony-web
cd /var/lib/harmony-web

# Create virtual environment
sudo python3 -m venv venv
sudo venv/bin/pip install -r requirements.txt

# Set ownership
sudo chown -R www-data:www-data /var/lib/harmony-web
```

### 2. Configure Environment Variables

Edit `/var/lib/harmony-web/deployment/harmony-web.service` and set:
- `HARMONY_IP` - Optional Hub IP override; leave commented out for automatic SSDP discovery (requires local-network multicast access)
- `URL_PREFIX` - URL prefix (default: /harmony)
- `ENVIRONMENT` - Keep `production` for service deployments
- `PORT` - Local listening port (default: 5000)

### 3. Install systemd Service

```bash
# Copy service file
sudo cp /var/lib/harmony-web/deployment/harmony-web.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable harmony-web

# Start service
sudo systemctl start harmony-web

# Check status
sudo systemctl status harmony-web
```

### 4. Configure nginx

```bash
# Copy nginx config to conf.d
sudo cp /var/lib/harmony-web/deployment/nginx-harmony.conf /etc/nginx/conf.d/harmony.conf

# Test nginx configuration
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

### 5. Configure Ingress Nginx (if applicable)

If you have an ingress nginx that proxies to this server, configure it to pass the client IP:

```nginx
# Ingress nginx configuration
# Add to your main ingress nginx server block

location /harmony {
    # Proxy to harmony-web server
    # Replace with your harmony-web server IP/hostname
    proxy_pass http://192.168.1.100;

    # Preserve original client IP (REQUIRED for IP restrictions)
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # Connection handling
    proxy_http_version 1.1;
    proxy_set_header Connection "";
}
```

**Important:** The `X-Forwarded-For` header is required if you want to restrict access by client IP (see Optional Security Configuration below).

## Verification

Access the application at: `http://your-server/harmony`

## Gunicorn Configuration

The systemd service runs gunicorn with the following configuration:

- **Workers:** 1 (shares one Hub connection across request threads)
- **Threads:** 4 per worker (handles async I/O to Harmony Hub efficiently)
- **Bind:** 127.0.0.1:5000 (localhost only, nginx proxies external requests)
- **Timeout:** 75 seconds (longer than the application’s 60-second request wait)

Edit `/etc/systemd/system/harmony-web.service` to change the bind address, port, or thread count. Keep one worker so requests share a Hub connection.

After changes:
```bash
sudo systemctl daemon-reload
sudo systemctl restart harmony-web
```

## Monitoring

```bash
# View logs
sudo journalctl -u harmony-web -f

# Check service status
sudo systemctl status harmony-web

# Restart service
sudo systemctl restart harmony-web
```

## Updating

```bash
# Pull latest changes
cd /var/lib/harmony-web
sudo git pull

# Restart service
sudo systemctl restart harmony-web
```

## Changing URL Prefix

1. Edit `/etc/systemd/system/harmony-web.service`
2. Change `URL_PREFIX` environment variable
3. Update nginx config location to match
4. Reload systemd and restart services:

```bash
sudo systemctl daemon-reload
sudo systemctl restart harmony-web
sudo systemctl reload nginx
```

## Troubleshooting

### Service won't start

```bash
# Check logs
sudo journalctl -u harmony-web -n 50

# Check if port is in use
sudo netstat -tulpn | grep 5000
```

### 502 Bad Gateway from nginx

- Check if harmony-web service is running: `sudo systemctl status harmony-web`
- Check if Flask is listening on port 5000: `sudo netstat -tulpn | grep 5000`
- Check nginx error logs: `sudo tail -f /var/log/nginx/error.log`

### Permission Issues

```bash
# Fix ownership
sudo chown -R www-data:www-data /var/lib/harmony-web

# Ensure writable cache directory
sudo chmod 755 /var/lib/harmony-web/static/images/activities
```
