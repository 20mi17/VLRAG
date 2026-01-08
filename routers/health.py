from fastapi import APIRouter
from config import get_settings
from supabase_client import get_supabase

router = APIRouter()

@router.get("/health")
def health_basic():
    return {"status": "ok"}

@router.get("/health/deep")
def health_deep():
    # 1) Check env vars exist (won't return secrets)
    try:
        _ = get_settings()
    except Exception as e:
        return {"status": "error", "checks": {"env": "missing_or_invalid"}, "detail": str(e)}

    # 2) Check Supabase connectivity
    try:
        supabase = get_supabase()
        # simplest possible query: fetch 1 row from a known table
        resp = supabase.table("documents").select("id").limit(1).execute()
        # if no exception, connection and auth are fine
        return {"status": "ok", "checks": {"env": "ok", "supabase": "ok"}}
    except Exception as e:
        return {"status": "error", "checks": {"env": "ok", "supabase": "failed"}, "detail": str(e)}
