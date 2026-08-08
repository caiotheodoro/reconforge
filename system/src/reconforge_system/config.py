"""Environment-driven settings (pydantic-settings). No secrets in code."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILES = [".env", ".env.local", str(Path(__file__).resolve().parents[3] / ".env")]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Kafka
    kafka_broker: str = "localhost:9092"
    kafka_retries: int = 3
    kafka_retry_backoff_s: float = 0.5
    decision_consumer_group: str = "reconforge-decision"

    # Services
    ledger_url: str = "http://localhost:9103"
    hitl_url: str = "http://localhost:9105"
    model_service_url: str = "http://localhost:9100/v1"
    model_service_model: str = "mlx-model"

    # Model provider (DeepSeek, judge/cadence LLM calls)
    model_provider_base_url: str = "https://api.deepseek.com"
    model_provider_model_id: str = "deepseek-v4-flash"
    model_provider_api_key: str = ""

    # Temporal Cloud
    temporal_host: str = ""
    temporal_namespace: str = ""
    temporal_cloud_account_id: str = ""
    temporal_cloud_api_key: str = ""
    temporal_task_queue: str = "reconforge-main"
    review_timeout_hours: int = 24

    # Postgres
    postgres_user: str = "reconforge"
    postgres_password: str = "reconforge_local"
    postgres_db: str = "reconforge"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # Decision thresholds
    decision_confidence_threshold: float = 0.6
    decision_escalate_severities: str = "HIGH"
    decision_consume: bool = False

    # Drift / cadence
    drift_psi_threshold: float = 0.10
    drift_stats_window_hours: int = 168
    drift_baseline_json: str = (
        '{"AMOUNT_MISMATCH":0.30,"FX_CONVERSION_ERROR":0.25,"BENEFICIARY_MISMATCH":0.15,'
        '"COUNTERPARTY_MISMATCH":0.10,"VALUE_DATE_MISMATCH":0.08,"MISSING_MESSAGE":0.05,'
        '"PARTIAL_MATCH":0.03,"DUPLICATE":0.02,"FIELD_CORRUPTION":0.02}'
    )

    # Cadence schedules
    contamination_cron: str = "0 3 * * *"
    recalibration_cron: str = "0 4 * * 1"
    drift_cron: str = "0 * * * *"

    @field_validator("drift_baseline_json", mode="before")
    @classmethod
    def _coerce_baseline(cls, v: object) -> object:
        if isinstance(v, dict):
            return json.dumps(v)
        return v

    @property
    def escalate_severities(self) -> list[str]:
        return [s.strip().upper() for s in self.decision_escalate_severities.split(",") if s.strip()]

    @property
    def drift_baseline(self) -> dict[str, float]:
        return json.loads(self.drift_baseline_json)

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def temporal_configured(self) -> bool:
        return bool(self.temporal_host and self.temporal_namespace and self.temporal_cloud_api_key)


def load_settings() -> Settings:
    for path in ENV_FILES:
        if path.startswith("/") and os.path.exists(path):
            from dotenv import load_dotenv

            load_dotenv(path)
    return Settings()
