import os
import uuid
from datetime import datetime, timezone # Removed timedelta
from flask import Flask, render_template, request, jsonify, send_from_directory, url_for, abort
import requests 

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- Configuration for Shared Files ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED_FILES_DIR_NAME = 'shared_m3u_files'
SHARED_FILES_FULL_PATH = os.path.join(BASE_DIR, SHARED_FILES_DIR_NAME)
# LINK_EXPIRY_HOURS = 1 # Not actively used for deletion in app.py

if not os.path.exists(SHARED_FILES_FULL_PATH):
    os.makedirs(SHARED_FILES_FULL_PATH)
# --- End Configuration ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/proxy_m3u_url', methods=['POST'])
def proxy_m3u_url():
    target_url = None
    try:
        data = request.get_json()
        if not data:
            app.logger.warn("Proxy request failed: No JSON data.")
            return jsonify({'success': False, 'error': 'Invalid request. No JSON data.'}), 400
        target_url = data.get('url')
        if not target_url:
            app.logger.warn("Proxy request failed: No URL provided in JSON.")
            return jsonify({'success': False, 'error': 'No URL provided.'}), 400
        if not target_url.startswith(('http://', 'https://')):
            app.logger.warn(f"Proxy request failed: Invalid URL scheme for {target_url}")
            return jsonify({'success': False, 'error': 'Invalid URL scheme. URL must start with http:// or https://'}), 400
        
        app.logger.info(f"Proxying M3U request to: {target_url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(target_url, timeout=60, headers=headers)
        response.raise_for_status()
        m3u_content = response.text
        if not m3u_content or not m3u_content.strip().upper().startsWith("#EXTM3U"):
            app.logger.warn(f"Content from proxied URL ({target_url}) did not look like an M3U playlist. Content (first 200 chars): {m3u_content[:200]}...")
        return jsonify({'success': True, 'm3uContent': m3u_content})
    except requests.exceptions.Timeout:
        app.logger.error(f"Timeout connecting to proxied URL: {target_url if target_url else 'unknown'}")
        return jsonify({'success': False, 'error': 'Connection to the provided URL timed out.'}), 504
    except requests.exceptions.HTTPError as http_err:
        error_message = f'The URL returned an HTTP error: {http_err.response.status_code if http_err.response else "N/A"}.'
        if http_err.response and http_err.response.status_code == 403:
            error_message = "The remote server denied access (403 Forbidden)."
            app.logger.error(f"403 Forbidden from proxied URL ({target_url}). Response Headers: {http_err.response.headers}. Response Text (first 200): {http_err.response.text[:200]}")
        elif http_err.response:
            app.logger.error(f"HTTP error from proxied URL ({target_url}): {http_err.response.status_code} - Response: {http_err.response.text[:200]}")
        else:
            app.logger.error(f"HTTP error from proxied URL ({target_url}): No response object from server.")
        return jsonify({'success': False, 'error': error_message}), http_err.response.status_code if http_err.response else 500
    except requests.exceptions.RequestException as req_err:
        app.logger.error(f"Request error connecting to proxied URL {target_url if target_url else 'unknown'}: {req_err}")
        return jsonify({'success': False, 'error': f'Error connecting to the provided URL: {req_err}'}), 500
    except Exception as e:
        app.logger.error(f"Generic error proxying M3U URL ({target_url if target_url else 'unknown'}): {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to fetch playlist from the URL due to an unexpected server error.'}), 500

@app.route('/fetch_xtream_playlist', methods=['POST'])
def fetch_xtream_playlist():
    panel_url_from_user = None
    username = None # Initialize for broader scope in error logging
    password = None # Initialize for broader scope in error logging
    xtream_api_url_for_logging = None # For logging in case of early error
    try:
        data = request.get_json()
        if not data:
            app.logger.warn("Xtream request failed: No JSON data.")
            return jsonify({'success': False, 'error': 'Invalid request. No JSON data.'}), 400

        panel_url_from_user = data.get('panelUrl')
        username = data.get('username')
        password = data.get('password')
        output_type_extension = data.get('outputType', 'ts').lower()

        if not all([panel_url_from_user, username, password]):
            app.logger.warn("Xtream request failed: Missing panel URL, username, or password.")
            return jsonify({'success': False, 'error': 'Missing Xtream panel URL, username, or password.'}), 400

        if not panel_url_from_user.startswith(('http://', 'https://')):
            panel_url_base = 'http://' + panel_url_from_user.rstrip('/')
        else:
            panel_url_base = panel_url_from_user.rstrip('/')
        
        api_endpoint = f"{panel_url_base}/player_api.php"
        xtream_api_url_for_logging = api_endpoint # For logging

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json'
        }
        auth_params = {'username': username, 'password': password}
        
        app.logger.info(f"Fetching Xtream categories from: {api_endpoint}")
        categories_response = requests.get(api_endpoint, params={**auth_params, 'action': 'get_live_categories'}, headers=headers, timeout=30)
        categories_response.raise_for_status()
        categories_json = categories_response.json()
        
        categories_map = {}
        if isinstance(categories_json, list):
            categories_map = {item['category_id']: item['category_name'] for item in categories_json if isinstance(item, dict) and 'category_id' in item and 'category_name' in item}
        elif categories_json is None: # Some panels might return null for no categories
             app.logger.warn(f"No categories data (null) returned from Xtream panel: {api_endpoint}")
        else: # Some panels return empty JSON object {} on no categories, or error
             app.logger.warn(f"No categories list returned or unexpected format from Xtream panel: {str(categories_json)[:200]}")
        
        app.logger.info(f"Fetching Xtream live streams from: {api_endpoint}")
        streams_response = requests.get(api_endpoint, params={**auth_params, 'action': 'get_live_streams'}, headers=headers, timeout=60)
        streams_response.raise_for_status()
        streams_json = streams_response.json()

        if not isinstance(streams_json, list): # streams_json could be None or {} from some panels
            app.logger.warn(f"No live streams list returned or unexpected format from Xtream panel: {str(streams_json)[:200]}")
            return jsonify({'success': False, 'error': 'No live streams found or panel returned an unexpected format.'}), 404

        m3u_lines = ["#EXTM3U"]
        for stream in streams_json:
            if not isinstance(stream, dict): 
                app.logger.warn(f"Skipping malformed stream entry: {str(stream)[:100]}")
                continue

            name = stream.get('name', f"Stream {stream.get('stream_id', 'Unknown')}")
            tvg_id = stream.get('epg_channel_id', '')
            tvg_logo = stream.get('stream_icon', '')
            category_id = stream.get('category_id')
            group_title = categories_map.get(category_id, 'Undefined Category')
            
            tvg_id = str(tvg_id if tvg_id is not None else '')
            tvg_logo = str(tvg_logo if tvg_logo is not None else '')
            name_escaped = name.replace('"', "'") if name else ""
            group_title_escaped = group_title.replace('"', "'") if group_title else "Undefined Category"

            extinf_line = f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name_escaped}" tvg-logo="{tvg_logo}" group-title="{group_title_escaped}",{name}'
            m3u_lines.append(extinf_line)
            
            stream_id = stream.get('stream_id')
            if stream_id is not None:
                 stream_url = f"{panel_url_base}/live/{username}/{password}/{stream_id}.{output_type_extension}"
                 m3u_lines.append(stream_url)
            else:
                app.logger.warn(f"Stream '{name}' missing stream_id, cannot form URL.")

        m3u_content_final = "\n".join(m3u_lines)
        return jsonify({'success': True, 'm3uContent': m3u_content_final})

    except requests.exceptions.Timeout:
        app.logger.error(f"Timeout connecting to Xtream panel API (Panel: {panel_url_from_user}, API URL: {xtream_api_url_for_logging})")
        return jsonify({'success': False, 'error': 'Connection to Xtream panel API timed out.'}), 504
    except requests.exceptions.HTTPError as http_err:
        error_code = http_err.response.status_code if http_err.response else 500
        error_text = http_err.response.text[:200] if http_err.response and hasattr(http_err.response, 'text') else "No response text"
        error_message = f"Xtream panel API returned HTTP error: {error_code}."
        if error_code == 401: error_message = "Unauthorized (401). Please check your Xtream username and password."
        elif error_code == 403: error_message = "Forbidden (403). The Xtream panel API blocked the request."
        app.logger.error(f"HTTP error from Xtream panel API (Panel: {panel_url_from_user}, API URL: {xtream_api_url_for_logging}): {error_code} - Response: {error_text}")
        return jsonify({'success': False, 'error': error_message}), error_code
    except requests.exceptions.RequestException as req_err:
        app.logger.error(f"Request error connecting to Xtream panel API (Panel: {panel_url_from_user}, API URL: {xtream_api_url_for_logging}): {req_err}")
        return jsonify({'success': False, 'error': f'Error connecting to Xtream panel API: {req_err}'}), 500
    except ValueError as json_err: 
        app.logger.error(f"Error decoding JSON response from Xtream panel API (Panel: {panel_url_from_user}, API URL: {xtream_api_url_for_logging}): {json_err}")
        return jsonify({'success': False, 'error': 'Failed to understand response from Xtream panel (Invalid JSON).'}), 500
    except Exception as e:
        app.logger.error(f"Generic error fetching Xtream playlist via API (Panel: {panel_url_from_user if panel_url_from_user else 'unknown'}, API URL: {xtream_api_url_for_logging if xtream_api_url_for_logging else 'unknown'}): {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to fetch playlist from Xtream panel due to a server error.'}), 500

@app.route('/generate-share-link', methods=['POST'])
def generate_share_link():
    try:
        data = request.get_json()
        if not data: return jsonify({'success': False, 'error': 'Invalid request. No JSON data.'}), 400
        content = data.get('content', '')
        if not content: return jsonify({'success': False, 'error': 'No content provided.'}), 400
        unique_id = str(uuid.uuid4())
        filename_on_server = f"{unique_id}.m3u"
        filepath = os.path.join(SHARED_FILES_FULL_PATH, filename_on_server)
        with open(filepath, 'w', encoding='utf-8') as f: f.write(content)
        shareable_link = url_for('serve_shared_file', filename=filename_on_server, _external=True)
        return jsonify({'success': True, 'shareableLink': shareable_link, 'expires_in': "Link does not automatically expire." })
    except Exception as e:
        app.logger.error(f"Error generating share link: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to generate shareable link on server.'}), 500

@app.route('/shared/<path:filename>')
def serve_shared_file(filename):
    if '..' in filename or filename.startswith('/') or filename.startswith('\\'): abort(400, description="Invalid filename.")
    filepath = os.path.join(SHARED_FILES_FULL_PATH, filename)
    if not os.path.exists(filepath) or not os.path.isfile(filepath): return "Link expired or file not found.", 404
    try:
        return send_from_directory(SHARED_FILES_FULL_PATH, filename, as_attachment=True, download_name=f"filtered_playlist_{filename[:8]}.m3u")
    except FileNotFoundError: return "Link expired or file not found.", 404
    except Exception as e:
        app.logger.error(f"Error serving file {filename}: {e}", exc_info=True)
        return "Error serving file.", 500

if __name__ == '__main__':
    if not app.debug:
        import logging
        logging.basicConfig(level=logging.INFO)
    app.run(debug=True)