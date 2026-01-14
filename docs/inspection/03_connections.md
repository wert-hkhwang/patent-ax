# AX 시스템 연결 및 흐름 분석

**작성일**: 2026-01-02
**Phase**: 98 (시스템 종합 점검)

---

## 1. 전체 데이터 흐름

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              사용자 질문 처리 흐름                                │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  [1. 입력]                                                                       │
│     POST /chat {query: "경기도에서 광탄성시험기를 찾고싶어"}                        │
│           │                                                                     │
│           ▼                                                                     │
│  [2. 분석] analyze_query                                                        │
│     ├── _check_simple_query() → 인사/도움말 감지                                  │
│     ├── _check_equipment_query() → 장비 쿼리 감지 (Phase 98)                     │
│     └── _analyze_with_basic_llm() → LLM 의미 분석                               │
│           │                                                                     │
│           ▼                                                                     │
│     출력: {query_type: "sql", entity_types: ["equip"], keywords: ["광탄성"]}     │
│           │                                                                     │
│           ▼                                                                     │
│  [3. 라우팅] route_after_analyzer                                               │
│     ├── simple → generator                                                     │
│     ├── concept → rag_node                                                     │
│     ├── Loader 사용 → sql_node                                                 │
│     └── 그 외 → vector_enhancer                                                │
│           │                                                                     │
│           ▼                                                                     │
│  [4. 벡터 강화] enhance_with_vector                                             │
│     ├── ES Scout: 5개 인덱스 스캔                                               │
│     ├── 키워드 확장: "광탄성" → ["광탄성", "광탄성시험"]                          │
│     └── entity_types 결정: ES 히트 기반                                         │
│           │                                                                     │
│           ▼                                                                     │
│  [5. 검색 실행] route_query → sql_node / rag_node / parallel                    │
│     ├── SQL: Loader 또는 LLM 생성 쿼리                                          │
│     ├── RAG: Qdrant 벡터 + cuGraph PageRank                                    │
│     └── ES: 키워드 BM25 검색                                                    │
│           │                                                                     │
│           ▼                                                                     │
│  [6. 결과 병합] merge_results                                                   │
│     └── RRF (k=60) 융합                                                        │
│           │                                                                     │
│           ▼                                                                     │
│  [7. 응답 생성] generate_response                                               │
│     ├── 테이블 생성                                                             │
│     └── 문맥 기반 답변                                                          │
│           │                                                                     │
│           ▼                                                                     │
│  [8. 출력] {response: "...", sources: [...], elapsed_ms: 3500}                  │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 라우팅 의사결정 트리

### 2.1 route_after_analyzer (분석 후 라우팅)

```python
def route_after_analyzer(state: AgentState) -> str:
    """
    분기 조건:
    1. simple + 검색 의도 없음 → generator (직접 응답)
    2. concept → rag_node (개념 설명)
    3. Loader 사용 가능 → sql_node
    4. SQL 전용 + 벡터 확장 필요 → vector_enhancer
    5. Vector 전용 → rag_node
    6. 그 외 → vector_enhancer (기본)
    """
```

**의사결정 흐름도:**

```
                    route_after_analyzer
                           │
            ┌──────────────┼──────────────┐
            │              │              │
      query_type     query_subtype   search_config
      == "simple"?   == "concept"?   .use_loader?
            │              │              │
            ▼              ▼              ▼
     ┌──────────┐   ┌──────────┐   ┌──────────┐
     │generator │   │rag_node  │   │sql_node  │
     └──────────┘   └──────────┘   └──────────┘
            │              │              │
            │              │              │
            │     primary_sources         │
            │     == [SQL]?               │
            │        │                    │
            ▼        ▼                    ▼
                ┌──────────────────┐
                │ vector_enhancer  │
                │    (기본값)       │
                └──────────────────┘
```

### 2.2 route_query (검색 유형 라우팅)

```python
def route_query(state: AgentState) -> str:
    """
    분기 조건:
    1. ranking + complex → parallel_ranking (SQL + ES)
    2. ranking + simple → rag_node (ES aggregation)
    3. compound + sub_queries → sub_queries
    4. recommendation + equip → rag_node
    5. recommendation + proposal → sql_node
    6. evalp/ancm → sql_node
    7. query_type 기반 분기
    """
```

**의사결정 흐름도:**

```
                      route_query
                          │
     ┌────────────────────┼────────────────────┐
     │                    │                    │
query_subtype        is_compound?          query_type
 == "ranking"?           │                     │
     │                   ▼                     │
     ▼              ┌────────────┐             │
┌─────────┐        │ sub_queries│             │
│ranking_ │        └────────────┘             │
│_type?   │                                   │
└────┬────┘                                   │
     │                                        │
┌────┴────┐                              ┌────┴────┐
│complex  │                              │  sql    │
│         │                              │  rag    │
▼         ▼                              │ hybrid  │
┌──────────────┐  ┌──────────┐          └────┬────┘
│parallel_rank │  │ rag_node │               │
└──────────────┘  └──────────┘               ▼
                                    ┌────────────────┐
                                    │ sql_node       │
                                    │ rag_node       │
                                    │ parallel       │
                                    └────────────────┘
```

