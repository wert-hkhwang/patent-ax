# API (FastAPI)

특허 AI 검색 시스템 백엔드 API

## 실행

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

## 주요 엔드포인트

### POST /workflow/chat/stream
SSE 스트리밍 채팅 API

```json
{
  "query": "수소연료전지 특허 TOP 10",
  "session_id": "user-123",
  "level": "L1"
}
```

### GET /health
헬스체크

## 파일 구조

```
api/
├── main.py          # FastAPI 앱 및 라우터
├── config.py        # Qdrant 컬렉션 설정
├── streaming.py     # SSE 스트리밍 응답
└── models.py        # Pydantic 모델
```

## SSE 이벤트 타입

| 이벤트 | 설명 |
|--------|------|
| text | 응답 텍스트 청크 |
| perspective_summary | 관점별 요약 JSON |
| done | 스트리밍 완료 |
