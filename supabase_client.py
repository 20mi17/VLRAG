from supabase import create_client
from config import get_settings

def get_supabase():
    s = get_settings()
    return create_client(s["SUPABASE_URL"], s["SUPABASE_SERVICE_ROLE_KEY"])
