# SubtitlesGen

A self-hosted subtitle pipeline for your media library. Drop a movie in a folder, get back a transcribed and translated `.srt` next to the original — either on-demand from the UI, automatically when a new file appears, or on a schedule.

- **Transcription** is delegated to any OpenAI-compatible `/v1/audio/transcriptions` endpoint — self-host [faster-whisper-server](https://github.com/fedirz/faster-whisper-server) or [speaches](https://github.com/speaches-ai/speaches), or use a hosted provider (Groq, OpenAI).
- **Translation** is delegated to your choice of provider — Ollama (self-hosted), OpenAI, OpenRouter, Anthropic, or Google Translate.
- **Jellyfin** integration is optional — if configured, a library refresh is triggered after every completed job so the new subtitle track appears immediately.

The app itself is the orchestrator: a FastAPI backend, a React UI, a Celery worker, and Postgres + Redis. No GPU required on the docker host (your Whisper server does the heavy lifting wherever it lives).

## Screenshots

_(coming soon — Queue, Automations, Settings)_

---

## Architecture

```
                            ┌─────────────┐
                            │  Jellyfin   │  ← optional
                            └──────▲──────┘
                                   │ library refresh
                                   │
┌──────────┐   submit   ┌──────────┴─────────┐    enqueue    ┌──────────┐
│  Web UI  │ ─────────▶ │  app (FastAPI)     │  ──────────▶  │  redis   │
└──────────┘            └─────────┬──────────┘               └────┬─────┘
                                  │ persist                       │ broker
                                  ▼                               ▼
                            ┌───────────┐                  ┌─────────────┐
                            │ postgres  │ ◀──────────────  │   worker    │
                            └───────────┘   read job +     │  (Celery)   │
                                            settings       └──┬───────┬──┘
                                                    audio    │       │
                                                    extract  │       │
                                                             ▼       ▼
                                                      ┌─────────┐ ┌──────────┐
                                                      │ Whisper │ │  LLM     │
                                                      │ server  │ │  for     │
                                                      │ /v1/... │ │ translate│
                                                      └─────────┘ └──────────┘
                                                       (you run)   (you pick)
```

The single source of truth for what runs is [`docker-compose.yml`](docker-compose.yml) — go read it; the inline comments explain every service.

---

## Quick start

### Prerequisites

- Docker + docker compose plugin
- A directory on the host with your videos in it
- An OpenAI-compatible Whisper endpoint reachable from the worker container
- _(optional)_ A Jellyfin instance
- _(optional)_ A translation backend (Ollama, OpenAI key, etc.)

### Spin it up

```bash
mkdir subtitles-generator && cd subtitles-generator

# Grab the compose file and env template
curl -O https://raw.githubusercontent.com/radekderkacz/SubtitlesGenerator/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/radekderkacz/SubtitlesGenerator/main/.env.example
mv .env.example .env

# Edit .env — set MEDIA_HOST_PATH to your video library, set passwords
$EDITOR .env

# Create the bind-mount directories so they exist before compose starts
mkdir -p data/logs data/postgres

# Pull and start
docker compose pull
docker compose up -d

# Tail the app logs until you see "Uvicorn running on http://0.0.0.0:8000"
docker compose logs -f app
```

Then open <http://localhost:8000> and walk through Settings:

1. **Media Library** — set the container path. If you used the default `MEDIA_HOST_PATH` mapping it's `/media`.
2. **AI Backends → Transcription Engine** — paste your Whisper endpoint URL, model name, and (optional) API key. Click **Test Connection**.
3. **AI Backends → Translation Provider** — pick a provider, fill in the URL/key, **Test Connection**.
4. **Saved Configurations** — name a profile snapshotting steps 2 + 3 so you can pick it per-job.
5. _(optional)_ **Jellyfin** — URL + API key, **Test Connection**.

You're ready: open **Library**, pick a video, **Submit**.

---

## Configuration via the UI vs. via env

The compose file requires three env vars (`MEDIA_HOST_PATH`, `DB_PASSWORD`, `SECRET_KEY`) and nothing else. **Everything else lives in the database and is configured at runtime via the web UI.** That's deliberate: connection strings, API keys, profiles, watch triggers, cron schedules — they belong in the running app, not in environment variables on the host.

If you want to script the initial setup (e.g. ansible, terraform), hit the REST API directly:

```
POST /api/v1/settings        — set jellyfin URL, transcription URL, etc.
POST /api/v1/triggers        — create a watch folder or cron job
```

The OpenAPI doc is at `/docs` once the app is running.

---

## What goes where on disk

| Path inside container | What's there |
|---|---|
| `/media` | Your video library (read-only for the app, read-write for the worker). Mounted from `${MEDIA_HOST_PATH}` on the host. |
| `/app/logs/<job-id>.log` | Per-job pipeline log. Bind-mounted to `./data/logs/` on the host. |
| `/var/lib/postgresql/data` | Postgres data dir. Bind-mounted to `./data/postgres/` on the host. |

---

## Operational notes

- **The worker child respawns after every task** (`worker_max_tasks_per_child=1`). This is intentional — long-running pipeline tasks tend to accumulate per-process state (open file handles, HTTP pools, ffmpeg subprocess remnants). Fork cost is sub-second on the slim worker image; transcription tasks run for minutes, so the overhead is invisible. See [`backend/app/worker/celery_app.py`](backend/app/worker/celery_app.py) for the rationale.
- **Subtitles are written sibling to the source video** with naming `<basename>.<lang>.srt` (e.g. `MyMovie.pl.srt`). This is the convention Jellyfin and Plex auto-detect.
- **On every completed job the worker POSTs to Jellyfin's `/Library/Refresh`** if a Jellyfin URL is configured. The new subtitle track appears within seconds.
- **The Automations workspace** (sidebar → Sparkles icon) lets you create:
  - **Watch triggers** — fire when a new video appears under a folder. The poll interval is 15 s (works on NFS where inotify doesn't).
  - **Scheduled scans** — cron-style sweep of a folder, dispatching anything without an existing `.srt`.
  - **Webhooks** — POST a file path to a signed URL, get a job back. Useful for integrating with Sonarr/Radarr post-download hooks.

---

## Image sizes

Both images are slim and pulled fast:

| Image | Size |
|---|---|
| `ghcr.io/radekderkacz/subtitles-generator-app:latest` | ~620 MB |
| `ghcr.io/radekderkacz/subtitles-generator-worker:latest` | ~566 MB |

The worker image is a `python:3.12-slim` base + a static [`ffmpeg`](https://johnvansickle.com/ffmpeg/) binary with all common codecs (H.264, HEVC, AAC, AC-3, DTS, Opus, Vorbis, FLAC, TrueHD, VP9, AV1) + the Python deps. No CUDA, no torch, no whisperx — the heavy ML stack lives in your remote transcription server, wherever you run it.

---

## Updating

```bash
docker compose pull
docker compose up -d
```

The app container runs `alembic upgrade head` on boot, so schema migrations apply automatically.

### Automatic updates with Watchtower (optional)

The `app`, `worker`, and `beat` services run on `:latest` and carry
`com.centurylinklabs.watchtower.enable=true`; `db` and `redis` carry
`...enable=false`. So if you run [Watchtower](https://containrrr.dev/watchtower/),
it will auto-pull and recreate the three application containers when a new
release is published, and leave your database and broker alone.

```yaml
# add to docker-compose.yml, or run as a standalone container
  watchtower:
    image: containrrr/watchtower
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      # Honour the worker's long shutdown so an in-flight transcription can
      # finish or requeue instead of being killed mid-job.
      - WATCHTOWER_TIMEOUT=120
      - WATCHTOWER_CLEANUP=true          # remove the old image after updating
      - WATCHTOWER_LABEL_ENABLE=true     # only touch services labelled enable=true
    restart: unless-stopped
```

Notes:
- Keep the services on `:latest` — Watchtower only updates moving tags. If you
  [pin to a release](#pinning-to-a-release), Watchtower won't (and shouldn't) update it.
- `WATCHTOWER_TIMEOUT=120` matters: Watchtower ignores compose `stop_grace_period`
  and uses this value before SIGKILL. The default 10s can kill a running transcription.
- Without `WATCHTOWER_LABEL_ENABLE=true`, Watchtower updates **every** container
  it can see; the `enable=false` labels on `db`/`redis` still protect those two.

### Pinning to a release

`docker-compose.yml` tracks `:latest` so a `docker compose pull` always gets the newest build. For a reproducible deployment, pin both images to a release version instead — the tag matches the version shown in the app's sidebar:

```yaml
# docker-compose.yml
  app:
    image: ghcr.io/radekderkacz/subtitles-generator-app:0.1.0
  worker:
    image: ghcr.io/radekderkacz/subtitles-generator-worker:0.1.0
  beat:
    image: ghcr.io/radekderkacz/subtitles-generator-worker:0.1.0
```

Every build is also tagged with its commit SHA if you need to pin even more precisely.

---

## Troubleshooting

- **Worker idle, jobs queued forever** — check the beat container's `ENTRYPOINT` is overridden to `celery beat` and not silently running as a second worker. See [`docker-compose.yml`](docker-compose.yml).
- **`ffmpeg: No such file or directory` on extracting** — check `MEDIA_HOST_PATH` is actually mounted on the docker host AND your Settings → Media Library path matches the container path (`/media` by default).
- **Settings → AI Backends → Test Connection fails** — verify the worker container can reach your Whisper server. `docker compose exec worker curl http://<your-whisper>:9000/health`.
- **Jellyfin not refreshing after a job** — confirm the Jellyfin URL + API key in Settings, and that the user the API key belongs to has admin rights to refresh libraries.

For anything else, open an issue at <https://github.com/radekderkacz/SubtitlesGenerator/issues>.

---

## License

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

The worker image bundles a static [FFmpeg](https://johnvansickle.com/ffmpeg/)
binary licensed under GPLv3. FFmpeg runs as a separate executable and is not
linked into this project's code, so it does not affect the Apache-2.0 licensing
of the source. Redistributors of the image must comply with the GPLv3 for the
FFmpeg component — see [`NOTICE`](NOTICE) for details.
