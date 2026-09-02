from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    environment: str = Field(
        default="development", validation_alias="PATENT_EVIDENCE_ENVIRONMENT"
    )
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
    mfa_encryption_key: SecretStr = Field(
        default="pIfjx_eVKj7GkCcljbw2n9XWLy4NbWzGiDsPicJeC5U=",
        validation_alias="PATENT_EVIDENCE_MFA_ENCRYPTION_KEY",
    )
    expose_development_tokens: bool = Field(
        default=False,
        validation_alias="PATENT_EVIDENCE_EXPOSE_DEVELOPMENT_TOKENS",
    )
    disable_mfa: bool = Field(
        default=False,
        validation_alias="PATENT_EVIDENCE_DISABLE_MFA",
    )
    password_work_workers: int = Field(
        default=2,
        ge=1,
        le=4,
        validation_alias="PATENT_EVIDENCE_PASSWORD_WORK_WORKERS",
    )
    password_work_queue: int = Field(
        default=4,
        ge=0,
        le=16,
        validation_alias="PATENT_EVIDENCE_PASSWORD_WORK_QUEUE",
    )

    @model_validator(mode="after")
    def require_deployment_mfa_key(self) -> "Settings":
        development_key = "pIfjx_eVKj7GkCcljbw2n9XWLy4NbWzGiDsPicJeC5U="
        if (
            self.environment != "development"
            and self.mfa_encryption_key.get_secret_value() == development_key
        ):
            raise ValueError(
                "a deployment MFA encryption key is required outside development"
            )
        if self.environment != "development" and self.expose_development_tokens:
            raise ValueError(
                "development token exposure is forbidden outside development"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
