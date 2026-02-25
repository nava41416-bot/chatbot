"""
AI Database Chatbot — Vercel Serverless + Supabase PostgreSQL + Google Gemini AI
- Database: Supabase PostgreSQL (set DATABASE_URL env var)
- AI: Google Gemini API (set GEMINI_API_KEY env var)
"""

import os
import re
import json
import logging
from datetime import datetime
from urllib.parse import urlparse, unquote
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
from langdetect import detect, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException
import google.generativeai as genai

# ============================================================
# CONFIG
# ============================================================

DetectorFactory.seed = 0
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("chatbot")

# Build DATABASE_URL from individual env vars (as set in Vercel) or use direct DATABASE_URL
_db_url = os.environ.get("DATABASE_URL", "").strip()
if not _db_url:
    _host = os.environ.get("DB_HOST", "").strip()
    _user = os.environ.get("DB_USER", "").strip()
    _password = os.environ.get("DB_PASSWORD", "").strip()
    _port = os.environ.get("DB_PORT", "6543").strip()
    _name = os.environ.get("DB_NAME", "postgres").strip()
    if _host and _user and _password:
        import urllib.parse
        _password_encoded = urllib.parse.quote_plus(_password)
        _db_url = f"postgresql://{_user}:{_password_encoded}@{_host}:{_port}/{_name}"
DATABASE_URL = _db_url
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# Individual DB params (preferred — avoids URL encoding issues with special chars in password)
DB_HOST = os.environ.get("DB_HOST", "").strip()
DB_USER = os.environ.get("DB_USER", "").strip()
DB_PASSWORD = os.environ.get("DB_PASSWORD", "").strip()
DB_PORT_STR = os.environ.get("DB_PORT", "6543").strip()
DB_PORT = int(DB_PORT_STR) if DB_PORT_STR.isdigit() else 6543
DB_NAME = os.environ.get("DB_NAME", "postgres").strip()

# Configure Gemini AI
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ============================================================
# DATABASE LAYER (Supabase PostgreSQL)
# ============================================================

DB_SCHEMA = """
Table: users
Columns:
  - id (SERIAL, PRIMARY KEY, auto-increment)
  - name (TEXT, NOT NULL) — the user's full name
  - email (TEXT, NOT NULL, UNIQUE) — the user's email address
  - age (INTEGER) — the user's age in years
  - gender (TEXT) — the user's gender (Male, Female, Other)
  - phone (TEXT) — the user's phone number
  - registered_at (TIMESTAMP, DEFAULT NOW()) — when the user registered
""".strip()


def get_connection():
    """Get Supabase PostgreSQL connection. Prefers individual DB_* vars over DATABASE_URL."""
    # Use individual params if available (avoids URL encoding issues with special chars)
    if DB_HOST and DB_USER and DB_PASSWORD:
        return psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            dbname=DB_NAME,
            sslmode='require',
            connect_timeout=10,
            cursor_factory=RealDictCursor
        )
    # Fall back to DATABASE_URL
    if not DATABASE_URL:
        raise Exception("No DB credentials set. Configure DB_HOST/DB_USER/DB_PASSWORD or DATABASE_URL.")
    
    # Try direct connection string first (psycopg2 handles URIs natively)
    try:
        return psycopg2.connect(DATABASE_URL, sslmode='require', cursor_factory=RealDictCursor)
    except Exception as e:
        logger.warning(f"[DB] Direct connection failed, trying manual parse: {e}")
        parsed = urlparse(DATABASE_URL)
        user = unquote(parsed.username) if parsed.username else None
        password = unquote(parsed.password) if parsed.password else None
        host = parsed.hostname
        port = parsed.port or 5432
        dbname = parsed.path.lstrip('/') if parsed.path else 'postgres'
        return psycopg2.connect(
            host=host, port=port, user=user, password=password,
            dbname=dbname, sslmode='require', cursor_factory=RealDictCursor
        )



def init_db():
    """Create users table if it doesn't exist."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            age INTEGER,
            gender TEXT,
            phone TEXT,
            registered_at TIMESTAMP DEFAULT NOW()
        )
    """)
    # Add new columns if table already exists (safe migration)
    for col, col_type in [("age", "INTEGER"), ("gender", "TEXT"), ("phone", "TEXT")]:
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
            conn.commit()
        except Exception:
            conn.rollback()
    conn.commit()
    cur.close()
    conn.close()
    logger.info("[DB] Supabase PostgreSQL ready")


