# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Logitech Harmony Hub Web Controller - A Python Flask web application that provides a web interface and REST API for controlling Logitech Harmony Hub activities. The application communicates with the Harmony Hub via XMPP using the `aioharmony` library.

## Development Commands

### Running the Application

```bash
# Activate virtual environment first
source venv/bin/activate

# Direct Python execution
python app.py

# For debug mode with auto-reload, set FLASK_DEBUG
FLASK_DEBUG=true python app.py

# The app runs on http://0.0.0.0:5000
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

# Dependencies: Flask 3.1.2, aioharmony 0.5.3, requests 2.32.5, gunicorn 21.2.0
```

## Architecture

### Core Components

**app.py** - Main Flask application with the following architecture:

- **Blueprint Pattern**: All routes registered via Flask Blueprint for URL prefix support
  - Blueprint named 'harmony' contains all route handlers
  - Registered with configurable `url_prefix` from `URL_PREFIX` environment variable
  - Enables deployment at subpaths (e.g., `/harmony/*`) behind reverse proxy

- **Async-Sync Bridge Pattern**: Flask (synchronous) wraps aioharmony (asynchronous) using `run_async()` helper
  - Maintains a persistent event loop in a background thread
  - Uses `threading.Event` to ensure loop is ready before executing coroutines (eliminates race conditions)
  - Uses `asyncio.run_coroutine_threadsafe()` to execute async operations from sync Flask handlers
  - Single global `harmony_client` instance maintained via `get_harmony_client()`
  - Connection is persistent and reused across all requests
  - **Connection Resilience**: Automatically detects and reconnects if Harmony Hub connection is lost

- **Control Device Resolution**: Uses Harmony Hub's activity role fields to determine which device receives commands:
  - `VolumeActivityRole`: Device for volume commands (amplifier/receiver)
  - `PassThroughActivityRole`: Device for transport commands (separate media player)
  - Falls back to `PlayMediaActivityRole` if PassThroughActivityRole not present
  - This mapping ensures commands go to the correct device (e.g., play/pause to Squeezebox, volume to amplifier)

- **Activity Image Caching**: Downloads activity images from Harmony Hub CDN and caches locally
  - Images downloaded from `baseImageUri + imageKey` fields in activity config
  - **Security**: Domain whitelist restricts downloads to trusted Logitech/Harmony CDN domains only
    - Allowed domains: `rcbu-prod-ssl-amr.myharmony.com`, `home.myharmony.com`, `svcs.myharmony.com`
    - Rejects and logs attempts to download from untrusted domains
  - Cached in `static/images/activities/` directory (gitignored except .gitkeep)
  - Cache-forever strategy: images never expire once downloaded
  - Type-based fallback emoji icons used when no image available (music, video, TV, power, generic)
  - `/api/activities` endpoint includes `cachedImageUrl` field with local path

- **Input Validation**: Activity IDs validated against Harmony Hub config before execution
  - `/api/start_activity` validates activity_id exists in config
  - Returns 400 Bad Request for invalid activity IDs
  - Prevents commands to non-existent activities

- **Logging**: Comprehensive debug logging throughout
  - Application logs at DEBUG level
  - aioharmony library logs at DEBUG level
  - All logs include timestamps and full tracebacks

**templates/index.html** - Single-page web UI:
- Vanilla JavaScript (no frameworks)
- **UI Design**:
  - Black background for high contrast
  - White cards with rounded corners for all content sections
  - Power button in header on left side with emoji icon
  - Always-visible control buttons (grayed out when inactive)
  - Six control buttons in single row: Play, Pause, Stop, Volume Up, Volume Down, Mute
  - Square-shaped control buttons with large emoji icons above text
  - Color-coded controls: green (transport), purple (volume), red (power)
- **Activity Indication**:
  - Active activity card has prominent green border
  - Activity cards display images or type-based fallback emoji icons
  - No Active/Inactive text labels (visual border is sufficient)
