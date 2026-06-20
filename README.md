# SubtitlesGen

**Automatic subtitles for your movies and TV shows.** Drop a video into a folder and SubtitlesGen transcribes it — and optionally translates it — into a `.srt` subtitle file saved right next to the video, ready for Jellyfin, Plex, or any player.

It runs as a few small Docker containers on your own machine. **No GPU required.**

## What it does

- **Transcribes** speech in your videos into subtitles, automatically.
- **Translates** them into another language (optional).
- **Times them properly** — short, sentence-level lines that show up *when they're actually spoken*, wrapped to a comfortable length.
- **Checks its own work** — every finished job gets a pass / warn / fail quality check (with a one-click re-check) so you know which subtitles are worth reviewing. It never blocks output; it's just a heads-up.
- **Runs three ways** — on demand from the web UI, automatically when a new video appears, or on a schedule.
- **Refreshes Jellyfin** for you (optional) so new subtitles appear right away.

---

## What you'll need

- **Docker**, with the `docker compose` command.
- A **folder of videos** on the machine.
- A **transcription service** and (if you want translations) a **translation service**.

> ⚠️ **Important:** SubtitlesGen is the *coordinator* — it does **not** include the AI itself. You point it at a transcription service (the thing that turns speech into text) and a translation service. You can:
> - **self-host free ones** — e.g. [faster-whisper-server](https://github.com/fedirz/faster-whisper-server) or [speaches](https://github.com/speaches-ai/speaches) for transcription, and [Ollama](https://ollama.com/) for translation, or
> - **use a paid API** — OpenAI, Groq, OpenRouter, Anthropic, or Google.
>
> You enter these in the app's **Settings** after installing (next section). Nothing to configure up front.

---

## Install (about 5 minutes)

```bash
mkdir subtitlesgen && cd subtitlesgen

# 1. Grab the compose file and the environment template
curl -O https://raw.githubusercontent.com/radekderkacz/SubtitlesGenerator/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/radekderkacz/SubtitlesGenerator/main/.env.example
mv .env.example .env

# 2. Edit .env — set MEDIA_HOST_PATH to your video folder, and pick passwords
$EDITOR .env

# 3. Create the data folders, then start it
mkdir -p data/logs data/postgres
docker compose up -d
```

Now open **<http://localhost:8000>**. (First start pulls the images and sets up the database — give it a minute.)

---

## First run — connect your services

In the app, go to **Settings** and:

1. **Media Library** — confirm the video path. With the default setup it's `/media`.
2. **AI Backends → Transcription** — paste your transcription service's URL + model name (+ API key if it needs one), then click **Test Connection**.
3. **AI Backends → Translation** — pick your provider, fill in the URL/key, click **Test Connection**.
4. **Profiles** — save your transcription + translation choices as a named profile so you can pick it per job.
5. *(optional)* **Jellyfin** — add its URL + API key and **Test Connection**.

Then open **Library**, pick a video, and hit **Submit**. The subtitle file appears next to your video when it's done. 🎬

---

## Updating

```bash
docker compose pull
docker compose up -d
```

The app applies any database changes automatically on start. (Prefer a fixed version, or hands-off auto-updates? See **Advanced** below.)

---

## Common problems

- **"Directory not found" / can't see my videos** — make sure `MEDIA_HOST_PATH` in `.env` points at your real video folder, and that **Settings → Media Library** is set to `/media` (the path *inside* the container).
- **Settings → Test Connection fails** — your transcription/translation service must be reachable from the containers. Quick check: `docker compose exec worker curl <your-service-url>`.
- **A job is stuck "queued"** — check the containers are healthy with `docker compose ps`.
- **Jellyfin didn't refresh** — confirm the Jellyfin URL + API key in Settings, and that the API key's user has permission to refresh libraries.

For anything else, open an issue: <https://github.com/radekderkacz/SubtitlesGenerator/issues>

---

## Advanced &amp; reference

<details>
<summary><b>How it works (architecture)</b></summary>

The app is the orchestrator: a FastAPI backend, a React UI, a Celery worker, and Postgres + Redis. No GPU on the Docker host — your transcription server does the heavy lifting wherever it lives.

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

The single source of truth for what runs is [`docker-compose.yml`](docker-compose.yml) — the inline comments explain every service.

</details>

<details>
<summary><b>Configuration: UI vs. environment variables</b></summary>

The compose file needs only three env vars (`MEDIA_HOST_PATH`, `DB_PASSWORD`, `SECRET_KEY`). **Everything else lives in the database and is set at runtime via the web UI** — connection strings, API keys, profiles, watch triggers, cron schedules belong in the running app, not in host env vars.

To script the initial setup (ansible, terraform, etc.), hit the REST API directly:

```
POST /api/v1/settings        — set jellyfin URL, transcription URL, etc.
POST /api/v1/triggers        — create a watch folder or cron job
```

The OpenAPI docs are at `/docs` once the app is running.

</details>

<details>
<summary><b>What goes where on disk</b></summary>

| Path inside container | What's there |
|---|---|
| `/media` | Your video library (read-only for the app, read-write for the worker). Mounted from `${MEDIA_HOST_PATH}` on the host. |
| `/app/logs/<job-id>.log` | Per-job pipeline log. Bind-mounted to `./data/logs/` on the host. |
| `/var/lib/postgresql/data` | Postgres data dir. Bind-mounted to `./data/postgres/` on the host. |

</details>

<details>
<summary><b>Operational notes</b></summary>

- **The worker child respawns after every task** (`worker_max_tasks_per_child=1`). Intentional — long pipeline tasks accumulate per-process state (file handles, HTTP pools, ffmpeg remnants). Fork cost is sub-second on the slim worker image; transcription runs for minutes, so the overhead is invisible. See [`backend/app/worker/celery_app.py`](backend/app/worker/celery_app.py).
- **Subtitles are written sibling to the source video** as `<basename>.<lang>.srt` (e.g. `MyMovie.pl.srt`) — the convention Jellyfin and Plex auto-detect.
- **On every completed job the worker POSTs to Jellyfin's `/Library/Refresh`** if a Jellyfin URL is configured; the new track appears within seconds.
- **The Automations workspace** (sidebar → Sparkles icon) lets you create:
  - **Watch triggers** — fire when a new video appears under a folder (15 s poll; works on NFS where inotify doesn't).
  - **Scheduled scans** — cron-style sweep of a folder, dispatching anything without an existing `.srt`.
  - **Webhooks** — POST a file path to a signed URL, get a job back. Handy for Sonarr/Radarr post-download hooks.

</details>

<details>
<summary><b>Image sizes</b></summary>

| Image | Size |
|---|---|
| `ghcr.io/radekderkacz/subtitles-generator-app:latest` | ~620 MB |
| `ghcr.io/radekderkacz/subtitles-generator-worker:latest` | ~566 MB |

The worker image is `python:3.12-slim` + a static [`ffmpeg`](https://johnvansickle.com/ffmpeg/) binary with all common codecs (H.264, HEVC, AAC, AC-3, DTS, Opus, Vorbis, FLAC, TrueHD, VP9, AV1) + the Python deps. No CUDA, no torch — the heavy ML stack lives in your remote transcription server.

</details>

<details>
<summary><b>Automatic updates with Watchtower</b></summary>

The `app`, `worker`, and `beat` services run on `:latest` and carry `com.centurylinklabs.watchtower.enable=true`; `db` and `redis` carry `...enable=false`. So [Watchtower](https://containrrr.dev/watchtower/) will auto-update the three application containers and leave your database and broker alone.

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

- Keep the services on `:latest` — Watchtower only updates moving tags. If you pin to a release, Watchtower won't (and shouldn't) update it.
- `WATCHTOWER_TIMEOUT=120` matters: Watchtower ignores compose `stop_grace_period` and uses this value before SIGKILL. The default 10s can kill a running transcription.
- Without `WATCHTOWER_LABEL_ENABLE=true`, Watchtower updates **every** container it can see; the `enable=false` labels on `db`/`redis` still protect those two.

</details>

<details>
<summary><b>Pinning to a specific release</b></summary>

`docker-compose.yml` tracks `:latest`. For a reproducible deployment, pin both images to a version instead — the tag matches the version shown in the app's sidebar:

```yaml
# docker-compose.yml
  app:
    image: ghcr.io/radekderkacz/subtitles-generator-app:0.2.0
  worker:
    image: ghcr.io/radekderkacz/subtitles-generator-worker:0.2.0
  beat:
    image: ghcr.io/radekderkacz/subtitles-generator-worker:0.2.0
```

Every build is also tagged with its commit SHA for even more precise pinning.

</details>

---

## License

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

The worker image bundles a static [FFmpeg](https://johnvansickle.com/ffmpeg/) binary licensed under GPLv3. FFmpeg runs as a separate executable and is not linked into this project's code, so it does not affect the Apache-2.0 licensing of the source. Redistributors of the image must comply with the GPLv3 for the FFmpeg component — see [`NOTICE`](NOTICE) for details.
