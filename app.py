import os
import re
import json
import logging
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pymongo import MongoClient
import google.generativeai as genai
from langdetect import detect, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException

# ============================================================
# CONFIG & LOGGING
# ============================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("chatbot")
DetectorFactory.seed = 0

app = FastAPI(title="AI Chatbot (Hugging Face)")

# CORS settings for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================
MONGODB_URI = os.environ.get("MONGODB_URI", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ============================================================
# DATABASE LAYER (MongoDB)
# ============================================================
client = None
db = None

def get_db():
    global client, db
    if db is not None:
        return db
    if not MONGODB_URI:
        logger.warning("[DB] MONGODB_URI not set. Registration will fail.")
        return None
    try:
        client = MongoClient(MONGODB_URI)
        db = client.get_database("chatbot_db")
        # Ensure unique index on email
        db.users.create_index("email", unique=True)
        logger.info("[DB] Connected to MongoDB Atlas")
        return db
    except Exception as e:
        logger.error(f"[DB] Connection failed: {e}")
        return None

# ============================================================
# MODELS
# ============================================================
class RegisterRequest(BaseModel):
    name: str
    email: str
    age: int = None
    gender: str = None
    phone: str = None

class ChatRequest(BaseModel):
    message: str

# ============================================================
# UTILS
# ============================================================
LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "te": "Telugu", "ta": "Tamil", "mr": "Marathi"
}

def detect_language(text):
    try:
        if not text or len(text.strip()) < 3:
            return {"code": "en", "name": "English"}
        code = detect(text)
        return {"code": code, "name": LANGUAGE_NAMES.get(code, code.capitalize())}
    except LangDetectException:
        return {"code": "en", "name": "English"}

# ============================================================
# AI ENGINE
# ============================================================
SYSTEM_PROMPT = """You are a helpful assistant for a User Database. 
You can't write SQL. You should instead summarize what the user wants to know about the 'users' collection.

DATABASE SCHEMA:
- name (string)
- email (string)
- age (number)
- gender (string)
- phone (string)
- registered_at (timestamp)

If the user wants to count users, return: ACTION_COUNT
If the user wants to see all users, return: ACTION_LIST
If the user wants to find a specific user, return: ACTION_FIND:[Name or Email]
If unrelated, return: NOT_RELATED
"""

def ai_process_request(question):
    if not GEMINI_API_KEY:
        return "ACTION_LIST" # Fallback
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content([SYSTEM_PROMPT, question])
        return response.text.strip()
    except Exception:
        return "ACTION_LIST"

def format_answer(intent, results):
    if not results:
        return "No users found in the database."
    
    if intent == "ACTION_COUNT":
        return f"There are **{len(results)}** registered users in total."
    
    lines = []
    for i, u in enumerate(results, 1):
        info = f"{i}. **{u.get('name', u.get('name', '?'))}** — {u.get('email', '?')}"
        extras = []
        if u.get('age'): extras.append(f"Age: {u['age']}")
        if u.get('gender'): extras.append(f"{u['gender']}")
        if u.get('phone'): extras.append(f"Ph: {u['phone']}")
        if extras: info += f" ({', '.join(extras)})"
        lines.append(info)
    return f"Found **{len(results)}** users:\n" + "\n".join(lines)

# ============================================================
# API ENDPOINTS
# ============================================================

@app.get("/api/health")
def health():
    return {"status": "ok", "provider": "Hugging Face + MongoDB"}

@app.post("/api/register")
async def register(req: RegisterRequest):
    mongodb = get_db()
    if not mongodb:
        raise HTTPException(500, "Database connection not available")
    
    name = req.name.strip()
    email = req.email.strip().lower()
    
    if not name or "@" not in email:
        raise HTTPException(400, "Valid Name and Email are required.")

    if req.phone:
        digits = re.sub(r'\D', '', req.phone)
        if len(digits) != 10:
            raise HTTPException(400, "Phone number must be exactly 10 digits.")

    try:
        user_data = req.dict()
        user_data["registered_at"] = datetime.now()
        result = mongodb.users.insert_one(user_data)
        user_data["_id"] = str(result.inserted_id)
        user_data["registered_at"] = user_data["registered_at"].isoformat()
        return {"success": True, "message": f"User '{name}' registered!", "user": user_data}
    except Exception as e:
        if "duplicate key" in str(e).lower():
            raise HTTPException(409, f"Email '{email}' is already registered.")
        raise HTTPException(500, str(e))

@app.post("/api/chat")
async def chat(req: ChatRequest):
    message = req.message.strip()
    if not message:
        raise HTTPException(400, "Message required")

    intent = ai_process_request(message)
    mongodb = get_db()
    
    # Query logic
    users = []
    if mongodb:
        cursor = mongodb.users.find().sort("registered_at", -1).limit(50)
        users = list(cursor)
        for u in users:
            u["_id"] = str(u["_id"])
            if isinstance(u.get("registered_at"), datetime):
                u["registered_at"] = u.get("registered_at").isoformat()

    # Filter by AI intent
    if "ACTION_FIND" in intent:
        search = intent.split(":")[-1].strip().lower()
        users = [u for u in users if search in u['name'].lower() or search in u['email'].lower()]
    
    answer = format_answer(intent, users)
    
    return {
        "answer": answer,
        "language": detect_language(message),
        "query": intent
    }

# Serve Frontend
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # Hugging Face Spaces port is usually 7860
    uvicorn.run(app, host="0.0.0.0", port=7860)
