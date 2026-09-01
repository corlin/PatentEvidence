import pytest
from pydantic import ValidationError

from patent_evidence_api.core.settings import Settings


def test_non_development_requires_a_deployment_mfa_key() -> None:
    with pytest.raises(ValidationError, match="deployment MFA encryption key"):
        Settings(environment="production")


def test_non_development_cannot_expose_reset_tokens() -> None:
    with pytest.raises(ValidationError, match="token exposure is forbidden"):
        Settings(
            environment="production",
            mfa_encryption_key="E2iW82J-0jQ3AIOaPRdJbaMxFxoMr5yVUOmNe7MnP4Q=",
            expose_development_tokens=True,
        )


def test_password_work_pool_has_conservative_defaults() -> None:
    settings = Settings()

    assert settings.password_work_workers == 2
    assert settings.password_work_queue == 4


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("password_work_workers", 0),
        ("password_work_workers", 5),
        ("password_work_queue", -1),
        ("password_work_queue", 17),
    ],
)
def test_password_work_pool_rejects_unsafe_capacity(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})
