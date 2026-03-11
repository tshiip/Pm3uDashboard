import json
import os
import re
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask, abort, jsonify, render_template, request, send_from_directory, url_for

app = Flask(__name__)
app.secret_key = os.urandom(24)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('PM3U_DATA_DIR', BASE_DIR)
SHARED_FILES_DIR_NAME = 'shared_m3u_files'
SHARED_FILES_FULL_PATH = os.path.join(DATA_DIR, SHARED_FILES_DIR_NAME)
PERSISTENT_SHARE_FILENAME = 'playlist.m3u'
SHARE_STATE_FILENAME = 'share_config.json'
SHARE_STATE_FULL_PATH = os.path.join(DATA_DIR, SHARE_STATE_FILENAME)
AUTO_REFRESH_MINUTES = 15
NO_GROUP_CATEGORY_NAME = "[No Group / Uncategorized]"
ATTR_REGEX = re.compile(r'([a-zA-Z0-9_-]+)=("([^"]*)"|([^"\s]+))')

os.makedirs(SHARED_FILES_FULL_PATH, exist_ok=True)


class PlaylistContentError(ValueError):
    pass


def utc_now():
    return datetime.now(tz=timezone.utc)


def get_persistent_share_filepath():
    return os.path.join(SHARED_FILES_FULL_PATH, PERSISTENT_SHARE_FILENAME)


def load_share_state():
    if not os.path.exists(SHARE_STATE_FULL_PATH):
        return {}
    try:
        with open(SHARE_STATE_FULL_PATH, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        app.logger.warning("Share state file could not be read. Continuing with empty state.")
        return {}


def save_share_state(state):
    with open(SHARE_STATE_FULL_PATH, 'w', encoding='utf-8') as handle:
        json.dump(state, handle, indent=2, sort_keys=True)


def update_share_state(**updates):
    state = load_share_state()
    state.update(updates)
    save_share_state(state)
    return state


def normalize_source_config(source_config):
    if not isinstance(source_config, dict):
        return None

    source_type = str(source_config.get('type', '')).strip().lower()
    if source_type == 'url':
        source_url = str(source_config.get('url', '')).strip()
        if not source_url.startswith(('http://', 'https://')):
            return None
        return {'type': 'url', 'url': source_url}

    if source_type == 'xtream':
        panel_url = str(source_config.get('panelUrl', '')).strip()
        username = str(source_config.get('username', '')).strip()
        password = str(source_config.get('password', ''))
        output_type = str(source_config.get('outputType', 'ts')).strip().lower()
        if output_type not in {'ts', 'm3u8'}:
            output_type = 'ts'
        if not all([panel_url, username, password]):
            return None
        return {
            'type': 'xtream',
            'panelUrl': panel_url,
            'username': username,
            'password': password,
            'outputType': output_type,
        }

    return None


def normalize_filter_config(filter_config):
    if not isinstance(filter_config, dict):
        return None

    categories = filter_config.get('categories')
    if not isinstance(categories, dict):
        return None

    normalized_categories = {}
    for category_name, rule in categories.items():
        if not isinstance(category_name, str) or not category_name.strip():
            continue
        if not isinstance(rule, dict):
            continue

        mode = str(rule.get('mode', '')).strip().lower()
        if mode == 'all':
            normalized_categories[category_name] = {'mode': 'all', 'channels': []}
            continue

        if mode == 'channels':
            channels = sorted({
                str(channel_name).strip()
                for channel_name in rule.get('channels', [])
                if isinstance(channel_name, str) and channel_name.strip()
            })
            if channels:
                normalized_categories[category_name] = {'mode': 'channels', 'channels': channels}

    if not normalized_categories:
        return None

    return {'categories': normalized_categories}


def format_share_link_message(source_config):
    if source_config:
        return (
            f"This persistent link stays the same and refreshes from the saved provider "
            f"every {AUTO_REFRESH_MINUTES} minutes when requested."
        )
    return (
        "This persistent link stays the same, but auto-refresh is unavailable until you "
        "publish from a URL or Xtream source."
    )


def normalize_panel_url(panel_url_from_user):
    panel_url = panel_url_from_user.strip()
    if not panel_url.startswith(('http://', 'https://')):
        return 'http://' + panel_url.rstrip('/')
    return panel_url.rstrip('/')


def fetch_remote_m3u_content(target_url):
    if not target_url.startswith(('http://', 'https://')):
        raise ValueError('Invalid URL scheme. URL must start with http:// or https://')

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        )
    }
    response = requests.get(target_url, timeout=60, headers=headers)
    response.raise_for_status()
    return response.text


