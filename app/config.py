"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def clean_model_name(raw: str | None) -> str:
    """Normalise GEMINI_MODEL values such as 'GEMINI_MODEL=x', 'models/x' or quoted strings."""
    value = (raw or "").strip().strip('"').strip("'")
    while value.upper().startswith("GEMINI_MODEL="):
        value = value.split("=", 1)[1].strip()
    if value.startswith("models/"):
        value = value[len("models/") :]
    return value or DEFAULT_GEMINI_MODEL


def _default_db_uri() -> str:
    instance_dir = BASE_DIR / "instance"
    instance_dir.mkdir(parents=True, exist_ok=True)
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        return f"sqlite:///{(instance_dir / 'citizen_assistant.db').as_posix()}"
    if db_url.startswith("sqlite:///") and not db_url.startswith("sqlite:////"):
        rel_path = db_url.removeprefix("sqlite:///")
        abs_path = (BASE_DIR / rel_path).resolve()
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{abs_path.as_posix()}"
    return db_url


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-change-in-production")
    SQLALCHEMY_DATABASE_URI = _default_db_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = _as_bool(os.getenv("FLASK_DEBUG"), False)

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL = clean_model_name(os.getenv("GEMINI_MODEL"))

    # Core RAG pipeline
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1200"))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))
    TOP_K_MAX = int(os.getenv("TOP_K_MAX", "20"))
    HISTORY_WINDOW = int(os.getenv("HISTORY_WINDOW", "6"))
    CHROMA_COLLECTION_PREFIX = os.getenv("CHROMA_COLLECTION_PREFIX", "citizen_documents")

    # Retrieval and extraction options
    RETRIEVAL_MODE = os.getenv("RETRIEVAL_MODE", "hybrid").strip().lower()
    ENABLE_RERANKER = _as_bool(os.getenv("ENABLE_RERANKER"), True)
    RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
    ENABLE_OCR_FALLBACK = _as_bool(os.getenv("ENABLE_OCR_FALLBACK"), True)
    ENABLE_TABLE_EXTRACTION = _as_bool(os.getenv("ENABLE_TABLE_EXTRACTION"), True)
    ENABLE_MULTILINGUAL = _as_bool(os.getenv("ENABLE_MULTILINGUAL"), True)
    TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip()

    # Limits and privacy
    ADMIN_KEY = os.getenv("ADMIN_KEY", "").strip()
    DAILY_GEMINI_CAP = int(os.getenv("DAILY_GEMINI_CAP", "500"))
    SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "60"))
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH_MB", "25")) * 1024 * 1024
    MAX_FILE_SIZE_BYTES = int(os.getenv("MAX_FILE_SIZE_MB", "15")) * 1024 * 1024
    MAX_FILES_PER_SESSION = int(os.getenv("MAX_FILES_PER_SESSION", "10"))
    MAX_PAGES_PER_PDF = int(os.getenv("MAX_PAGES_PER_PDF", "100"))
    RATE_LIMIT_DEFAULT = f"{os.getenv('RATE_LIMIT_PER_MINUTE', '30')} per minute"
    RATELIMIT_STORAGE_URI = "memory://"
    RATELIMIT_HEADERS_ENABLED = True

    WTF_CSRF_TIME_LIMIT = None
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    SAMPLES_DIR = BASE_DIR / "data" / "samples"
    SCHEMES_PATH = BASE_DIR / "data" / "schemes" / "schemes.json"
    EVAL_RESULTS_PATH = BASE_DIR / "data" / "eval" / "results.json"


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    ENABLE_RERANKER = False


class ProductionConfig(BaseConfig):
    SESSION_COOKIE_SECURE = _as_bool(os.getenv("SESSION_COOKIE_SECURE"), False)


CONFIG_MAP = {
    "development": BaseConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
