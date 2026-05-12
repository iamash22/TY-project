from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any

from dotenv import load_dotenv, dotenv_values
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from app.auth import auth_context
from app.models import (
    CreateSessionResponse,
    ListMessagesResponse,
    ParsedIntent,
    PostMessageRequest,
    PostMessageResponse,
    SubmitSurveyRequest,
    SubmitSurveyResponse,
)
from app.ollama_client import OllamaClient
from app.supabase_rest import SupabaseRest


_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DOTENV_PATH = os.path.join(_BACKEND_ROOT, ".env")
_dotenv_loaded = load_dotenv(dotenv_path=_DOTENV_PATH, override=True)
_dotenv_kv = {}
try:
    _dotenv_kv = {k: v for k, v in (dotenv_values(_DOTENV_PATH) or {}).items() if k and v is not None}
    # Fallback: if load_dotenv failed to populate os.environ, set keys manually.
    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_ANON_KEY"):
        for k, v in _dotenv_kv.items():
            if v is None:
                continue
            os.environ[k] = str(v)
except Exception:
    _dotenv_kv = {}

app = FastAPI(title="Nearby Helpers AI (local)")

def _cors_origins() -> list[str]:
    """
    Accept a single FRONTEND_ORIGIN or a comma-separated FRONTEND_ORIGINS.
    """
    origins: list[str] = []
    raw_multi = os.getenv("FRONTEND_ORIGINS") or ""
    raw_single = os.getenv("FRONTEND_ORIGIN") or ""
    if raw_multi.strip():
        origins.extend([o.strip() for o in raw_multi.split(",") if o.strip()])
    if raw_single.strip():
        origins.append(raw_single.strip())
    # sensible defaults for local dev
    origins.extend(["http://localhost:8080", "http://127.0.0.1:8080", "http://localhost:5173", "http://127.0.0.1:5173"])
    # de-dup while preserving order
    out: list[str] = []
    for o in origins:
        if o not in out:
            out.append(o)
    return out


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _dbg(hypothesis_id: str, message: str, data: dict[str, Any]) -> None:
    # #region agent log
    try:
        import json
        payload = {
            "sessionId": "3fc183",
            "runId": os.getenv("DEBUG_RUN_ID") or "pre-fix",
            "hypothesisId": hypothesis_id,
            "location": "backend/app/main.py",
            "message": message,
            "data": data,
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
        }
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        # Write to repo root to match debug-mode log path.
        log_path_root = os.path.abspath(os.path.join(_BACKEND_ROOT, "..", "debug-3fc183.log"))
        # Also write to backend folder as a fallback if root isn't writable.
        log_path_backend = os.path.abspath(os.path.join(_BACKEND_ROOT, "debug-3fc183.backend.log"))
        wrote = False
        try:
            with open(log_path_root, "a", encoding="utf-8") as f:
                f.write(line)
            wrote = True
        except Exception as e1:  # noqa: BLE001
            try:
                with open(log_path_backend, "a", encoding="utf-8") as f:
                    f.write(line)
                    f.write(json.dumps({"err": str(e1), "log_path_root": log_path_root}, ensure_ascii=False) + "\n")
            except Exception:
                # Last resort: print (shows in uvicorn console)
                try:
                    print("DBG_WRITE_FAILED", str(e1), log_path_root)
                except Exception:
                    pass
        if not wrote:
            # Best-effort note
            try:
                with open(log_path_backend, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"note": "root_log_not_written", "log_path_root": log_path_root}, ensure_ascii=False) + "\n")
            except Exception:
                pass
    except Exception as e:  # noqa: BLE001
        try:
            print("DBG_FATAL", str(e))
        except Exception:
            pass
    # #endregion agent log


@app.middleware("http")
async def debug_middleware(request: Request, call_next):
    _dbg(
        "H1",
        "request_in",
        {
            "method": request.method,
            "path": request.url.path,
            "origin": request.headers.get("origin"),
            "host": request.headers.get("host"),
            "has_auth": bool(request.headers.get("authorization")),
        },
    )
    response = await call_next(request)
    _dbg(
        "H1",
        "request_out",
        {
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "allow_origin": response.headers.get("access-control-allow-origin"),
        },
    )
    return response

