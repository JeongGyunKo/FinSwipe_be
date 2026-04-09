# ai-news-curation-be

미국 주식 관련 영문 뉴스 자동 수집 · 감성분석 · 한국어 번역 백엔드

## Stack

FastAPI · Supabase · Finlight · DeepL · APScheduler · Zeabur

## 파이프라인

```
15분마다  Finlight 수집 → Supabase 저장 → GenAI 분석 → DeepL 번역
30분마다  미분석 기사 재분석
6시간마다 48h 지난 기사 삭제
```

## 로컬 실행

```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload
```
