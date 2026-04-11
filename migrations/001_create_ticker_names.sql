-- ticker_names 테이블 생성
-- 미국 주식 티커 → 영문/한국어 회사명 매핑

CREATE TABLE IF NOT EXISTS ticker_names (
    ticker TEXT PRIMARY KEY,
    corp   TEXT NOT NULL,
    ko     TEXT NOT NULL
);

-- 한국어 이름으로 검색할 수 있도록 인덱스
CREATE INDEX IF NOT EXISTS idx_ticker_names_ko   ON ticker_names USING gin(to_tsvector('simple', ko));
CREATE INDEX IF NOT EXISTS idx_ticker_names_corp ON ticker_names USING gin(to_tsvector('simple', corp));

-- RLS: 누구나 읽을 수 있음 (FE 직접 조회 허용)
ALTER TABLE ticker_names ENABLE ROW LEVEL SECURITY;

CREATE POLICY "ticker_names_public_read"
    ON ticker_names FOR SELECT
    USING (true);
