#!/usr/bin/env python3
# Copyright 2025-2026 Schibsted Products and Technology
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Logitech Harmony Hub Web Controller Flask web application providing
web interface and REST API for controlling Harmony Hub activities.

Authors:
    Nicolai Langfeldt
    Claude (Anthropic AI Assistant)
"""

import os
import asyncio
import json
import logging
import threading
import socket
import time
from ipaddress import IPv4Address
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, Blueprint, render_template, jsonify, request
from aioharmony.harmonyapi import HarmonyAPI, SendCommandDevice
import requests

# Configure logging based on environment
# Only enable DEBUG logging in development environment
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'production').lower()
LOG_LEVEL = logging.DEBUG if ENVIRONMENT == 'dev' else logging.INFO

logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Set aioharmony logging level to match application
logging.getLogger('aioharmony').setLevel(LOG_LEVEL)

logger.info(f"Starting application in {ENVIRONMENT} mode with log level {logging.getLevelName(LOG_LEVEL)}")

app = Flask(__name__)

# Configuration
HARMONY_IP = os.environ.get('HARMONY_IP', '').strip()
URL_PREFIX = os.environ.get('URL_PREFIX', '').rstrip('/')
PORT = int(os.environ.get('PORT', '5000'))
logger.info(f"Using Harmony Hub IP: {HARMONY_IP}" if HARMONY_IP else "Harmony Hub automatic discovery enabled")
if URL_PREFIX:
    logger.info(f"Using URL prefix: {URL_PREFIX}")
logger.info(f"Listening on port: {PORT}")

# Allowed domains for activity image downloads (Logitech/Harmony CDN only)
ALLOWED_IMAGE_DOMAINS = {
    'rcbu-prod-ssl-amr.myharmony.com',  # Harmony Hub CDN (Americas)
    'home.myharmony.com',                # Legacy Harmony domain
    'svcs.myharmony.com',                # Harmony services domain
}


def get_device_command(config, device_id, command_names):
    """Return the configured command name supported by a device, if any."""
    for device in config.get('device', []):
        if str(device.get('id')) != str(device_id):
            continue
        for control_group in device.get('controlGroup', []):
            for function in control_group.get('function', []):
                action = function.get('action')
                if isinstance(action, str):
                    try:
                        action = json.loads(action)
                    except json.JSONDecodeError:
                        continue
                command = action.get('command') if isinstance(action, dict) else None
                if command in command_names:
                    return command
        return None
    return None


def detect_image_type(file_path):
    """
    Detect image type by reading magic bytes (file signature).
    Returns image type string or None if not a valid image.
    Replaces deprecated imghdr module (removed in Python 3.13).
    """
    try:
        with open(file_path, 'rb') as f:
            header = f.read(32)  # Read first 32 bytes

        # Check magic bytes for common image formats
        if header.startswith(b'\x89PNG\r\n\x1a\n'):
            return 'png'
        elif header.startswith(b'\xff\xd8\xff'):
            return 'jpeg'
        elif header.startswith(b'GIF87a') or header.startswith(b'GIF89a'):
            return 'gif'
        elif header.startswith(b'RIFF') and header[8:12] == b'WEBP':
            return 'webp'
        elif header.startswith(b'BM'):
            return 'bmp'
        else:
            return None
    except Exception as e:
        logger.warning(f"Failed to detect image type for {file_path}: {e}")
        return None

# Global harmony client and event loop
harmony_client = None
loop = None
loop_thread = None
loop_ready = threading.Event()
loop_start_lock = threading.Lock()
client_lock = asyncio.Lock()


def discover_harmony_hub():
    """Find a single Harmony Hub via SSDP without fetching advertised URLs."""
    service = 'urn:myharmony-com:device:harmony:1'
    query = (
        'M-SEARCH * HTTP/1.1\r\n'
        'HOST: 239.255.255.250:1900\r\n'
        'MAN: "ssdp:discover"\r\n'
        'MX: 2\r\n'
        f'ST: {service}\r\n\r\n'
    ).encode('ascii')
    hubs = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.sendto(query, ('239.255.255.250', 1900))
        deadline = time.monotonic() + 5
        while (remaining := deadline - time.monotonic()) > 0:
            sock.settimeout(remaining)
            try:
                packet, address = sock.recvfrom(8192)
            except socket.timeout:
                break
            lines = packet.decode('utf-8', errors='replace').splitlines()
            if not lines or lines[0].strip().upper() != 'HTTP/1.1 200 OK':
                continue
            headers = dict(
                (key.strip().lower(), value.strip())
                for line in lines[1:] if ':' in line
                for key, value in [line.split(':', 1)]
            )
            if headers.get('st') == service:
                ip = IPv4Address(address[0])
                if not (ip.is_unspecified or ip.is_multicast or ip.is_loopback):
                    hubs.add(str(ip))
    if not hubs:
        raise ConnectionError('No Harmony Hub discovered; check multicast access or set HARMONY_IP')
    if len(hubs) > 1:
        raise ConnectionError(f'Multiple Harmony Hubs discovered ({", ".join(sorted(hubs))}); set HARMONY_IP')
    return hubs.pop()


def start_background_loop():
    """Start the asyncio event loop in a background thread."""
    global loop
    background_loop = asyncio.new_event_loop()
    loop = background_loop
    asyncio.set_event_loop(background_loop)
    logger.info("Starting background event loop")
    background_loop.call_soon(loop_ready.set)
    background_loop.run_forever()


def run_async(coro):
    """
    Run an async coroutine in the background event loop.
    Returns the result synchronously.
    """
    global loop, loop_thread

    with loop_start_lock:
        if loop is None or not loop.is_running():
            if loop_thread is None or not loop_thread.is_alive():
                loop_ready.clear()
                loop_thread = threading.Thread(target=start_background_loop, daemon=True)
                loop_thread.start()
            if not loop_ready.wait(timeout=5):
                coro.close()
                raise RuntimeError("Background event loop failed to start")

    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=60)


async def get_harmony_client():
    """
    Get or create the global Harmony client.
    Reuses existing connection unless creation is needed.
    """
    global harmony_client

    async with client_lock:
        if harmony_client is None:
            ip_address = HARMONY_IP or await asyncio.to_thread(discover_harmony_hub)
            logger.info("Connecting to Harmony Hub at %s", ip_address)
            client = HarmonyAPI(ip_address=ip_address)
            try:
                if not await client.connect():
                    raise ConnectionError("Could not connect to Harmony Hub")
                harmony_client = client
                logger.info("Successfully connected to Harmony Hub")
            except Exception:
                logger.exception("Error connecting to Harmony Hub at %s", ip_address)
                raise

    return harmony_client


def cache_activity_image(activity_id, base_uri, image_key):
    """
    Download and cache an activity image locally.
    Returns the local path relative to static directory, or None if download fails.
    Only downloads from whitelisted Logitech/Harmony domains for security.
    Validates image file type and size for security.
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

        # Validate file size (max 5MB)
        MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB
        content_length = len(response.content)
        if content_length > MAX_IMAGE_SIZE:
            logger.warning(
                f"Image too large for activity {activity_id}: {content_length} bytes "
                f"(max {MAX_IMAGE_SIZE} bytes)"
            )
            return None

        # Save to temporary location first for validation
        temp_path = local_path.with_suffix('.tmp')
        with open(temp_path, 'wb') as f:
            f.write(response.content)

        # Validate image file type by magic bytes
        image_type = detect_image_type(temp_path)
        if image_type not in ['png', 'jpeg', 'gif', 'webp', 'bmp']:
            logger.warning(
                f"Invalid image type for activity {activity_id}: {image_type}. "
                f"Only PNG, JPEG, GIF, WebP, and BMP are allowed."
            )
            temp_path.unlink()  # Delete invalid file
            return None

        # Move validated file to final location
        temp_path.rename(local_path)

        logger.info(f"Cached activity image: {local_filename} (type: {image_type}, size: {content_length} bytes)")
        return f'/static/images/activities/{local_filename}'

    except Exception as e:
        logger.warning(f"Failed to cache activity image from {full_url}: {e}")
        # Clean up any temporary files
        temp_path = local_path.with_suffix('.tmp')
        if temp_path.exists():
            temp_path.unlink()
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
        return jsonify({'error': 'Failed to fetch activities'}), 500


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
        return jsonify({'error': 'Failed to fetch current activity'}), 500


