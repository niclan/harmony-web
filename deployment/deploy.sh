#!/bin/bash
#
# Deploy script for Harmony Hub Web Controller
# Copies local checkout to /var/lib/harmony-web and sets up the service
#
# Usage: sudo ./deploy.sh [--skip-deps]
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Deployment configuration
DEPLOY_USER="www-data"
DEPLOY_GROUP="www-data"
DEPLOY_PATH="/var/lib/harmony-web"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(dirname "$SCRIPT_DIR")"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root (use sudo)${NC}"
    exit 1
fi

echo -e "${GREEN}=== Harmony Hub Web Controller Deployment ===${NC}"
echo ""
echo "Source directory: $SOURCE_DIR"
echo "Deploy path: $DEPLOY_PATH"
echo "User/Group: $DEPLOY_USER:$DEPLOY_GROUP"
echo ""

# Parse arguments
SKIP_DEPS=false
if [ "$1" == "--skip-deps" ]; then
    SKIP_DEPS=true
    echo -e "${YELLOW}Skipping dependency installation${NC}"
fi

# Step 1: Create deployment directory
echo -e "${GREEN}[1/8] Creating deployment directory...${NC}"
mkdir -p "$DEPLOY_PATH"

# Step 2: Copy application files
echo -e "${GREEN}[2/8] Copying application files...${NC}"
rsync -av --delete \
    --exclude='venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='*.pyd' \
    --exclude='.git/' \
    --exclude='.env' \
    --exclude='static/images/activities/*' \
    "$SOURCE_DIR/" "$DEPLOY_PATH/"

# Ensure image cache directory exists
mkdir -p "$DEPLOY_PATH/static/images/activities"

# Step 3: Set up virtual environment
if [ "$SKIP_DEPS" = false ]; then
    echo -e "${GREEN}[3/8] Setting up Python virtual environment...${NC}"
    if [ -d "$DEPLOY_PATH/venv" ]; then
        echo "Virtual environment exists, updating..."
    else
        echo "Creating virtual environment..."
        python3 -m venv "$DEPLOY_PATH/venv"
    fi

    echo -e "${GREEN}[4/8] Installing Python dependencies...${NC}"
    "$DEPLOY_PATH/venv/bin/pip" install --upgrade pip
    "$DEPLOY_PATH/venv/bin/pip" install -r "$DEPLOY_PATH/requirements.txt"
else
    echo -e "${YELLOW}[3/8] Skipped: Virtual environment setup${NC}"
    echo -e "${YELLOW}[4/8] Skipped: Installing dependencies${NC}"
fi

# Step 4: Set ownership
echo -e "${GREEN}[5/8] Setting ownership...${NC}"
chown -R "$DEPLOY_USER:$DEPLOY_GROUP" "$DEPLOY_PATH"

# Step 5: Set permissions
echo -e "${GREEN}[6/8] Setting permissions...${NC}"
chmod 755 "$DEPLOY_PATH"
chmod 755 "$DEPLOY_PATH/static/images/activities"

# Step 6: Install systemd service (if not exists or if updated)
echo -e "${GREEN}[7/8] Installing systemd service...${NC}"
SERVICE_FILE="/etc/systemd/system/harmony-web.service"
if [ ! -f "$SERVICE_FILE" ] || ! cmp -s "$DEPLOY_PATH/deployment/harmony-web.service" "$SERVICE_FILE"; then
    cp "$DEPLOY_PATH/deployment/harmony-web.service" "$SERVICE_FILE"
    echo "Systemd service file updated"
    systemctl daemon-reload

    if systemctl is-enabled harmony-web.service &>/dev/null; then
        echo "Service already enabled"
    else
        echo "Enabling service..."
        systemctl enable harmony-web.service
    fi
else
    echo "Systemd service file unchanged"
fi

# Step 7: Install nginx config (if not exists)
echo -e "${GREEN}[8/8] Checking nginx configuration...${NC}"
NGINX_CONF="/etc/nginx/conf.d/harmony.conf"

if [ -d "/etc/nginx/conf.d" ]; then
    if [ ! -f "$NGINX_CONF" ]; then
        echo "Installing nginx config..."
        cp "$DEPLOY_PATH/deployment/nginx-harmony.conf" "$NGINX_CONF"
        echo "Nginx config installed to $NGINX_CONF"
        echo -e "${YELLOW}Remember to reload nginx: sudo systemctl reload nginx${NC}"
    else
        echo "Nginx config already exists (not overwriting)"
        echo -e "${YELLOW}To update: sudo cp $DEPLOY_PATH/deployment/nginx-harmony.conf $NGINX_CONF${NC}"
    fi
else
    echo -e "${YELLOW}Warning: /etc/nginx/conf.d not found. Install nginx config manually.${NC}"
fi

echo ""
echo -e "${GREEN}=== Deployment Complete ===${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit configuration: sudo nano /etc/systemd/system/harmony-web.service"
echo "     - Optionally set HARMONY_IP to override automatic Hub discovery"
echo "     - Adjust PORT if needed (default: 5000)"
echo "     - Adjust URL_PREFIX if needed (default: /harmony)"
echo ""
echo "  2. Reload systemd: sudo systemctl daemon-reload"
echo ""
echo "  3. Start service: sudo systemctl start harmony-web"
echo ""
echo "  4. Check status: sudo systemctl status harmony-web"
echo ""
echo "  5. View logs: sudo journalctl -u harmony-web -f"
echo ""
echo "  6. If nginx config was installed, reload nginx: sudo systemctl reload nginx"
echo ""
echo "Access URL: http://your-server/harmony"
echo ""
