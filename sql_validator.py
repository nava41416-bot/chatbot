"""
SQL Safety Validator — ensures only safe SELECT queries are executed.
"""

import re
import logging

logger = logging.getLogger("sql_validator")

# Dangerous SQL keywords that must be blocked
BLOCKED_KEYWORDS = [
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE",
    "TRUNCATE", "EXEC", "EXECUTE", "GRANT", "REVOKE", "MERGE",
    "REPLACE", "ATTACH", "DETACH", "PRAGMA", "VACUUM",
]

# Dangerous patterns
BLOCKED_PATTERNS = [
    r";\s*",           # semicolons (multi-statement)
    r"--",             # line comments
    r"/\*",            # block comments
    r"INTO\s+OUTFILE", # file writes
    r"LOAD_FILE",      # file reads
]


def validate_sql(query: str) -> tuple[bool, str]:
    """
    Validate that a SQL query is safe to execute.

    Returns:
        (is_safe, reason) — True if the query is safe, with a reason string.
    """
    if not query or not query.strip():
        return False, "Empty query."

    cleaned = query.strip()

    # Log the generated SQL
    logger.info(f"[SQL VALIDATOR] Checking query: {cleaned}")

    # Must start with SELECT
    if not cleaned.upper().startswith("SELECT"):
        return False, "Only SELECT queries are allowed."

    # Check for blocked keywords
    upper_query = cleaned.upper()
    for keyword in BLOCKED_KEYWORDS:
        # Match as whole word to avoid false positives (e.g., "UPDATED_AT")
        pattern = r'\b' + keyword + r'\b'
        if re.search(pattern, upper_query):
            return False, f"Query contains blocked keyword: {keyword}"

    # Check for blocked patterns
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, cleaned, re.IGNORECASE):
            return False, f"Query contains a blocked pattern."

    return True, "Query is safe."
