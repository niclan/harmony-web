"""Tests for the Harmony interface, independent of Flask."""
import asyncio
import socket
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, Mock, patch

import harmony


class TestHubDiscovery(unittest.TestCase):
    @patch('harmony.socket.socket')
    def test_discovery_filters_and_deduplicates(self, mock_socket):
        from harmony import discover_harmony_hub
        sock = mock_socket.return_value.__enter__.return_value
        valid = b'HTTP/1.1 200 OK\r\nst: urn:myharmony-com:device:harmony:1\r\n\r\n'
        sock.recvfrom.side_effect = [
            (b'garbage', ('192.168.1.2', 1900)),
            (b'HTTP/1.1 200 OK\r\nST: unrelated\r\n', ('192.168.1.3', 1900)),
            (valid, ('192.168.1.4', 1900)),
            (valid, ('192.168.1.4', 1900)), socket.timeout(),
        ]
        self.assertEqual(discover_harmony_hub(), '192.168.1.4')
        self.assertIn(b'M-SEARCH', sock.sendto.call_args.args[0])
        mock_socket.return_value.__exit__.assert_called_once()

    @patch('harmony.socket.socket')
    def test_no_hub(self, mock_socket):
        from harmony import discover_harmony_hub
        mock_socket.return_value.__enter__.return_value.recvfrom.side_effect = socket.timeout()
        with self.assertRaisesRegex(ConnectionError, 'No Harmony Hub'):
            discover_harmony_hub()

    @patch('harmony.socket.socket')
    def test_multiple_hubs_require_explicit_ip(self, mock_socket):
        from harmony import discover_harmony_hub
        valid = b'HTTP/1.1 200 OK\r\nST: urn:myharmony-com:device:harmony:1\r\n'
        mock_socket.return_value.__enter__.return_value.recvfrom.side_effect = [
            (valid, ('192.168.1.4', 1900)),
            (valid, ('192.168.1.5', 1900)), socket.timeout(),
        ]
        with self.assertRaisesRegex(ConnectionError, 'Multiple Harmony Hubs'):
            discover_harmony_hub()


class TestHubConnection(unittest.IsolatedAsyncioTestCase):
    @patch('harmony.harmony_client', None)
    @patch('harmony.HARMONY_IP', '192.168.1.10')
    @patch('harmony.discover_harmony_hub')
    @patch('harmony.HarmonyAPI')
    async def test_explicit_ip_skips_discovery(self, api, discover):
        from harmony import get_harmony_client
        api.return_value.connect = AsyncMock(return_value=True)
        self.assertIs(await get_harmony_client(), api.return_value)
        api.assert_called_once_with(ip_address='192.168.1.10')
        discover.assert_not_called()

    @patch('harmony.harmony_client', None)
    @patch('harmony.HARMONY_IP', '')
    @patch('harmony.discover_harmony_hub', return_value='192.168.1.20')
    @patch('harmony.HarmonyAPI')
    async def test_discovered_client_is_reused(self, api, discover):
        from harmony import get_harmony_client
        api.return_value.connect = AsyncMock(return_value=True)
        self.assertIs(await get_harmony_client(), api.return_value)
        self.assertIs(await get_harmony_client(), api.return_value)
        discover.assert_called_once()
        api.assert_called_once_with(ip_address='192.168.1.20')

    @patch('harmony.harmony_client', None)
    @patch('harmony.HARMONY_IP', '')
    @patch('harmony.discover_harmony_hub', side_effect=[ConnectionError('No hub'), '192.168.1.20'])
    @patch('harmony.HarmonyAPI')
    async def test_discovery_retries_after_failure(self, api, discover):
        from harmony import get_harmony_client
        api.return_value.connect = AsyncMock(return_value=True)
        with self.assertRaises(ConnectionError):
            await get_harmony_client()
        self.assertIs(await get_harmony_client(), api.return_value)
        self.assertEqual(discover.call_count, 2)


class TestAsyncInfrastructure(unittest.TestCase):
    """Test async infrastructure."""

    def test_concurrent_requests_share_one_background_loop(self):
        import harmony as module
        barrier = threading.Barrier(8)

        async def identify_loop():
            return id(asyncio.get_running_loop())

        def request():
            barrier.wait(timeout=5)
            return module.run_async(identify_loop())

        with patch.object(module, 'loop', None), \
             patch.object(module, 'loop_thread', None), \
             patch.object(module, 'loop_ready', threading.Event()), \
             patch.object(module, 'start_background_loop', wraps=module.start_background_loop) as start:
            try:
                with ThreadPoolExecutor(max_workers=8) as workers:
                    results = list(workers.map(lambda _: request(), range(8)))
                self.assertEqual(len(set(results)), 1)
                start.assert_called_once()
            finally:
                if module.loop is not None and module.loop.is_running():
                    module.loop.call_soon_threadsafe(module.loop.stop)
                    module.loop_thread.join(timeout=5)
                    module.loop.close()

    @patch('harmony.asyncio.run_coroutine_threadsafe')
    @patch('harmony.loop')
    def test_run_async_timeout(self, mock_loop, mock_run_coroutine):
        """Test run_async handles timeout."""
        # Setup mock
        mock_loop.is_running.return_value = True
        future = Mock()
        future.result.side_effect = asyncio.TimeoutError("Operation timed out")
        mock_run_coroutine.return_value = future

        async def dummy_coro():
            return "test"

        # This test documents expected behavior
        # In practice, timeout would raise TimeoutError
        with self.assertRaises(asyncio.TimeoutError):
            from harmony import run_async
            coro = dummy_coro()
            try:
                run_async(coro)
            finally:
                coro.close()


