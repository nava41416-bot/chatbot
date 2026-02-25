import os
import re
import json
import logging
from datetime import datetime
from firebase_functions import https_fn, options
from firebase_admin import initialize_app, firestore
import google.generativeai as genai
from langdetect import detect, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException

# Initialize Firebase Admin
initialize_app()
db = firestore.client()

# ============================================================
# CONFIG
# ============================================================
DetectorFactory.seed = 0
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("chatbot")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ============================================================
# DATABASE LAYER (Firestore)
# ============================================================

def db_insert_user(name, email, age=None, gender=None, phone=None):
    """Insert a new user into Firestore."""
    try:
        # Check if email exists
        users_ref = db.collection("users")
        existing_users = users_ref.where("email", "==", email).get()
        if existing_users:
            return {"success": False, "error": f"Email '{email}' is already registered."}

        new_user = {
            "name": name,
            "email": email,
            "age": age,
            "gender": gender,
            "phone": phone,
            "registered_at": datetime.now()
        }
        
        doc_ref = users_ref.document()
        doc_ref.set(new_user)
        
        # Format for return
        new_user["id"] = doc_ref.id
        new_user["registered_at"] = new_user["registered_at"].isoformat()
        
        return {"success": True, "user": new_user}
    except Exception as e:
        logger.error(f"[DB] Firestore insert error: {e}")
        return {"success": False, "error": str(e)}

def db_query_users(limit=50):
    """Fetch all users from Firestore."""
    try:
        users_ref = db.collection("users").order_by("registered_at", direction=firestore.Query.DESCENDING).limit(limit)
        docs = users_ref.get()
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            if isinstance(data.get("registered_at"), datetime):
                data["registered_at"] = data["registered_at"].isoformat()
            results.append(data)
        return results
    except Exception as e:
        logger.error(f"[DB] Firestore query error: {e}")
        return []

# ============================================================
# LANGUAGE DETECTION
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
# AI ENGINE (NL → Firestore Intent)
# ============================================================

SYSTEM_PROMPT = """You are a helpful assistant for a User Database. 
You can't write SQL anymore. You should instead summarize what the user wants to know about the 'users' collection.

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
    """Use Gemini to understand intent for Firestore."""
    if not GEMINI_API_KEY:
        return "ACTION_LIST" # Fallback

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content([SYSTEM_PROMPT, question])
        return response.text.strip()
    except Exception as e:
        logger.error(f"[AI] Gemini error: {e}")
        return "ACTION_LIST"

def format_answer(intent, results):
    if not results:
        return "No data found."
    
    if intent == "ACTION_COUNT":
        return f"There are **{len(results)}** registered users in total."
    
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
# FIREBASE FUNCTIONS (API)
# ============================================================

@https_fn.on_request(cors=options.CorsOptions(cors_origins="*", cors_methods=["GET", "POST"]))
def api(req: https_fn.Request) -> https_fn.Response:
    path = req.path.strip("/")
    
    if path == "api/health":
        return https_fn.Response(json.dumps({"status": "ok", "engine": "Firebase + Firestore + Gemini"}), mimetype="application/json")

    if path == "api/register" and req.method == "POST":
        try:
            data = req.get_json()
            name = data.get("name", "").strip()
            email = data.get("email", "").strip().lower()
            age = data.get("age")
            gender = data.get("gender")
            phone = data.get("phone")

            if not name or not email:
                return https_fn.Response(json.dumps({"detail": "Name and Email are required."}), status=400, mimetype="application/json")

            if phone:
                digits = re.sub(r'\D', '', phone)
                if len(digits) != 10:
                    return https_fn.Response(json.dumps({"detail": "Phone must be 10 digits."}), status=400, mimetype="application/json")

            result = db_insert_user(name, email, age, gender, phone)
            if result["success"]:
                return https_fn.Response(json.dumps({"success": True, "message": f"User '{name}' registered!", "user": result["user"]}), mimetype="application/json")
            else:
                return https_fn.Response(json.dumps({"detail": result["error"]}), status=409, mimetype="application/json")
        except Exception as e:
            return https_fn.Response(json.dumps({"detail": str(e)}), status=500, mimetype="application/json")

    if path == "api/chat" and req.method == "POST":
        try:
            data = req.get_json()
            message = data.get("message", "").strip()
            if not message:
                return https_fn.Response(json.dumps({"detail": "Message required."}), status=400, mimetype="application/json")

            intent = ai_process_request(message)
            results = db_query_users() # For now, fetch all and format
            
            # Simple filtering logic for FIREBASE (can be improved)
            if "ACTION_FIND" in intent:
                search_term = intent.split(":")[-1].strip().lower()
                results = [u for u in results if search_term in u['name'].lower() or search_term in u['email'].lower()]

            answer = format_answer(intent, results)
            return https_fn.Response(json.dumps({
                "answer": answer,
                "language": detect_language(message),
                "query": intent
            }), mimetype="application/json")
        except Exception as e:
            return https_fn.Response(json.dumps({"detail": str(e)}), status=500, mimetype="application/json")

    return https_fn.Response("Chatbot API", status=200)
