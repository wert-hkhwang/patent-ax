# 별첨 C. 워크플로우 노드 상세

> Patent-AX 기술 백서 별첨

---

## 1. LangGraph 워크플로우 개요

### 1.1 노드 구성

```
                    ┌──────────────┐
                    │   analyzer   │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │   es_scout   │
                    └──────┬───────┘
                           │
              ┌────────────┴────────────┐
              │                         │
     ┌────────▼────────┐       ┌────────▼────────┐
     │ vector_enhancer │       │    generator    │
     └────────┬────────┘       │   (simple만)    │
              │                └─────────────────┘
    ┌─────────┼─────────┬─────────────┐
    │         │         │             │
┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───────▼───────┐
│sql_node│ │rag_node│ │parallel│ │  sub_queries  │
└───┬───┘ └───┬───┘ └───┬───┘ └───────┬───────┘
    │         │         │             │
    └────────┬┴─────────┴─────────────┘
             │
      ┌──────▼──────┐
      │   merger    │
      └──────┬──────┘
             │
      ┌──────▼──────┐
      │  generator  │
      └──────┬──────┘
             │
           [END]
```

### 1.2 라우팅 규칙

| 조건 | 경로 |
|------|------|
| simple + 검색 의도 없음 | es_scout → generator |
| concept | es_scout → rag_node |
| trend_analysis | es_scout → sql_node |
| ranking (simple) | vector_enhancer → rag_node |
| ranking (complex) | vector_enhancer → parallel_ranking |
| compound | vector_enhancer → sub_queries |
| 기본 | vector_enhancer → sql_node/rag_node |

---

## 2. 노드 상세

### 2.1 Analyzer (쿼리 분석)

**파일**: `workflow/nodes/analyzer.py`

**역할**: LLM 기반 사용자 의도 분석

**입력**
| 필드 | 타입 | 설명 |
|------|------|------|
| query | string | 사용자 질문 |
| session_id | string | 세션 ID |
| level | string | 리터러시 레벨 |

**출력**
| 필드 | 타입 | 설명 |
|------|------|------|
| query_type | string | sql, rag, hybrid, simple |
| query_subtype | string | list, aggregation, ranking, concept, compound, recommendation, comparison, trend_analysis |
| entity_types | list | ["patent"] |
| keywords | list | 추출된 핵심 키워드 |
| structured_keywords | dict | {tech, country, filter, metric} |
| is_compound | bool | 복합 질의 여부 |
| sub_queries | list | 하위 질의 목록 |
| search_config | SearchConfig | 검색 전략 설정 |

**프롬프트 구조**
```
질문의 **의도**를 분석하여 JSON으로 응답하세요.

## 핵심 원칙
키워드가 아닌 **문맥과 의도**로 분류:
- "출원인별 현황 분석해줘" → aggregation
- "딥러닝 연구 동향" → trend_analysis
...
```

**처리 시간**: 약 30-40초 (LLM 호출)

---

### 2.2 ES Scout (Phase 100)

**파일**: `workflow/nodes/es_scout.py`

**역할**: 동의어 확장 및 전체 도메인 스캔

**입력**
| 필드 | 타입 | 설명 |
|------|------|------|
| keywords | list | 분석된 키워드 |
| query | string | 원본 질문 |
| entity_types | list | 엔티티 타입 |

**출력**
| 필드 | 타입 | 설명 |
|------|------|------|
| synonym_keywords | list | 동의어 확장 키워드 |
| es_doc_ids | dict | 도메인별 문서 ID 목록 |
| domain_hits | dict | 도메인별 히트 수 |

**동의어 사전 예시**
```python
{
    "배터리": ["battery", "축전지", "이차전지", "전지"],
    "AI": ["인공지능", "딥러닝", "기계학습", "machine learning"],
    "반도체": ["semiconductor", "칩", "IC", "웨이퍼"]
}
```

**처리 시간**: 약 0.1초

---

### 2.3 Vector Enhancer (Phase 29, 53, 96)

**파일**: `workflow/nodes/vector_enhancer.py`

**역할**: Qdrant 벡터 검색 기반 키워드 확장

**입력**
| 필드 | 타입 | 설명 |
|------|------|------|
| keywords | list | 기존 키워드 |
| entity_types | list | 엔티티 타입 |
| query | string | 원본 질문 |

**출력**
| 필드 | 타입 | 설명 |
|------|------|------|
| expanded_keywords | list | 확장된 키워드 |
| entity_keywords | dict | 엔티티별 키워드 |
| keyword_extraction_result | dict | 추출 상세 정보 |

**확장 알고리즘**
1. 키워드로 Qdrant 벡터 검색 (limit=100)
2. 검색 결과 문서에서 형태소 분석 (Komoran)
3. 빈도 60% 이상 키워드 필터링
4. 최대 3개 새 키워드 추가

