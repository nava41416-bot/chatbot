"""
Language Detection module — detects the language of user input.
"""

from langdetect import detect, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException

# Make detection deterministic
DetectorFactory.seed = 0

# Language code to name mapping
LANGUAGE_NAMES = {
    "en": "English", "fr": "French", "es": "Spanish", "de": "German",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "ru": "Russian",
    "zh-cn": "Chinese", "zh-tw": "Chinese", "ja": "Japanese", "ko": "Korean",
    "ar": "Arabic", "hi": "Hindi", "ur": "Urdu", "tr": "Turkish",
    "pl": "Polish", "sv": "Swedish", "da": "Danish", "no": "Norwegian",
    "fi": "Finnish", "cs": "Czech", "ro": "Romanian", "hu": "Hungarian",
    "th": "Thai", "vi": "Vietnamese", "id": "Indonesian", "ms": "Malay",
    "bn": "Bengali", "ta": "Tamil", "te": "Telugu", "mr": "Marathi",
}


def detect_language(text: str) -> dict:
    """
    Detect the language of the given text.

    Returns:
        {"code": "en", "name": "English"}
    """
    try:
        if not text or len(text.strip()) < 3:
            return {"code": "en", "name": "English"}

        code = detect(text)
        name = LANGUAGE_NAMES.get(code, code.capitalize())
        return {"code": code, "name": name}
    except LangDetectException:
        return {"code": "en", "name": "English"}
