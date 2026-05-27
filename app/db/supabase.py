from supabase import create_client, Client
from app.core.config import settings

# Backend client: uses service_role key when available (bypasses RLS)
# Falls back to anon key for backward compatibility
supabase_key = settings.SUPABASE_SERVICE_KEY or settings.SUPABASE_KEY
supabase: Client = create_client(
    settings.SUPABASE_URL,
    supabase_key
)

# Anon client for dashboard/RLS-aware operations
supabase_anon: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_KEY
)
