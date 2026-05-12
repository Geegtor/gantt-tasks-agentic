from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    cors_origin: str = "http://localhost:5173"
    llm_provider: str = "openai"  # openai | gemini | yandex | gigachat | mock
    llm_model: str = "gpt-4o-mini"
    openai_api_key: str = ""
    gemini_api_key: str = ""
    # Yandex Cloud Foundation Models (YandexGPT): https://yandex.cloud/en/docs/foundation-models/
    yandex_api_key: str = ""  # "Api-Key ..." value without prefix, or full key for Authorization
    yandex_folder_id: str = ""
    yandex_model_uri: str = ""  # optional; default gpt://<folder>/yandexgpt/latest
    yandex_completion_url: str = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    # Sber GigaChat: https://developers.sber.ru/docs/ru/gigachat/api/overview
    gigachat_client_id: str = ""
    gigachat_client_secret: str = ""
    gigachat_oauth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    gigachat_api_url: str = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    max_chat_turns_per_session: int = 50
    max_tasks_in_prompt: int = 200
    llm_request_timeout_seconds: int = 60
    max_tasks_total: int = 200
    max_commands_per_batch: int = 50
    # How many delete_task ops a single chat turn may execute without the
    # YES_DELETE_BULK confirmation phrase.  Override via MAX_DELETES_PER_BATCH
    # in the environment / .env.  Default is generous (200) so normal bulk
    # operations work without manual env tweaks.
    max_deletes_per_batch: int = 200

    # PostgreSQL (async). Empty = persistence disabled (in-memory only; tests / local without DB).
    database_url: str = ""
    run_migrations_on_start: bool = True

    @field_validator("database_url", mode="before")
    @classmethod
    def fix_postgres_scheme(cls, v: str) -> str:
        """Render provides postgresql:// but asyncpg requires postgresql+asyncpg://."""
        if v and v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    # RAG / exemplar replay
    replay_similarity_threshold: float = 0.95
    # Stricter ceiling when using HashBag (256-dim); dense OpenAI embeddings use replay_similarity_threshold.
    replay_similarity_threshold_hash: float = 0.92
    exemplar_search_limit: int = 5
    embedding_model: str = "text-embedding-3-small"


@lru_cache
def get_settings() -> Settings:
    return Settings()
