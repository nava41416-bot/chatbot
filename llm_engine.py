"""
LLM Engine — Converts natural language questions to SQL queries and formats results.

This uses a smart template-based approach (no API keys, no heavy models, fully free).
It pattern-matches common question types against the database schema to generate SQL,
and formats query results into natural language answers.
"""

import re
import logging
from datetime import datetime

logger = logging.getLogger("llm_engine")


def generate_sql(question: str, schema: str) -> str:
    """
    Convert a natural language question into a SQL query.

    Uses intelligent pattern matching against the users table schema.
    Returns a SQL SELECT query string, or empty string if not related.
    """
    q = question.lower().strip()

    # ---- Count queries ----
    if any(kw in q for kw in ["how many", "count", "total", "number of", "kitne", "combien", "कितने", "कुल"]):
        if any(kw in q for kw in ["user", "member", "people", "person", "registered", "signup",
                                   "log", "utilisateur", "उपयोगकर्ता"]):
            # Count with date filters
            if any(kw in q for kw in ["today", "aaj", "aujourd'hui", "आज"]):
                return "SELECT COUNT(*) as total_users FROM users WHERE DATE(registered_at) = DATE('now')"
            elif any(kw in q for kw in ["yesterday", "kal", "hier", "कल"]):
                return "SELECT COUNT(*) as total_users FROM users WHERE DATE(registered_at) = DATE('now', '-1 day')"
            elif any(kw in q for kw in ["this week", "is hafte", "cette semaine"]):
                return "SELECT COUNT(*) as total_users FROM users WHERE registered_at >= DATE('now', '-7 days')"
            elif any(kw in q for kw in ["this month", "is mahine", "ce mois"]):
                return "SELECT COUNT(*) as total_users FROM users WHERE registered_at >= DATE('now', 'start of month')"
            else:
                return "SELECT COUNT(*) as total_users FROM users"

    # ---- List / Show all queries ----
    if any(kw in q for kw in ["list", "show", "display", "get all", "all user", "sab", "tous",
                                "sabhi", "dikhao", "दिखाओ", "सभी", "afficher"]):
        if any(kw in q for kw in ["user", "member", "people", "person", "registered",
                                   "utilisateur", "उपयोगकर्ता"]):
            if any(kw in q for kw in ["today", "aaj", "aujourd'hui"]):
                return "SELECT id, name, email, registered_at FROM users WHERE DATE(registered_at) = DATE('now') ORDER BY registered_at DESC"
            elif any(kw in q for kw in ["recent", "latest", "newest", "last", "naye", "récent"]):
                return "SELECT id, name, email, registered_at FROM users ORDER BY registered_at DESC LIMIT 10"
            else:
                return "SELECT id, name, email, registered_at FROM users ORDER BY registered_at DESC"

    # ---- Search by name ----
    name_match = re.search(r'(?:find|search|look for|who is|user named|naam|chercher|ढूंढो)\s+["\']?([a-zA-Z\s]+)["\']?', q)
    if name_match:
        name = name_match.group(1).strip().rstrip('?.,!')
        if name and len(name) > 1:
            return f"SELECT id, name, email, registered_at FROM users WHERE LOWER(name) LIKE '%{name.lower()}%'"

    # ---- Search by email ----
    email_match = re.search(r'(?:email|mail|e-mail)\s+["\']?([^\s"\']+@[^\s"\']+)["\']?', q)
    if email_match:
        email = email_match.group(1).strip()
        return f"SELECT id, name, email, registered_at FROM users WHERE LOWER(email) = '{email.lower()}'"

    if any(kw in q for kw in ["email", "mail", "e-mail"]):
        # Generic email-related query
        email_in_q = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', q)
        if email_in_q:
            return f"SELECT id, name, email, registered_at FROM users WHERE LOWER(email) = '{email_in_q.group().lower()}'"

    # ---- Who registered first / last ----
    if any(kw in q for kw in ["first", "oldest", "earliest", "pehla", "premier"]):
        if any(kw in q for kw in ["user", "member", "person", "registered", "utilisateur"]):
            return "SELECT id, name, email, registered_at FROM users ORDER BY registered_at ASC LIMIT 1"

    if any(kw in q for kw in ["last", "latest", "newest", "most recent", "aakhri", "dernier"]):
        if any(kw in q for kw in ["user", "member", "person", "registered", "utilisateur"]):
            return "SELECT id, name, email, registered_at FROM users ORDER BY registered_at DESC LIMIT 1"

    # ---- Specific user by ID ----
    id_match = re.search(r'(?:user|id)\s*(?:#|number|no\.?)?\s*(\d+)', q)
    if id_match:
        user_id = id_match.group(1)
        return f"SELECT id, name, email, registered_at FROM users WHERE id = {user_id}"

    # ---- General "users" / "data" query ----
    if any(kw in q for kw in ["user", "member", "data", "database", "record", "registration",
                                "registered", "utilisateur", "données", "डेटा", "उपयोगकर्ता"]):
        return "SELECT id, name, email, registered_at FROM users ORDER BY registered_at DESC LIMIT 10"

    # ---- Not related to database ----
    return ""


def format_answer(question: str, sql: str, results: list[dict]) -> str:
    """
    Convert SQL query results into a natural language answer.
    """
    if not results:
        return "No data found matching your query. There may be no users registered yet, or no users match your criteria."

    q = question.lower()

    # ---- Count result ----
    if len(results) == 1 and "total_users" in results[0]:
        count = results[0]["total_users"]
        if "today" in q:
            return f"There are **{count}** users who registered today."
        elif "yesterday" in q:
            return f"There were **{count}** users who registered yesterday."
        elif "week" in q:
            return f"There are **{count}** users who registered this week."
        elif "month" in q:
            return f"There are **{count}** users who registered this month."
        else:
            return f"There are **{count}** registered users in total."

    # ---- Single user result ----
    if len(results) == 1:
        user = results[0]
        name = user.get("name", "Unknown")
        email = user.get("email", "N/A")
        reg = user.get("registered_at", "N/A")
        return f"**{name}** (Email: {email}) — registered on {reg}."

    # ---- Multiple users ----
    lines = []
    for i, user in enumerate(results, 1):
        name = user.get("name", "Unknown")
        email = user.get("email", "N/A")
        reg = user.get("registered_at", "N/A")
        lines.append(f"{i}. **{name}** — {email} (Registered: {reg})")

    header = f"Found **{len(results)}** users:"
    return header + "\n" + "\n".join(lines)


def get_not_related_response() -> str:
    """Return a response for questions not related to the database."""
    return "This question is not related to registered data. I can only answer questions about users in the database — such as how many users are registered, who registered recently, or finding users by name or email."
