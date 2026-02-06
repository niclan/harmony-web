#!/usr/bin/env python3
"""
Logitech Harmony Hub Web Controller
Flask web application providing web interface and REST API for controlling Harmony Hub activities.
"""

import os
import asyncio
import logging
import threading
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, Blueprint, render_template, jsonify, request
from aioharmony.harmonyapi import HarmonyAPI, SendCommandDevice
import requests

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Set aioharmony logging to DEBUG
logging.getLogger('aioharmony').setLevel(logging.DEBUG)

app = Flask(__name__)

# Configuration
HARMONY_IP = os.environ.get('HARMONY_IP', '192.168.1.123')
URL_PREFIX = os.environ.get('URL_PREFIX', '').rstrip('/')
PORT = int(os.environ.get('PORT', '5000'))
logger.info(f"Using Harmony Hub IP: {HARMONY_IP}")
if URL_PREFIX:
    logger.info(f"Using URL prefix: {URL_PREFIX}")
logger.info(f"Listening on port: {PORT}")

# Allowed domains for activity image downloads (Logitech/Harmony CDN only)
ALLOWED_IMAGE_DOMAINS = {
    'rcbu-prod-ssl-amr.myharmony.com',  # Harmony Hub CDN (Americas)
    'home.myharmony.com',                # Legacy Harmony domain
    'svcs.myharmony.com',                # Harmony services domain
}

# Global harmony client and event loop
harmony_client = None
loop = None
loop_thread = None
loop_ready = threading.Event()


def start_background_loop():
    """Start the asyncio event loop in a background thread."""
    global loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    logger.info("Starting background event loop")
    loop_ready.set()  # Signal that loop is ready
    loop.run_forever()


def run_async(coro):
    """
    Run an async coroutine in the background event loop.
    Returns the result synchronously.
    """
    global loop, loop_thread

    if loop is None or not loop.is_running():
        # Start background loop thread if not running
        loop_ready.clear()
        loop_thread = threading.Thread(target=start_background_loop, daemon=True)
        loop_thread.start()
        # Wait for loop to be ready (max 5 seconds)
        if not loop_ready.wait(timeout=5):
            raise RuntimeError("Background event loop failed to start")

    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=30)


async def get_harmony_client():
    """
    Get or create the global Harmony client.
    Automatically reconnects if connection is lost.
    """
    global harmony_client

    # Check if we need to create a new client or reconnect
    needs_connection = harmony_client is None

    if harmony_client is not None:
        # Test if connection is still alive by checking if we can get config
        try:
            # Simple connection health check - if config is empty, connection is dead
            if not harmony_client.config:
                logger.warning("Harmony Hub connection lost, reconnecting...")
                harmony_client = None
                needs_connection = True
        except Exception:
            logger.warning("Harmony Hub connection appears dead, reconnecting...")
            harmony_client = None
            needs_connection = True

    if needs_connection:
        logger.debug(f"Creating new Harmony client for {HARMONY_IP}")
        harmony_client = HarmonyAPI(ip_address=HARMONY_IP)

        try:
            if not await harmony_client.connect():
                logger.error("Failed to connect to Harmony Hub")
                harmony_client = None
                raise ConnectionError("Could not connect to Harmony Hub")
            logger.info("Successfully connected to Harmony Hub")
        except Exception as e:
            logger.error(f"Error connecting to Harmony Hub: {e}", exc_info=True)
            harmony_client = None
            raise

    return harmony_client


def cache_activity_image(activity_id, base_uri, image_key):
    """
    Download and cache an activity image locally.
    Returns the local path relative to static directory, or None if download fails.
    Only downloads from whitelisted Logitech/Harmony domains for security.
    """
    if not image_key:
        return None

    # Validate the base_uri domain is from Logitech/Harmony CDN
    if not base_uri:
        logger.warning(f"Empty base_uri for activity {activity_id}, skipping image download")
        return None

    try:
        parsed_url = urlparse(base_uri)
        domain = parsed_url.netloc.lower()

        if domain not in ALLOWED_IMAGE_DOMAINS:
            logger.warning(
                f"Rejected image download from untrusted domain '{domain}' "
                f"for activity {activity_id}. Only Logitech/Harmony CDN domains are allowed."
            )
            return None
    except Exception as e:
        logger.warning(f"Failed to parse base_uri '{base_uri}' for activity {activity_id}: {e}")
        return None

    # Create cache directory if it doesn't exist
    cache_dir = Path('static/images/activities')
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Use activity ID as filename to ensure uniqueness
    file_extension = Path(image_key).suffix or '.png'
    local_filename = f"{activity_id}{file_extension}"
    local_path = cache_dir / local_filename

    # If already cached, return the path
    if local_path.exists():
        return f'/static/images/activities/{local_filename}'

    # Download the image
    try:
        full_url = base_uri + image_key
        logger.debug(f"Downloading activity image from {full_url}")
        response = requests.get(full_url, timeout=10)
        response.raise_for_status()

        # Save to cache
        with open(local_path, 'wb') as f:
            f.write(response.content)

        logger.info(f"Cached activity image: {local_filename}")
        return f'/static/images/activities/{local_filename}'

    except Exception as e:
        logger.warning(f"Failed to cache activity image from {full_url}: {e}")
        return None


