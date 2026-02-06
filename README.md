# Logitech Harmony Hub Web Controller

A Python Flask web application that provides a web interface and REST API for controlling Logitech Harmony Hub activities.

## Features

- Modern web interface with black background and visual activity indicators
- Activity cards with cached images from Harmony Hub CDN or type-based fallback icons
- Active activity highlighted with prominent green border
- Transport controls (play/pause/stop) with large emoji icons
- Volume control (up/down/mute) with visual feedback
- Power button conveniently located in header
- Always-visible controls (grayed out when inactive)
- Intelligent button enabling/disabling based on activity capabilities
- REST API for programmatic control
- Auto-refresh of current activity status every 5 seconds
- Docker support for easy deployment

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

# Run the application
python app.py
```

Visit http://localhost:5000 to access the web interface.

### Using Docker

```bash
# Set your Harmony Hub IP
export HARMONY_IP="192.168.1.123"

# Build and run
docker-compose up -d
```

## Configuration

Set the `HARMONY_IP` environment variable to your Harmony Hub's IP address. Default is `192.168.1.123`.

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

- Python 3.11+
- Flask 3.1.2
- aioharmony 0.5.3
- Logitech Harmony Hub on your network

## Architecture

The application uses Flask (synchronous) with aioharmony (asynchronous) via an async-sync bridge pattern. A persistent event loop runs in a background thread to maintain stable connections with the Harmony Hub.

**Control Mapping:**
- **Volume controls**: Use `VolumeActivityRole` from activity configuration
- **Transport controls**: Use `PassThroughActivityRole` (separate media player) or `PlayMediaActivityRole` (integrated player)
- Buttons automatically enable/disable based on activity capabilities
