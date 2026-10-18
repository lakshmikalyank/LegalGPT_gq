"""
config.py

Central configuration module for the LegalGPT application.

This module defines the Config class used by the Flask application
factory to configure the app, database, file uploads, mail server,
and RAG (Retrieval Augmented Generation) pipeline settings.

Usage:
    from config import Config
    app.config.from_object(Config)
"""

import os

from dotenv import load_dotenv

# Base directory of the project (the folder containing this file)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Keep downloaded ML models (embeddings, OCR) inside the project folder so
# models fetched during the Render *build* are still present at runtime.
MODEL_CACHE_DIR = os.environ.get(
    "MODEL_CACHE_DIR", os.path.join(BASE_DIR, "model_cache")
)
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", MODEL_CACHE_DIR)
os.environ.setdefault("HF_HOME", os.path.join(MODEL_CACHE_DIR, "hf"))

# Load variables from a .env file in the project root into the process
# environment, before Config reads any of them via os.environ.get().
# Existing OS-level environment variables always take precedence over
# .env values (override=False), which is dotenv's default behavior.
load_dotenv(os.path.join(BASE_DIR, ".env"))


class Config:
    """
    Application configuration class.

    All configuration values are defined as class attributes so that
    Flask can load them directly via `app.config.from_object(Config)`.

    In a production deployment, secret values (SECRET_KEY, mail
    credentials, etc.) should be supplied via environment variables
    instead of being hardcoded here.
    """

    # ------------------------------------------------------------------
    # Core Flask settings
    # ------------------------------------------------------------------

    # Secret key used for session signing, CSRF protection, etc.
    # In production, always set this via an environment variable.
    # On Render (the RENDER env var is set automatically) a missing key
    # is a hard error so the insecure dev default can never be used in
    # production. Locally, the dev default is still allowed.
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if not SECRET_KEY:
        if os.environ.get("RENDER"):
            raise RuntimeError(
                "SECRET_KEY environment variable must be set in production."
            )
        SECRET_KEY = "dev-secret-key-change-this-in-production-2024"

    # ------------------------------------------------------------------
    # Database settings (SQLite via Flask-SQLAlchemy)
    # ------------------------------------------------------------------

    # Path to the SQLite database file
    # Render/Heroku-style "postgres://" URLs are normalised to the
    # "postgresql://" scheme SQLAlchemy 2.x requires.
    _db_url = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + os.path.join(BASE_DIR, "legalgpt.db")
    )
    if _db_url.startswith("postgres://"):
        _db_url = "postgresql://" + _db_url[len("postgres://"):]
    SQLALCHEMY_DATABASE_URI = _db_url
    # Recycle pooled connections so a managed Postgres doesn't hand out
    # stale ones (harmless for SQLite).
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Insert the default advocate records (idempotently) on startup.
    SEED_ADVOCATES_ON_STARTUP = (
        os.environ.get("SEED_ADVOCATES_ON_STARTUP", "true").lower() == "true"
    )

    # Disable modification tracking to save resources; not needed
    # unless using Flask-SQLAlchemy event signals.
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Print SQL statements to console when True (useful for debugging)
    SQLALCHEMY_ECHO = False

    # ------------------------------------------------------------------
    # File upload settings
    # ------------------------------------------------------------------

    # Directory where uploaded PDF/DOCX documents are stored. Overridable
    # via UPLOAD_FOLDER so a Render persistent disk (e.g. mounted at
    # /var/data) can be used in production without changing the code.
    UPLOAD_FOLDER = os.environ.get(
        "UPLOAD_FOLDER", os.path.join(BASE_DIR, "uploads")
    )

    # Directory where AI-generated PDF documents are stored
    GENERATED_FOLDER = os.environ.get(
        "GENERATED_FOLDER", os.path.join(BASE_DIR, "generated_docs")
    )

    # Maximum allowed upload size: 16 MB
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    # Allowed file extensions for document uploads
    ALLOWED_EXTENSIONS = {"pdf", "docx", "jpg", "jpeg", "png"}

    MODEL_CACHE_DIR = MODEL_CACHE_DIR

    # Safeguards for OCR (images and scanned PDFs)
    OCR_MAX_PDF_PAGES = int(os.environ.get("OCR_MAX_PDF_PAGES", 10))
    OCR_MAX_IMAGE_PIXELS = 25_000_000  # reject absurdly large images
    OCR_MAX_IMAGE_SIDE = 2400  # downscale larger images before OCR
    # EasyOCR language groups, ";"-separated, each a ","-separated list.
    # Default keeps the original English+Hindi and English+Telugu readers.
    # Use e.g. OCR_LANGUAGE_GROUPS="en" to cut memory use on small instances.
    OCR_LANGUAGE_GROUPS = [
        [l.strip() for l in grp.split(",") if l.strip()]
        for grp in os.environ.get("OCR_LANGUAGE_GROUPS", "en,hi;en,te").split(";")
        if grp.strip()
    ]

    # ------------------------------------------------------------------
    # ChromaDB / Vector store settings
    # ------------------------------------------------------------------

    # Directory where the persistent Chroma vector database is stored.
    # Overridable via CHROMA_DB_DIR for the same persistent-disk reason
    # as UPLOAD_FOLDER/GENERATED_FOLDER above.
    CHROMA_DB_DIR = os.environ.get(
        "CHROMA_DB_DIR", os.path.join(BASE_DIR, "chroma_db")
    )

    # Name of the collection used to store document embeddings
    CHROMA_COLLECTION_NAME = "legalgpt_documents"

    # ------------------------------------------------------------------
    # Embedding model settings (SentenceTransformers)
    # ------------------------------------------------------------------
    # Default is small (~80MB) and safe for Render's 512MB free tier,
    # but is English-optimized — retrieval quality for non-English
    # source documents (Hindi/Telugu/Tamil, etc.) is weaker with it.
    #
    # For better multilingual retrieval quality, you can override this
    # via the EMBEDDING_MODEL_NAME env var with a multilingual model,
    # e.g. "paraphrase-multilingual-MiniLM-L12-v2". Be aware that model
    # is roughly 5-6x larger (~470MB) and may not fit safely alongside
    # everything else on a 512MB instance — test carefully before
    # relying on it in production on the free tier.
    EMBEDDING_MODEL_NAME = os.environ.get(
        "EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2"
    )

    # ------------------------------------------------------------------
    # Text chunking settings (for RAG pipeline)
    # ------------------------------------------------------------------

    CHUNK_SIZE = 600
    CHUNK_OVERLAP = 100

    # ------------------------------------------------------------------
    # Groq / LLM settings
    # ------------------------------------------------------------------
    # All AI features (chat, RAG, document analysis, translation,
    # summarization) run on the Groq API via LangChain's ChatGroq.

    # Groq API key (console.groq.com/keys). Required in production —
    # set this via an environment variable, never hardcode it here.
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

    # Model used for chat (RAG Q&A) and document analysis.
    #
    # Groq deprecated "llama-3.3-70b-versatile" (shutdown 08/16/2026;
    # see console.groq.com/docs/deprecations) in favor of
    # "openai/gpt-oss-120b", which Groq's own migration guidance
    # describes as delivering "exceptional performance with faster
    # inference" than the model it replaces. gpt-oss-120b is a strong,
    # general-purpose reasoning model well suited to every AI feature
    # here (chat, RAG, document analysis, translation, summarization),
    # so it — not the deprecated 3.3 70B — is the default.
    GROQ_MODEL_NAME = os.environ.get("GROQ_MODEL_NAME", "openai/gpt-oss-120b")

    # Translation quality for lower-resource Indian languages can benefit
    # from a different (e.g. larger/more capable) model than the one used
    # for analysis/chat, without slowing those down. Defaults to the same
    # model as GROQ_MODEL_NAME if not explicitly set.
    GROQ_TRANSLATION_MODEL_NAME = os.environ.get(
        "GROQ_TRANSLATION_MODEL_NAME", GROQ_MODEL_NAME
    )

    # Ordered fallback models, tried in order if GROQ_MODEL_NAME (or
    # GROQ_TRANSLATION_MODEL_NAME) turns out to be unavailable/retired
    # at request time. Only used when the failure looks like "this
    # specific model is unavailable" (a 404/decommissioned-style
    # error); it is never used to retry an invalid-API-key, rate-limit,
    # or network error, since switching models can't fix those.
    # qwen/qwen3.6-27b is Groq's other officially recommended
    # replacement for the deprecated llama-3.3-70b-versatile;
    # openai/gpt-oss-20b is the smaller/faster sibling model, used as a
    # last resort. Override with a comma-separated list via the
    # GROQ_FALLBACK_MODELS env var if needed.
    GROQ_FALLBACK_MODELS = [
        m.strip()
        for m in os.environ.get(
            "GROQ_FALLBACK_MODELS",
            "openai/gpt-oss-120b,qwen/qwen3.6-27b,openai/gpt-oss-20b",
        ).split(",")
        if m.strip()
    ]
    

    # Number of top-matching chunks to retrieve for each query
    RETRIEVER_TOP_K = 2

    # ------------------------------------------------------------------
    # Flask-Login settings
    # ------------------------------------------------------------------

    REMEMBER_COOKIE_DURATION_DAYS = 7

    # ------------------------------------------------------------------
    # Mail / SMTP settings (for emailing generated documents)
    # ------------------------------------------------------------------

    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "your-email@gmail.com")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "your-app-password")
    MAIL_DEFAULT_SENDER = os.environ.get(
        "MAIL_DEFAULT_SENDER", MAIL_USERNAME
    )

    # ------------------------------------------------------------------
    # Pagination settings
    # ------------------------------------------------------------------

    DOCUMENTS_PER_PAGE = 10
    ADVOCATES_PER_PAGE = 10
    CHAT_HISTORY_PER_PAGE = 20

    # ------------------------------------------------------------------
    # Admin settings
    # ------------------------------------------------------------------

    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@legalgpt.com")

    @classmethod
    def init_app(cls, app):
        """
        Perform any additional initialization that requires the app
        instance (e.g., creating required directories).

        Args:
            app: The Flask application instance.
        """
        os.makedirs(cls.UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(cls.GENERATED_FOLDER, exist_ok=True)
        os.makedirs(cls.CHROMA_DB_DIR, exist_ok=True)