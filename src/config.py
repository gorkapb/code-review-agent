from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@localhost:5432/code_review"
    redis_url: str = "redis://localhost:6379"
    service_name: str = "code-review-agent"
    service_version: str = "0.1.0"
    env: str = "development"
    log_level: str = "INFO"
    github_api_base_url: str = ""
    github_token: str = ""
    gh_token: str = ""
    anthropic_api_base_url: str = "https://api.anthropic.com"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"
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

    @property
    def database_async_url(self) -> str:
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)


settings = Settings()