def fetch_xtream_playlist_content(panel_url_from_user, username, password, output_type_extension='ts'):
    panel_url_base = normalize_panel_url(panel_url_from_user)
    api_endpoint = f"{panel_url_base}/player_api.php"
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        ),
        'Accept': 'application/json'
    }
    auth_params = {'username': username, 'password': password}

    categories_response = requests.get(
        api_endpoint,
        params={**auth_params, 'action': 'get_live_categories'},
        headers=headers,
        timeout=30,
    )
    categories_response.raise_for_status()
    categories_json = categories_response.json()

    categories_map = {}
    if isinstance(categories_json, list):
        categories_map = {
            item['category_id']: item['category_name']
            for item in categories_json
            if isinstance(item, dict) and 'category_id' in item and 'category_name' in item
        }
    elif categories_json is None:
        app.logger.warning(f"No categories data (null) returned from Xtream panel: {api_endpoint}")
    else:
        app.logger.warning(
            f"No categories list returned or unexpected format from Xtream panel: {str(categories_json)[:200]}"
        )

    streams_response = requests.get(
        api_endpoint,
        params={**auth_params, 'action': 'get_live_streams'},
        headers=headers,
        timeout=60,
    )
    streams_response.raise_for_status()
    streams_json = streams_response.json()

    if not isinstance(streams_json, list):
        raise PlaylistContentError('No live streams found or panel returned an unexpected format.')

    m3u_lines = ["#EXTM3U"]
    for stream in streams_json:
        if not isinstance(stream, dict):
            app.logger.warning(f"Skipping malformed stream entry: {str(stream)[:100]}")
            continue

        name = stream.get('name', f"Stream {stream.get('stream_id', 'Unknown')}")
        tvg_id = str(stream.get('epg_channel_id', '') or '')
        tvg_logo = str(stream.get('stream_icon', '') or '')
        category_id = stream.get('category_id')
        group_title = categories_map.get(category_id, 'Undefined Category')
        name_escaped = name.replace('"', "'") if name else ""
        group_title_escaped = group_title.replace('"', "'") if group_title else "Undefined Category"
        extinf_line = (
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name_escaped}" '
            f'tvg-logo="{tvg_logo}" group-title="{group_title_escaped}",{name}'
        )
        m3u_lines.append(extinf_line)

        stream_id = stream.get('stream_id')
        if stream_id is not None:
            stream_url = f"{panel_url_base}/live/{username}/{password}/{stream_id}.{output_type_extension}"
            m3u_lines.append(stream_url)
        else:
            app.logger.warning(f"Stream '{name}' missing stream_id, cannot form URL.")

    return "\n".join(m3u_lines)


def parse_m3u_content(content):
    entries = []
    other_directives = []
    original_header = "#EXTM3U"
    current_channel_info = None

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.upper().startswith("#EXTM3U"):
            original_header = line
            continue

        if line.startswith('#EXTINF:'):
            attributes = {}
            if len(line) <= 4096:
                for match in ATTR_REGEX.finditer(line):
                    key = match.group(1)
                    if key in {'__proto__', 'constructor', 'prototype'}:
                        continue
                    attributes[key] = match.group(3) or match.group(4) or ''

            name_match = re.search(r',(.+)$', line)
            display_name = name_match.group(1).strip() if name_match else 'Unknown Channel'
            current_channel_info = {
                'info': line,
                'name': display_name,
                'attributes': attributes,
                'url': '',
            }
            continue

        if current_channel_info and not line.startswith('#'):
            current_channel_info['url'] = line
            current_channel_info['group_title'] = (
                current_channel_info['attributes'].get('group-title') or NO_GROUP_CATEGORY_NAME
            )
            entries.append(current_channel_info)
            current_channel_info = None
            continue

        if current_channel_info and line.startswith('#') and line.upper() != "#EXTM3U":
            current_channel_info['group_title'] = (
                current_channel_info['attributes'].get('group-title') or NO_GROUP_CATEGORY_NAME
            )
            entries.append(current_channel_info)
            current_channel_info = None
            other_directives.append(line)
            continue

        if line.startswith('#'):
            other_directives.append(line)

    return {
        'original_header': original_header,
        'other_directives': other_directives,
        'entries': entries,
    }