---

## 3. 상태 흐름 (AgentState)

### 3.1 노드별 상태 변경

| 노드 | 읽는 필드 | 쓰는 필드 |
|------|----------|----------|
| `analyzer` | query | query_type, query_subtype, entity_types, keywords, is_compound, sub_queries |
| `vector_enhancer` | keywords, entity_types | expanded_keywords, search_config, entity_types (ES Scout) |
| `sql_executor` | query, entity_types, keywords | sql_result, generated_sql, sources, loader_used |
| `rag_retriever` | keywords, entity_types, search_config | rag_results, sources, es_enabled |
| `merger` | sql_result, rag_results | merged_results, sources |
| `generator` | query, merged_results, sql_result, rag_results | response, sources |

### 3.2 상태 전파 다이어그램

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            AgentState 흐름                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  create_initial_state(query)                                                │
│         │                                                                   │
│         ▼                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ query: "경기도에서 광탄성시험기를 찾고싶어"                           │   │
│  │ query_type: "simple" (초기값)                                        │   │
│  │ entity_types: []                                                     │   │
│  │ keywords: []                                                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│         │                                                                   │
│         │ analyzer                                                          │
│         ▼                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ query_type: "sql"                                                    │   │
│  │ query_subtype: "list"                                                │   │
│  │ entity_types: ["equip"]                                              │   │
│  │ keywords: ["광탄성시험기", "광탄성"]                                   │   │
│  │ structured_keywords: {tech: [...], region: ["경기"]}                 │   │
│  │ is_equipment_query: true                                             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│         │                                                                   │
│         │ vector_enhancer                                                   │
│         ▼                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ expanded_keywords: ["광탄성시험기", "광탄성", "탄성"]                  │   │
│  │ search_config: SearchConfig(primary=[SQL], loader=EquipmentKPILoader)│   │
│  │ es_enabled: true                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│         │                                                                   │
│         │ sql_executor                                                      │
│         ▼                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ sql_result: SQLQueryResult(success=true, rows=[...], row_count=15)  │   │
│  │ generated_sql: "SELECT ... FROM f_equipments WHERE ..."             │   │
│  │ loader_used: "EquipmentKPILoader"                                   │   │
│  │ sources: [{type: "sql", name: "광탄성시험기", ...}]                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│         │                                                                   │
│         │ generator                                                         │
│         ▼                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ response: "경기도 지역에서 광탄성시험기를 보유한 기관입니다:\n\n|..." │   │
│  │ elapsed_ms: 3500                                                     │   │
│  │ stage_timing: {analyzer_ms: 500, sql_node_ms: 2000, ...}            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. 검색 시스템 연결

### 4.1 하이브리드 검색 흐름

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          하이브리드 검색 흐름                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                         retrieve_rag(state)                                 │
│                              │                                              │
│        ┌─────────────────────┼─────────────────────┐                       │
│        │                     │                     │                       │
│        ▼                     ▼                     ▼                       │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │   Qdrant     │    │  cuGraph     │    │     ES       │                  │
│  │   Vector     │    │  PageRank    │    │    BM25      │                  │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘                  │
│         │                   │                   │                          │
│         │ score             │ pagerank          │ score                    │
│         │                   │                   │                          │
│         └─────────┬─────────┴─────────┬─────────┘                          │
│                   │                   │                                    │
│                   ▼                   ▼                                    │
│            ┌─────────────────────────────────────┐                         │
│            │           RRF 융합 (k=60)            │                         │
│            │                                     │                         │
│            │ score_i = Σ 1/(k + rank_source)     │                         │
│            └─────────────────────────────────────┘                         │
│                              │                                              │
│                              ▼                                              │
│            ┌─────────────────────────────────────┐                         │
│            │      Graph Cross Validation         │                         │
│            │   (Phase 96: 그래프 교차 검증)        │                         │
│            └─────────────────────────────────────┘                         │
│                              │                                              │
│                              ▼                                              │
│                    rag_results: List[SearchResult]                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 SQL 실행 흐름

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SQL 실행 흐름                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                        execute_sql(state)                                   │
│                              │                                              │
│         ┌────────────────────┴────────────────────┐                        │
│         │                                         │                        │
│   use_loader?                              LLM SQL 생성                     │
│         │                                         │                        │
│         ▼                                         ▼                        │
│  ┌──────────────────┐                    ┌──────────────────┐              │
│  │   Loader 실행     │                    │  SQL Agent      │              │
│  │                  │                    │  (LLM + Schema)  │              │
│  │ EquipmentKPILoader│                   └─────────┬────────┘              │
│  │ PatentRankingLoader│                            │                       │
│  │ CollaborationLoader│                            │                       │
│  └────────┬─────────┘                              │                       │
│           │                                        │                        │
│           ▼                                        ▼                        │
│  ┌─────────────────────────────────────────────────────────────┐           │
│  │                    PostgreSQL 실행                          │           │
│  │                                                             │           │
│  │  f_equipments, f_patents, f_projects, f_proposal_profile    │           │
│  │  f_ancm_evalp, f_ancm_prcnd, f_gis, ...                    │           │
│  └───────────────────────────┬─────────────────────────────────┘           │
│                              │                                              │
│                              ▼                                              │
│                    SQLQueryResult(success, rows, columns)                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. 병렬 실행 패턴