**설정값**
```python
VECTOR_SEARCH_LIMIT = 100
KEYWORD_MIN_FREQUENCY = 60  # 60% 이상
KEYWORD_MAX_COUNT = 3
```

**처리 시간**: 약 0.5초

---

### 2.4 SQL Executor (SQL 실행)

**파일**: `workflow/nodes/sql_executor.py`

**역할**: 자연어 → SQL 변환 및 실행

**입력**
| 필드 | 타입 | 설명 |
|------|------|------|
| query | string | 사용자 질문 |
| query_type | string | 쿼리 유형 |
| query_subtype | string | 세부 유형 |
| expanded_keywords | list | 확장 키워드 |
| related_tables | list | 관련 테이블 |

**출력**
| 필드 | 타입 | 설명 |
|------|------|------|
| sql_result | SQLQueryResult | 실행 결과 |
| multi_sql_results | dict | 다중 엔티티 결과 (Phase 19) |
| generated_sql | string | 생성된 SQL |
| sources | list | 데이터 소스 |

**SQLQueryResult 구조**
```python
@dataclass
class SQLQueryResult:
    success: bool
    columns: List[str]
    rows: List[List[Any]]
    row_count: int
    execution_time_ms: float
    error: Optional[str] = None
```

**쿼리 타입별 SQL 패턴**
| 타입 | SQL 패턴 |
|------|----------|
| list | `SELECT ... WHERE ... LIMIT 10` |
| aggregation | `SELECT ... GROUP BY ... ORDER BY ...` |
| ranking | `SELECT ... ORDER BY count DESC LIMIT 10` |
| trend_analysis | `SELECT year, COUNT(*) GROUP BY year` |

**처리 시간**: 약 0.5-2초

---

### 2.5 RAG Retriever (벡터 검색)

**파일**: `workflow/nodes/rag_retriever.py`

**역할**: Qdrant 벡터 + Graph RAG 검색

**입력**
| 필드 | 타입 | 설명 |
|------|------|------|
| expanded_keywords | list | 확장 키워드 |
| entity_types | list | 엔티티 타입 |
| search_config | SearchConfig | 검색 전략 |
| es_doc_ids | dict | ES Scout 결과 |

**출력**
| 필드 | 타입 | 설명 |
|------|------|------|
| rag_results | list | SearchResult 목록 |
| search_strategy | string | 사용된 전략 |
| sources | list | 참조 소스 |

**SearchResult 구조**
```python
@dataclass
class SearchResult:
    node_id: str
    name: str
    entity_type: str
    score: float
    metadata: Optional[Dict] = None
```

**검색 전략 (GraphRAGStrategy)**
| 전략 | 설명 |
|------|------|
| VECTOR_ONLY | Qdrant 벡터만 사용 |
| GRAPH_ONLY | cuGraph 그래프만 사용 |
| HYBRID | Vector + Graph RRF 병합 |
| GRAPH_ENHANCED | Vector 결과에 그래프 관계 보강 |

**신뢰도 필터링 임계값**
```python
MIN_VECTOR_SCORE = 0.35
MIN_GRAPH_SCORE = 0.25
MIN_ES_SCORE = 3.0
```

**처리 시간**: 약 0.8-1.5초

---

### 2.6 Merger (결과 병합)

**파일**: `workflow/nodes/merger.py`

**역할**: SQL + RAG 결과 통합

**입력**
| 필드 | 타입 | 설명 |
|------|------|------|
| sql_result | SQLQueryResult | SQL 결과 |
| multi_sql_results | dict | 다중 SQL 결과 |
| rag_results | list | RAG 결과 |
| search_config | SearchConfig | 병합 우선순위 |

**출력**
| 필드 | 타입 | 설명 |
|------|------|------|
| merged_context | dict | 통합된 컨텍스트 |
| sources | list | 최종 소스 목록 |

**병합 우선순위 (merge_priority)**
```python
# list 쿼리
{"sql": 0, "vector": 1, "es": 2, "graph": 3}

# ranking 쿼리
{"es": 0, "vector": 1, "sql": 2}

# concept 쿼리
{"vector": 0, "graph": 1, "es": 2}
```

**RRF 병합 (Phase 90.2)**
```python
# Reciprocal Rank Fusion
# score = Σ (1 / (k + rank + 1)), k=60
```

**처리 시간**: 약 0.1초

---

### 2.7 Generator (응답 생성)

**파일**: `workflow/nodes/generator.py`

**역할**: LLM 기반 최종 응답 생성

**입력**
| 필드 | 타입 | 설명 |
|------|------|------|
| query | string | 원본 질문 |
| query_intent | string | 분석된 의도 |
| level | string | 리터러시 레벨 |
| merged_context | dict | 병합된 데이터 |
| search_strategy | string | 검색 전략 |

