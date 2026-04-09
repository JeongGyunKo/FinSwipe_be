# AI News Curation API

미국 주식 시장 관련 영문 뉴스를 자동 수집하고, GenAI로 감성 분석 및 요약을 생성한 뒤 한국어로 번역해 Supabase에 저장하는 백엔드 서비스입니다.

## 기술 스택

- **FastAPI** + **Uvicorn** — 웹 프레임워크
- **APScheduler** — 뉴스 수집/분석 자동화 스케줄러
- **Supabase** — 데이터베이스
- **Finlight API** — 금융 뉴스 수집
- **GenAI 서버** — 감성 분석 + 3줄 요약 생성
- **DeepL API** — 한국어 번역

## 파이프라인 흐름

```
[15분마다] Finlight API → 뉴스 수집
    → content/ticker 없는 기사 필터링
    → Supabase 저장
    → [백그라운드] GenAI 분석 (감성 + 요약)
    → DeepL 번역 (한국어)
    → Supabase 업데이트

[30분마다] 미분석 기사(sentiment NULL) 재분석
[6시간마다] 48시간 지난 기사 삭제
```

## 환경 변수 설정

`.env.example`을 복사해 `.env`를 만들고 값을 채워주세요.

```bash
cp .env.example .env
```

| 변수명 | 설명 |
|--------|------|
| `SUPABASE_URL` | Supabase 프로젝트 URL |
| `SUPABASE_SERVICE_KEY` | Supabase service_role 키 (RLS 우회) |
| `FINLIGHT_API_KEY` | Finlight 뉴스 API 키 |
| `GENAI_URL` | GenAI 서버 URL |
| `GENAI_USER` | GenAI 서버 Basic Auth 아이디 |
| `GENAI_PASSWORD` | GenAI 서버 Basic Auth 비밀번호 |
| `DEEPL_API_KEY` | DeepL Free API 키 (없으면 번역 스킵) |
| `ADMIN_API_KEY` | 관리용 엔드포인트 인증 키 |

## 실행

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API 문서: `http://localhost:8000/docs`

## API 엔드포인트

### 공개
| Method | Path | 설명 |
|--------|------|------|
| GET | `/health` | 서버 상태 확인 |
| GET | `/news/latest` | 최신 뉴스 조회 (limit: 1~100) |
| GET | `/news/genai/health` | GenAI 서버 상태 확인 |

### 관리용 (Header: `X-Admin-Key` 필요)
| Method | Path | 설명 |
|--------|------|------|
| POST | `/news/collect` | 뉴스 수동 수집 트리거 |
| GET | `/news/reanalyze` | 미분석 기사 재분석 트리거 |
| POST | `/news/translate-all` | 미번역 기사 전체 번역 |
| POST | `/news/analyze` | 단일 기사 분석 |
| GET | `/news/analyze/latest` | 최신 기사 일괄 분석 |
| POST | `/news/diagnose` | 특정 기사 GenAI 진단 |
| GET | `/news/test` | DB 연결 테스트 |

## 배포

[Zeabur](https://zeabur.com) 기준으로 GitHub 레포와 연결 후 Variables에 환경변수를 설정하면 자동 배포됩니다.
