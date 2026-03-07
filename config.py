import os
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv

# load .env in local dev only; on Render the variables come from the environment.
load_dotenv()


class Settings:
    """
    Central place for configuration.
    Reads environment variables for:
    - OpenAI
    - Supabase
    - Generic runtime environment marker (ENV)
    - Upload staging settings
    """

    def __init__(self) -> None:
        # OpenAI
        self.openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")

        # Supabase
        self.supabase_url: Optional[str] = os.getenv("SUPABASE_URL")
        self.supabase_anon_key: Optional[str] = os.getenv("SUPABASE_ANON_KEY")
        self.supabase_service_role_key: Optional[str] = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

        # Runtime environment
        self.env: str = os.getenv("ENV", "local")

        # Upload staging config
        self.upload_staging_bucket: str = os.getenv("UPLOAD_STAGING_BUCKET", "user-uploads-staging")
        self.max_upload_size_mb: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "25"))

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)


@lru_cache
def get_settings() -> Settings:
    """
    Cached accessor so we only read env vars once.
    """
    return Settings()


def get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_required_settings():
    return {
        "SUPABASE_URL": get_env("SUPABASE_URL"),
        "SUPABASE_SERVICE_ROLE_KEY": get_env("SUPABASE_SERVICE_ROLE_KEY"),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "ENV": os.getenv("ENV", "dev"),
        "UPLOAD_STAGING_BUCKET": os.getenv("UPLOAD_STAGING_BUCKET", "user-uploads-staging"),
        "MAX_UPLOAD_SIZE_MB": os.getenv("MAX_UPLOAD_SIZE_MB", "25"),
    }