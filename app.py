#!/usr/bin/env python3
"""
Logitech Harmony Hub Web Controller
Flask web application providing web interface and REST API for controlling Harmony Hub activities.
"""

import os
import asyncio
import logging
import threading
from flask import Flask, render_template, jsonify, request
from aioharmony.harmonyapi import HarmonyAPI, SendCommandDevice

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
logger.info(f"Using Harmony Hub IP: {HARMONY_IP}")

# Global harmony client and event loop
harmony_client = None
loop = None
loop_thread = None


def start_background_loop():
    """Start the asyncio event loop in a background thread."""
    global loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    logger.info("Starting background event loop")
    loop.run_forever()


def run_async(coro):
    """
    Run an async coroutine in the background event loop.
    Returns the result synchronously.
    """
    global loop, loop_thread

    if loop is None or not loop.is_running():
        # Start background loop thread if not running
        loop_thread = threading.Thread(target=start_background_loop, daemon=True)
        loop_thread.start()
        # Give the loop a moment to start
        import time
        time.sleep(0.1)

    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=30)


async def get_harmony_client():
    """Get or create the global Harmony client."""
    global harmony_client

    if harmony_client is None:
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


@app.route('/')
def index():
    """Serve the main web interface."""
    return render_template('index.html')


@app.route('/api/activities', methods=['GET'])
def get_activities():
    """Get list of all available Harmony activities."""
    try:
        logger.debug("Fetching activities list")

        async def fetch_activities():
            client = await get_harmony_client()
            activities = client.config.get('activity', [])
            return activities

        activities = run_async(fetch_activities())
        logger.debug(f"Found {len(activities)} activities")
        return jsonify({'activities': activities})

    except Exception as e:
        logger.error(f"Error fetching activities: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/current_activity', methods=['GET'])
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


@app.route('/api/start_activity', methods=['POST'])
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
            result = await client.start_activity(activity_id)
            return result

        result = run_async(start())
        logger.info(f"Successfully started activity {activity_id}")

        return jsonify({'success': True, 'activity_id': activity_id})

    except Exception as e:
        logger.error(f"Error starting activity: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/power_off', methods=['POST'])
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


@app.route('/api/volume', methods=['POST'])
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

            # Find volume device from config
            volume_device = None
            volume_device_id = None

            # Search in controlGroups for volume functions
            control_groups = client.config.get('controlGroup', [])
            for group in control_groups:
                for func in group.get('function', []):
                    func_name = func.get('name', '').lower()
                    if 'volume' in func_name:
                        volume_device_id = func.get('controlId')
                        if volume_device_id:
                            logger.debug(f"Found volume control device ID: {volume_device_id}")
                            break
                if volume_device_id:
                    break

            if not volume_device_id:
                logger.warning("No volume device found in configuration")
                raise ValueError("No volume device found")

            # Map action to command
            command_map = {
                'up': 'VolumeUp',
                'down': 'VolumeDown',
                'mute': 'Mute'
            }
            command = command_map[action]

            # Send command
            await client.send_command(volume_device_id, command)
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


@app.route('/api/devices', methods=['GET'])
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


if __name__ == '__main__':
    logger.info("Starting Harmony Hub Web Controller")
    app.run(host='0.0.0.0', port=5000, debug=True)