def db_insert_user(name: str, email: str, age: int = None, gender: str = None, phone: str = None) -> dict:
    """Insert a new user."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (name, email, age, gender, phone) VALUES (%s, %s, %s, %s, %s) RETURNING id, name, email, age, gender, phone, registered_at",
            (name, email, age, gender, phone)
        )
        user = dict(cur.fetchone())
        # Convert datetime to string for JSON serialization
        if isinstance(user.get("registered_at"), datetime):
            user["registered_at"] = user["registered_at"].isoformat()
        conn.commit()
        return {"success": True, "user": user}
    except Exception as e:
        conn.rollback()
        error_msg = str(e)
        if "unique" in error_msg.lower() or "duplicate" in error_msg.lower():
            return {"success": False, "error": f"Email '{email}' is already registered."}
        return {"success": False, "error": error_msg}
    finally:
        cur.close()
        conn.close()


def db_execute_query(sql: str) -> list:
    """Execute a SELECT query, return list of dicts."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql)
        rows = cur.fetchmany(100)
        results = []
        for row in rows:
            row_dict = dict(row)
            # Convert datetime objects to strings for JSON serialization
            for key, value in row_dict.items():
                if isinstance(value, datetime):
                    row_dict[key] = value.isoformat()
            results.append(row_dict)
        return results
    finally:
        cur.close()
        conn.close()


# ============================================================
# LANGUAGE DETECTION
# ============================================================

LANGUAGE_NAMES = {
    "en": "English", "fr": "French", "es": "Spanish", "de": "German",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "ru": "Russian",
    "zh-cn": "Chinese", "ja": "Japanese", "ko": "Korean",
    "ar": "Arabic", "hi": "Hindi", "ur": "Urdu", "tr": "Turkish",
    "bn": "Bengali", "ta": "Tamil", "te": "Telugu", "mr": "Marathi",
}


def detect_language(text: str) -> dict:
    try:
        if not text or len(text.strip()) < 3:
            return {"code": "en", "name": "English"}
        code = detect(text)
        return {"code": code, "name": LANGUAGE_NAMES.get(code, code.capitalize())}
    except LangDetectException:
        return {"code": "en", "name": "English"}


# ============================================================
# SQL SAFETY VALIDATOR
# ============================================================

BLOCKED_KEYWORDS = [
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE",
    "TRUNCATE", "EXEC", "EXECUTE", "GRANT", "REVOKE",
]


def validate_sql(query: str) -> tuple:
    if not query or not query.strip():
        return False, "Empty query."
    cleaned = query.strip()
    if not cleaned.upper().startswith("SELECT"):
        return False, "Only SELECT queries are allowed."
    for kw in BLOCKED_KEYWORDS:
        if re.search(r'\b' + kw + r'\b', cleaned.upper()):
            return False, f"Blocked keyword: {kw}"
    if re.search(r";\s*", cleaned):
        return False, "Multiple statements not allowed."
    if "--" in cleaned or "/*" in cleaned:
        return False, "Comments not allowed."
    return True, "Safe."


# ============================================================
# AI ENGINE — Google Gemini (NL → SQL)
# ============================================================

SYSTEM_PROMPT = f"""You are a SQL expert assistant. Your job is to convert natural language questions into PostgreSQL SELECT queries.

DATABASE SCHEMA:
{DB_SCHEMA}

RULES:
1. ONLY generate SELECT queries. Never INSERT, UPDATE, DELETE, DROP, or any other modification.
2. Return ONLY the raw SQL query, nothing else. No explanation, no markdown, no code blocks.
3. If the question is NOT related to users/database, return exactly: NOT_RELATED
4. Use PostgreSQL syntax (e.g., CURRENT_DATE, NOW(), ILIKE for case-insensitive).
5. Limit results to 50 rows maximum unless the user asks for a specific count.
6. The user may ask in ANY language (Hindi, French, Spanish, etc.). Understand their intent regardless of language.

EXAMPLES:
- "How many users?" → SELECT COUNT(*) as total_users FROM users
- "Show all users" → SELECT id, name, email, registered_at FROM users ORDER BY registered_at DESC LIMIT 50
- "Find user John" → SELECT id, name, email, registered_at FROM users WHERE name ILIKE '%John%'
- "Who registered today?" → SELECT id, name, email, registered_at FROM users WHERE DATE(registered_at) = CURRENT_DATE ORDER BY registered_at DESC
- "kitne users hain?" → SELECT COUNT(*) as total_users FROM users
- "What is the weather?" → NOT_RELATED
"""


