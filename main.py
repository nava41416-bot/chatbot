"""
Cloud-Based AI Database Chatbot — FastAPI Server
No API keys, No OpenAI, Fully Offline.
"""

import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr
from database import init_db, register_user, execute_safe_query, get_schema
from sql_validator import validate_sql
from language_detector import detect_language
from llm_engine import generate_sql, format_answer, get_not_related_response

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("chatbot")

# Initialize FastAPI app
app = FastAPI(
    title="AI Database Chatbot",
    description="Cloud-based AI chatbot — No API keys, No OpenAI, Fully Offline",
    version="1.0.0"
)

# Mount static files
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---- Pydantic Models ----

class RegisterRequest(BaseModel):
    name: str
    email: str
    age: int = None
    gender: str = None
    phone: str = None

class ChatRequest(BaseModel):
    message: str


# ---- Startup Event ----

@app.on_event("startup")
def startup():
    init_db()
    logger.info("Chatbot server started — fully offline, no API keys.")


# ---- Endpoints ----

@app.get("/")
def serve_ui():
    """Serve the chat web UI."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "message": "AI Database Chatbot is running (offline, no API keys)."}


@app.post("/api/register")
def register(req: RegisterRequest):
    """Register a new user in the database."""
    if not req.name or not req.name.strip():
        raise HTTPException(status_code=400, detail="Name is required.")
    if not req.email or not req.email.strip():
        raise HTTPException(status_code=400, detail="Email is required.")
    if "@" not in req.email:
        raise HTTPException(status_code=400, detail="Invalid email address.")

    result = register_user(
        name=req.name.strip(),
        email=req.email.strip().lower(),
        age=req.age,
        gender=req.gender.strip() if req.gender else None,
        phone=req.phone.strip() if req.phone else None
    )

    if result["success"]:
        logger.info(f"[REGISTER] New user: {result['name']} ({result['email']})")
        return {
            "success": True,
            "message": f"User '{result['name']}' registered successfully!",
            "user": result
        }
    else:
        raise HTTPException(status_code=409, detail=result["error"])


@app.post("/api/chat")
def chat(req: ChatRequest):
    """Process a natural language question about the database."""
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="Message is required.")

    question = req.message.strip()
    logger.info(f"[CHAT] Question: {question}")

    # Step 1: Detect language
    lang = detect_language(question)
    logger.info(f"[CHAT] Detected language: {lang['name']} ({lang['code']})")

    # Step 2: Get database schema
    schema = get_schema()

    # Step 3: Generate SQL from question
    sql = generate_sql(question, schema)

    if not sql:
        # Question not related to database
        logger.info("[CHAT] Question not related to database.")
        return {
            "answer": get_not_related_response(),
            "language": lang,
            "sql": None,
            "related": False
        }

    logger.info(f"[CHAT] Generated SQL: {sql}")

    # Step 4: Validate SQL safety
    is_safe, reason = validate_sql(sql)
    if not is_safe:
        logger.warning(f"[CHAT] Unsafe SQL blocked: {reason}")
        return {
            "answer": f"I cannot execute that query. Reason: {reason}",
            "language": lang,
            "sql": sql,
            "related": True,
            "blocked": True
        }

    # Step 5: Execute query
    try:
        results = execute_safe_query(sql)
        logger.info(f"[CHAT] Query returned {len(results)} rows.")
    except Exception as e:
        logger.error(f"[CHAT] Query execution error: {e}")
        return {
            "answer": "Sorry, there was an error executing the query. Please try rephrasing your question.",
            "language": lang,
            "sql": sql,
            "related": True,
            "error": str(e)
        }

    # Step 6: Format answer
    answer = format_answer(question, sql, results)
    logger.info(f"[CHAT] Answer: {answer[:100]}...")

    return {
        "answer": answer,
        "language": lang,
        "sql": sql,
        "results_count": len(results),
        "related": True
    }


# ---- Run Server ----

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))

    # Try ngrok for public URL (free tier)
    try:
        from pyngrok import ngrok
        public_url = ngrok.connect(port)
        logger.info(f"{'='*50}")
        logger.info(f"PUBLIC URL: {public_url}")
        logger.info(f"{'='*50}")
    except Exception as e:
        logger.info(f"[INFO] ngrok not available: {e}")
        logger.info(f"[INFO] Running on http://localhost:{port}")

    uvicorn.run(app, host="0.0.0.0", port=port)