@app.on_event("startup")
async def debug_startup() -> None:
    _dbg(
        "H2",
        "startup_env",
        {
            "dotenv_path": _DOTENV_PATH,
            "dotenv_exists": os.path.exists(_DOTENV_PATH),
            "dotenv_loaded": bool(_dotenv_loaded),
            "dotenv_keys_count": len(_dotenv_kv),
            "cwd": os.getcwd(),
            "has_url": bool(os.getenv("SUPABASE_URL")),
            "has_anon": bool(os.getenv("SUPABASE_ANON_KEY")),
        },
    )

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _dev_anon_enabled() -> bool:
    return (os.getenv("ALLOW_ANON_AI") or "").lower() in ("1", "true", "yes", "on")


def get_ollama() -> OllamaClient:
    return OllamaClient()


def get_db() -> SupabaseRest:
    try:
        return SupabaseRest()
    except RuntimeError as e:
        _dbg("H2", "supabase_env_missing", {"error": str(e), "has_url": bool(os.getenv("SUPABASE_URL")), "has_anon": bool(os.getenv("SUPABASE_ANON_KEY"))})
        # Don't crash the whole request with a stacktrace; return a clear 500 instead.
        raise HTTPException(status_code=500, detail=str(e)) from e

# Very small in-memory store for anonymous dev mode.
# Only intended for local testing.
ANON_SESSIONS: dict[str, list[dict[str, Any]]] = {}


@app.get("/health")
async def health() -> dict[str, Any]:
    anon = (os.getenv("ALLOW_ANON_AI") or "").lower() in ("1", "true", "yes", "on")
    _dbg(
        "H3",
        "health_check",
        {
            "anon": anon,
            "has_url": bool(os.getenv("SUPABASE_URL")),
            "has_anon": bool(os.getenv("SUPABASE_ANON_KEY")),
            "origins_count": len(_cors_origins()),
            "dotenv_path": _DOTENV_PATH,
            "dotenv_exists": os.path.exists(_DOTENV_PATH),
            "dotenv_loaded": bool(_dotenv_loaded),
            "cwd": os.getcwd(),
        },
    )
    return {"ok": True, "anon": anon}


@app.post("/api/chat/sessions", response_model=CreateSessionResponse)
async def create_chat_session(
    ctx: tuple[str, str | None] = Depends(auth_context),
    db: SupabaseRest = Depends(get_db),
) -> CreateSessionResponse:
    user_id, jwt_token = ctx
    if _dev_anon_enabled() or (user_id == "anon" and jwt_token is None):
        sid = str(uuid4())
        ANON_SESSIONS[sid] = []
        return CreateSessionResponse(id=sid)
    row = await db.insert(
        jwt_token,
        "chat_sessions",
        {"user_id": user_id, "title": "New chat", "last_message_at": now_iso()},
    )
    return CreateSessionResponse(id=row["id"])


@app.get("/api/chat/sessions/{session_id}/messages", response_model=ListMessagesResponse)
async def list_chat_messages(
    session_id: str,
    ctx: tuple[str, str | None] = Depends(auth_context),
    db: SupabaseRest = Depends(get_db),
) -> ListMessagesResponse:
    _user_id, jwt_token = ctx
    if _dev_anon_enabled() or jwt_token is None:
        return ListMessagesResponse(messages=ANON_SESSIONS.get(session_id, []))  # type: ignore[arg-type]
    rows = await db.select(
        jwt_token,
        "chat_messages",
        select="id,session_id,user_id,role,content,metadata,created_at",
        filters={"session_id": f"eq.{session_id}"},
        order="created_at.asc",
        limit=200,
    )
    return ListMessagesResponse(messages=rows)  # type: ignore[arg-type]