def ai_generate_sql(question: str) -> str:
    """Use Google Gemini to convert natural language to SQL."""
    if not GEMINI_API_KEY:
        logger.warning("[AI] No GEMINI_API_KEY set — falling back to basic matching")
        return fallback_generate_sql(question)

    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(
            [
                {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
                {"role": "model", "parts": [{"text": "Understood. I will convert natural language questions to PostgreSQL SELECT queries only, and return NOT_RELATED for unrelated questions."}]},
                {"role": "user", "parts": [{"text": question}]},
            ]
        )

        sql = response.text.strip()

        # Clean up: remove markdown code blocks if Gemini wraps them
        sql = re.sub(r'^```(?:sql)?\s*', '', sql)
        sql = re.sub(r'\s*```$', '', sql)
        sql = sql.strip()

        logger.info(f"[AI] Gemini generated: {sql}")

        if sql.upper() == "NOT_RELATED" or not sql.upper().startswith("SELECT"):
            return ""

        return sql

    except Exception as e:
        logger.error(f"[AI] Gemini error: {e}")
        return fallback_generate_sql(question)


def fallback_generate_sql(question: str) -> str:
    """Basic fallback if Gemini is unavailable."""
    q = question.lower().strip()

    if any(kw in q for kw in ["how many", "count", "total", "number of", "kitne", "combien"]):
        if any(kw in q for kw in ["user", "member", "people", "person", "registered", "signup"]):
            return "SELECT COUNT(*) as total_users FROM users"

    if any(kw in q for kw in ["list", "show", "display", "get all", "all user", "sab", "tous", "sabhi"]):
        if any(kw in q for kw in ["user", "member", "people", "person", "registered"]):
            return "SELECT id, name, email, age, gender, phone, registered_at FROM users ORDER BY registered_at DESC LIMIT 50"

    if any(kw in q for kw in ["user", "member", "data", "database", "record", "registration"]):
        return "SELECT id, name, email, age, gender, phone, registered_at FROM users ORDER BY registered_at DESC LIMIT 10"

    return ""


def format_answer(question: str, results: list) -> str:
    """Convert query results into a natural language answer."""
    if not results:
        return "No data found. There may be no users registered yet."
    q = question.lower()

    if len(results) == 1 and "total_users" in results[0]:
        count = results[0]["total_users"]
        if "today" in q:
            return f"There are **{count}** users who registered today."
        return f"There are **{count}** registered users in total."

    if len(results) == 1:
        u = results[0]
        parts = [f"**{u.get('name', '?')}** (Email: {u.get('email', '?')})"]
        if u.get('age'): parts.append(f"Age: {u['age']}")
        if u.get('gender'): parts.append(f"Gender: {u['gender']}")
        if u.get('phone'): parts.append(f"Phone: {u['phone']}")
        parts.append(f"Registered: {u.get('registered_at', '?')}")
        return " — ".join(parts)

    lines = []
    for i, u in enumerate(results, 1):
        info = f"{i}. **{u.get('name', '?')}** — {u.get('email', '?')}"
        extras = []
        if u.get('age'): extras.append(f"Age: {u['age']}")
        if u.get('gender'): extras.append(f"{u['gender']}")
        if u.get('phone'): extras.append(f"Ph: {u['phone']}")
        if extras: info += f" ({', '.join(extras)})"
        lines.append(info)
    return f"Found **{len(results)}** users:\n" + "\n".join(lines)


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(title="AI Database Chatbot", version="3.0.0")


class RegisterRequest(BaseModel):
    name: str
    email: str
    age: int = None
    gender: str = None
    phone: str = None


class ChatRequest(BaseModel):
    message: str


@app.on_event("startup")
def startup():
    try:
        init_db()
        logger.info("[APP] Chatbot started — Supabase + Gemini AI")
    except Exception as e:
        logger.error(f"[APP] DB init error: {e}")


@app.get("/")
def serve_ui():
    paths = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "index.html"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", "index.html"),
    ]
    for p in paths:
        if os.path.exists(p):
            return FileResponse(p)
    return HTMLResponse("<h1>AI Database Chatbot</h1><p>Use /api/health to check status.</p>")