# Create blueprint for all routes
bp = Blueprint('harmony', __name__)


@bp.route('/')
def index():
    """Serve the main web interface."""
    return render_template('index.html')


@bp.route('/api/activities', methods=['GET'])
def get_activities():
    """Get list of all available Harmony activities."""
    try:
        logger.debug("Fetching activities list")

        async def fetch_activities():
            client = await get_harmony_client()
            activities = client.config.get('activity', [])
            return activities

        activities = run_async(fetch_activities())

        # Filter out PowerOff activity (redundant with Power Off button)
        activities = [a for a in activities if a.get('label') != 'PowerOff']

        # Cache activity images and add local image paths
        for activity in activities:
            base_uri = activity.get('baseImageUri', '')
            image_key = activity.get('imageKey', '')
            if image_key:
                local_image_path = cache_activity_image(activity['id'], base_uri, image_key)
                activity['cachedImageUrl'] = local_image_path

        logger.debug(f"Found {len(activities)} activities")
        return jsonify({'activities': activities})

    except Exception as e:
        logger.error(f"Error fetching activities: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/current_activity', methods=['GET'])
def get_current_activity():
    """Get the current activity."""
    try:
        logger.debug("Fetching current activity")

        async def fetch_current():
            client = await get_harmony_client()
            current = client.current_activity
            return current

        current = run_async(fetch_current())
        activity_id, activity_name = current
        logger.debug(f"Current activity: {activity_name} (ID: {activity_id})")

        return jsonify({
            'activity_id': activity_id,
            'activity_name': activity_name
        })

    except Exception as e:
        logger.error(f"Error fetching current activity: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/start_activity', methods=['POST'])
def start_activity():
    """Start a specific activity by ID."""
    try:
        data = request.get_json()
        if not data or 'activity_id' not in data:
            return jsonify({'error': 'activity_id required'}), 400

        activity_id = data['activity_id']
        logger.debug(f"Starting activity ID: {activity_id}")

        async def start():
            client = await get_harmony_client()

            # Validate activity_id exists in config
            activities = client.config.get('activity', [])
            valid_ids = [str(a['id']) for a in activities]

            if str(activity_id) not in valid_ids:
                raise ValueError(f"Invalid activity_id: {activity_id}")

            result = await client.start_activity(activity_id)
            return result

        result = run_async(start())
        logger.info(f"Successfully started activity {activity_id}")

        return jsonify({'success': True, 'activity_id': activity_id})

    except ValueError as e:
        logger.warning(f"Invalid activity ID: {e}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error starting activity: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/power_off', methods=['POST'])
def power_off():
    """Power off all activities."""
    try:
        logger.debug("Powering off all activities")

        async def power_off_async():
            client = await get_harmony_client()
            result = await client.power_off()
            return result

        result = run_async(power_off_async())
        logger.info("Successfully powered off")

        return jsonify({'success': True})

    except Exception as e:
        logger.error(f"Error powering off: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/volume', methods=['POST'])
def volume_control():
    """Control volume (up/down/mute)."""
    try:
        data = request.get_json()
        if not data or 'action' not in data:
            return jsonify({'error': 'action required (up/down/mute)'}), 400

        action = data['action']
        if action not in ['up', 'down', 'mute']:
            return jsonify({'error': 'action must be up, down, or mute'}), 400

        logger.debug(f"Volume control: {action}")

        async def send_volume_command():
            client = await get_harmony_client()

            # Get current activity
            current_activity_id, current_activity_name = client.current_activity

            if current_activity_id == '-1':
                logger.warning("Cannot control volume when powered off")
                raise ValueError("No activity is running")

            # Find the current activity in config
            activities = client.config.get('activity', [])
            current_activity = None
            for activity in activities:
                if str(activity['id']) == str(current_activity_id):
                    current_activity = activity
                    break

            if not current_activity:
                logger.warning(f"Current activity {current_activity_id} not found in config")
                raise ValueError("Current activity not found")

            # Get volume device ID from VolumeActivityRole
            volume_device_id = current_activity.get('VolumeActivityRole')

            if not volume_device_id:
                logger.warning(f"No VolumeActivityRole found for activity {current_activity_name}")
                raise ValueError("No volume device configured for this activity")

            logger.debug(f"Found volume device ID: {volume_device_id} for activity {current_activity_name}")

            # Map action to command
            command_map = {
                'up': 'VolumeUp',
                'down': 'VolumeDown',
                'mute': 'Mute'
            }
            command = command_map[action]

            # Send command using SendCommandDevice
            send_command = SendCommandDevice(
                device=str(volume_device_id),
                command=command,
                delay=0
            )
            await client.send_commands(send_command)
            return True

        run_async(send_volume_command())
        logger.info(f"Successfully sent volume {action} command")

        return jsonify({'success': True, 'action': action})

    except ValueError as e:
        logger.error(f"Volume device not found: {e}")
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Error controlling volume: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/transport_controls', methods=['GET'])
def get_transport_controls():
    """Get available transport controls for current activity."""
    try:
        logger.debug("Checking available transport controls")

        async def check_transport():
            client = await get_harmony_client()
            current_activity_id, current_activity_name = client.current_activity

            if current_activity_id == '-1':
                return {'available': False, 'controls': []}

            # Find the current activity in config
            activities = client.config.get('activity', [])
            current_activity = None
            for activity in activities:
                if str(activity['id']) == str(current_activity_id):
                    current_activity = activity
                    break

            if not current_activity:
                return {'available': False, 'controls': []}

            # Check if activity has transport control capability
            # Uses same logic as transport_control() function:
            # Try PassThroughActivityRole first (for separate media players like Squeezebox)
            # Fall back to PlayMediaActivityRole (for integrated players like CD on Denon)
            roles = current_activity.get('roles', {})
            transport_device_id = roles.get('PassThroughActivityRole') or roles.get('PlayMediaActivityRole')

            if transport_device_id:
                # Activity has a transport-capable device
                return {
                    'available': True,
                    'controls': ['play', 'pause', 'stop']
                }
            else:
                return {
                    'available': False,
                    'controls': []
                }

        result = run_async(check_transport())
        logger.debug(f"Transport controls: {result}")
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error checking transport controls: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/transport', methods=['POST'])
def transport_control():
    """Control media transport (play/pause/stop)."""
    try:
        data = request.get_json()
        if not data or 'action' not in data:
            return jsonify({'error': 'action required (play/pause/stop)'}), 400

        action = data['action'].lower()
        if action not in ['play', 'pause', 'stop', 'playpause']:
            return jsonify({'error': 'action must be play, pause, stop, or playpause'}), 400

        logger.debug(f"Transport control: {action}")

        async def send_transport_command():
            client = await get_harmony_client()

            # Get current activity
            current_activity_id, current_activity_name = client.current_activity

            if current_activity_id == '-1':
                logger.warning("Cannot control transport when powered off")
                raise ValueError("No activity is running")

            # Find the current activity in config
            activities = client.config.get('activity', [])
            current_activity = None
            for activity in activities:
                if str(activity['id']) == str(current_activity_id):
                    current_activity = activity
                    break

            if not current_activity:
                logger.warning(f"Current activity {current_activity_id} not found in config")
                raise ValueError("Current activity not found")

            # Get transport device ID from activity roles
            # Try PassThroughActivityRole first (for media players), then fall back to PlayMediaActivityRole
            roles = current_activity.get('roles', {})
            transport_device_id = roles.get('PassThroughActivityRole') or roles.get('PlayMediaActivityRole')

            if not transport_device_id:
                logger.warning(f"No PassThroughActivityRole or PlayMediaActivityRole found for activity {current_activity_name}")
                raise ValueError("No transport control device configured for this activity")

            logger.debug(f"Found transport device ID: {transport_device_id} for activity {current_activity_name}")

            # Map action to standard command names
            command_map = {
                'play': 'Play',
                'pause': 'Pause',
                'stop': 'Stop',
                'playpause': 'PlayPause'
            }
            command_name = command_map[action]

            # Send command using SendCommandDevice
            send_command = SendCommandDevice(
                device=str(transport_device_id),
                command=command_name,
                delay=0
            )
            await client.send_commands(send_command)
            return True

        run_async(send_transport_command())
        logger.info(f"Successfully sent transport {action} command")

        return jsonify({'success': True, 'action': action})

    except ValueError as e:
        logger.error(f"Transport control error: {e}")
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Error controlling transport: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/devices', methods=['GET'])
def get_devices():
    """Get list of all devices."""
    try:
        logger.debug("Fetching devices list")

        async def fetch_devices():
            client = await get_harmony_client()
            devices = client.config.get('device', [])
            return devices

        devices = run_async(fetch_devices())
        logger.debug(f"Found {len(devices)} devices")
        return jsonify({'devices': devices})

    except Exception as e:
        logger.error(f"Error fetching devices: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# Register blueprint with URL prefix
app.register_blueprint(bp, url_prefix=URL_PREFIX if URL_PREFIX else None)


if __name__ == '__main__':
    logger.info("Starting Harmony Hub Web Controller")
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() in ('true', '1', 'yes')
    app.run(host='0.0.0.0', port=PORT, debug=debug_mode)
