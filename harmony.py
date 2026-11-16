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

"""Harmony Hub control without Flask or HTTP dependencies.

The public control functions are synchronous. They share one client and run
Hub operations on a persistent background asyncio event loop.
"""

import asyncio
import json
import logging
import os
import socket
import threading
import time
from ipaddress import IPv4Address

from aioharmony.harmonyapi import HarmonyAPI, SendCommandDevice

logger = logging.getLogger(__name__)
HARMONY_IP = os.environ.get('HARMONY_IP', '').strip()


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


def get_activities():
    """Get list of all available Harmony activities."""

    async def fetch_activities():
        client = await get_harmony_client()
        activities = client.config.get('activity', [])
        return [activity.copy() for activity in activities]

    return run_async(fetch_activities())


def get_current_activity():
    """Get the current activity."""

    async def fetch_current():
        client = await get_harmony_client()
        current = client.current_activity
        return current

    return run_async(fetch_current())


def start_activity(activity_id):
    """Start a specific activity by ID."""

    async def start():
        client = await get_harmony_client()

        # Validate activity_id exists in config
        activities = client.config.get('activity', [])
        valid_ids = [str(a['id']) for a in activities]

        if str(activity_id) not in valid_ids:
            raise ValueError(f"Invalid activity_id: {activity_id}")

        result = await client.start_activity(activity_id)
        return result

    return run_async(start())


def power_off():
    """Power off all activities."""

    async def power_off_async():
        client = await get_harmony_client()
        result = await client.power_off()
        return result

    return run_async(power_off_async())


def volume_control(action):
    """Control volume (up/down/mute)."""

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

    return run_async(send_volume_command())


def get_transport_controls():
    """Get available transport controls for current activity."""

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

    return run_async(check_transport())


def transport_control(action):
    """Control media transport."""

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

    return run_async(send_transport_command())


def get_devices():
    """Get list of all devices."""

    async def fetch_devices():
        client = await get_harmony_client()
        devices = client.config.get('device', [])
        return devices

    return run_async(fetch_devices())
