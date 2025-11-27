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
    """

    def __init__(self) -> None:
        # openAI
        self.openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")

        # supabase
        self.supabase_url: Optional[str] = os.getenv("SUPABASE_URL")
        self.supabase_anon_key: Optional[str] = os.getenv("SUPABASE_ANON_KEY")
        self.supabase_service_role_key: Optional[str] = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

        # runtime environment (optional convenience flag)
        # e.g. "local", "dev", "prod"
        self.env: str = os.getenv("ENV", "local")

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
    Use this anywhere in the app instead of calling Settings() directly.
    """
    return Settings()