@app.post("/api/chat/sessions/{session_id}/messages", response_model=PostMessageResponse)
async def post_chat_message(
    session_id: str,
    body: PostMessageRequest,
    ctx: tuple[str, str | None] = Depends(auth_context),
    db: SupabaseRest = Depends(get_db),
    ollama: OllamaClient = Depends(get_ollama),
) -> PostMessageResponse:
    user_id, jwt_token = ctx

    use_anon_store = _dev_anon_enabled() or jwt_token is None
    if use_anon_store:
        ANON_SESSIONS.setdefault(session_id, []).append(
            {
                "id": str(uuid4()),
                "session_id": session_id,
                "user_id": "anon",
                "role": "user",
                "content": body.content,
                "metadata": {},
                "created_at": now_iso(),
            }
        )
    else:
        # Save user message
        await db.insert(
            jwt_token,
            "chat_messages",
            {
                "session_id": session_id,
                "user_id": user_id,
                "role": "user",
                "content": body.content,
                "metadata": {},
            },
        )

    # Load short context for the model
    if use_anon_store:
        history = [{"role": m["role"], "content": m["content"]} for m in ANON_SESSIONS.get(session_id, [])][-20:]
    else:
        history = await db.select(
            jwt_token,
            "chat_messages",
            select="role,content",
            filters={"session_id": f"eq.{session_id}"},
            order="created_at.desc",
            limit=20,
        )
    history_text = "\n".join(
        f"{m.get('role')}: {m.get('content')}" for m in reversed(history) if m.get("content")
    )

    # Parse intent (robust: fallback to heuristic if Ollama is down)
    intent = await _parse_intent(ollama, history_text, body.content)

    # Fetch candidate services (loose)
    # In dev anonymous mode, do NOT query Supabase (users may not have the DB schema/policies).
    if use_anon_store:
        services = []
    else:
        services = await db.select(
            jwt_token,
            "services",
            select="id,title,category,description,city,price_range,provider_id",
            limit=200,
        )
    ranked = _rank_services_loose(services, intent)
    top = ranked[:5]
    matched_ids = [s["id"] for s in top]

    assistant_text = _format_service_discovery_answer(intent, top)

    if use_anon_store:
        assistant_row = {
            "id": str(uuid4()),
            "session_id": session_id,
            "user_id": "anon",
            "role": "assistant",
            "content": assistant_text,
            "metadata": {"matched_service_ids": matched_ids, "intent": intent.model_dump()},
            "created_at": now_iso(),
        }
        ANON_SESSIONS.setdefault(session_id, []).append(assistant_row)
    else:
        assistant_row = await db.insert(
            jwt_token,
            "chat_messages",
            {
                "session_id": session_id,
                "user_id": user_id,
                "role": "assistant",
                "content": assistant_text,
                "metadata": {"matched_service_ids": matched_ids, "intent": intent.model_dump()},
            },
        )

    # Update session last_message_at
    if (jwt_token is not None) and (not _dev_anon_enabled()):
        await db.update(
            jwt_token,
            "chat_sessions",
            {"last_message_at": now_iso()},
            filters={"id": f"eq.{session_id}"},
        )

    return PostMessageResponse(assistant_message=assistant_row, matched_service_ids=matched_ids)  # type: ignore[arg-type]


@app.post("/api/survey/submit", response_model=SubmitSurveyResponse)
async def submit_survey(
    body: SubmitSurveyRequest,
    ctx: tuple[str, str] = Depends(auth_context),
    db: SupabaseRest = Depends(get_db),
    ollama: OllamaClient = Depends(get_ollama),
) -> SubmitSurveyResponse:
    user_id, jwt_token = ctx

    # Store survey response
    await db.insert(
        jwt_token,
        "survey_responses",
        {"user_id": user_id, "answers": body.answers},
    )

    # Convert answers into a preference intent
    intent = await _parse_survey_preferences(ollama, body.answers)

    services = await db.select(
        jwt_token,
        "services",
        select="id,title,category,description,city,price_range,provider_id",
        limit=300,
    )
    ranked = _rank_services_loose(services, intent)[:10]

    rec_rows = []
    for idx, s in enumerate(ranked):
        score = float(max(0.0, 100.0 - idx * 3.0))
        reason = _simple_reason(intent, s)
        rec_rows.append({"user_id": user_id, "service_id": s["id"], "score": score, "reason": reason})

    # Store recommendations
    for r in rec_rows:
        await db.insert(jwt_token, "recommendations", r)

    return SubmitSurveyResponse(
        recommendations=[{"service_id": r["service_id"], "score": r["score"], "reason": r["reason"]} for r in rec_rows]
    )