@bp.route('/api/start_activity', methods=['POST'])
def start_activity():
    """Start a specific activity by ID."""
    try:
        data = request.get_json()
        if not data or 'activity_id' not in data:
            return jsonify({'error': 'activity_id required'}), 400

        activity_id = data['activity_id']

        # Validate activity_id is a string
        if not isinstance(activity_id, str):
            return jsonify({'error': 'activity_id must be a string'}), 400

        # Validate activity_id format (digits or -1 for PowerOff)
        if not (activity_id.isdigit() or activity_id == '-1'):
            return jsonify({'error': 'activity_id must be a numeric string or "-1"'}), 400

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
        return jsonify({'error': 'Failed to start activity'}), 500


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
        return jsonify({'error': 'Failed to power off'}), 500


@bp.route('/api/volume', methods=['POST'])
def volume_control():
    """Control volume (up/down/mute)."""
    try:
        data = request.get_json()
        if not data or 'action' not in data:
            return jsonify({'error': 'action required (up/down/mute)'}), 400

        action = data['action']

        # Validate action is a string
        if not isinstance(action, str):
            return jsonify({'error': 'action must be a string'}), 400

        # Validate action value against whitelist
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
        return jsonify({'error': 'Failed to control volume'}), 500


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
                controls = ['play', 'pause', 'stop']
                if get_device_command(client.config, transport_device_id, ('Next', 'NextTrack')):
                    controls.append('next')
                return {
                    'available': True,
                    'controls': controls
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
        return jsonify({'error': 'Failed to check transport controls'}), 500


@bp.route('/api/transport', methods=['POST'])
def transport_control():
    """Control media transport."""
    try:
        data = request.get_json()
        if not data or 'action' not in data:
            return jsonify({'error': 'action required (play/pause/stop/next)'}), 400

        action = data['action']

        # Validate action is a string
        if not isinstance(action, str):
            return jsonify({'error': 'action must be a string'}), 400

        # Normalize to lowercase
        action = action.lower()

        # Validate action value against whitelist
        if action not in ['play', 'pause', 'stop', 'playpause', 'next']:
            return jsonify({'error': 'action must be play, pause, stop, playpause, or next'}), 400

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

            next_command = get_device_command(client.config, transport_device_id, ('Next', 'NextTrack'))
            if action == 'next' and not next_command:
                raise ValueError("Next track is not available for this activity")

            logger.debug(f"Found transport device ID: {transport_device_id} for activity {current_activity_name}")

            # Map action to standard command names
            command_map = {
                'play': 'Play',
                'pause': 'Pause',
                'stop': 'Stop',
                'playpause': 'PlayPause',
                'next': next_command
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
        return jsonify({'error': 'Failed to control transport'}), 500


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
        return jsonify({'error': 'Failed to fetch devices'}), 500


# Register blueprint with URL prefix
app.register_blueprint(bp, url_prefix=URL_PREFIX if URL_PREFIX else None)


if __name__ == '__main__':
    logger.info("Starting Harmony Hub Web Controller")
    # Only enable Flask debug mode in development environment
    # Never enable in production for security
    debug_mode = ENVIRONMENT == 'dev'
    app.run(host='0.0.0.0', port=PORT, debug=debug_mode)
