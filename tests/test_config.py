import pytest
from pydantic import ValidationError

from src.config import Settings


def test_pepper_required_outside_development():
    with pytest.raises(ValidationError):
        Settings(env="production", api_key_pepper="")


def test_pepper_optional_in_development():
    settings = Settings(env="development", api_key_pepper="")

    assert settings.api_key_pepper == ""


def test_pepper_accepted_when_set_in_production():
    settings = Settings(env="production", api_key_pepper="a-real-secret")

    assert settings.env == "production"
