# Pm3uDashboard

A small Flask dashboard for loading, filtering, and exporting M3U playlists.

## What It Does

- Loads playlists from a local `.m3u`/`.m3u8` file
- Proxies remote playlist URLs through the backend
- Builds an M3U playlist from Xtream Codes credentials
- Lets you enable or disable categories and individual channels
- Saves the filtered playlist locally or updates one persistent shared link

## Local Setup

1. Create a virtual environment:

```bash
python3 -m venv .venv
```

2. Install dependencies:

```bash
./.venv/bin/pip install -r requirements.txt
```

3. Run the app:

```bash
./.venv/bin/python app.py
```

The dashboard will be available at [http://127.0.0.1:5000](http://127.0.0.1:5000).

## Run Tests

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

## Docker Deployment

Build and run with Docker Compose:

```bash
docker compose up --build -d
```

The app will be available at [http://127.0.0.1:5000](http://127.0.0.1:5000).

Useful Docker commands:

```bash
docker compose logs -f
docker compose down
```

Persistent app data is stored in the local `data/` directory, including:

- `data/shared_m3u_files/playlist.m3u`
- `data/share_config.json`

## Persistent Shared Link

Publishing updates writes the filtered playlist to a single persistent URL:

- `/shared/playlist.m3u`
- Each publish overwrites the existing contents at that URL
- IPTV clients can keep the same subscription link even when the source provider changes
- If you publish from a remote M3U URL or Xtream source, the app saves that provider and your current filter rules
- When `/shared/playlist.m3u` is requested later, the app automatically refreshes from the saved provider every 15 minutes and reapplies the saved filters before serving the playlist

The repository still includes `cleanup_script.py`, but it now only reports whether the persistent shared playlist exists and leaves it in place:

```bash
./.venv/bin/python cleanup_script.py
```
