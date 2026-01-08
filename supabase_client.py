from __future__ import annotations

from typing import Optional

from supabase import Client, create_client

from config import get_settings


_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """
    Lazy singleton Supabase client.

    - Uses SUPABASE_SERVICE_ROLE_KEY if present, otherwise SUPABASE_ANON_KEY.
    - Does not print/log secrets.
    """
    global _client
    if _client is not None:
        return _client

    settings = get_settings()

    if not settings.supabase_url:
        raise RuntimeError("Missing SUPABASE_URL")

    key = settings.supabase_service_role_key or settings.supabase_anon_key
    if not key:
        raise RuntimeError("Missing SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY")

    _client = create_client(settings.supabase_url, key)
    return _client
