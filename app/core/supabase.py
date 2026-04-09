from supabase import create_client
from app.core.config import settings

# 서비스 클라이언트 (BE 내부용 - RLS 우회)
supabase_admin = create_client(settings.supabase_url, settings.supabase_service_key)