def build_filtered_content(content, filter_config):
    if not filter_config or not isinstance(filter_config.get('categories'), dict):
        return content

    parsed = parse_m3u_content(content)
    filtered_lines = [parsed['original_header']]
    filtered_lines.extend(parsed['other_directives'])

    category_rules = filter_config['categories']
    for entry in parsed['entries']:
        group_title = entry.get('group_title') or NO_GROUP_CATEGORY_NAME
        rule = category_rules.get(group_title)
        if not rule:
            continue

        if rule.get('mode') == 'channels' and entry['name'] not in set(rule.get('channels', [])):
            continue

        filtered_lines.append(entry['info'])
        if entry.get('url'):
            filtered_lines.append(entry['url'])

    return "\n".join(filtered_lines) + "\n"


def fetch_source_content(source_config):
    if not source_config:
        raise ValueError('No saved provider is configured for auto-refresh.')

    source_type = source_config.get('type')
    if source_type == 'url':
        return fetch_remote_m3u_content(source_config['url'])
    if source_type == 'xtream':
        return fetch_xtream_playlist_content(
            source_config['panelUrl'],
            source_config['username'],
            source_config['password'],
            source_config.get('outputType', 'ts'),
        )
    raise ValueError('Unsupported provider type for auto-refresh.')


def refresh_persistent_share_if_due(force=False):
    state = load_share_state()
    source_config = state.get('sourceConfig')
    if not source_config:
        return {'refreshed': False, 'reason': 'no_saved_source'}

    last_refresh_at_raw = state.get('lastRefreshAt')
    last_refresh_at = None
    if last_refresh_at_raw:
        try:
            last_refresh_at = datetime.fromisoformat(last_refresh_at_raw)
        except ValueError:
            last_refresh_at = None

    if not force and last_refresh_at:
        refresh_cutoff = utc_now() - timedelta(minutes=state.get('autoRefreshMinutes', AUTO_REFRESH_MINUTES))
        if last_refresh_at > refresh_cutoff:
            return {'refreshed': False, 'reason': 'not_due'}

    try:
        source_content = fetch_source_content(source_config)
        filtered_content = build_filtered_content(source_content, state.get('filterConfig'))
        with open(get_persistent_share_filepath(), 'w', encoding='utf-8') as handle:
            handle.write(filtered_content)

        update_share_state(
            lastRefreshAt=utc_now().isoformat(),
            lastRefreshStatus='success',
            lastRefreshError=None,
        )
        return {'refreshed': True, 'reason': 'success'}
    except Exception as exc:
        update_share_state(
            lastRefreshAt=utc_now().isoformat(),
            lastRefreshStatus='error',
            lastRefreshError=str(exc),
        )
        app.logger.error(f"Persistent share refresh failed: {exc}", exc_info=True)
        return {'refreshed': False, 'reason': 'error', 'error': str(exc)}


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/proxy_m3u_url', methods=['POST'])
def proxy_m3u_url():
    target_url = None
    try:
        data = request.get_json()
        if not data:
            app.logger.warning("Proxy request failed: No JSON data.")
            return jsonify({'success': False, 'error': 'Invalid request. No JSON data.'}), 400

        target_url = data.get('url')
        if not target_url:
            app.logger.warning("Proxy request failed: No URL provided in JSON.")
            return jsonify({'success': False, 'error': 'No URL provided.'}), 400

        app.logger.info(f"Proxying M3U request to: {target_url}")
        m3u_content = fetch_remote_m3u_content(target_url)
        if not m3u_content or not m3u_content.strip().upper().startswith("#EXTM3U"):
            app.logger.warning(
                f"Content from proxied URL ({target_url}) did not look like an M3U playlist. "
                f"Content (first 200 chars): {m3u_content[:200]}..."
            )
        return jsonify({'success': True, 'm3uContent': m3u_content})
    except ValueError as exc:
        app.logger.warning(f"Proxy request failed validation for {target_url}: {exc}")
        return jsonify({'success': False, 'error': str(exc)}), 400
    except requests.exceptions.Timeout:
        app.logger.error(f"Timeout connecting to proxied URL: {target_url if target_url else 'unknown'}")
        return jsonify({'success': False, 'error': 'Connection to the provided URL timed out.'}), 504
    except requests.exceptions.HTTPError as http_err:
        error_message = (
            f'The URL returned an HTTP error: '
            f'{http_err.response.status_code if http_err.response else "N/A"}.'
        )
        if http_err.response and http_err.response.status_code == 403:
            error_message = "The remote server denied access (403 Forbidden)."
            app.logger.error(
                f"403 Forbidden from proxied URL ({target_url}). Response Headers: "
                f"{http_err.response.headers}. Response Text (first 200): {http_err.response.text[:200]}"
            )
        elif http_err.response:
            app.logger.error(
                f"HTTP error from proxied URL ({target_url}): {http_err.response.status_code} - "
                f"Response: {http_err.response.text[:200]}"
            )
        else:
            app.logger.error(f"HTTP error from proxied URL ({target_url}): No response object from server.")
        return jsonify({'success': False, 'error': error_message}), http_err.response.status_code if http_err.response else 500
    except requests.exceptions.RequestException as req_err:
        app.logger.error(
            f"Request error connecting to proxied URL {target_url if target_url else 'unknown'}: {req_err}"
        )
        return jsonify({'success': False, 'error': f'Error connecting to the provided URL: {req_err}'}), 500
    except Exception as exc:
        app.logger.error(
            f"Generic error proxying M3U URL ({target_url if target_url else 'unknown'}): {exc}",
            exc_info=True,
        )
        return jsonify(
            {'success': False, 'error': 'Failed to fetch playlist from the URL due to an unexpected server error.'}
        ), 500