@app.get("/api/health")
def health():
    has_db = bool(DATABASE_URL)
    has_ai = bool(GEMINI_API_KEY)
    return {
        "status": "ok",
        "database": "Supabase PostgreSQL" if has_db else "NOT CONFIGURED",
        "ai_engine": "Google Gemini" if has_ai else "Fallback (basic matching)",
        "message": "AI Database Chatbot is running"
    }


@app.post("/api/register")
def register(req: RegisterRequest):
    if not req.name or not req.name.strip():
        raise HTTPException(400, "Name is required.")
    if not req.email or "@" not in req.email:
        raise HTTPException(400, "Valid email is required.")
    if req.phone:
        digits = re.sub(r'\D', '', req.phone)
        if len(digits) != 10:
            raise HTTPException(400, "Phone number must be exactly 10 digits.")

    # Ensure table + columns exist
    try:
        init_db()
    except Exception as e:
        logger.error(f"[DB] init_db failed: {e}")

    result = db_insert_user(
        name=req.name.strip(),
        email=req.email.strip().lower(),
        age=req.age,
        gender=req.gender.strip() if req.gender else None,
        phone=req.phone.strip() if req.phone else None
    )
    if result["success"]:
        return {
            "success": True,
            "message": f"User '{result['user']['name']}' registered successfully!",
            "user": result["user"]
        }
    else:
        raise HTTPException(409, result["error"])


@app.get("/api/debug")
def debug():
    """Debug endpoint to test DB connection."""
    info = {
        "database_url_set": bool(DATABASE_URL),
        "gemini_key_set": bool(GEMINI_API_KEY),
        "db_host_len": len(DB_HOST),
        "db_user_len": len(DB_USER),
        "db_password_len": len(DB_PASSWORD),
        "database_url_start": DATABASE_URL[:15] + "..." if DATABASE_URL else "",
    }
    # Show parsed URL components (masks password) for debugging
    if DATABASE_URL:
        try:
            parsed = urlparse(DATABASE_URL)
            info["parsed_scheme"] = parsed.scheme
            info["parsed_user"] = unquote(parsed.username) if parsed.username else None
            info["parsed_host"] = parsed.hostname
            info["parsed_port"] = parsed.port
            info["parsed_path"] = parsed.path
        except Exception as pe:
            info["url_parse_error"] = str(pe)
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'users' ORDER BY ordinal_position")
        info["columns"] = [{"name": r["column_name"], "type": r["data_type"]} for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) as cnt FROM users")
        info["user_count"] = cur.fetchone()["cnt"]
        cur.close()
        conn.close()
        info["db_connection"] = "OK"
    except Exception as e:
        import traceback
        info["db_error"] = str(e)
        info["db_traceback"] = traceback.format_exc()
    return info


@app.post("/api/chat")
def chat(req: ChatRequest):
    if not req.message or not req.message.strip():
        raise HTTPException(400, "Message is required.")

    question = req.message.strip()
    lang = detect_language(question)

    # Use AI to generate SQL
    sql = ai_generate_sql(question)

    if not sql:
        return {
            "answer": "This question doesn't seem related to the user database. I can answer questions about registered users — like how many there are, who registered recently, or finding users by name or email.",
            "language": lang,
            "query": None,
            "related": False
        }

    # Validate SQL safety
    is_safe, reason = validate_sql(sql)
    if not is_safe:
        return {
            "answer": f"I generated a query but it was blocked for safety: {reason}",
            "language": lang,
            "query": sql,
            "related": True,
            "blocked": True
        }

    # Execute query
    try:
        results = db_execute_query(sql)
    except Exception as e:
        logger.error(f"[CHAT] Query error: {e}")
        return {
            "answer": "Sorry, there was a database error. Please try rephrasing your question.",
            "language": lang,
            "query": sql,
            "related": True,
            "error": str(e)
        }

    answer = format_answer(question, results)
    return {
        "answer": answer,
        "language": lang,
        "query": sql,
        "results_count": len(results),
        "related": True
    }
