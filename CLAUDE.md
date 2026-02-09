# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Logitech Harmony Hub Web Controller - A Python Flask web application that provides a web interface and REST API for controlling Logitech Harmony Hub activities. The application communicates with the Harmony Hub via XMPP using the `aioharmony` library.

## Development Commands

### Running the Application

```bash
# Activate virtual environment first
source venv/bin/activate

# Direct Python execution (production mode - INFO logging)
python app.py

# For development mode with DEBUG logging and auto-reload
ENVIRONMENT=dev python app.py

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

# Dependencies defined in requirements.txt (see file for current versions)
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

- **Activity Image Caching**: Downloads activity images from Harmony Hub CDN and caches locally with validation
  - Images downloaded from `baseImageUri + imageKey` fields in activity config
  - **Security Features**:
    - Domain whitelist: Only trusted Logitech/Harmony CDN domains allowed (`rcbu-prod-ssl-amr.myharmony.com`, `home.myharmony.com`, `svcs.myharmony.com`)
    - File size limit: 5MB maximum
    - Magic byte validation: Only PNG, JPEG, GIF, WebP, and BMP image types accepted
    - Temporary file validation before moving to cache
    - Automatic cleanup of invalid files
  - Cached in `static/images/activities/` directory (gitignored except .gitkeep)
  - Cache-forever strategy: images never expire once downloaded
  - Type-based fallback emoji icons used when no image available
  - `/api/activities` endpoint includes `cachedImageUrl` field with local path

- **Input Validation**: Comprehensive validation for all API inputs
  - **Type validation**: All POST parameters must be correct type (string) using `isinstance()` checks
  - **Activity ID validation**: Must be numeric string matching `/^\d+$/` or "-1", then validated against hub config
  - **Action parameter validation**: Whitelisted values only (e.g., "up"/"down"/"mute" for volume)
  - Returns 400 Bad Request with descriptive error for invalid inputs
  - Prevents: Type confusion attacks, injection attempts, commands to non-existent entities

- **Logging**: Environment-aware logging configuration
  - **Production** (default): INFO level for application and aioharmony
  - **Development** (`ENVIRONMENT=dev`): DEBUG level with verbose output
  - All logs include timestamps and source information
  - Error logs include full tracebacks for debugging
  - Generic error messages sent to users while full details logged internally

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
- `ENVIRONMENT` - Application environment mode (default: "production", set to "dev" for development)
  - **production** (default): INFO logging, Flask debug disabled
  - **dev**: DEBUG logging, Flask debug and auto-reload enabled
- `PORT` - Port to listen on (default: "5000")

Set via export, .env file, Docker environment, or systemd service file.

**URL Prefix Support:**
All routes are registered via Flask Blueprint with configurable `url_prefix`. This allows the app to run behind nginx reverse proxy at a subpath (e.g., `/harmony`). When `URL_PREFIX` is set, all endpoints are prefixed (e.g., `/harmony/api/activities`).

**Production Deployment:**
- Use default `ENVIRONMENT=production` (INFO logging, no debug mode)
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
- All Flask route endpoints (index, activities, current_activity, start_activity, power_off, volume, transport, devices)
- Volume control endpoint with validation and error handling
- Transport control endpoints with availability detection
- Image caching with domain whitelist, size limits, and type validation
- Input type and format validation for all POST parameters
- Error handling for invalid requests and connection failures

**Test Files:**
- `tests/test_app.py` - Main application tests (47 tests)

**Key Test Areas:**
- Mocked `HarmonyAPI` client for isolated testing
- Input type validation (string type enforcement)
- Input format validation (numeric activity IDs, whitelisted actions)
- Activity ID validation against hub config
- Domain whitelist enforcement for image downloads
- Image file size and type validation
- Error responses for invalid input
- Generic error messages without internal details
- Successful API responses with mocked data

## ALWAYS REMEMBER

- Update test suite
- Update CLAUDE.md - but avoid line numbers, and replicating
  information you have in other files such as the version numbers
  given in requirements.txt and so on.

## Security

### Security Implementation

The application implements multiple layers of security appropriate for local network deployment:

**Input Validation & Injection Prevention:**
- All POST parameters validated for correct type using `isinstance()` checks
- Activity IDs must match `/^\d+$/` or "-1" format
- Action parameters validated against whitelists before processing
- Prevents: Type confusion attacks, SQL injection (N/A - no database), command injection

**Image Security:**
- Domain whitelist: Only Logitech/Harmony CDN domains accepted
- File size limit: 5MB maximum per image
- Magic byte validation: PNG, JPEG, GIF, WebP, BMP only
- Temporary file validation before moving to cache
- Automatic cleanup of invalid files
- Prevents: SSRF attacks, malicious file uploads, disk exhaustion

**Error Handling:**
- Generic error messages sent to users ("Failed to start activity")
- Full exception details logged internally with stack traces
- ValueError messages preserved for input validation errors
- Prevents: Information disclosure of internal system details

**Logging Security:**
- INFO level logging by default (production)
- DEBUG level only when `ENVIRONMENT=dev`
- Prevents: Sensitive data leakage in production logs

**Debug Mode Protection:**
- Flask debug mode ONLY enabled when `ENVIRONMENT=dev`
- Cannot be enabled via environment variable in production
- Prevents: Exposure of interactive debugger and code execution

### Security Assumptions

**Deployment Model:**
- Assumes friendly local network OR
- Authentication, authorization, HTTPS, and rate limiting provided by nginx or other reverse proxy

**Out of Scope (Handled at Network/Proxy Level):**
- Authentication/Authorization (assumes trusted network or proxy handles it)
- HTTPS/TLS (nginx terminates SSL if needed)
- CSRF protection (assumes same-origin or proxy enforces it)
- Rate limiting (nginx can implement if needed)

### Code Security Guidelines

When writing new code:
- Always validate input types with `isinstance()` before processing
- Validate string formats with regex or whitelist checks
- Return generic error messages to users, log full details internally
- Use INFO level logging for production, DEBUG only for development
- Never execute shell commands with user input
- Sanitize all user-controlled data before HTML output (use `escapeHtml()` in JavaScript)
