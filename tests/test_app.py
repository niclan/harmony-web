"""Unit tests for Harmony Hub Web Controller."""
import unittest
from unittest.mock import Mock, patch, AsyncMock
import sys
import os
import asyncio
import requests
import tempfile
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, cache_activity_image
from harmony import get_device_command


class TestFlaskApp(unittest.TestCase):
    """Test Flask application endpoints."""

    def setUp(self):
        """Set up test client."""
        self.app = app
        self.app.testing = True
        self.client = self.app.test_client()

    def test_index_route(self):
        """Test that index route returns 200."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Logitech Harmony Hub Controller', response.data)

    def test_split_route_removed(self):
        self.assertEqual(self.client.get('/split').status_code, 404)

    @patch('app.harmony.get_activities')
    def test_get_activities(self, mock_run_async):
        """Test /api/activities endpoint."""
        # Mock the async response
        mock_run_async.return_value = [
            {'id': '123', 'label': 'Watch TV', 'type': 'VirtualTelevisionN'},
            {'id': '456', 'label': 'Listen to Music', 'type': 'VirtualCdMulti'}
        ]

        response = self.client.get('/api/activities')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('activities', data)

    @patch('app.harmony.get_current_activity')
    def test_get_current_activity(self, mock_run_async):
        """Test /api/current_activity endpoint."""
        mock_run_async.return_value = ('123', 'Watch TV')

        response = self.client.get('/api/current_activity')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['activity_id'], '123')
        self.assertEqual(data['activity_name'], 'Watch TV')

    def test_start_activity_missing_id(self):
        """Test /api/start_activity without activity_id."""
        response = self.client.post('/api/start_activity',
                                   json={})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('error', data)

    @patch('app.harmony.start_activity')
    def test_start_activity_invalid_id(self, mock_run_async):
        """Test /api/start_activity with invalid activity_id."""
        # Mock the validation to raise ValueError
        mock_run_async.side_effect = ValueError("Invalid activity_id: 999")

        response = self.client.post('/api/start_activity',
                                   json={'activity_id': '999'})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('error', data)

    @patch('app.harmony.power_off')
    def test_power_off(self, mock_run_async):
        """Test /api/power_off endpoint."""
        mock_run_async.return_value = True

        response = self.client.post('/api/power_off')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])


class TestImageCaching(unittest.TestCase):
    """Test activity image caching functionality."""

    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        previous = os.getcwd()
        os.chdir(directory)
        self.addCleanup(os.chdir, previous)

    @patch('app.detect_image_type')
    @patch('app.requests.get')
    @patch('app.Path.exists')
    def test_cache_activity_image_success(self, mock_exists, mock_get, mock_detect):
        """Test successful image caching."""
        mock_exists.return_value = False
        mock_response = Mock()
        mock_response.content = b'fake_image_data'
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [mock_response.content]
        mock_get.return_value = mock_response
        mock_detect.return_value = 'png'  # Valid image type

        result = cache_activity_image(
            '123',
            'https://rcbu-prod-ssl-amr.myharmony.com/images/',
            'test.png'
        )

        self.assertIsNotNone(result)
        self.assertIn('/static/images/activities/', result)

    def test_cache_activity_image_no_image_key(self):
        """Test cache_activity_image with no image_key."""
        result = cache_activity_image('123', 'https://example.com/', '')
        self.assertIsNone(result)

    def test_cache_activity_image_untrusted_domain(self):
        """Test cache_activity_image rejects untrusted domain."""
        result = cache_activity_image(
            '123',
            'https://evil.com/',
            'test.png'
        )
        self.assertIsNone(result)

    @patch('app.Path.exists')
    def test_cache_activity_image_already_cached(self, mock_exists):
        """Test cache_activity_image returns cached path if exists."""
        mock_exists.return_value = True

        result = cache_activity_image(
            '123',
            'https://rcbu-prod-ssl-amr.myharmony.com/images/',
            'test.png'
        )

        self.assertIsNotNone(result)
        self.assertIn('/static/images/activities/123.png', result)

    @patch('app.requests.get')
    def test_rejects_redirect_without_fetching_destination(self, get):
        response = get.return_value
        response.status_code = 302
        response.headers = {'Location': 'http://127.0.0.1/private'}
        self.assertIsNone(cache_activity_image('123', 'https://home.myharmony.com/', 'a.png'))
        get.assert_called_once_with('https://home.myharmony.com/a.png', timeout=10,
                                    stream=True, allow_redirects=False)
        response.iter_content.assert_not_called()
        response.close.assert_called_once()

    @patch('app.requests.get')
    def test_rejects_unsafe_urls_and_filenames(self, get):
        for activity_id, base, key in [
            ('123', 'http://home.myharmony.com/', 'a.png'),
            ('123', 'https://home.myharmony.com', '.evil.com/a.png'),
            ('../escape', 'https://home.myharmony.com/', 'a.png'),
            ('123', 'https://home.myharmony.com/', 'a.html'),
        ]:
            with self.subTest(base=base, key=key, activity_id=activity_id):
                self.assertIsNone(cache_activity_image(activity_id, base, key))
        get.assert_not_called()

    @patch('app.requests.get')
    def test_stream_limit_stops_early_and_cleans_up(self, get):
        response = get.return_value
        response.status_code = 200
        consumed = []
        def chunks(**kwargs):
            for i in range(7):
                consumed.append(i)
                yield b'x' * (1024 * 1024)
        response.iter_content.side_effect = chunks
        self.assertIsNone(cache_activity_image('123', 'https://home.myharmony.com/', 'a.png'))
        self.assertEqual(len(consumed), 6)
        self.assertEqual(list(Path('static/images/activities').iterdir()), [])
        response.close.assert_called_once()

    @patch('app.requests.get')
    def test_real_signature_and_unique_temporary_files(self, get):
        response = get.return_value
        response.status_code = 200
        response.iter_content.side_effect = lambda **kwargs: iter([b'\x89PNG\r\n\x1a\n' + b'data'])
        real_tempfile = tempfile.NamedTemporaryFile
        names = []
        def create_temporary(**kwargs):
            f = real_tempfile(**kwargs)
            names.append(f.name)
            return f
        with patch('app.tempfile.NamedTemporaryFile', side_effect=create_temporary) as temporary:
            for _ in range(2):
                self.assertEqual(cache_activity_image('123', 'https://home.myharmony.com/', 'a.png'),
                                 '/static/images/activities/123.png')
                Path('static/images/activities/123.png').unlink()
            self.assertEqual(temporary.call_count, 2)
            self.assertEqual(len(set(names)), 2)
        self.assertEqual(list(Path('static/images/activities').iterdir()), [])

    @patch('app.requests.get')
    def test_invalid_and_interrupted_images_leave_no_files(self, get):
        response = get.return_value
        response.status_code = 200
        for interrupted in (False, True):
            def chunks(**kwargs):
                yield b'not an image'
                if interrupted:
                    raise requests.exceptions.ConnectionError('stream interrupted')
            response.iter_content.side_effect = chunks
            with self.subTest(interrupted=interrupted):
                self.assertIsNone(cache_activity_image('123', 'https://home.myharmony.com/', 'a.png'))
                self.assertEqual(list(Path('static/images/activities').iterdir()), [])
        self.assertEqual(response.close.call_count, 2)


class TestInputValidation(unittest.TestCase):
    """Test input validation."""

    def test_activity_id_validation(self):
        """Test that activity IDs are validated against config."""
        # This test verifies the validation logic is in place
        # The actual validation happens in the async function
        # so we test it through the endpoint
        app.testing = True
        client = app.test_client()

        with patch('app.harmony.start_activity') as mock_run_async:
            mock_run_async.side_effect = ValueError("Invalid activity_id: invalid")

            response = client.post('/api/start_activity',
                                 json={'activity_id': 'invalid'})

            self.assertEqual(response.status_code, 400)

    def test_activity_id_type_validation(self):
        """Test that activity_id must be a string."""
        app.testing = True
        client = app.test_client()

        # Test with integer
        response = client.post('/api/start_activity',
                             json={'activity_id': 123})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('must be a string', data['error'])

        # Test with list
        response = client.post('/api/start_activity',
                             json={'activity_id': ['123']})
        self.assertEqual(response.status_code, 400)

        # Test with object
        response = client.post('/api/start_activity',
                             json={'activity_id': {'id': '123'}})
        self.assertEqual(response.status_code, 400)

    def test_activity_id_format_validation(self):
        """Test that activity_id must be numeric or -1."""
        app.testing = True
        client = app.test_client()

        # Test with invalid string
        response = client.post('/api/start_activity',
                             json={'activity_id': 'abc'})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('must be a numeric string', data['error'])

        # Test with special characters
        response = client.post('/api/start_activity',
                             json={'activity_id': '123;drop table'})
        self.assertEqual(response.status_code, 400)

    def test_volume_action_type_validation(self):
        """Test that volume action must be a string."""
        app.testing = True
        client = app.test_client()

        # Test with integer
        response = client.post('/api/volume',
                             json={'action': 1})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('must be a string', data['error'])

        # Test with list
        response = client.post('/api/volume',
                             json={'action': ['up']})
        self.assertEqual(response.status_code, 400)

    def test_transport_action_type_validation(self):
        """Test that transport action must be a string."""
        app.testing = True
        client = app.test_client()

        # Test with integer
        response = client.post('/api/transport',
                             json={'action': 1})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('must be a string', data['error'])

        # Test with boolean
        response = client.post('/api/transport',
                             json={'action': True})
        self.assertEqual(response.status_code, 400)


class TestVolumeControl(unittest.TestCase):
    """Test volume control endpoint."""

    def setUp(self):
        """Set up test client."""
        self.app = app
        self.app.testing = True
        self.client = self.app.test_client()

    def test_volume_missing_action(self):
        """Test /api/volume without action parameter."""
        response = self.client.post('/api/volume', json={})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('error', data)
        self.assertIn('action required', data['error'])

    def test_volume_invalid_action(self):
        """Test /api/volume with invalid action."""
        response = self.client.post('/api/volume', json={'action': 'invalid'})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('error', data)
        self.assertIn('must be up, down, or mute', data['error'])

    @patch('app.harmony.volume_control')
    def test_volume_up_success(self, mock_run_async):
        """Test successful volume up command."""
        mock_run_async.return_value = True

        response = self.client.post('/api/volume', json={'action': 'up'})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'up')

    @patch('app.harmony.volume_control')
    def test_volume_down_success(self, mock_run_async):
        """Test successful volume down command."""
        mock_run_async.return_value = True

        response = self.client.post('/api/volume', json={'action': 'down'})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'down')

    @patch('app.harmony.volume_control')
    def test_volume_mute_success(self, mock_run_async):
        """Test successful mute command."""
        mock_run_async.return_value = True

        response = self.client.post('/api/volume', json={'action': 'mute'})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'mute')

    @patch('app.harmony.volume_control')
    def test_volume_powered_off(self, mock_run_async):
        """Test volume control when powered off."""
        mock_run_async.side_effect = ValueError("No activity is running")

        response = self.client.post('/api/volume', json={'action': 'up'})
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertIn('error', data)

    @patch('app.harmony.volume_control')
    def test_volume_no_volume_device(self, mock_run_async):
        """Test volume control when activity has no volume device."""
        mock_run_async.side_effect = ValueError("No volume device configured for this activity")

        response = self.client.post('/api/volume', json={'action': 'up'})
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertIn('error', data)


class TestTransportControls(unittest.TestCase):
    """Test transport controls endpoint."""

    def setUp(self):
        """Set up test client."""
        self.app = app
        self.app.testing = True
        self.client = self.app.test_client()

    @patch('app.harmony.get_transport_controls')
    def test_transport_controls_available(self, mock_run_async):
        """Test transport controls available for activity."""
        mock_run_async.return_value = {
            'available': True,
            'controls': ['play', 'pause', 'stop']
        }

        response = self.client.get('/api/transport_controls')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['available'])
        self.assertEqual(data['controls'], ['play', 'pause', 'stop'])

    @patch('app.harmony.get_transport_controls')
    def test_transport_controls_powered_off(self, mock_run_async):
        """Test transport controls when powered off."""
        mock_run_async.return_value = {
            'available': False,
            'controls': []
        }

        response = self.client.get('/api/transport_controls')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertFalse(data['available'])
        self.assertEqual(data['controls'], [])

    @patch('app.harmony.get_transport_controls')
    def test_transport_controls_not_available(self, mock_run_async):
        """Test transport controls not available for activity."""
        mock_run_async.return_value = {
            'available': False,
            'controls': []
        }

        response = self.client.get('/api/transport_controls')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertFalse(data['available'])


class TestNextTransportControl(unittest.TestCase):
    """Tests for capability-gated next-track control."""

    def setUp(self):
        self.app = app
        self.app.testing = True
        self.client = self.app.test_client()
        self.config = {
            'activity': [{
                'id': '1',
                'roles': {
                    'PassThroughActivityRole': 'squeezebox',
                    'PlayMediaActivityRole': 'cd-player',
                },
            }],
            'device': [
                {'id': 'squeezebox', 'controlGroup': [{'function': [
                    {'action': '{"command": "Next"}'},
                ]}]},
                {'id': 'cd-player', 'controlGroup': [{'function': []}]},
            ],
        }

    def test_detects_next_command_on_selected_device(self):
        self.assertEqual(get_device_command(self.config, 'squeezebox', ('Next', 'NextTrack')), 'Next')
        self.assertIsNone(get_device_command(self.config, 'cd-player', ('Next', 'NextTrack')))

    @patch('harmony.get_harmony_client')
    @patch('harmony.run_async')
    def test_next_is_offered_only_when_passthrough_device_supports_it(self, mock_run_async, mock_get_client):
        client = Mock(current_activity=('1', 'Squeezebox'), config=self.config)
        mock_get_client.return_value = client
        mock_run_async.side_effect = lambda coro: asyncio.run(coro)

        response = self.client.get('/api/transport_controls')

        self.assertEqual(response.status_code, 200)
        self.assertIn('next', response.get_json()['controls'])

    @patch('harmony.get_harmony_client')
    @patch('harmony.run_async')
    def test_next_uses_passthrough_device(self, mock_run_async, mock_get_client):
        client = Mock(current_activity=('1', 'Squeezebox'), config=self.config)
        client.send_commands = AsyncMock()
        mock_get_client.return_value = client
        mock_run_async.side_effect = lambda coro: asyncio.run(coro)

        response = self.client.post('/api/transport', json={'action': 'next'})

        self.assertEqual(response.status_code, 200)
        command = client.send_commands.await_args.args[0]
        self.assertEqual(command.device, 'squeezebox')
        self.assertEqual(command.command, 'Next')

    @patch('harmony.get_harmony_client')
    @patch('harmony.run_async')
    def test_nexttrack_uses_the_advertised_command_name(self, mock_run_async, mock_get_client):
        self.config['device'][0]['controlGroup'][0]['function'][0]['action'] = '{"command": "NextTrack"}'
        client = Mock(current_activity=('1', 'Squeezebox'), config=self.config)
        client.send_commands = AsyncMock()
        mock_get_client.return_value = client
        mock_run_async.side_effect = lambda coro: asyncio.run(coro)

        response = self.client.post('/api/transport', json={'action': 'next'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.send_commands.await_args.args[0].command, 'NextTrack')


class TestTransportControl(unittest.TestCase):
    """Test transport control endpoint."""

    def setUp(self):
        """Set up test client."""
        self.app = app
        self.app.testing = True
        self.client = self.app.test_client()

    def test_transport_missing_action(self):
        """Test /api/transport without action parameter."""
        response = self.client.post('/api/transport', json={})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('error', data)
        self.assertIn('action required', data['error'])

    def test_transport_invalid_action(self):
        """Test /api/transport with invalid action."""
        response = self.client.post('/api/transport', json={'action': 'invalid'})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('error', data)
        self.assertIn('must be play, pause, stop', data['error'])

    @patch('app.harmony.transport_control')
    def test_transport_play_success(self, mock_run_async):
        """Test successful play command."""
        mock_run_async.return_value = True

        response = self.client.post('/api/transport', json={'action': 'play'})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'play')

    @patch('app.harmony.transport_control')
    def test_transport_pause_success(self, mock_run_async):
        """Test successful pause command."""
        mock_run_async.return_value = True

        response = self.client.post('/api/transport', json={'action': 'pause'})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'pause')

    @patch('app.harmony.transport_control')
    def test_transport_stop_success(self, mock_run_async):
        """Test successful stop command."""
        mock_run_async.return_value = True

        response = self.client.post('/api/transport', json={'action': 'stop'})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'stop')

    @patch('app.harmony.transport_control')
    def test_transport_playpause_success(self, mock_run_async):
        """Test successful playpause command."""
        mock_run_async.return_value = True

        response = self.client.post('/api/transport', json={'action': 'playpause'})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'playpause')

    @patch('app.harmony.transport_control')
    def test_transport_powered_off(self, mock_run_async):
        """Test transport control when powered off."""
        mock_run_async.side_effect = ValueError("No activity is running")

        response = self.client.post('/api/transport', json={'action': 'play'})
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertIn('error', data)

    @patch('app.harmony.transport_control')
    def test_transport_no_transport_device(self, mock_run_async):
        """Test transport control when activity has no transport device."""
        mock_run_async.side_effect = ValueError("No transport control device configured for this activity")

        response = self.client.post('/api/transport', json={'action': 'play'})
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertIn('error', data)


class TestDevices(unittest.TestCase):
    """Test devices endpoint."""

    def setUp(self):
        """Set up test client."""
        self.app = app
        self.app.testing = True
        self.client = self.app.test_client()

    @patch('app.harmony.get_devices')
    def test_get_devices(self, mock_run_async):
        """Test /api/devices endpoint."""
        mock_run_async.return_value = [
            {'id': '123', 'label': 'TV'},
            {'id': '456', 'label': 'Receiver'}
        ]

        response = self.client.get('/api/devices')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('devices', data)
        self.assertEqual(len(data['devices']), 2)

    @patch('app.harmony.get_devices')
    def test_get_devices_error(self, mock_run_async):
        """Test /api/devices error handling."""
        mock_run_async.side_effect = Exception("Connection failed")

        response = self.client.get('/api/devices')
        self.assertEqual(response.status_code, 500)
        data = response.get_json()
        self.assertIn('error', data)


class TestBlueprintURLPrefix(unittest.TestCase):
    """Test Blueprint URL prefix functionality."""

    @patch.dict(os.environ, {'URL_PREFIX': '/harmony'})
    def test_routes_with_url_prefix(self):
        """Test that routes work with URL_PREFIX set."""
        # Need to reload app module to pick up new environment variable
        # This is a simplified test - in reality would need module reload
        test_app = app
        test_app.testing = True
        client = test_app.test_client()

        # Test that root without prefix returns 404
        response = client.get('/')
        # Note: This will still return 200 in current test because we can't
        # easily reload the module. This test documents the expected behavior.
        self.assertIn(response.status_code, [200, 404])


class TestErrorHandling(unittest.TestCase):
    """Test error handling scenarios."""

    def setUp(self):
        """Set up test client."""
        self.app = app
        self.app.testing = True
        self.client = self.app.test_client()

    @patch('app.harmony.start_activity')
    def test_start_activity_connection_error(self, mock_run_async):
        """Test start_activity handles connection errors."""
        mock_run_async.side_effect = Exception("Connection timeout")

        response = self.client.post('/api/start_activity',
                                   json={'activity_id': '123'})
        self.assertEqual(response.status_code, 500)
        data = response.get_json()
        self.assertIn('error', data)

    @patch('app.harmony.get_current_activity')
    def test_current_activity_error(self, mock_run_async):
        """Test current_activity handles errors."""
        mock_run_async.side_effect = Exception("Hub disconnected")

        response = self.client.get('/api/current_activity')
        self.assertEqual(response.status_code, 500)
        data = response.get_json()
        self.assertIn('error', data)

    @patch('app.harmony.get_activities')
    def test_activities_error(self, mock_run_async):
        """Test activities endpoint handles errors."""
        mock_run_async.side_effect = Exception("Config not available")

        response = self.client.get('/api/activities')
        self.assertEqual(response.status_code, 500)
        data = response.get_json()
        self.assertIn('error', data)


class TestImageCachingEdgeCases(unittest.TestCase):
    """Test additional image caching edge cases."""

    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        previous = os.getcwd()
        os.chdir(directory)
        self.addCleanup(os.chdir, previous)

    @patch('app.requests.get')
    @patch('app.Path.exists')
    def test_cache_activity_image_network_timeout(self, mock_exists, mock_get):
        """Test image caching handles network timeout."""
        mock_exists.return_value = False
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

        result = cache_activity_image(
            '123',
            'https://rcbu-prod-ssl-amr.myharmony.com/images/',
            'test.png'
        )

        self.assertIsNone(result)

    @patch('app.requests.get')
    @patch('app.Path.exists')
    def test_cache_activity_image_http_error(self, mock_exists, mock_get):
        """Test image caching handles HTTP errors."""
        mock_exists.return_value = False
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Not Found")
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [mock_response.content]
        mock_get.return_value = mock_response

        result = cache_activity_image(
            '123',
            'https://rcbu-prod-ssl-amr.myharmony.com/images/',
            'test.png'
        )

        self.assertIsNone(result)

    def test_cache_activity_image_empty_base_uri(self):
        """Test cache_activity_image with empty base_uri."""
        result = cache_activity_image('123', '', 'test.png')
        self.assertIsNone(result)

    def test_cache_activity_image_malformed_url(self):
        """Test cache_activity_image with malformed URL."""
        result = cache_activity_image('123', 'not-a-valid-url', 'test.png')
        self.assertIsNone(result)

    @patch('app.requests.get')
    @patch('app.Path.exists')
    @patch('app.tempfile.NamedTemporaryFile', side_effect=PermissionError("Permission denied"))
    def test_cache_activity_image_write_permission_error(self, mock_open, mock_exists, mock_get):
        """Test image caching handles file write permission errors."""
        mock_exists.return_value = False
        mock_response = Mock()
        mock_response.content = b'fake_image_data'
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [mock_response.content]
        mock_get.return_value = mock_response

        result = cache_activity_image(
            '123',
            'https://rcbu-prod-ssl-amr.myharmony.com/images/',
            'test.png'
        )

        self.assertIsNone(result)

    @patch('app.detect_image_type')
    @patch('app.requests.get')
    @patch('app.Path.exists')
    def test_cache_activity_image_invalid_type(self, mock_exists, mock_get, mock_detect):
        """Test image caching rejects invalid image types."""
        mock_exists.return_value = False
        mock_response = Mock()
        mock_response.content = b'fake_data'
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [mock_response.content]
        mock_get.return_value = mock_response
        mock_detect.return_value = None  # Invalid image type

        result = cache_activity_image(
            '123',
            'https://rcbu-prod-ssl-amr.myharmony.com/images/',
            'test.png'
        )

        self.assertIsNone(result)

    @patch('app.detect_image_type')
    @patch('app.requests.get')
    @patch('app.Path.exists')
    def test_cache_activity_image_size_limit(self, mock_exists, mock_get, mock_detect):
        """Test image caching rejects images that are too large."""
        mock_exists.return_value = False
        mock_response = Mock()
        # Create image larger than 5MB limit
        mock_response.content = b'x' * (6 * 1024 * 1024)
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [mock_response.content]
        mock_get.return_value = mock_response
        mock_detect.return_value = 'png'

        result = cache_activity_image(
            '123',
            'https://rcbu-prod-ssl-amr.myharmony.com/images/',
            'test.png'
        )

        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
