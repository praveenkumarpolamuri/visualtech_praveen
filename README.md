# VisualTech

VisualTech is an AI-assisted documentary production studio for a faceless technology, photography, and AI YouTube channel.

## Run locally

### Frontend and backend

```bash
cp .env.example .env
cd frontend && npm install && npm run dev
```

In a second terminal:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:3000. The API is available at http://localhost:8000 and documentation at http://localhost:8000/docs. When using an existing database, run `alembic upgrade head` from `backend` before starting the API.

For scheduled YouTube uploads outside Docker, start a second backend process with `python -m app.publisher` from `backend` after the API is available. Docker Compose starts this publisher as a separate service.

### Full Docker environment

```bash
cp .env.example .env
docker compose up --build
```

Services: frontend :3000, API :8000, publishing worker, PostgreSQL :5432, Redis :6379, and n8n :5678. The publisher runs separately from the API and polls persisted schedule/retry state.

## Integrations

Copy `.env.example` to `.env` and set credentials as needed. OpenAI image generation and speech synthesis require `OPENAI_API_KEY`. YouTube publishing and analytics require a Google OAuth client with the YouTube Data API and YouTube Analytics API enabled; set `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_TOKEN_ENCRYPTION_KEY`, `YOUTUBE_REDIRECT_URI`, and `FRONTEND_URL` (the default callback is `http://localhost:8000/api/integrations/youtube/callback`, which returns to `http://localhost:3000`). Generate a Fernet key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. OAuth state values are random, hashed in the database, expire after 10 minutes, and are consumed once. Connect the account from Studio > YouTube & Analytics.

S3-compatible storage is enabled when `S3_ENDPOINT`, `S3_ACCESS_KEY`, and `S3_SECRET_KEY` are all set; otherwise media is stored privately under `media/private-assets/` and served through five-minute signed links. Set `MEDIA_UPLOAD_MAX_BYTES` to control upload size (default 100 MiB). Rendered videos are served separately under `media/public/`. YouTube OAuth tokens use `YOUTUBE_TOKEN_ENCRYPTION_KEY`; keep that key stable or reconnect after rotating it. Publishing requires an approved upload record, final-video and publishing approval records, and a completed render. Scheduled times entered in Studio are interpreted as UTC; the database-backed publisher retries transient upload failures with capped exponential backoff and reclaims stale worker leases after restart. A schedule missed before upload is marked `schedule_missed` and needs a new future time. Attach a generated image to a storyboard scene and associate voiceover or uploaded audio with a project to use them in the next render.

## Content Workflow

Set the channel's audience, tone, language, format, and default duration in Studio > Settings. Research results are unverified by default; mark sources verified only after reviewing the source itself. Script generation uses only verified project sources, retains stable citation IDs, and marks unsupported claims `[VERIFY]` for human review. Target script length is estimated at about 130 spoken words per minute. Storyboard regeneration creates a new revision without deleting previous versions; renders use the latest revision. Long voiceovers are split into sentence-safe requests and joined into a single audio asset.

The dashboard reads projects, approvals, scheduled uploads, and analytics from the database. Provider-backed actions remain unavailable until their credentials are configured; no credentials are committed to the repository.

## Validation

```bash
cd backend && pytest
cd frontend && npm run lint && npm run build
```
