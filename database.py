"""
Database module — SQLite operations for the AI Database Chatbot.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chatbot.db")


def get_connection():
    """Get a new database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database and create the users table if it doesn't exist."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    print(f"[DB] Database initialized at {DB_PATH}")


def register_user(name: str, email: str) -> dict:
    """Insert a new user into the database."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            (name, email)
        )
        conn.commit()
        user_id = cursor.lastrowid
        return {"success": True, "id": user_id, "name": name, "email": email}
    except sqlite3.IntegrityError:
        return {"success": False, "error": f"Email '{email}' is already registered."}
    finally:
        conn.close()


def execute_safe_query(sql: str) -> list[dict]:
    """Execute a SELECT query and return results (max 100 rows)."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        rows = cursor.fetchmany(100)
        columns = [description[0] for description in cursor.description] if cursor.description else []
        results = [dict(zip(columns, row)) for row in rows]
        return results
    finally:
        conn.close()


def get_schema() -> str:
    """Return the database schema as a text description for context."""
    return """
Table: users
Columns:
  - id (INTEGER, PRIMARY KEY, AUTO INCREMENT)
  - name (TEXT, NOT NULL) — the user's full name
  - email (TEXT, NOT NULL, UNIQUE) — the user's email address
  - registered_at (TIMESTAMP, DEFAULT CURRENT_TIMESTAMP) — when the user registered
""".strip()