- **Behavior**:
  - Auto-refreshes current activity every 5 seconds
  - Smart UI updates that avoid flickering by checking state changes before DOM manipulation
  - Transport buttons auto-enable/disable based on PassThroughActivityRole availability
  - Volume and power buttons disabled when no activity is active
  - Button click feedback with processing state (scale/opacity animations)
  - Grace period after activity changes to prevent auto-refresh interference
- **Layout**:
  - Responsive grid layout for activities (auto-fill based on screen width)
  - Single-row grid layout for control buttons
  - Flexbox header with power button and centered title
- Inline CSS and JS (no external dependencies)

### API Endpoints

All endpoints return JSON with `{'error': str}` on failure or appropriate success response.

- `GET /api/activities` - List all available Harmony activities from hub config (excludes PowerOff activity - redundant with Power Off button)
- `GET /api/current_activity` - Get current activity ID and name (returns tuple from `client.current_activity`)
- `POST /api/start_activity` - Start activity by ID (requires `{"activity_id": str}`)
- `POST /api/power_off` - Turn off all activities (activity ID -1)
- `GET /api/transport_controls` - Check if current activity supports transport controls (checks for PassThroughActivityRole or PlayMediaActivityRole)
- `POST /api/transport` - Transport control (requires `{"action": "play"|"pause"|"stop"}`)
  - Uses PassThroughActivityRole first, falls back to PlayMediaActivityRole
  - Sends standard command names (Play, Pause, Stop) to the appropriate device
- `POST /api/volume` - Volume control (requires `{"action": "up"|"down"|"mute"}`)
  - Uses VolumeActivityRole to find correct device
  - Returns 404 if no volume device found for activity
- `GET /api/devices` - List all devices from hub config

### Configuration

Environment variables:
- `HARMONY_IP` - Harmony Hub IP address (default: "192.168.1.123")
- `URL_PREFIX` - URL prefix for reverse proxy deployment (default: empty, example: "/harmony")
- `FLASK_DEBUG` - Enable Flask debug mode (default: "False", accepts: "true", "1", "yes")

Set via export, .env file, Docker environment, or systemd service file.

**URL Prefix Support:**
All routes are registered via Flask Blueprint with configurable `url_prefix`. This allows the app to run behind nginx reverse proxy at a subpath (e.g., `/harmony`). When `URL_PREFIX` is set, all endpoints are prefixed (e.g., `/harmony/api/activities`).

**Production Deployment:**
- Keep `FLASK_DEBUG=False` (default) to disable debug mode
- See `deployment/` directory for nginx config and systemd service files
- Runs via gunicorn WSGI server (not Flask's built-in server)
- systemd service manages gunicorn process
- nginx reverse proxies external requests to gunicorn

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
- UI implements a grace period after activity changes where auto-refresh is paused to prevent flickering
- Transport button availability is determined by presence of PassThroughActivityRole OR PlayMediaActivityRole, not by checking controlGroups
- Volume and transport controls both validate that an activity is running (not PowerOff state with ID "-1")

## Testing

**Test Framework:** Python's built-in `unittest` module

**Running Tests:**
```bash
python -m unittest discover tests -v
```

**Test Coverage:**
- Flask route endpoints (index, activities, current_activity, start_activity, power_off)
- Image caching functionality with domain validation
- Input validation for activity IDs
- Error handling for invalid requests

**Test Files:**
- `tests/test_app.py` - Main application tests

**Key Test Areas:**
- Mocked `HarmonyAPI` client for isolated testing
- Activity ID validation against config
- Domain whitelist enforcement for image downloads
- Error responses for invalid input
- Successful API responses with mocked data

## ALWAYS REMEMBER

- Consider injection, quoting and validation when writing code
- Update test suite
- Update CLAUDE.md - but avoid line numbers, and replicating information you have in
  other files such as the version numbers given in requirements.txt and so on.

## Security

- Assume friendly local network or that:
- Any needed (authentication, authorization, https, rate limiting)
  will be provided by NGiNX or other fronting proxy

