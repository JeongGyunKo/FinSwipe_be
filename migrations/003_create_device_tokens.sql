-- device_tokens 테이블 생성
-- 사용자 디바이스 푸시 알림 토큰 저장

CREATE TABLE IF NOT EXISTS public.device_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    token       TEXT NOT NULL,
    platform    TEXT NOT NULL DEFAULT 'web',  -- web / ios / android
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, token)
);

ALTER TABLE public.device_tokens ENABLE ROW LEVEL SECURITY;

CREATE POLICY "device_tokens_own"
    ON public.device_tokens
    USING (auth.uid() = user_id);
