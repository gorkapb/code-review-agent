from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@127.0.0.1:15432/code_review"
    db_pool_size: int = 5
    db_max_overflow: int = 5
    redis_url: str = "redis://127.0.0.1:16379"
    service_name: str = "code-review-agent"
    service_version: str = "0.1.0"
    env: str = "development"
    log_level: str = "INFO"
    github_api_base_url: str = ""
    github_token: str = ""
    anthropic_api_base_url: str = "https://api.anthropic.com"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"
    # Server-side secret for HMAC-keyed hashing of API keys. Set per environment;
    # rotating it invalidates every existing key (they'd need re-hashing/re-issue).
    api_key_pepper: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = ""
    langfuse_tracing_enabled: bool = True
    langfuse_capture_content: bool = False
    langfuse_debug: bool = False
    langfuse_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    otel_enabled: bool = True
    otel_traces_enabled: bool = True
    otel_metrics_enabled: bool = True
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_traces_endpoint: str = ""
    otel_exporter_otlp_metrics_endpoint: str = ""
    otel_exporter_otlp_headers: str = ""
    otel_exporter_otlp_timeout: float = 10.0
    otel_metric_export_interval_millis: float = 60000.0
    otel_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    openai_api_key: str = ""
    eval_judge_model: str = "gpt-4o-mini"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "code_review"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _require_api_key_pepper_outside_dev(self) -> "Settings":
        # An empty pepper silently degrades HMAC to a keyed hash with a public
        # (empty) key — effectively plain SHA-256. Refuse to boot insecurely
        # anywhere but local development, where convenience wins.
        if self.env != "development" and not self.api_key_pepper:
            raise ValueError(
                "api_key_pepper must be set when env is not 'development'."
            )
        return self

    @property
    def database_async_url(self) -> str:
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    @property
    def langfuse_url(self) -> str:
        return (self.langfuse_base_url or "https://cloud.langfuse.com").rstrip("/")


settings = Settings()
