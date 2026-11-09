"""Application configuration loaded from environment variables.

All secrets (LLM keys, Google credentials, admin password) come from the
environment or from files excluded from Git. Nothing here is sent to the
frontend except the non-secret `public_runtime_info()` summary.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # --- LLM -----------------------------------------------------------
    # auto -> openai if OPENAI_API_KEY, gemini if GOOGLE_API_KEY, else offline
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "auto").lower())
    openai_api_key: str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY") or None)
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    google_api_key: str | None = field(default_factory=lambda: os.getenv("GOOGLE_API_KEY") or None)
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
    llm_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_SECONDS", "30")))
    llm_max_retries: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_RETRIES", "2")))
    llm_temperature: float = field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0")))

    # --- Data source ---------------------------------------------------
    # auto -> google_sheets if credentials + spreadsheet id present, else local_demo
    data_source: str = field(default_factory=lambda: os.getenv("DATA_SOURCE", "auto").lower())
    google_sheets_spreadsheet_id: str | None = field(
        default_factory=lambda: os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID") or None
    )
    google_service_account_file: str | None = field(
        default_factory=lambda: os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or None
    )
    sheets_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("SHEETS_TIMEOUT_SECONDS", "10")))
    sheets_cache_seconds: float = field(default_factory=lambda: float(os.getenv("SHEETS_CACHE_SECONDS", "30")))

    # --- Persistence ---------------------------------------------------
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", str(BACKEND_DIR / "data"))))

    # --- Admin auth ----------------------------------------------------
    admin_username: str = field(default_factory=lambda: os.getenv("ADMIN_USERNAME", "admin"))
    admin_password: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", "change-me"))
    auth_secret: str = field(default_factory=lambda: os.getenv("AUTH_SECRET", "dev-secret-change-me"))
    token_ttl_minutes: int = field(default_factory=lambda: int(os.getenv("TOKEN_TTL_MINUTES", "480")))

    # --- Agent bounds --------------------------------------------------
    max_agent_steps: int = field(default_factory=lambda: int(os.getenv("MAX_AGENT_STEPS", "12")))
    max_revisions: int = field(default_factory=lambda: int(os.getenv("MAX_REVISIONS", "2")))

    # --- Uploads -------------------------------------------------------
    max_upload_bytes: int = field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024))))

    # --- Email (Gmail SMTP) ---------------------------------------------
    # auto -> gmail if GMAIL_ADDRESS + GMAIL_APP_PASSWORD are set, else demo_outbox (nothing is sent)
    email_mode: str = field(default_factory=lambda: os.getenv("EMAIL_MODE", "auto").lower())
    gmail_address: str | None = field(default_factory=lambda: os.getenv("GMAIL_ADDRESS") or None)
    gmail_app_password: str | None = field(
        default_factory=lambda: (os.getenv("GMAIL_APP_PASSWORD") or "").replace(" ", "") or None
    )
    # If set, every customer email is delivered here instead of the order's address (safe for demos).
    email_demo_recipient: str | None = field(default_factory=lambda: os.getenv("EMAIL_DEMO_RECIPIENT") or None)
    email_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("EMAIL_TIMEOUT_SECONDS", "15")))

    cors_origins: list[str] = field(
        default_factory=lambda: os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    )

    # ------------------------------------------------------------------
    @property
    def resolved_llm_provider(self) -> str:
        p = self.llm_provider
        if p == "auto":
            if self.openai_api_key:
                return "openai"
            if self.google_api_key:
                return "gemini"
            return "offline"
        return p

    @property
    def resolved_data_source(self) -> str:
        d = self.data_source
        if d == "auto":
            if self.google_sheets_spreadsheet_id and self.google_service_account_file and Path(
                self.google_service_account_file
            ).exists():
                return "google_sheets"
            return "local_demo"
        return d

    @property
    def resolved_email_mode(self) -> str:
        if self.email_mode == "auto":
            return "gmail" if self.gmail_address and self.gmail_app_password else "demo_outbox"
        return self.email_mode

    @property
    def db_path(self) -> Path:
        return self.data_dir / "resolveai.db"

    @property
    def checkpoint_path(self) -> Path:
        return self.data_dir / "checkpoints.db"

    @property
    def evidence_dir(self) -> Path:
        return self.data_dir / "evidence"

    def public_runtime_info(self) -> dict:
        provider = self.resolved_llm_provider
        return {
            "planner": provider,
            "planner_label": {
                "openai": f"LLM tool-calling agent (OpenAI {self.openai_model})",
                "gemini": f"LLM tool-calling agent (Gemini {self.gemini_model})",
                "offline": "OFFLINE DEMO PLANNER (deterministic, no LLM key configured)",
            }.get(provider, provider),
            "data_source": self.resolved_data_source,
            "data_source_label": {
                "google_sheets": "Google Sheets",
                "local_demo": "LOCAL DEMO DATA (not Google Sheets)",
            }.get(self.resolved_data_source, self.resolved_data_source),
            "email_mode": self.resolved_email_mode,
            "email_label": (
                f"Gmail ({self.gmail_address}"
                + (f" -> all mail to {self.email_demo_recipient})" if self.email_demo_recipient else ")")
                if self.resolved_email_mode == "gmail"
                else "DEMO OUTBOX (emails recorded, not sent)"
            ),
            "demo_mode": provider == "offline" or self.resolved_data_source == "local_demo"
            or self.resolved_email_mode != "gmail",
        }


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.evidence_dir.mkdir(parents=True, exist_ok=True)
    return s
