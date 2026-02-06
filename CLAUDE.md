# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Logitech Harmony Hub Web Controller - A Python Flask web application that provides a web interface and REST API for controlling Logitech Harmony Hub activities. The application communicates with the Harmony Hub via XMPP using the `aioharmony` library.

## Development Commands

### Running the Application

```bash
# Activate virtual environment first
source venv/bin/activate

# Direct Python execution (development mode with auto-reload)
python app.py

# The app runs on http://0.0.0.0:5000 with debug=True enabled
```

### Docker

```bash
# Build and run with Docker Compose
export HARMONY_IP="192.168.1.123"  # Set your Harmony Hub IP
docker-compose up -d

# Build Docker image directly
docker build -t harmony-controller .

# Run Docker container
docker run -d -p 5000:5000 -e HARMONY_IP="192.168.1.123" harmony-controller
```

### Dependencies

```bash
# Install dependencies
pip install -r requirements.txt

# Dependencies: Flask 3.1.2, aioharmony 0.5.3, requests 2.32.5
```

## Architecture

### Core Components

**app.py** - Main Flask application with the following architecture:

- **Async-Sync Bridge Pattern**: Flask (synchronous) wraps aioharmony (asynchronous) using `run_async()` helper
  - Maintains a persistent event loop in a background thread (app.py:36-42)
  - Uses `asyncio.run_coroutine_threadsafe()` to execute async operations from sync Flask handlers (app.py:45-61)
  - Single global `harmony_client` instance maintained via `get_harmony_client()` (app.py:64-83)
  - Connection is persistent and reused across all requests

- **Control Device Resolution**: Uses Harmony Hub's activity role fields to determine which device receives commands:
  - `VolumeActivityRole`: Device for volume commands (amplifier/receiver) - app.py:221
  - `PassThroughActivityRole`: Device for transport commands (media player) - app.py:342-344
  - Falls back to `PlayMediaActivityRole` if PassThroughActivityRole not present
  - This mapping ensures commands go to the correct device (e.g., play/pause to Squeezebox, volume to amplifier)

- **Logging**: Comprehensive debug logging throughout
  - Application logs at DEBUG level
  - aioharmony library logs at DEBUG level
  - All logs include timestamps and full tracebacks

**templates/index.html** - Single-page web UI:
- Vanilla JavaScript (no frameworks)
- Auto-refreshes current activity every 5 seconds
- Smart UI updates that avoid flickering by checking state changes before DOM manipulation
- Transport buttons auto-enable/disable based on PassThroughActivityRole availability
- Responsive grid layout for activities
- Inline CSS and JS (no external dependencies)

### API Endpoints

All endpoints return JSON with `{'error': str}` on failure or appropriate success response.

- `GET /api/activities` - List all available Harmony activities from hub config
- `GET /api/current_activity` - Get current activity ID and name (returns tuple from `client.current_activity`)
- `POST /api/start_activity` - Start activity by ID (requires `{"activity_id": str}`)
- `POST /api/power_off` - Turn off all activities (activity ID -1)
- `GET /api/transport_controls` - Check if current activity supports transport controls (checks for PassThroughActivityRole or PlayMediaActivityRole)
- `POST /api/transport` - Transport control (requires `{"action": "play"|"pause"|"stop"}`)
  - Uses PassThroughActivityRole first, falls back to PlayMediaActivityRole (app.py:342-344)
  - Sends standard command names (Play, Pause, Stop) to the appropriate device
- `POST /api/volume` - Volume control (requires `{"action": "up"|"down"|"mute"}`)
  - Uses VolumeActivityRole to find correct device (app.py:221)
  - Returns 404 if no volume device found for activity
- `GET /api/devices` - List all devices from hub config

### Configuration

Environment variable:
- `HARMONY_IP` - Harmony Hub IP address (default: "192.168.1.123")

Set via export, .env file, or Docker environment.

### Harmony Hub Communication

The application uses the `aioharmony` library which:
- Communicates via XMPP protocol on port 5222
- Returns activity info as tuples: `(activity_id, activity_name)`
- Stores hub configuration in `client.config` dict with 'activity', 'device', 'roles', 'controlGroup' keys
- Activity ID "-1" represents PowerOff state
- Commands are sent using `SendCommandDevice(device, command, delay)` objects via `client.send_commands()`

### Activity Role Fields

Understanding Harmony Hub activity roles is critical for proper device control:

- **VolumeActivityRole** (string): Device ID for volume control (typically an amplifier/receiver)
- **roles['PassThroughActivityRole']** (dict entry): Device ID for transport controls when using a separate media player (e.g., Squeezebox, Roku)
- **roles['PlayMediaActivityRole']** (dict entry): Device ID for transport controls when media playback is integrated into the amplifier/receiver (e.g., CD player)
- **controlGroup** (list): Contains button mappings but may be incorrectly configured - do NOT rely on these for determining which device to send commands to

**Transport Control Resolution:**
1. Check for PassThroughActivityRole first (separate media player)
2. Fall back to PlayMediaActivityRole (integrated media player)
3. If neither exists, transport controls are disabled

Example from Squeezebox activity (separate media player):
```python
activity = {
    'id': '18609707',
    'label': 'Squeezebox',
    'VolumeActivityRole': '63205085',  # Denon amplifier
    'roles': {
        'PassThroughActivityRole': '69365831',  # Squeezebox Touch media player
        'PlayMediaActivityRole': '63205085',    # Also present but not used (PassThrough takes priority)
        'VolumeActivityRole': '63205085'
    }
}
```

Example from CD activity (integrated media player):
```python
activity = {
    'id': '44317642',
    'label': 'CD',
    'VolumeActivityRole': '63205085',  # Denon amplifier
    'roles': {
        'PlayMediaActivityRole': '63205085',  # CD player is part of the Denon device
        'VolumeActivityRole': '63205085'
        # No PassThroughActivityRole - CD is integrated
    }
}
```

### Error Handling

All API routes:
1. Wrap operations in try/except
2. Log full tracebacks at ERROR level
3. Return JSON error responses with 500 status (or 400/404 for validation errors)
4. Never expose internal details to frontend

### Known Implementation Details

- The async-sync bridge uses a background thread with a persistent event loop to avoid connection instability
- UI implements a 3-second "grace period" after activity changes where auto-refresh is paused to prevent flickering (templates/index.html)
- Transport button availability is determined by presence of PassThroughActivityRole OR PlayMediaActivityRole, not by checking controlGroups
- Volume and transport controls both validate that an activity is running (not PowerOff state with ID "-1")

## Testing

No test framework is currently configured. When adding tests, consider:
- Mocking `HarmonyAPI` client for unit tests
- Testing the async-sync bridge behavior
- Testing error handling for connection failures
- Testing role-based device resolution logic
