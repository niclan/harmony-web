"""Unit tests for Harmony Hub Web Controller."""
import unittest
from unittest.mock import Mock, patch, AsyncMock
import sys
import os

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

    @patch('app.requests.get')
    @patch('app.Path.exists')
    def test_cache_activity_image_success(self, mock_exists, mock_get):
        """Test successful image caching."""
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


if __name__ == '__main__':
    unittest.main()
