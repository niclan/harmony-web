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
    Codex
    Claude (Anthropic AI Assistant)
"""

import os
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, Blueprint, render_template, jsonify, request
import requests

import harmony

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
URL_PREFIX = os.environ.get('URL_PREFIX', '').rstrip('/')
PORT = int(os.environ.get('PORT', '5000'))
logger.info(f"Using Harmony Hub IP: {harmony.HARMONY_IP}" if harmony.HARMONY_IP else "Harmony Hub automatic discovery enabled")
if URL_PREFIX:
    logger.info(f"Using URL prefix: {URL_PREFIX}")
logger.info(f"Listening on port: {PORT}")

# Allowed domains for activity image downloads (Logitech/Harmony CDN only)
ALLOWED_IMAGE_DOMAINS = {
    'rcbu-prod-ssl-amr.myharmony.com',   # Harmony Hub CDN (Americas)
    'home.myharmony.com',                # Legacy Harmony domain
    'svcs.myharmony.com',                # Harmony services domain
}


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

def cache_activity_image(activity_id, base_uri, image_key):
    """
    Download and cache an activity image locally.
    Returns the local path relative to static directory, or None if download fails.
    Only downloads from whitelisted Logitech/Harmony domains for security.
    Validates image file type and size for security.
    """
    if not image_key:
        return None

    try:
        full_url = base_uri + image_key if base_uri else ''
        parsed_url = urlparse(full_url)
        if (parsed_url.scheme != 'https' or
                parsed_url.netloc.lower() not in ALLOWED_IMAGE_DOMAINS):
            logger.warning("Rejected untrusted activity image URL")
            return None
        if not isinstance(activity_id, str) or not activity_id.isascii() or not activity_id.isdigit():
            return None
        file_extension = Path(parsed_url.path).suffix.lower() or '.png'
        if file_extension not in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}:
            return None
    except (TypeError, ValueError):
        return None

    cache_dir = Path('static/images/activities')
    local_filename = f"{activity_id}{file_extension}"
    local_path = cache_dir / local_filename
    temp_path = None
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        if local_path.exists():
            return f'/static/images/activities/{local_filename}'

        response = requests.get(full_url, timeout=10, stream=True, allow_redirects=False)
        try:
            # Reject redirects rather than fetching an unchecked destination.
            if 300 <= response.status_code < 400:
                return None
            response.raise_for_status()
            content_length = 0
            with tempfile.NamedTemporaryFile(dir=cache_dir, suffix='.tmp', delete=False) as f:
                temp_path = Path(f.name)
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    content_length += len(chunk)
                    if content_length > 5 * 1024 * 1024:
                        logger.warning("Activity image exceeds size limit")
                        return None
                    f.write(chunk)
        finally:
            response.close()

        image_type = detect_image_type(temp_path)
        if image_type not in {'png', 'jpeg', 'gif', 'webp', 'bmp'}:
            logger.warning("Invalid activity image type")
            return None
        temp_path.replace(local_path)
        logger.info("Cached activity image: %s (size: %s bytes)", local_filename, content_length)
        return f'/static/images/activities/{local_filename}'
    except Exception:
        logger.warning("Failed to cache activity image", exc_info=True)
        return None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


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

        activities = harmony.get_activities()

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

        current = harmony.get_current_activity()
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

        harmony.start_activity(activity_id)
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

        harmony.power_off()
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

        harmony.volume_control(action)
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

        result = harmony.get_transport_controls()
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

        harmony.transport_control(action)
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

        devices = harmony.get_devices()
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