**출력**
| 필드 | 타입 | 설명 |
|------|------|------|
| response | string | 최종 응답 텍스트 |
| sources | list | 참조 소스 |
| confidence_score | float | 신뢰도 점수 (0-1) |
| reasoning_trace | string | 추론 과정 |

**리터러시 레벨별 응답 스타일**
| 레벨 | 스타일 |
|------|--------|
| L1 (초등) | 쉬운 용어, 이모지, 짧은 문장 |
| L2 (일반) | 기본 전문용어, 예시 포함 |
| L3 (실무) | 실무 관점, 활용 사례 |
| L4 (연구) | 기술 상세, 참고문헌 |
| L5 (전문가) | 법률 용어, 청구항 분석 |
| L6 (정책) | 통계 중심, 정책 시사점 |

**응답 구조**
```markdown
### 제목

#### 배경
배경 설명...

#### 표
| 컬럼1 | 컬럼2 | ... |
|-------|-------|-----|
| 값1   | 값2   | ... |

#### 소결
- 핵심 발견: ...
- 시사점: ...
```

**처리 시간**: 약 15-20초 (LLM 호출)

---

## 3. 병렬 실행 노드

### 3.1 Parallel (SQL + RAG 동시)

**파일**: `workflow/graph.py` - `_parallel_execution()`

```python
with ThreadPoolExecutor(max_workers=2) as executor:
    sql_future = executor.submit(execute_sql, state)
    rag_future = executor.submit(retrieve_rag, state)

    sql_state = sql_future.result(timeout=60)
    rag_state = rag_future.result(timeout=60)
```

### 3.2 Parallel Ranking (Phase 90.2)

**파일**: `workflow/graph.py` - `_parallel_ranking_execution()`

SQL ranking + ES ranking 병렬 실행 후 RRF 통합

### 3.3 Sub Queries (Phase 20)

**파일**: `workflow/graph.py` - `_execute_sub_queries()`

복합 질의 하위 질의 병렬/순차 실행

```python
# 의존성 없는 쿼리: 병렬 실행
independent_queries = [sq for sq in sub_queries if sq.get("depends_on") is None]

# 의존성 있는 쿼리: 순차 실행
dependent_queries = [sq for sq in sub_queries if sq.get("depends_on") is not None]
```

---

## 4. 상태 관리

### 4.1 AgentState 주요 필드

```python
class AgentState(TypedDict):
    # 입력
    query: str
    session_id: str
    level: str

    # 분석 결과
    query_type: str
    query_subtype: str
    entity_types: List[str]
    keywords: List[str]
    expanded_keywords: List[str]

    # 실행 결과
    sql_result: Optional[SQLQueryResult]
    rag_results: List[SearchResult]

    # 최종 출력
    response: str
    sources: List[Dict]

    # 메타데이터
    elapsed_ms: float
    stage_timing: Dict[str, float]
```

### 4.2 단계별 타이밍

```python
stage_timing = {
    "analyzer_ms": 30000.0,
    "es_scout_ms": 100.0,
    "vector_enhancer_ms": 500.0,
    "sql_node_ms": 500.0,
    "rag_node_ms": 800.0,
    "merger_ms": 100.0,
    "generator_ms": 17000.0
}
```

---

## 5. 에러 처리

### 5.1 노드별 폴백

| 노드 | 에러 발생 시 |
|------|-------------|
| analyzer | 기본 분류 (query_type=rag) |
| es_scout | 동의어 확장 스킵 |
| vector_enhancer | 원본 키워드만 사용 |
| sql_node | error 필드에 메시지 저장 |
| rag_node | 빈 결과 반환 |
| generator | "오류 발생" 메시지 반환 |

### 5.2 Graceful Degradation (Phase 98)

```python
try:
    graph_results = graph_rag.search(...)
except Exception as e:
    logger.warning(f"cuGraph 서비스 불가: {e}")
    graph_results = []  # 벡터 결과만 사용
```

---

## 6. 성능 최적화

### 6.1 캐싱

| 대상 | 캐시 타입 | TTL |
|------|----------|-----|
| 임베딩 | 메모리 LRU | 30분 |
| SQL 결과 | 없음 | - |
| 그래프 PageRank | 메모리 | 세션 |

### 6.2 병렬 처리

| 상황 | 병렬화 |
|------|--------|
| SQL + RAG | ThreadPoolExecutor(2) |
| 다중 엔티티 SQL | 각각 별도 실행 |
| 복합 질의 | 독립 쿼리 병렬 |

### 6.3 권장 개선사항

1. **Reasoning Mode 비활성화**: analyzer 시간 50% 단축
2. **프롬프트 캐싱**: 반복 패턴 캐싱
3. **비동기 스트리밍**: 노드 간 파이프라인