### 5.1 parallel (SQL + RAG)

```python
def _parallel_execution(state: AgentState) -> AgentState:
    """
    ThreadPoolExecutor로 병렬 실행:
    - Worker 1: execute_sql(state)
    - Worker 2: retrieve_rag(state)

    결과 병합:
    - sql_result, rag_results, sources 통합
    - 에러 있으면 error 필드에 병합
    """
```

### 5.2 parallel_ranking (SQL + ES)

```python
def _parallel_ranking_execution(state: AgentState) -> AgentState:
    """
    Phase 90.2: 복잡한 ranking용 병렬 실행

    - Worker 1: SQL ranking (통계/비율 계산)
    - Worker 2: ES ranking (terms aggregation)

    결과: merger에서 RRF 통합
    """
```

### 5.3 sub_queries (복합 질의)

```python
def _execute_sub_queries(state: AgentState) -> AgentState:
    """
    Phase 20/37: 복합 질의 분해 실행

    1. 독립 하위 질의: 병렬 실행 (max_workers=3)
    2. 의존 하위 질의: 순차 실행

    각 하위 질의:
    - subtype → query_type 변환 (list→sql, concept→rag)
    - 부모 keywords 상속
    - 개별 execute_sql 또는 retrieve_rag 호출
    """
```

---

## 6. 검색 설정 (SearchConfig) 결정 흐름

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      SearchConfig 결정 흐름                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                     get_search_config(state)                                │
│                              │                                              │
│        ┌─────────────────────┴─────────────────────┐                       │
│        │                                           │                       │
│ query_subtype?                             entity_types?                   │
│        │                                           │                       │
│        ▼                                           ▼                       │
│ ┌──────────────────────────────────────────────────────────────────────┐   │
│ │                    SUBTYPE_CONFIG_MAP 조회                            │   │
│ │                                                                      │   │
│ │  "list" → SQL, 벡터 폴백                                             │   │
│ │  "aggregation" → SQL 전용                                            │   │
│ │  "ranking" → ES + Vector                                             │   │
│ │  "recommendation" → SQL + Vector + Graph                             │   │
│ │  "concept" → Vector 전용                                             │   │
│ └────────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼                                              │
│ ┌──────────────────────────────────────────────────────────────────────┐   │
│ │                 _adjust_for_entity_types()                           │   │
│ │                                                                      │   │
│ │  evalp/evalp_detail → Graph OFF, Loader=AnnouncementScoringLoader   │   │
│ │  equip → ES KEYWORD_BOOST, Loader=EquipmentKPILoader                │   │
│ │  proposal + recommendation → Loader=CollaborationLoader             │   │
│ └────────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼                                              │
│ ┌──────────────────────────────────────────────────────────────────────┐   │
│ │                 _adjust_for_query_type()                             │   │
│ │                                                                      │   │
│ │  "sql" → primary=[SQL], Graph OFF                                   │   │
│ │  "rag" → SQL 제거, Graph HYBRID                                     │   │
│ │  "hybrid" → SQL + Vector + Graph                                    │   │
│ └────────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼                                              │
│                     SearchConfig 인스턴스 반환                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. 점검 포인트

### 7.1 라우팅 검증

| 입력 | 예상 경로 | 검증 필드 |
|------|----------|----------|
| 인사 ("안녕") | analyzer → generator | query_type="simple" |
| 개념 ("특허란?") | analyzer → rag_node → generator | query_subtype="concept" |
| 장비 검색 | analyzer → sql_node → generator | is_equipment_query=true |
| 복합 질의 | analyzer → sub_queries → merger → generator | is_compound=true |
| 협업 추천 | analyzer → sql_node → generator | query_subtype="recommendation" |

### 7.2 상태 전파 검증

| 노드 | 필수 출력 필드 |
|------|---------------|
| analyzer | query_type, entity_types, keywords |
| vector_enhancer | expanded_keywords, search_config |
| sql_executor | sql_result (success 필수) |
| rag_retriever | rag_results |
| generator | response |

### 7.3 병렬 실행 검증

| 패턴 | 조건 | Worker 수 |
|------|------|----------|
| parallel | query_type="hybrid" | 2 (SQL + RAG) |
| parallel_ranking | ranking_type="complex" | 2 (SQL + ES) |
| sub_queries | is_compound=true | max 3 |

---

## 8. 다음 단계

- [Part 4: 테스트 결과](./04_test_results.md) - 실제 테스트 실행
- [Part 5: 이슈 추적](./05_issues.md) - 발견된 문제점
