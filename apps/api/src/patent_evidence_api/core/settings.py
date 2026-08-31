from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    environment: str = Field(default="development", validation_alias="PATENT_EVIDENCE_ENVIRONMENT")
    database_url: str = Field(
        default="postgresql+asyncpg://patent_evidence_app@localhost/patent_evidence",
        validation_alias=AliasChoices("PATENT_EVIDENCE_DATABASE_URL", "DATABASE_URL"),
    )
    platform_database_url: str = Field(
        default="postgresql+asyncpg://patent_evidence_platform@localhost/patent_evidence",
        validation_alias="PATENT_EVIDENCE_PLATFORM_DATABASE_URL",
    )
    worker_database_url: str = Field(
        default="postgresql+asyncpg://patent_evidence_worker@localhost/patent_evidence",
        validation_alias="PATENT_EVIDENCE_WORKER_DATABASE_URL",
    )
    migration_database_url: str | None = Field(
        default=None,
        validation_alias="PATENT_EVIDENCE_MIGRATION_DATABASE_URL",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