async def _parse_intent(ollama: OllamaClient, history_text: str, message: str) -> ParsedIntent:
    system = (
        "You are a service discovery assistant for a marketplace of local services. "
        "Extract the user's intent for finding a service. If city/category aren't provided, set them to null. "
        "Keep query short."
    )
    schema = '{"query": "string", "city": "string|null", "category": "string|null", "budget": "string|null", "urgency": "string|null", "constraints": ["string"]}'
    prompt = f"Chat so far:\n{history_text}\n\nNew message:\n{message}"
    try:
        obj = await ollama.chat_json(system=system, user=prompt, schema_hint=schema)
        obj.setdefault("query", message)
        return ParsedIntent.model_validate(obj)
    except Exception:
        # Heuristic fallback
        return ParsedIntent(query=message)


async def _parse_survey_preferences(ollama: OllamaClient, answers: dict[str, Any]) -> ParsedIntent:
    system = (
        "You convert a user's survey answers into structured preferences for recommending services. "
        "Return concise fields. If unknown, use null."
    )
    schema = '{"query": "string", "city": "string|null", "category": "string|null", "budget": "string|null", "urgency": "string|null", "constraints": ["string"]}'
    user = f"Survey answers JSON:\n{answers}"
    try:
        obj = await ollama.chat_json(system=system, user=user, schema_hint=schema)
        obj.setdefault("query", "survey")
        return ParsedIntent.model_validate(obj)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"AI service unavailable: {e}") from e


def _rank_services_loose(services: list[dict[str, Any]], intent: ParsedIntent) -> list[dict[str, Any]]:
    q = (intent.query or "").lower()
    city = (intent.city or "").lower()
    cat = (intent.category or "").lower()

    def score(s: dict[str, Any]) -> float:
        t = (s.get("title") or "").lower()
        d = (s.get("description") or "").lower()
        c = (s.get("city") or "").lower()
        k = (s.get("category") or "").lower()
        sc = 0.0
        if q:
            if q in t:
                sc += 4.0
            if q in d:
                sc += 2.0
        if cat:
            if cat == k:
                sc += 3.0
            elif cat in k or k in cat:
                sc += 1.5
        if city:
            if city == c:
                sc += 2.0
            elif city and city in c:
                sc += 1.0
        # Small bonus for having price info
        if s.get("price_range"):
            sc += 0.25
        return sc

    return sorted(services, key=score, reverse=True)


def _format_service_discovery_answer(intent: ParsedIntent, services: list[dict[str, Any]]) -> str:
    parts = []
    if not services:
        return "I couldn't find matching services yet. Tell me your city and what you need (e.g., plumbing, electrician)."

    headline = "Here are a few services you might like:"
    if intent.category or intent.city:
        headline = f"Here are a few services I found{(' in ' + intent.city) if intent.city else ''}{(' for ' + intent.category) if intent.category else ''}:"
    parts.append(headline)

    for s in services:
        title = s.get("title") or "Service"
        city = s.get("city") or ""
        category = s.get("category") or ""
        parts.append(f"- {title} ({category}) — {city} — open: /services/{s.get('id')}")

    parts.append("\nIf you tell me your city and budget, I can narrow this down further.")
    return "\n".join(parts)


def _simple_reason(intent: ParsedIntent, service: dict[str, Any]) -> str:
    bits = []
    if intent.category and (service.get("category") or "").lower() == intent.category.lower():
        bits.append("matches your category")
    if intent.city and (service.get("city") or "").lower() == intent.city.lower():
        bits.append("in your city")
    if not bits:
        bits.append("relevant to your request")
    return ", ".join(bits).capitalize() + "."

