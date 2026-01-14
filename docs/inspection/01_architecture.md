# AX 시스템 아키텍처 개요

**작성일**: 2026-01-02
**Phase**: 98 (시스템 종합 점검)

---

## 1. 시스템 전체 구조

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AX RAG Agent System                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   [사용자 질문]                                                              │
│        │                                                                    │
│        ▼                                                                    │
│   ┌─────────┐                                                               │
│   │ API     │  FastAPI (api/main.py)                                        │
│   │ Server  │  - POST /chat: 채팅 요청                                       │
│   └────┬────┘  - POST /stream: 스트리밍                                      │
│        │                                                                    │
│        ▼                                                                    │
│   ┌─────────────────────────────────────────────────────────────────┐       │
│   │                    LangGraph Workflow                           │       │
│   │                    (workflow/graph.py)                          │       │
│   │                                                                 │       │
│   │  ┌──────────┐    ┌────────────────┐    ┌──────────────┐        │       │
│   │  │ analyzer │───▶│vector_enhancer │───▶│ sql_executor │        │       │
│   │  └──────────┘    └────────────────┘    └──────┬───────┘        │       │
│   │        │                                       │                │       │
│   │        │ (parallel)                           │                │       │
│   │        ▼                                       ▼                │       │
│   │  ┌──────────────┐                      ┌──────────┐            │       │
│   │  │ rag_retriever│─────────────────────▶│  merger  │            │       │
│   │  └──────────────┘                      └────┬─────┘            │       │
│   │                                              │                  │       │
│   │                                              ▼                  │       │
│   │                                        ┌───────────┐           │       │
│   │                                        │ generator │           │       │
│   │                                        └───────────┘           │       │
│   └─────────────────────────────────────────────────────────────────┘       │
│                                                                             │
│        │                                                                    │
│        ▼                                                                    │
│   [응답 생성] (마크다운 테이블 포함)                                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 워크플로우 노드 상세

### 2.1 노드 목록 (6개)

| 노드명 | 파일 | 역할 | 입력 | 출력 |
|--------|------|------|------|------|
| `analyzer` | `workflow/nodes/analyzer.py` | 쿼리 유형 분류 | query | query_type, entity_types, keywords |
| `vector_enhancer` | `workflow/nodes/vector_enhancer.py` | 키워드 확장 | keywords | expanded_keywords, search_config |
| `sql_executor` | `workflow/nodes/sql_executor.py` | SQL 실행 | query_type, entity_types | sql_result |
| `rag_retriever` | `workflow/nodes/rag_retriever.py` | RAG 검색 | keywords, entity_types | rag_results |
| `merger` | `workflow/nodes/merger.py` | 결과 병합 | sql_result, rag_results | merged_results |
| `generator` | `workflow/nodes/generator.py` | 응답 생성 | merged_results | response |

### 2.2 특수 실행 노드 (3개)

| 노드명 | 역할 | 사용 조건 |
|--------|------|----------|
| `parallel` | SQL + RAG 병렬 실행 | query_type == "hybrid" |
| `parallel_ranking` | SQL + ES 병렬 랭킹 | query_subtype == "complex_ranking" |
| `sub_queries` | 복합 질의 분해 실행 | is_compound == true |

---

## 3. 라우팅 로직

### 3.1 엣지 정의 (workflow/edges.py)

```
                    analyzer
                       │
          ┌────────────┼────────────┐
          │            │            │
          ▼            ▼            ▼
    vector_enhancer  sql_node   rag_node
          │
    ┌─────┼─────┬─────────┬────────────┐
    │     │     │         │            │
    ▼     ▼     ▼         ▼            ▼
 sql_node rag parallel parallel_ranking sub_queries
    │     │     │         │            │
    └─────┴─────┴────┬────┴────────────┘
                     │
                     ▼
                  merger
                     │
                     ▼
                 generator
                     │
                     ▼
                    END
```

### 3.2 라우팅 함수

| 함수 | 위치 | 분기 조건 |
|------|------|----------|
| `route_after_analyzer` | edges.py | simple → generator, 그 외 → vector_enhancer 또는 직접 실행 |
| `route_query` | edges.py | query_type에 따라 sql_node/rag_node/parallel 분기 |
| `route_after_sql` | edges.py | rag 필요 여부에 따라 merger 또는 generator |
| `route_after_rag` | edges.py | SQL 결과 존재 시 merger, 없으면 generator |

---

## 4. 검색 시스템

### 4.1 검색 소스 (4개)

| 소스 | 파일 | 용도 | 연결 정보 |
|------|------|------|----------|
| **PostgreSQL** | `sql/sql_agent.py` | 구조화 데이터 조회 | DB 직접 연결 |
| **Qdrant** | `api/config.py` | 벡터 검색 | QDRANT_HOST:6333 |
| **cuGraph** | `graph/cugraph_client.py` | 그래프 관계 분석 | GPU 기반 |
| **Elasticsearch** | `search/elasticsearch_client.py` | 키워드 검색 | ES_HOST:9200 |

### 4.2 하이브리드 검색 (GraphRAG)

