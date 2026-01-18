# 별첨 A. API 엔드포인트 상세

> Patent-AX 기술 백서 별첨

---

## 1. 헬스 체크

### GET /health

**설명**: API 서버 상태 확인

**Response**
```json
{
  "status": "healthy"
}
```

---

## 2. 스트리밍 채팅 API

### POST /workflow/chat/stream

**설명**: SSE 기반 실시간 스트리밍 채팅

**Request**
```json
{
  "query": "배터리 특허 알려줘",
  "session_id": "user123",
  "level": "L2"
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| query | string | O | 사용자 질문 |
| session_id | string | X | 세션 ID (기본: "default") |
| level | string | X | 리터러시 레벨 (L1-L6 또는 초등/일반인/전문가) |

**Response (SSE Events)**

| 이벤트 | 데이터 | 설명 |
|--------|--------|------|
| status | `{"status": "analyzing", "message": "..."}` | 처리 상태 |
| analysis_complete | `{"query_type": "sql", "keywords": [...]}` | 분석 완료 |
| sql_complete | `{"row_count": 10, "columns": [...]}` | SQL 실행 완료 |
| rag_complete | `{"result_count": 20, "top_results": [...]}` | RAG 검색 완료 |
| text | `"### 제목\n\n본문..."` | 응답 텍스트 |
| stage_timing | `{"analyzer_ms": 30000, ...}` | 단계별 소요 시간 |
| done | `{"sources": [...], "confidence_score": 0.85}` | 완료 |
| error | `{"error": "오류 메시지"}` | 오류 발생 |

---

## 3. 벡터 검색 API

### POST /search

**설명**: 단일 컬렉션 벡터 검색

**Request**
```json
{
  "query": "인공지능 반도체",
  "collection": "patents",
  "limit": 10,
  "filters": {
    "ipc_main": "H01L"
  }
}
```

**Response**
```json
{
  "query": "인공지능 반도체",
  "total": 10,
  "results": [
    {
      "id": "KR10-2023-0001234",
      "score": 0.92,
      "collection": "patents",
      "payload": {
        "title": "AI 기반 반도체 설계 방법",
        "applicant": "삼성전자",
        "ipc_main": "H01L-021/66"
      }
    }
  ],
  "elapsed_ms": 125.5
}
```

### POST /search/multi

**설명**: 다중 컬렉션 통합 검색

**Request**
```json
{
  "query": "배터리 기술",
  "collections": ["patents"],
  "limit": 20
}
```

---

## 4. SQL Agent API

### POST /sql/query

**설명**: 자연어를 SQL로 변환하여 실행

**Request**
```json
{
  "question": "2023년 배터리 특허 출원 건수",
  "interpret_result": true,
  "max_tokens": 1024
}
```

**Response**
```json
{
  "question": "2023년 배터리 특허 출원 건수",
  "generated_sql": "SELECT COUNT(*) FROM f_patents WHERE ...",
  "result": {
    "success": true,
    "columns": ["count"],
    "rows": [[1234]],
    "row_count": 1,
    "execution_time_ms": 45.2
  },
  "interpretation": "2023년 배터리 관련 특허는 총 1,234건이 출원되었습니다.",
  "elapsed_ms": 2500.0
}
```

### GET /sql/tables

**설명**: 데이터베이스 테이블 목록 조회

**Response**
```json
{
  "tables": [
    "f_patents",
    "f_patent_applicants",
    "patent_ipc_normalized"
  ]
}
```

### GET /sql/schema/{table_name}

**설명**: 특정 테이블 스키마 조회

**Response**
```json
{
  "table_name": "f_patents",
  "columns": [
    {"name": "documentid", "type": "VARCHAR", "nullable": false},
    {"name": "ipc_main", "type": "VARCHAR", "nullable": true},
    {"name": "patent_abstc_ko", "type": "TEXT", "nullable": true}
  ]
}
```

---

## 5. Graph RAG API

### POST /graph/search

**설명**: 지식 그래프 기반 검색

**Request**
```json
{
  "query": "삼성전자 배터리 특허",
  "strategy": "hybrid",
  "entity_types": ["patent"],
  "max_depth": 2,
  "limit": 20
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| strategy | string | 검색 전략 (hybrid, graph_only, vector_only) |
| max_depth | int | 그래프 탐색 깊이 (1-5) |

**Response**
```json
{
  "query": "삼성전자 배터리 특허",
  "strategy": "hybrid",
  "total": 15,
  "results": [
    {
      "node": {
        "node_id": "patent_123",
        "name": "리튬이온 배터리 제조방법",
        "entity_type": "patent",
        "score": 0.88
      },
      "related_entities": [
        {
          "node_id": "org_samsung",
          "name": "삼성SDI",
          "relation": "applicant",
          "depth": 1
        }
      ]
    }
  ],
  "elapsed_ms": 350.0
}
```

### GET /graph/central-nodes

**설명**: PageRank 기반 중심 노드 조회

**Response**
```json
{
  "nodes": [
    {"node_id": "org_samsung", "name": "삼성전자", "pagerank": 0.0234},
    {"node_id": "ipc_H01L", "name": "반도체", "pagerank": 0.0189}
  ]
}
```

---

## 6. 시각화 API

### GET /visualization/graph

**설명**: 그래프 시각화 데이터 조회

**Parameters**
| 파라미터 | 타입 | 설명 |
|----------|------|------|
| entity_types | string | 엔티티 타입 (쉼표 구분) |
| limit | int | 노드 수 제한 (기본: 100) |

**Response**
```json
{
  "nodes": [
    {"id": "patent_1", "name": "특허A", "type": "patent", "size": 10}
  ],
  "edges": [
    {"source": "patent_1", "target": "org_1", "relation": "applicant"}
  ]
}
```

### GET /visualization/vectors

**설명**: 벡터 공간 시각화 데이터 (t-SNE/UMAP)

---

## 7. 사용자 프로필 API

### POST /user/profile

**설명**: 사용자 프로필 생성

**Request**
```json
{
  "user_id": "user123",
  "education": "대학원",
  "occupation": "연구원",
  "initial_level": "L4"
}
```

### GET /user/profile/{user_id}

**설명**: 사용자 프로필 조회

### POST /user/level/change

**설명**: 리터러시 레벨 변경

**Request**
```json
{
  "user_id": "user123",
  "new_level": "L5"
}
```

---

## 8. 컬렉션 관리 API

### GET /collections

**설명**: 컬렉션 목록 및 정보 조회

**Response**
```json
{
  "collections": [
    {
      "name": "patents",
      "display_name": "특허",
      "count": 1820000,
      "dimension": 1024
    }
  ]
}
```

### GET /collections/{collection_name}/count

**설명**: 특정 컬렉션 벡터 수 조회

---

## 9. 공공 AX API

### POST /chat/ask

**설명**: 공공 서비스용 채팅 API

**Request**
```json
{
  "level": "일반인",
  "question": "전기차 배터리 특허 알려줘"
}
```

**Response**
```json
{
  "workflow": {
    "analysis": 2.5,
    "sql": 0.5,
    "rag": 0.8,
    "merge": 0.1
  },
  "answer": "전기차 배터리 관련 주요 특허를 분석해드리겠습니다...",
  "confidence_score": 0.85,
  "related_patents": [
    {"id": "KR10-2023-0001234", "title": "고효율 배터리 셀", "score": "95%"}
  ],
  "graph_data": {
    "nodes": [...],
    "edges": [...]
  }
}
```

---

## 10. 에러 응답

### 공통 에러 형식

```json
{
  "error": "에러 메시지",
  "detail": "상세 설명 (선택)"
}
```

### HTTP 상태 코드

| 코드 | 설명 |
|------|------|
| 400 | 잘못된 요청 (유효하지 않은 파라미터) |
| 404 | 리소스를 찾을 수 없음 |
| 500 | 서버 내부 오류 |
| 503 | 서비스 초기화 실패 |

---

## 11. Rate Limiting

현재 Rate Limiting 미적용. 프로덕션 배포 시 다음 설정 권장:

| 엔드포인트 | 제한 |
|------------|------|
| /workflow/chat/stream | 10 req/min/user |
| /search | 60 req/min/user |
| /sql/query | 30 req/min/user |

---

## 12. 인증

현재 인증 미적용 (개발 환경).

프로덕션 배포 시 Bearer Token 인증 권장:

```http
Authorization: Bearer <token>
```
