import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core.supabase import supabase_admin

logger = logging.getLogger(__name__)
router = APIRouter()


def _mask_email(email: str) -> str:
    """이메일 마스킹: sw22tm1dn1ght@gmail.com → sw2***@gmail.com"""
    try:
        local, domain = email.split("@")
        masked_local = local[:3] + "***"
        return f"{masked_local}@{domain}"
    except Exception:
        return "***@***.com"


class FindEmailRequest(BaseModel):
    login_id: str


class FindLoginIdRequest(BaseModel):
    email: str


@router.post("/find-email")
async def find_email(body: FindEmailRequest):
    """login_id로 가입 이메일 조회 (마스킹 처리)"""
    try:
        result = supabase_admin.table("user_profiles") \
            .select("email") \
            .eq("login_id", body.login_id.strip()) \
            .execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="해당 아이디로 가입된 계정을 찾을 수 없습니다.")

        email = result.data[0].get("email") or ""
        if not email:
            raise HTTPException(status_code=404, detail="이메일 정보가 없습니다.")

        return {"masked_email": _mask_email(email)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[이메일 찾기] 오류: {e}")
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")


@router.post("/find-login-id")
async def find_login_id(body: FindLoginIdRequest):
    """이메일로 login_id 조회"""
    try:
        result = supabase_admin.table("user_profiles") \
            .select("login_id") \
            .eq("email", body.email.strip().lower()) \
            .execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="해당 이메일로 가입된 계정을 찾을 수 없습니다.")

        login_id = result.data[0].get("login_id") or ""
        if not login_id:
            raise HTTPException(status_code=404, detail="아이디 정보가 없습니다.")

        return {"login_id": login_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[아이디 찾기] 오류: {e}")
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")