@app.route('/fetch_xtream_playlist', methods=['POST'])
def fetch_xtream_playlist():
    panel_url_from_user = None
    username = None
    xtream_api_url_for_logging = None
    try:
        data = request.get_json()
        if not data:
            app.logger.warning("Xtream request failed: No JSON data.")
            return jsonify({'success': False, 'error': 'Invalid request. No JSON data.'}), 400

        panel_url_from_user = data.get('panelUrl')
        username = data.get('username')
        password = data.get('password')
        output_type_extension = data.get('outputType', 'ts').lower()

        if not all([panel_url_from_user, username, password]):
            app.logger.warning("Xtream request failed: Missing panel URL, username, or password.")
            return jsonify({'success': False, 'error': 'Missing Xtream panel URL, username, or password.'}), 400

        xtream_api_url_for_logging = f"{normalize_panel_url(panel_url_from_user)}/player_api.php"
        app.logger.info(f"Fetching Xtream playlist from: {xtream_api_url_for_logging}")
        m3u_content = fetch_xtream_playlist_content(
            panel_url_from_user,
            username,
            password,
            output_type_extension,
        )
        return jsonify({'success': True, 'm3uContent': m3u_content})
    except PlaylistContentError as exc:
        app.logger.warning(
            f"Xtream request returned invalid content (Panel: {panel_url_from_user}, API URL: {xtream_api_url_for_logging}): {exc}"
        )
        return jsonify({'success': False, 'error': str(exc)}), 404
    except requests.exceptions.Timeout:
        app.logger.error(
            f"Timeout connecting to Xtream panel API (Panel: {panel_url_from_user}, API URL: {xtream_api_url_for_logging})"
        )
        return jsonify({'success': False, 'error': 'Connection to Xtream panel API timed out.'}), 504
    except requests.exceptions.HTTPError as http_err:
        error_code = http_err.response.status_code if http_err.response else 500
        error_text = (
            http_err.response.text[:200]
            if http_err.response and hasattr(http_err.response, 'text')
            else "No response text"
        )
        error_message = f"Xtream panel API returned HTTP error: {error_code}."
        if error_code == 401:
            error_message = "Unauthorized (401). Please check your Xtream username and password."
        elif error_code == 403:
            error_message = "Forbidden (403). The Xtream panel API blocked the request."
        app.logger.error(
            f"HTTP error from Xtream panel API (Panel: {panel_url_from_user}, API URL: {xtream_api_url_for_logging}): "
            f"{error_code} - Response: {error_text}"
        )
        return jsonify({'success': False, 'error': error_message}), error_code
    except requests.exceptions.RequestException as req_err:
        app.logger.error(
            f"Request error connecting to Xtream panel API (Panel: {panel_url_from_user}, API URL: {xtream_api_url_for_logging}): {req_err}"
        )
        return jsonify({'success': False, 'error': f'Error connecting to Xtream panel API: {req_err}'}), 500
    except ValueError as json_err:
        app.logger.error(
            f"Error decoding JSON response from Xtream panel API (Panel: {panel_url_from_user}, API URL: {xtream_api_url_for_logging}): {json_err}"
        )
        return jsonify({'success': False, 'error': 'Failed to understand response from Xtream panel (Invalid JSON).'}), 500
    except Exception as exc:
        app.logger.error(
            f"Generic error fetching Xtream playlist via API (Panel: {panel_url_from_user if panel_url_from_user else 'unknown'}, "
            f"API URL: {xtream_api_url_for_logging if xtream_api_url_for_logging else 'unknown'}): {exc}",
            exc_info=True,
        )
        return jsonify(
            {'success': False, 'error': 'Failed to fetch playlist from Xtream panel due to a server error.'}
        ), 500


