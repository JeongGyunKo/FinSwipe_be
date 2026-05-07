-- device_tokens: 알림 설정 토글 컬럼 추가
ALTER TABLE public.device_tokens
    ADD COLUMN IF NOT EXISTS notify_all_news BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS notify_sentiment_news BOOLEAN NOT NULL DEFAULT true;

-- user_profiles: 메인카드 노출 순서 정렬 컬럼 추가
ALTER TABLE public.user_profiles
    ADD COLUMN IF NOT EXISTS card_sort_order TEXT NOT NULL DEFAULT 'latest';
