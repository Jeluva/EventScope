"""Central configuration. Every live integration defaults OFF so the pipeline
and the test suite run fully offline with zero credentials."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EVENTSCOPE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Pilot geographic scope (Fase 0: Adrogué / Zona Sur GBA) ---
    pilot_lat: float = -34.7998
    pilot_lng: float = -58.3897
    pilot_radius_km: float = 15.0

    # --- Database. SQLite by default (no external dependency). ---
    database_url: str = "sqlite:///./data/eventscope.db"

    # --- LLM extraction: "stub" | "gemini" | "openai" ---
    llm_provider: str = "stub"
    llm_api_key: str = ""
    llm_model: str = ""

    # --- Embeddings for dedup: "stub" | "sentence-transformers" ---
    embedding_provider: str = "stub"

    # --- Source credentials (all optional) ---
    eventbrite_token: str = ""
    ig_access_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
