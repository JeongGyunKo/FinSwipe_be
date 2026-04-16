# ai-news-curation-be

미국 주식 관련 영문 뉴스 자동 수집 · 감성분석 백엔드

## Stack

FastAPI · Supabase · Finlight · APScheduler · Zeabur

## 파이프라인

```
15분마다  Finlight 수집 (7쿼리 × 100개) → Supabase 저장 → GenAI 분석
30분마다  미분석 기사 재분석
6시간마다 content/ticker 없는 기사 정리
```

## 티커

NYSE + NASDAQ + AMEX 전체 보통주 5,531개 지원  
한국어 이름 474개, 나머지 영문 회사명 표시

## 로컬 실행

```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## 환경변수

| 변수 | 설명 |
|------|------|
| `SUPABASE_URL` | Supabase 프로젝트 URL |
| `SUPABASE_SERVICE_KEY` | Supabase service_role 키 |
| `FINLIGHT_API_KEY` | Finlight API 키 |
| `GENAI_URL` | GenAI 서버 URL |
| `GENAI_USER` | GenAI 인증 유저 |
| `GENAI_PASSWORD` | GenAI 인증 패스워드 |
| `ADMIN_API_KEY` | 관리용 API 키 (16자 이상) |
