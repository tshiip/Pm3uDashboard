import os
from datetime import datetime, timezone

# Ensure this script can find SHARED_FILES_DIR_NAME relative to its own location
# This assumes cleanup_script.py is in the same directory as app.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED_FILES_DIR_NAME = 'shared_m3u_files' # Must match app.py
SHARED_FILES_FULL_PATH = os.path.join(BASE_DIR, SHARED_FILES_DIR_NAME)
PERSISTENT_SHARE_FILENAME = 'playlist.m3u' # Must match app.py

def cleanup_expired_files():
    now = datetime.now(tz=timezone.utc)
    print(f"[{now.isoformat()}] Checking shared files in {SHARED_FILES_FULL_PATH}...")
    
    if not os.path.isdir(SHARED_FILES_FULL_PATH):
        print(f"Shared files directory {SHARED_FILES_FULL_PATH} does not exist. Nothing to do.")
        return

    for filename in os.listdir(SHARED_FILES_FULL_PATH):
        if filename != PERSISTENT_SHARE_FILENAME:
            continue

        filepath = os.path.join(SHARED_FILES_FULL_PATH, filename)
        if not os.path.isfile(filepath):
            continue

        file_mod_time_timestamp = os.path.getmtime(filepath)
        file_mod_time = datetime.fromtimestamp(file_mod_time_timestamp, tz=timezone.utc)
        print(
            f"Persistent shared playlist found: {filename} "
            f"(last updated {file_mod_time.isoformat()}). Leaving it in place."
        )
        break
    else:
        print("No persistent shared playlist exists yet.")

if __name__ == "__main__":
    cleanup_expired_files()
