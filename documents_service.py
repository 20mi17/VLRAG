from __future__ import annotations

from typing import Any, Optional

from supabase_client import get_supabase_client


def supabase_ping() -> bool:
    """
    check if Supabase connection is live, returns ONLY TRUE/FALSE, no metadata.
    """
    try:
        sb = get_supabase_client()
        # Assumes a 'documents' table exists with an 'id' column.
        sb.table("documents").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def get_document(doc_id: str) -> Optional[dict[str, Any]]:
    """
    retrieve a document by ID from Supabase.
    returns:
      - dict if found
      - None if not found
    Raises:
      - exceptions for unexpected issues (caller should translate to 500)
    """
    sb = get_supabase_client()
    res = (
        sb.table("documents")
        .select("*")
        .eq("id", doc_id)
        .limit(1)
        .execute()
    )

    data = getattr(res, "data", None)
    if not data:
        return None
    return data[0]
