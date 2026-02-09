# Logitech Harmony Hub Web Controller

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-47%20passing-brightgreen.svg)](tests/)

A Python Flask web application that provides a web interface and REST
API for controlling Logitech Harmony Hub activities.

## Features

- **Modern Web Interface** with black background and visual activity indicators
- **Activity Cards** with cached images from Harmony Hub CDN or type-based fallback icons
- **Active Activity Highlighting** with prominent green border
- **Transport Controls** (play/pause/stop) with large emoji icons
- **Volume Control** (up/down/mute) with visual feedback
- **Power Button** conveniently located in header
- **Always-visible Controls** (grayed out when inactive)
- **Intelligent Button Management** - auto-enable/disable based on activity capabilities
- **Keyboard Shortcuts** for quick control (Space, P, S, M, Arrow keys, Q/Escape)
- **Media Session API** integration for lock screen controls (mobile/desktop)
- **REST API** for programmatic control
- **Auto-refresh** of current activity status every 5 seconds
- **Security Hardening** with input validation, image validation, and error sanitization
- **Production Ready** with gunicorn WSGI server
- **Docker Support** for easy deployment

## Quick Start

### Using Python (Development)

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set your Harmony Hub IP
export HARMONY_IP="192.168.1.123"

# Run in production mode (INFO logging)
python app.py

# OR run in development mode (DEBUG logging, auto-reload)
ENVIRONMENT=dev python app.py
```

Visit http://localhost:5000 to access the web interface.

### Running Tests

The project includes 47 comprehensive tests covering all endpoints, security validation, and error handling.

```bash
# Run unit tests
python -m unittest discover tests -v
```

### Using Docker

```bash
# Set your Harmony Hub IP
export HARMONY_IP="192.168.1.123"

# Build and run
docker-compose up -d
```

## Configuration

Environment variables:
- `HARMONY_IP` - Harmony Hub IP address (default: `192.168.1.123`)
- `URL_PREFIX` - URL prefix for reverse proxy deployment (default: none, example: `/harmony`)
- `ENVIRONMENT` - Application mode (default: `production`, set to `dev` for development)
  - `production`: INFO level logging, Flask debug disabled
  - `dev`: DEBUG level logging, Flask debug and auto-reload enabled
- `PORT` - Port to listen on (default: `5000`)

### Production Deployment

The application uses **gunicorn** as the production WSGI server (not Flask's built-in development server).

For detailed instructions on deploying with nginx reverse proxy and systemd, see [deployment/README.md](deployment/README.md).

Docker deployments automatically use gunicorn in production mode.

## API Endpoints

- `GET /api/activities` - List all available activities
- `GET /api/current_activity` - Get current activity
- `POST /api/start_activity` - Start activity (requires `activity_id` in JSON body)
- `POST /api/power_off` - Turn off all activities
- `GET /api/transport_controls` - Get available transport controls for current activity
- `POST /api/transport` - Transport control (requires `action`: "play", "pause", or "stop")
- `POST /api/volume` - Volume control (requires `action`: "up", "down", or "mute")
- `GET /api/devices` - List all devices

## Requirements

- Python 3.11+ (tested with 3.13)
- Flask, aioharmony, requests, gunicorn (see [requirements.txt](requirements.txt) for versions)
- Logitech Harmony Hub on your network

## Architecture

The application uses Flask (synchronous) with aioharmony (asynchronous) via an async-sync bridge pattern. A persistent event loop runs in a background thread to maintain stable connections with the Harmony Hub.

**Control Mapping:**
- **Volume controls**: Use `VolumeActivityRole` from activity configuration
- **Transport controls**: Use `PassThroughActivityRole` (separate media player) or `PlayMediaActivityRole` (integrated player)
- Buttons automatically enable/disable based on activity capabilities

## Security

The application implements comprehensive security measures for local network deployment:

- **Input Validation**: Type and format validation for all API inputs
- **Image Security**: Domain whitelist, file size limits (5MB), and magic byte validation
- **Error Sanitization**: Generic error messages to users, full details logged internally
- **Logging Control**: INFO level by default, DEBUG only in dev mode
- **Debug Mode Protection**: Flask debug mode only enabled in development environment

**Security Assumptions:**
- Designed for trusted local network deployment
- Authentication/authorization handled by reverse proxy if needed (e.g., nginx)
- HTTPS termination at reverse proxy level

For production internet-facing deployments, implement authentication and HTTPS at the proxy level.

## License

Copyright 2025-2026 Schibsted Products and Technology

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

## Authors

- Nicolai Langfeldt
- Claude (Anthropic AI Assistant)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
