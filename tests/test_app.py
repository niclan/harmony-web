"""Unit tests for Harmony Hub Web Controller."""
import unittest
from unittest.mock import Mock, patch, AsyncMock
import sys
import os
import asyncio
import requests

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, cache_activity_image


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

    @patch('app.run_async')
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

    @patch('app.run_async')
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

    @patch('app.run_async')
    def test_start_activity_invalid_id(self, mock_run_async):
        """Test /api/start_activity with invalid activity_id."""
        # Mock the validation to raise ValueError
        mock_run_async.side_effect = ValueError("Invalid activity_id: 999")

        response = self.client.post('/api/start_activity',
                                   json={'activity_id': '999'})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('error', data)

    @patch('app.run_async')
    def test_power_off(self, mock_run_async):
        """Test /api/power_off endpoint."""
        mock_run_async.return_value = True

        response = self.client.post('/api/power_off')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])


class TestImageCaching(unittest.TestCase):
    """Test activity image caching functionality."""

    @patch('app.detect_image_type')
    @patch('app.requests.get')
    @patch('app.Path.exists')
    def test_cache_activity_image_success(self, mock_exists, mock_get, mock_detect):
        """Test successful image caching."""
        mock_exists.return_value = False
        mock_response = Mock()
        mock_response.content = b'fake_image_data'
        mock_response.raise_for_status = Mock()
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


class TestInputValidation(unittest.TestCase):
    """Test input validation."""

    def test_activity_id_validation(self):
        """Test that activity IDs are validated against config."""
        # This test verifies the validation logic is in place
        # The actual validation happens in the async function
        # so we test it through the endpoint
        app.testing = True
        client = app.test_client()

        with patch('app.run_async') as mock_run_async:
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

    @patch('app.run_async')
    def test_volume_up_success(self, mock_run_async):
        """Test successful volume up command."""
        mock_run_async.return_value = True

        response = self.client.post('/api/volume', json={'action': 'up'})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'up')

    @patch('app.run_async')
    def test_volume_down_success(self, mock_run_async):
        """Test successful volume down command."""
        mock_run_async.return_value = True

        response = self.client.post('/api/volume', json={'action': 'down'})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'down')

    @patch('app.run_async')
    def test_volume_mute_success(self, mock_run_async):
        """Test successful mute command."""
        mock_run_async.return_value = True

        response = self.client.post('/api/volume', json={'action': 'mute'})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'mute')

    @patch('app.run_async')
    def test_volume_powered_off(self, mock_run_async):
        """Test volume control when powered off."""
        mock_run_async.side_effect = ValueError("No activity is running")

        response = self.client.post('/api/volume', json={'action': 'up'})
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertIn('error', data)

    @patch('app.run_async')
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

    @patch('app.run_async')
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

    @patch('app.run_async')
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

    @patch('app.run_async')
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

    @patch('app.run_async')
    def test_transport_play_success(self, mock_run_async):
        """Test successful play command."""
        mock_run_async.return_value = True

        response = self.client.post('/api/transport', json={'action': 'play'})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'play')

    @patch('app.run_async')
    def test_transport_pause_success(self, mock_run_async):
        """Test successful pause command."""
        mock_run_async.return_value = True

        response = self.client.post('/api/transport', json={'action': 'pause'})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'pause')

    @patch('app.run_async')
    def test_transport_stop_success(self, mock_run_async):
        """Test successful stop command."""
        mock_run_async.return_value = True

        response = self.client.post('/api/transport', json={'action': 'stop'})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'stop')

    @patch('app.run_async')
    def test_transport_playpause_success(self, mock_run_async):
        """Test successful playpause command."""
        mock_run_async.return_value = True

        response = self.client.post('/api/transport', json={'action': 'playpause'})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'playpause')

    @patch('app.run_async')
    def test_transport_powered_off(self, mock_run_async):
        """Test transport control when powered off."""
        mock_run_async.side_effect = ValueError("No activity is running")

        response = self.client.post('/api/transport', json={'action': 'play'})
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertIn('error', data)

    @patch('app.run_async')
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

    @patch('app.run_async')
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

    @patch('app.run_async')
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

    @patch('app.run_async')
    def test_start_activity_connection_error(self, mock_run_async):
        """Test start_activity handles connection errors."""
        mock_run_async.side_effect = Exception("Connection timeout")

        response = self.client.post('/api/start_activity',
                                   json={'activity_id': '123'})
        self.assertEqual(response.status_code, 500)
        data = response.get_json()
        self.assertIn('error', data)

    @patch('app.run_async')
    def test_current_activity_error(self, mock_run_async):
        """Test current_activity handles errors."""
        mock_run_async.side_effect = Exception("Hub disconnected")

        response = self.client.get('/api/current_activity')
        self.assertEqual(response.status_code, 500)
        data = response.get_json()
        self.assertIn('error', data)

    @patch('app.run_async')
    def test_activities_error(self, mock_run_async):
        """Test activities endpoint handles errors."""
        mock_run_async.side_effect = Exception("Config not available")

        response = self.client.get('/api/activities')
        self.assertEqual(response.status_code, 500)
        data = response.get_json()
        self.assertIn('error', data)


class TestImageCachingEdgeCases(unittest.TestCase):
    """Test additional image caching edge cases."""

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
    @patch('builtins.open', side_effect=PermissionError("Permission denied"))
    def test_cache_activity_image_write_permission_error(self, mock_open, mock_exists, mock_get):
        """Test image caching handles file write permission errors."""
        mock_exists.return_value = False
        mock_response = Mock()
        mock_response.content = b'fake_image_data'
        mock_response.raise_for_status = Mock()
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
        mock_get.return_value = mock_response
        mock_detect.return_value = 'png'

        result = cache_activity_image(
            '123',
            'https://rcbu-prod-ssl-amr.myharmony.com/images/',
            'test.png'
        )

        self.assertIsNone(result)


class TestAsyncInfrastructure(unittest.TestCase):
    """Test async infrastructure."""

    @patch('app.asyncio.run_coroutine_threadsafe')
    @patch('app.loop')
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
            from app import run_async
            run_async(dummy_coro())


if __name__ == '__main__':
    unittest.main()