class TestHarmonyOperations(unittest.TestCase):
    def setUp(self):
        self.config = {
            'activity': [{
                'id': '1', 'label': 'Music', 'VolumeActivityRole': 'receiver',
                'roles': {'PassThroughActivityRole': 'player', 'PlayMediaActivityRole': 'receiver'},
            }, {'id': '-1', 'label': 'PowerOff'}],
            'device': [{'id': 'player', 'controlGroup': [{'function': [
                {'action': '{"command": "NextTrack"}'},
            ]}]}],
        }
        self.client = Mock(current_activity=('1', 'Music'), config=self.config)
        self.client.start_activity = AsyncMock(return_value=(True, '1'))
        self.client.power_off = AsyncMock(return_value=True)
        self.client.send_commands = AsyncMock(return_value=[])
        get_client = self.enterContext(patch('harmony.get_harmony_client', new_callable=AsyncMock))
        get_client.return_value = self.client
        self.enterContext(patch('harmony.run_async', side_effect=asyncio.run))

    def test_reads_and_activity_copies(self):
        activities = harmony.get_activities()
        self.assertEqual(activities, self.config['activity'])
        activities[0]['cachedImageUrl'] = '/static/image.png'
        self.assertNotIn('cachedImageUrl', self.config['activity'][0])
        self.assertEqual(harmony.get_current_activity(), ('1', 'Music'))
        self.assertEqual(harmony.get_devices(), self.config['device'])

    def test_start_validates_config_and_power_off_delegates(self):
        self.assertEqual(harmony.start_activity('1'), (True, '1'))
        self.client.start_activity.assert_awaited_once_with('1')
        with self.assertRaisesRegex(ValueError, 'Invalid activity_id'):
            harmony.start_activity('999')
        self.client.start_activity.assert_awaited_once()
        self.assertTrue(harmony.power_off())
        self.client.power_off.assert_awaited_once()

    def test_volume_commands_use_volume_role(self):
        for action, command_name in [('up', 'VolumeUp'), ('down', 'VolumeDown'), ('mute', 'Mute')]:
            with self.subTest(action=action):
                harmony.volume_control(action)
                command = self.client.send_commands.await_args.args[0]
                self.assertEqual((command.device, command.command), ('receiver', command_name))

    def test_transport_priority_fallback_and_next_capability(self):
        self.assertEqual(harmony.get_transport_controls(), {
            'available': True, 'controls': ['play', 'pause', 'stop', 'next'],
        })
        for action, command_name in [('play', 'Play'), ('pause', 'Pause'), ('stop', 'Stop'),
                                     ('playpause', 'PlayPause'), ('next', 'NextTrack')]:
            harmony.transport_control(action)
            command = self.client.send_commands.await_args.args[0]
            self.assertEqual((command.device, command.command), ('player', command_name))
        del self.config['activity'][0]['roles']['PassThroughActivityRole']
        harmony.transport_control('play')
        self.assertEqual(self.client.send_commands.await_args.args[0].device, 'receiver')
        self.assertNotIn('next', harmony.get_transport_controls()['controls'])
        count = self.client.send_commands.await_count
        with self.assertRaisesRegex(ValueError, 'Next track is not available'):
            harmony.transport_control('next')
        self.assertEqual(self.client.send_commands.await_count, count)

    def test_powered_off_and_missing_activity_send_no_commands(self):
        for activity_id, message in [('-1', 'No activity is running'), ('999', 'Current activity not found')]:
            self.client.current_activity = (activity_id, 'Unknown')
            self.assertEqual(harmony.get_transport_controls(), {'available': False, 'controls': []})
            for operation, action in [(harmony.volume_control, 'up'), (harmony.transport_control, 'play')]:
                with self.subTest(activity_id=activity_id, operation=operation.__name__):
                    with self.assertRaisesRegex(ValueError, message):
                        operation(action)
        self.client.send_commands.assert_not_awaited()

    def test_missing_roles_send_no_commands(self):
        del self.config['activity'][0]['VolumeActivityRole']
        self.config['activity'][0]['roles'] = {}
        with self.assertRaisesRegex(ValueError, 'No volume device configured'):
            harmony.volume_control('up')
        with self.assertRaisesRegex(ValueError, 'No transport control device configured'):
            harmony.transport_control('play')
        self.assertFalse(harmony.get_transport_controls()['available'])
        self.client.send_commands.assert_not_awaited()