```
┌─────────────────────────────────────────────────────────┐
│                   GraphRAG                              │
│                (graph/graph_rag.py)                     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│   ┌──────────┐        ┌──────────┐                     │
│   │ cuGraph  │        │  Qdrant  │                     │
│   │ PageRank │        │  Vector  │                     │
│   └────┬─────┘        └────┬─────┘                     │
│        │                   │                            │
│        └─────────┬─────────┘                            │
│                  ▼                                      │
│           RRF 융합 (k=60)                               │
│                  │                                      │
│                  ▼                                      │
│        ┌─────────────────┐                              │
│        │ Cross Validation│ (그래프 교차 검증)            │
│        └─────────────────┘                              │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 5. Loader 시스템

### 5.1 개요

Loader는 특정 query_subtype에 대해 최적화된 SQL을 생성하는 모듈입니다.

**설계 원칙 (DBFirst)**:
- 실제 테이블/컬럼 스키마 기반
- LLM 의존 없이 규칙 기반 SQL 생성
- 빠른 응답 (LLM 호출 없음)

### 5.2 Loader 목록 (19개)

| Loader | entity_type | 파일 |
|--------|-------------|------|
| `EquipmentSearchLoader` | equip | `loaders/equipment_kpi_loader.py` |
| `EquipmentByRegionLoader` | equip | `loaders/equipment_kpi_loader.py` |
| `EquipmentByKeywordLoader` | equip | `loaders/equipment_kpi_loader.py` |
| `EquipmentKPILoader` | equip | `loaders/equipment_kpi_loader.py` |
| `PatentRankingLoader` | patent | `loaders/patent_loader.py` |
| `PatentTrendLoader` | patent | `loaders/patent_loader.py` |
| `ProjectLoader` | project | `loaders/project_loader.py` |
| `ExpertLoader` | expert | `loaders/expert_loader.py` |
| `CollaborationLoader` | proposal | `loaders/collaboration_loader.py` |
| `AnnouncementScoringLoader` | evalp | `loaders/announcement_loader.py` |
| `AnnouncementAdvantageLoader` | evalp_pref | `loaders/announcement_loader.py` |
| ... (8개 추가) | | |

---

## 6. 검색 설정 (SearchConfig)

### 6.1 Phase 89: 의도별 검색 전략

`workflow/search_config.py`에서 query_subtype별 최적 검색 전략 정의:

| query_subtype | primary_sources | graph_rag_strategy | es_mode |
|---------------|-----------------|-------------------|---------|
| list | SQL | NONE | OFF |
| aggregation | SQL | NONE | OFF |
| trend_analysis | SQL | NONE | AGGREGATION |
| simple_ranking | ES, VECTOR | GRAPH_ENHANCED | AGGREGATION |
| complex_ranking | SQL, ES | NONE | KEYWORD_BOOST |
| concept | VECTOR | VECTOR_ONLY | KEYWORD_BOOST |
| recommendation | SQL, VECTOR | GRAPH_ENHANCED | KEYWORD_BOOST |
| comparison | SQL, VECTOR | HYBRID | KEYWORD_BOOST |
| compound | SQL, VECTOR | HYBRID | KEYWORD_BOOST |

---

## 7. 상태 관리 (AgentState)

### 7.1 TypedDict 구조

```python
class AgentState(TypedDict, total=False):
    # 입력
    query: str
    session_id: str

    # 분석 결과
    query_type: str       # sql, rag, hybrid, simple
    query_subtype: str    # list, aggregation, ranking, ...
    entity_types: List[str]
    keywords: List[str]
    expanded_keywords: List[str]

    # 검색 결과
    sql_result: SQLResult
    rag_results: List[RAGResult]
    es_results: List[Dict]

    # 최종 출력
    merged_results: List[Dict]
    response: str
    sources: List[Dict]

    # 메타
    error: str
    stage_timing: Dict[str, float]
```

---

## 8. 핵심 수정 이력

### Phase 98 (2026-01-02)

| 파일 | 수정 내용 |
|------|----------|
| `analyzer.py` | `_check_equipment_query()` 함수 추가 - 장비 쿼리 규칙 기반 분류 |
| `graph_rag.py` | `get_graph_rag()` 자동 초기화 - graph_builder None 문제 해결 |
| `rag_retriever.py` | 그래프 초기화 상태 명시적 확인 (2곳) |
| `equipment_kpi_loader.py` | 스키마 수정 - f_equips → f_equipments |

---

## 9. 테스트 정보

### 9.1 테스트 파일

| 파일 | 테스트 대상 | 케이스 수 |
|------|------------|----------|
| `test_phase97_easy.py` | 단순 조회 | 3개 |
| `test_phase97_medium.py` | 필터링/집계 | 2개 |
| `test_phase97_hard.py` | 복합 질문 | 2개 |
| `test_phase97_additional.py` | 기존 실패 케이스 | 4개 |

### 9.2 최신 테스트 결과 (Phase 97)

| 지표 | 값 |
|------|-----|
| 전체 성공률 | 100% (11/11) |
| 평균 품질 점수 | 91.8/100 |
| Easy 평균 | 100점 (Phase 98 수정 후) |
| Medium 평균 | 100점 |
| Hard 평균 | 100점 |
| Additional 평균 | 92.5점 |

---

## 10. 다음 단계

- [Part 2: 기능요소 인벤토리](./02_components.md) - 각 노드별 상세 코드
- [Part 3: 연결 및 흐름](./03_connections.md) - 데이터 흐름 분석
- [Part 4: 테스트 결과](./04_test_results.md) - 실제 테스트 실행
- [Part 5: 이슈 추적](./05_issues.md) - 발견된 문제점
