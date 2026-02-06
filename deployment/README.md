# Deployment Guide

This directory contains configuration files for deploying Harmony Hub Web Controller on a server with nginx and systemd.

## Prerequisites

- Ubuntu/Debian Linux server
- nginx installed
- Python 3.11+ installed
- sudo/root access

## Installation Steps

### 1. Clone and Setup Application

```bash
# Clone repository to /opt
sudo git clone <repository-url> /opt/harmony-web
cd /opt/harmony-web

# Create virtual environment
sudo python3 -m venv venv
sudo venv/bin/pip install -r requirements.txt

# Set ownership
sudo chown -R www-data:www-data /opt/harmony-web
```

### 2. Configure Environment Variables

Edit `/opt/harmony-web/deployment/harmony-web.service` and set:
- `HARMONY_IP` - Your Harmony Hub IP address
- `URL_PREFIX` - URL prefix (default: /harmony)
- `FLASK_DEBUG` - Debug mode (default: False)

### 3. Install systemd Service

```bash
# Copy service file
sudo cp /opt/harmony-web/deployment/harmony-web.service /etc/systemd/system/

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
# Copy nginx config
sudo cp /opt/harmony-web/deployment/nginx-harmony.conf /etc/nginx/sites-available/harmony

# Create symlink to enable
sudo ln -s /etc/nginx/sites-available/harmony /etc/nginx/sites-enabled/

# Test nginx configuration
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

## Verification

Access the application at: `http://your-server/harmony`

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
cd /opt/harmony-web
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
sudo chown -R www-data:www-data /opt/harmony-web

# Ensure writable cache directory
sudo chmod 755 /opt/harmony-web/static/images/activities
```
