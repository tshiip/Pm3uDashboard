# Pm3uDashboard

A small Flask dashboard for loading, filtering, and exporting M3U playlists.

## Quick Start

Use the included Docker Compose YAML file:

```bash
docker compose -f docker-compose.yml up --build -d
```

Then open [http://127.0.0.1:5000](http://127.0.0.1:5000).

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
docker compose -f docker-compose.yml up --build -d
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

## GitHub Container Registry

The repo includes a GitHub Actions workflow at `.github/workflows/publish-ghcr.yml` that builds and publishes the Docker image to GHCR on every push to `main` and on version tags.

After the workflow runs, the image will be available at:

- `ghcr.io/<github-owner>/pm3udashboard:latest`

If the package is private, make it public in GitHub Packages before using it from TrueNAS or another host without GitHub credentials.

## TrueNAS SCALE

The repo includes a TrueNAS custom app example YAML in `truenas-app.yaml`.

To use it on TrueNAS SCALE:

1. Build and push the image from this repo to a registry such as GitHub Container Registry.
2. Create a dataset for persistent app data, for example `/mnt/tank/apps/pm3udashboard`.
3. Open `Apps > Discover Apps > Install via YAML` in TrueNAS.
4. Paste the contents of `truenas-app.yaml`.
5. Replace:
   - `ghcr.io/YOURUSER/pm3udashboard:latest` with your real image
   - `/mnt/tank/apps/pm3udashboard` with your real dataset path

The app will then be exposed on port `5000` by default.

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
