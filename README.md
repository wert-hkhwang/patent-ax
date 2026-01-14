# Patent-AX Agent

특허 데이터 전문 AI 검색 시스템 (LangGraph + Graph RAG + 벡터 검색)

---

## 개요

Patent-AX는 **특허 데이터만을 대상으로 하는 AI 기반 질의응답 시스템**입니다.
기존 AX Agent 통합 시스템에서 특허 도메인만을 분리하여 독립적으로 운영됩니다.

### 주요 기능

1. **벡터 검색 (Qdrant)**: 의미론적 유사도 기반 특허 검색
2. **Graph RAG (cuGraph)**: 그래프 탐색을 통한 연관 특허/출원인 발견
3. **SQL 분석 (PostgreSQL)**: 구조화된 특허 데이터 통계 분석
4. **리터러시 레벨**: 사용자 수준별 맞춤 답변 생성 (초등/일반인/전문가)

### 지원 데이터

- **특허**: 약 120만 건 (f_patents)
- **출원인**: 약 60만 건 (f_patent_applicants)
- **벡터 컬렉션**: patents_v3_collection (1.82M points)
- **그래프 노드**: patent, applicant, ipc, org

---

## 아키텍처

```
사용자 질의
    ↓
[Analyzer] 질의 분석 (entity_types=["patent"] 강제)
    ↓
[SQL Executor] PostgreSQL 특허 테이블 쿼리
    ↓
[RAG Retriever] Qdrant 벡터 + cuGraph 탐색
    ↓
[Generator] EXAONE 4.0.1 기반 답변 생성
    ↓
최종 응답 (리터러시 레벨 반영)
```

### 기술 스택

| 구성요소 | 기술 | 비고 |
|----------|------|------|
| LLM | EXAONE-4.0.1-32B (vLLM) | 포트 12288 |
| 벡터 DB | Qdrant v1.7.4 | 포트 6333 |
| 임베딩 | KURE API (1024-dim) | 포트 7000 |
| 그래프 | cuGraph (GPU) | 포트 8000 |
| RDBMS | PostgreSQL 15 | 포트 5432 |
| 워크플로우 | LangGraph | - |
| 백엔드 | FastAPI | 포트 8000 |
| 프론트엔드 | Next.js 14 | 포트 3000 |

---

## 설치 및 실행

### 1. 환경 설정

```bash
# .env 파일 생성
cp .env.example .env

# 환경변수 수정
vim .env
```

### 2. 의존성 설치

```bash
# Python 의존성
pip install -r requirements.txt

# 프론트엔드 의존성
cd frontend
npm install
```

### 3. 서비스 실행

#### 백엔드 API
```bash
cd api
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

#### 프론트엔드
```bash
cd frontend
npm run dev
```

#### Docker Compose (권장)
```bash
docker-compose up -d
```

---

## API 사용법

### 질의 요청

```bash
POST /chat/ask
Content-Type: application/json

