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

Open http://localhost:3000. The API is available at http://localhost:8000 and documentation at http://localhost:8000/docs.

### Full Docker environment

```bash
cp .env.example .env
docker compose up --build
```

Services: frontend :3000, API :8000, PostgreSQL :5432, Redis :6379, and n8n :5678.

## Data status

The initial dashboard is backed by FastAPI and uses clearly labeled demonstration data until production, publishing, and analytics integrations are connected. Real credentials and media provider configuration are intentionally excluded from source control.

## Validation

```bash
cd backend && pytest
cd frontend && npm run lint && npm run build
```
