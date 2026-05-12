# Local AI backend (FastAPI + Ollama)

This folder adds a local AI backend that:
- receives requests from the React app
- calls Ollama running on your PC
- stores chat + survey + recommendations in Supabase (with RLS)

## 1) Install Ollama (Windows)

1. Download and install from `https://ollama.com/download`
2. Open a new PowerShell and run:

```powershell
ollama --version
ollama pull llama3.2:3b
ollama run llama3.2:3b
```

Ollama runs an API at `http://127.0.0.1:11434`.

## 2) Apply Supabase migrations

This repo includes a migration that adds:
- `chat_sessions`, `chat_messages`
- `survey_responses`, `recommendations`

If you are using Supabase CLI locally, run migrations as you normally do for this project.

## 3) Configure backend env

Create `backend/.env`:

```env
SUPABASE_URL="https://YOUR_PROJECT.supabase.co"
SUPABASE_ANON_KEY="YOUR_SUPABASE_ANON_KEY"

OLLAMA_BASE_URL="http://127.0.0.1:11434"
OLLAMA_MODEL="llama3.2:3b"

FRONTEND_ORIGIN="http://localhost:8080"
```

Use the same Supabase URL/key you already have in the frontend `.env` (the publishable/anon key).

## 4) Run the FastAPI server

From this folder:

```powershell
py -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Health check: `http://127.0.0.1:8000/health`