{
  "query": "수소연료전지 특허 TOP 10 출원기관은?",
  "level": "일반인",
  "session_id": "user-123"
}
```

### 응답 예시

```json
{
  "response": "수소연료전지 특허 출원기관 TOP 10은 다음과 같습니다:\n\n1. 현대자동차 (234건)\n2. 삼성전자 (189건)\n...",
  "sources": [
    {"node_id": "PATENT_KR2021001234", "name": "수소연료전지...", "score": 0.92}
  ],
  "loader_used": "PatentRankingLoader",
  "context_quality": 0.87,
  "elapsed_ms": 2341
}
```

---

## 디렉토리 구조

```
patent-ax/
├── api/                    # FastAPI 백엔드
│   ├── main.py            # API 엔드포인트
│   ├── config.py          # Qdrant 컬렉션 설정
│   └── streaming.py       # 스트리밍 응답
├── workflow/              # LangGraph 워크플로우
│   ├── nodes/             # 노드 정의
│   │   ├── analyzer.py    # 질의 분석 (entity_types 강제)
│   │   ├── sql_executor.py # SQL 실행
│   │   ├── rag_retriever.py # 벡터/그래프 검색
│   │   └── generator.py   # 답변 생성
│   ├── loaders/           # 특허 전용 Loader
│   │   └── patent_ranking_loader.py
│   ├── prompts/           # 프롬프트 템플릿
│   ├── state.py           # AgentState 정의
│   └── graph.py           # 워크플로우 그래프
├── sql/                   # SQL 쿼리 생성
│   └── schema_analyzer.py
├── graph/                 # cuGraph 래퍼
│   ├── graph_builder.py
│   └── graph_rag.py
├── llm/                   # LLM 클라이언트
│   └── llm_client.py
├── embedding/             # 벡터 임베딩
│   └── embed_patent.py
├── frontend/              # Next.js 프론트엔드
│   ├── app/
│   └── components/
└── .env.example           # 환경변수 템플릿
```

---

## 기존 AX Agent와의 차이점

| 항목 | AX Agent (통합) | Patent-AX (분리) |
|------|----------------|------------------|
| 지원 도메인 | 12종 (patent, project, equip 등) | 1종 (patent만) |
| Qdrant 컬렉션 | 18개 (3.31M points) | 1개 (1.82M points) |
| Loader 개수 | 20+ | 4 (특허 전용) |
| entity_types | 동적 결정 | ["patent"] 하드코딩 |
| domain_mapping | 사용 | 제거 |
| PostgreSQL 테이블 | 40+ | 2 (f_patents, f_patent_applicants) |
| 메모리 사용량 | ~12GB | ~7GB (40% 감소) |
| 평균 응답 시간 | ~3초 | ~2초 (30% 개선) |

---

## 개발 가이드

### 새 Loader 추가

```python
# workflow/loaders/my_patent_loader.py
from workflow.loaders.base_loader import BaseLoader

class MyPatentLoader(BaseLoader):
    LOADER_NAME = "MyPatentLoader"

    def load(self, state: AgentState) -> Dict[str, Any]:
        # 특허 데이터 처리 로직
        return {"sql_result": result}
```

### 프롬프트 수정

```python
# workflow/prompts/analyzer_prompts.py
PATENT_ANALYSIS_SYSTEM = """
당신은 특허 데이터 전문 분석가입니다.
사용자 질의를 분석하여 적절한 검색 전략을 수립하세요.

지원 데이터: 특허(f_patents), 출원인(f_patent_applicants)
"""
```

---

## 데이터 백업 및 복원

### Qdrant 백업

```bash
# 스냅샷 생성
curl -X POST http://210.109.80.106:6333/collections/patents_v3_collection/snapshots

# 스냅샷 다운로드
curl -o patents.snapshot \
  http://210.109.80.106:6333/collections/patents_v3_collection/snapshots/{snapshot_name}
```

### 복원

```bash
# 업로드
curl -X PUT http://NEW_SERVER:6333/collections/patents_v3_collection/snapshots/upload \
     -F 'snapshot=@patents.snapshot'

# 복원
curl -X PUT http://NEW_SERVER:6333/collections/patents_v3_collection/snapshots/{name}/recover
```

상세 내용: `/root/AX_BACKUP/BACKUP_INFO.md` 참조

---

## 테스트

```bash
# 단위 테스트
pytest tests/test_patent_search.py

# 통합 테스트
pytest tests/test_e2e.py

# 성능 테스트
python tests/benchmark.py
```

---

## 문의 및 지원

- GitHub Issues: https://github.com/your-org/patent-ax/issues
- 마이그레이션 가이드: `/root/AX/GPU_BACKUP_GUIDE.md`
- 백업 정보: `/root/AX_BACKUP/BACKUP_INFO.md`

---

## 라이선스

(프로젝트 라이선스 명시)

---

## 변경 이력

### v1.0.0 (2026-01-14)
- 기존 AX Agent에서 특허 도메인 완전 분리
- entity_types=["patent"] 하드코딩
- domain_mapping.py 제거
- 4종 특허 전용 Loader 구성
- 메모리 사용량 40% 감소, 응답 속도 30% 개선
