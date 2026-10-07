# RailRoute Alternate — React + Vite + FastAPI

Converted from the original Streamlit MVP. The Python routing engine in `backend/engine.py` is retained as the core search engine. The Streamlit UI has been replaced by a React + Vite frontend and a FastAPI REST API.

## Architecture

- `frontend/` — React + Vite UI
- `backend/` — FastAPI API + original pure Python/pandas routing engine
- `backend/data/` — sample timetable, station, availability and train-stop data
- `backend/tests/` — original engine tests

## Local development

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

API: http://127.0.0.1:8000/docs

### Frontend

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

Vite proxies `/api` requests to the local FastAPI server.

## Production deployment

Recommended:

- Frontend: Vercel
- Backend: Render, Railway, Fly.io, or another Python ASGI host
- Source: GitHub
- Domain: your domain points to Vercel

Set `VITE_API_URL` in the Vercel project to the public backend URL.

## Important

The included railway data is SAMPLE data. It is not live railway availability, timetable, or fare information.
