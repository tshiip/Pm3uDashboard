import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from unittest.mock import Mock, patch

import app as dashboard_app


class DashboardAppTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_shared_files_path = dashboard_app.SHARED_FILES_FULL_PATH
        self.original_share_state_path = dashboard_app.SHARE_STATE_FULL_PATH
        dashboard_app.SHARED_FILES_FULL_PATH = self.temp_dir.name
        dashboard_app.SHARE_STATE_FULL_PATH = os.path.join(self.temp_dir.name, 'share_config.json')
        dashboard_app.app.config.update(TESTING=True)
        self.client = dashboard_app.app.test_client()

    def tearDown(self):
        dashboard_app.SHARED_FILES_FULL_PATH = self.original_shared_files_path
        dashboard_app.SHARE_STATE_FULL_PATH = self.original_share_state_path
        self.temp_dir.cleanup()

    def test_index_renders_dashboard(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'M3U Playlist Filter', response.data)

    @patch('app.requests.get')
    def test_proxy_m3u_url_returns_playlist_content(self, mock_get):
        mocked_response = Mock()
        mocked_response.raise_for_status.return_value = None
        mocked_response.text = "#EXTM3U\n#EXTINF:-1,Example\nhttp://example.com/stream"
        mock_get.return_value = mocked_response

        response = self.client.post('/proxy_m3u_url', json={'url': 'https://example.com/list.m3u'})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertIn('#EXTM3U', payload['m3uContent'])
        mock_get.assert_called_once()

    def test_proxy_m3u_url_rejects_invalid_scheme(self):
        response = self.client.post('/proxy_m3u_url', json={'url': 'ftp://example.com/list.m3u'})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()['success'])

    @patch('app.requests.get')
    def test_fetch_xtream_playlist_builds_m3u_output(self, mock_get):
        categories_response = Mock()
        categories_response.raise_for_status.return_value = None
        categories_response.json.return_value = [
            {'category_id': '10', 'category_name': 'News'},
        ]

        streams_response = Mock()
        streams_response.raise_for_status.return_value = None
        streams_response.json.return_value = [
            {
                'name': 'Example News',
                'epg_channel_id': 'example.news',
                'stream_icon': 'https://example.com/logo.png',
                'category_id': '10',
                'stream_id': 123,
            }
        ]

        mock_get.side_effect = [categories_response, streams_response]

        response = self.client.post(
            '/fetch_xtream_playlist',
            json={
                'panelUrl': 'panel.example.com:8080',
                'username': 'demo',
                'password': 'secret',
                'outputType': 'm3u8',
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertIn('group-title="News"', payload['m3uContent'])
        self.assertIn('http://panel.example.com:8080/live/demo/secret/123.m3u8', payload['m3uContent'])
        self.assertEqual(mock_get.call_count, 2)

    def test_generate_share_link_and_download_shared_file(self):
        first_response = self.client.post('/generate-share-link', json={'content': '#EXTM3U\n#EXTINF:-1,First'})
        second_response = self.client.post('/generate-share-link', json={'content': '#EXTM3U\n#EXTINF:-1,Second'})

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)

        first_payload = first_response.get_json()
        second_payload = second_response.get_json()

        self.assertTrue(first_payload['success'])
        self.assertTrue(second_payload['success'])
        self.assertEqual(first_payload['shareableLink'], second_payload['shareableLink'])
        self.assertIn('This persistent link stays the same', second_payload['shareInfo'])

        download_path = urlparse(second_payload['shareableLink']).path
        filename = os.path.basename(download_path)
        self.assertEqual(filename, dashboard_app.PERSISTENT_SHARE_FILENAME)
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir.name, filename)))

        download_response = self.client.get(download_path)
        self.assertEqual(download_response.status_code, 200)
        self.assertIn(b'Second', download_response.data)
        self.assertNotIn(b'First', download_response.data)
        download_response.close()

    @patch('app.requests.get')
    def test_persistent_shared_file_auto_refreshes_from_saved_url_source(self, mock_get):
        publish_response = self.client.post(
            '/generate-share-link',
            json={
                'content': '#EXTM3U\n#EXTINF:-1 group-title="News",Keep Me\nhttp://old.example/keep',
                'sourceConfig': {'type': 'url', 'url': 'https://provider.example/playlist.m3u'},
                'filterConfig': {
                    'categories': {
                        'News': {'mode': 'channels', 'channels': ['Keep Me']},
                    }
                },
            },
        )
        self.assertEqual(publish_response.status_code, 200)

        with open(dashboard_app.SHARE_STATE_FULL_PATH, 'r', encoding='utf-8') as handle:
            state = json.load(handle)
        state['lastRefreshAt'] = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        with open(dashboard_app.SHARE_STATE_FULL_PATH, 'w', encoding='utf-8') as handle:
            json.dump(state, handle)

        mocked_response = Mock()
        mocked_response.raise_for_status.return_value = None
        mocked_response.text = (
            '#EXTM3U\n'
            '#EXTINF:-1 group-title="News",Keep Me\n'
            'http://fresh.example/keep\n'
            '#EXTINF:-1 group-title="News",Drop Me\n'
            'http://fresh.example/drop\n'
        )
        mock_get.return_value = mocked_response

        response = self.client.get('/shared/playlist.m3u')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Keep Me', response.data)
        self.assertIn(b'http://fresh.example/keep', response.data)
        self.assertNotIn(b'Drop Me', response.data)
        self.assertEqual(mock_get.call_count, 1)
        response.close()


if __name__ == '__main__':
    unittest.main()