@app.route('/generate-share-link', methods=['POST'])
def generate_share_link():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Invalid request. No JSON data.'}), 400

        content = data.get('content', '')
        if not content:
            return jsonify({'success': False, 'error': 'No content provided.'}), 400

        source_config = normalize_source_config(data.get('sourceConfig'))
        filter_config = normalize_filter_config(data.get('filterConfig'))
        with open(get_persistent_share_filepath(), 'w', encoding='utf-8') as handle:
            handle.write(content)

        shareable_link = url_for('serve_shared_file', filename=PERSISTENT_SHARE_FILENAME, _external=True)
        update_share_state(
            sourceConfig=source_config,
            filterConfig=filter_config,
            autoRefreshMinutes=AUTO_REFRESH_MINUTES,
            lastRefreshAt=utc_now().isoformat(),
            lastRefreshStatus='success',
            lastRefreshError=None,
        )
        return jsonify({
            'success': True,
            'shareableLink': shareable_link,
            'shareInfo': format_share_link_message(source_config),
        })
    except Exception as exc:
        app.logger.error(f"Error updating shared link: {exc}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to update the persistent share link on server.'}), 500


@app.route('/shared/<path:filename>')
def serve_shared_file(filename):
    if '..' in filename or filename.startswith('/') or filename.startswith('\\'):
        abort(400, description="Invalid filename.")

    if filename == PERSISTENT_SHARE_FILENAME:
        refresh_result = refresh_persistent_share_if_due(force=False)
        if refresh_result.get('reason') == 'error' and not os.path.exists(get_persistent_share_filepath()):
            return "Persistent playlist refresh failed.", 500

    filepath = os.path.join(SHARED_FILES_FULL_PATH, filename)
    if not os.path.exists(filepath) or not os.path.isfile(filepath):
        return "Link expired or file not found.", 404

    try:
        return send_from_directory(
            SHARED_FILES_FULL_PATH,
            filename,
            as_attachment=False,
            mimetype='audio/x-mpegurl',
        )
    except FileNotFoundError:
        return "Link expired or file not found.", 404
    except Exception as exc:
        app.logger.error(f"Error serving file {filename}: {exc}", exc_info=True)
        return "Error serving file.", 500


if __name__ == '__main__':
    debug_enabled = os.environ.get('PM3U_DEBUG', '').strip().lower() in {'1', 'true', 'yes', 'on'}
    host = os.environ.get('PM3U_HOST', '127.0.0.1')
    port = int(os.environ.get('PM3U_PORT', '5000'))

    if not debug_enabled:
        import logging

        logging.basicConfig(level=logging.INFO)
    app.run(host=host, port=port, debug=debug_enabled)
