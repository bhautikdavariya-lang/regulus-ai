import pytest

from regulus.config import Settings, load_settings


@pytest.fixture(scope="session")
def settings() -> Settings:
    return load_settings(use_dotenv=False)
