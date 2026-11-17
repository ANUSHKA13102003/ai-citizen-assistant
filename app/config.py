"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    """Shared default configuration matching the IEEE BT-90 paper and extensions."""

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-change-in-production")
    SQLALCHEMY_DATABASE_URI = _default_db_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Gemini SDK configuration
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"

    # Paper baseline pipeline constants
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))
    TOP_K_MAX = int(os.getenv("TOP_K_MAX", "20"))
    HISTORY_WINDOW = int(os.getenv("HISTORY_WINDOW", "6"))
    CHROMA_COLLECTION_PREFIX = os.getenv("CHROMA_COLLECTION_PREFIX", "citizen_documents")

    # Feature flags for improvements beyond the paper
    RETRIEVAL_MODE = os.getenv("RETRIEVAL_MODE", "hybrid").strip().lower()
    ENABLE_RERANKER = _as_bool(os.getenv("ENABLE_RERANKER"), False)
    RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
    ENABLE_OCR_FALLBACK = _as_bool(os.getenv("ENABLE_OCR_FALLBACK"), True)
    ENABLE_TABLE_EXTRACTION = _as_bool(os.getenv("ENABLE_TABLE_EXTRACTION"), True)
    ENABLE_MULTILINGUAL = _as_bool(os.getenv("ENABLE_MULTILINGUAL"), True)
    TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip()

    # Security, upload limits, and session expiry
    SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "60"))
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH_MB", "25")) * 1024 * 1024
    MAX_FILE_SIZE_BYTES = int(os.getenv("MAX_FILE_SIZE_MB", "15")) * 1024 * 1024
    MAX_FILES_PER_SESSION = int(os.getenv("MAX_FILES_PER_SESSION", "10"))
    MAX_PAGES_PER_PDF = int(os.getenv("MAX_PAGES_PER_PDF", "100"))
    RATE_LIMIT_DEFAULT = f"{os.getenv('RATE_LIMIT_PER_MINUTE', '30')} per minute"
    RATELIMIT_STORAGE_URI = "memory://"
    RATELIMIT_HEADERS_ENABLED = True

    WTF_CSRF_TIME_LIMIT = 3600
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    SAMPLES_DIR = BASE_DIR / "data" / "samples"
    EVAL_RESULTS_PATH = BASE_DIR / "eval" / "results.json"


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = _as_bool(os.getenv("SESSION_COOKIE_SECURE"), False)


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
