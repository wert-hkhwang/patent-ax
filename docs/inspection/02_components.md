# AX 시스템 기능요소 인벤토리

**작성일**: 2026-01-02
**Phase**: 98 (시스템 종합 점검)

---

## 1. 쿼리 분석기 (analyzer.py)

### 1.1 핵심 함수

| 함수명 | 역할 | 라인 |
|--------|------|------|
| `analyze_query()` | 메인 분석 엔트리포인트 | 344 |
| `_check_simple_query()` | 인사/도움말 감지 | 401 |
| `_check_equipment_query()` | Phase 98: 장비 쿼리 감지 | 430 |
| `_analyze_with_basic_llm()` | LLM 기반 의미 분류 | 580+ |
| `_is_complex_ranking()` | 복잡 랭킹 판단 | 258 |

### 1.2 Phase 98 핵심 코드: 장비 쿼리 분류

```python
def _check_equipment_query(query: str) -> Dict[str, Any] | None:
    """Phase 98: 장비 관련 쿼리 규칙 기반 분류

    장비 보유 기관, 장비 추천, 장비 검색 등을 SQL로 분류하여
    LLM이 잘못 RAG로 분류하는 문제 해결

    Args:
        query: 사용자 질문

    Returns:
        분류 결과 또는 None (매칭 안 될 경우)
    """
    query_lower = query.lower()

    # 장비 관련 키워드
    equip_keywords = ["장비", "측정기", "시험기", "분석기", "시스템", "기기", "스캐너", "현미경"]
    # 검색/조회 액션 키워드
    action_keywords = ["보유", "찾", "추천", "검색", "알려", "있는", "가진", "갖고"]
    # 지역 키워드 (지역 필터 장비 검색)
    region_keywords = ["경기", "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
                       "경북", "경남", "전북", "전남", "충북", "충남", "강원", "제주", "지역"]

    has_equip = any(kw in query_lower for kw in equip_keywords)
    has_action = any(kw in query_lower for kw in action_keywords)
    has_region = any(kw in query_lower for kw in region_keywords)

    # 장비 키워드 + 액션 키워드 조합 감지
    if has_equip and (has_action or has_region):
        # 키워드 추출 (기술 용어 위주)
        extracted_keywords = []

        # Phase 98: 장비 이름에서 핵심 용어만 추출
        # "광탄성시험기" → "광탄성", "표면단차측정기" → "표면단차"
        import re

        # 1. 먼저 전체 장비명 패턴 매칭
        equip_pattern = r'([가-힣a-zA-Z]+(?:측정기|시험기|분석기|스캐너|현미경|시스템|기기|장비))'
        equip_matches = re.findall(equip_pattern, query)

        # 2. 매칭된 장비명에서 접미사 제거하여 핵심 키워드 추출
        for match in equip_matches:
            extracted_keywords.append(match)
            core_keyword = re.sub(r'(측정기|시험기|분석기|스캐너|현미경|시스템|기기|장비)$', '', match)
            if core_keyword and len(core_keyword) >= 2 and core_keyword != match:
                extracted_keywords.append(core_keyword)
                logger.info(f"Phase 98: 장비 핵심 키워드 추출 - {match} → {core_keyword}")

        # 지역 추출
        extracted_regions = []
        for region in region_keywords:
            if region in query_lower and region != "지역":
                extracted_regions.append(region)

        logger.info(f"Phase 98: 장비 검색 쿼리 감지 → SQL 분류")

        return {
            "query_type": "sql",
            "query_subtype": "list",
            "query_intent": "장비 검색 또는 보유 기관 조회",
            "entity_types": ["equip"],
            "related_tables": ["f_equipments"],
            "keywords": extracted_keywords if extracted_keywords else [],
            "structured_keywords": {
                "tech": extracted_keywords,
                "org": [],
                "country": [],
                "region": extracted_regions,
                "filter": [],
                "metric": []
            },
            "is_equipment_query": True
        }

    return None
```

### 1.3 분류 프롬프트 핵심 (QUERY_CLASSIFICATION_PROMPT)

```python
QUERY_CLASSIFICATION_PROMPT = """질문의 **의도**를 분석하여 JSON으로 응답하세요.

## 핵심 원칙
키워드가 아닌 **문맥과 의도**로 분류:
- "출원인별 현황 분석해줘" → 그룹별 통계 = **aggregation**
- "국내 vs 해외 비교 분석해줘" → 두 대상 비교 = **comparison**
- "딥러닝 연구 동향" / "AI 특허 동향" → **trend_analysis** (반드시!)

## query_subtype 분류:
| 유형 | 의도 | 패턴 |
|------|------|------|
| list | 목록 조회 | "알려줘/N개/목록" |
| aggregation | 통계/집계 | "~별 현황/추이/동향/분포" |
| trend_analysis | 동향 분석 | "~동향/기술동향/연구동향/특허동향" |
| ranking | 순위 | "TOP N/가장/상위" |
| recommendation | 추천 | "추천/매칭/적합한" |
| comparison | 비교 | "A vs B/비교/차이" |
| concept | 개념 | "~란/설명해줘/뭐야" |
| compound | 복합 | 2개 이상 독립적 요청 |

## [Phase 96] entity_types/related_tables 결정 방식 변경
- entity_types는 **비워두세요** (빈 배열 [])
- related_tables도 **비워두세요** (빈 배열 [])
- 이 값들은 **ES Scout** 단계에서 데이터 존재 여부 확인 후 자동 결정
"""
```

---

## 2. GraphRAG (graph_rag.py)

### 2.1 핵심 함수

| 함수명 | 역할 | 라인 |
|--------|------|------|
| `get_graph_rag()` | 싱글톤 인스턴스 (Phase 98: 자동 초기화) | 792 |
| `initialize()` | cuGraph + Qdrant 초기화 | 100+ |
| `search()` | 하이브리드 검색 실행 | 300+ |
| `cross_validate_results()` | 그래프 교차 검증 | 500+ |

### 2.2 Phase 98 핵심 코드: 자동 초기화

```python
def get_graph_rag() -> GraphRAG:
    """Graph RAG 싱글톤 인스턴스 반환 (Phase 98: 자동 초기화)

    첫 호출 시 GraphRAG를 생성하고 자동으로 초기화합니다.
    이전에는 get_graph_rag() 호출 후 별도로 initialize()를 호출해야 했으나,
    이로 인해 graph_builder가 None인 상태로 남아 그래프 검색이 스킵되는 문제가 있었습니다.

    Returns:
        초기화된 GraphRAG 인스턴스
    """
    global _graph_rag_instance
    if _graph_rag_instance is None:
        _graph_rag_instance = GraphRAG()
        # Phase 98: 첫 호출 시 기본 초기화 수행
        try:
            _graph_rag_instance.initialize(graph_id="713365bb", project_limit=500)
            logger.info("Phase 98: GraphRAG 자동 초기화 완료")
        except Exception as e:
            logger.warning(f"Phase 98: GraphRAG 자동 초기화 실패 (나중에 재시도): {e}")
    return _graph_rag_instance
```

---

## 3. RAG 검색기 (rag_retriever.py)

### 3.1 핵심 함수

| 함수명 | 역할 | 라인 |
|--------|------|------|
| `retrieve_rag()` | 메인 RAG 검색 | 800+ |
| `_search_qdrant()` | Qdrant 벡터 검색 | 400+ |
| `_search_elasticsearch()` | ES 키워드 검색 | 600+ |
| `_merge_search_results()` | RRF 융합 | 700+ |
| `enrich_rag_with_sql()` | SQL 보강 | 1103 |

### 3.2 Phase 98 핵심 코드: 교차 검증 초기화 보장

```python
# Phase 96: 그래프 교차 검증
# 검색 결과들이 그래프에서 서로 연결되어 있는지 확인하여 신뢰도 조정
graph_rag = get_graph_rag()

# Phase 98: 교차검증 전 graph_builder 초기화 재확인
if graph_rag and rag_results:
    if not graph_rag.graph_builder:
        try:
            logger.info("Phase 98: 교차검증 전 graph_builder 초기화...")
            graph_rag.initialize(graph_id="713365bb", project_limit=500)
        except Exception as init_e:
            logger.warning(f"Phase 98: graph_builder 초기화 실패: {init_e}")

    if graph_rag.graph_builder:
        try:
            rag_results = graph_rag.cross_validate_results(rag_results)
            validated_count = sum(1 for r in rag_results if r.metadata.get("graph_validated"))
            logger.info(f"Phase 96: 그래프 교차 검증 완료 - {validated_count}/{len(rag_results)}건 검증됨")
        except Exception as e:
            logger.warning(f"Phase 96: 그래프 교차 검증 실패 (스킵): {e}")
```

---

## 4. Equipment KPI Loader (equipment_kpi_loader.py)

### 4.1 로더 클래스

| 클래스 | 용도 |
|--------|------|
| `EquipmentKPILoader` | KPI 기반 장비 검색 |
| `EquipmentSearchLoader` | 장비명 기반 검색 |
| `EquipmentByRegionLoader` | 지역별 장비 검색 |
| `EquipmentByKeywordLoader` | 키워드 기반 장비 검색 |

### 4.2 Phase 98 스키마 수정

**변경 전:**
```
테이블: f_equips
컬럼: equip_nm, equip_model, lat, lng
```

**변경 후:**
```
테이블: f_equipments
컬럼: conts_klang_nm, equip_mdel_nm, x_coord, y_coord
```

### 4.3 핵심 쿼리 (수정 후)

```python
# Phase 98: 실제 스키마에 맞게 쿼리 수정
# f_equipments 테이블: conts_klang_nm(장비명), equip_mdel_nm(모델), equip_spec(스펙)
# f_gis 테이블: x_coord, y_coord (lat/lng 대신)
query = """
    SELECT
        e.conts_klang_nm AS equipment_name,
        e.org_nm AS org_name,
        e.org_addr AS address,
        e.equip_mdel_nm AS model,
        e.equip_spec AS spec,
        e.address_dosi AS location,
        g.x_coord AS longitude,
        g.y_coord AS latitude
    FROM f_equipments e
    LEFT JOIN f_gis g
        ON e.conts_id = g.conts_id
        AND g.conts_lclas_nm = '장비'
    WHERE (
        e.conts_klang_nm ILIKE '%' || $1 || '%'
        OR e.equip_spec ILIKE '%' || $1 || '%'
        OR e.equip_mdel_nm ILIKE '%' || $1 || '%'
        OR e.kpi_nm_list ILIKE '%' || $1 || '%'
    )
"""
```

---

## 5. 검색 설정 (search_config.py)

### 5.1 SearchConfig 구조

```python
@dataclass
class SearchConfig:
    primary_sources: List[SearchSource]      # 주요 검색 소스
    fallback_sources: List[SearchSource]     # 폴백 소스
    graph_rag_strategy: GraphRAGStrategy     # 그래프 전략
    es_mode: ESMode                          # ES 모드
    merge_priority: Dict[str, int]           # 병합 우선순위
    sql_limit: int = 100
    rag_limit: int = 15
    es_limit: int = 15
    need_vector_enhancement: bool = True
    use_loader: bool = False
    loader_name: Optional[str] = None
```

### 5.2 Subtype별 설정 매핑

```python
SUBTYPE_CONFIG_MAP: Dict[str, SearchConfig] = {
    # list: 목록 조회 - SQL 우선
    "list": SearchConfig(
        primary_sources=[SearchSource.SQL],
        fallback_sources=[SearchSource.VECTOR],
        graph_rag_strategy=GraphRAGStrategy.NONE,
        es_mode=ESMode.OFF,
        merge_priority={"sql": 0, "vector": 1, "es": 2, "graph": 3},
        sql_limit=100,
        need_vector_enhancement=True,
        use_loader=False,
    ),

    # aggregation: 통계/집계 - SQL 전용
    "aggregation": SearchConfig(
        primary_sources=[SearchSource.SQL],
        fallback_sources=[],
        graph_rag_strategy=GraphRAGStrategy.NONE,
        es_mode=ESMode.OFF,
        merge_priority={"sql": 0},
        sql_limit=1000,
    ),

    # recommendation: 추천 - SQL + Vector + Graph
    "recommendation": SearchConfig(
        primary_sources=[SearchSource.SQL, SearchSource.VECTOR],
        fallback_sources=[SearchSource.GRAPH],
        graph_rag_strategy=GraphRAGStrategy.GRAPH_ENHANCED,
        es_mode=ESMode.KEYWORD_BOOST,
        merge_priority={"sql": 0, "vector": 1, "graph": 2, "es": 3},
        use_loader=True,
        loader_name="CollaborationLoader",
    ),
}
```

---

## 6. 워크플로우 그래프 (graph.py)

### 6.1 노드 래퍼 함수

```python
def _timed_node(name: str, func):
    """노드 함수를 래핑하여 처리 시간을 측정하고 로깅"""
    def wrapper(state: AgentState) -> AgentState:
        start = time.time()
        result = func(state)
        elapsed_ms = (time.time() - start) * 1000
        logger.info(f"⏱️ [{name}] 처리 시간: {elapsed_ms:.2f}ms")

        # 상태에 단계별 타이밍 기록
        stage_timing = result.get("stage_timing", {}) if isinstance(result, dict) else {}
        stage_timing[f"{name}_ms"] = round(elapsed_ms, 2)
        if isinstance(result, dict):
            result["stage_timing"] = stage_timing

        return result
    return wrapper

# 시간 측정 래퍼 적용
analyze_query = _timed_node("analyzer", _analyze_query)
execute_sql = _timed_node("sql_node", _execute_sql)
retrieve_rag = _timed_node("rag_node", _retrieve_rag)
merge_results = _timed_node("merger", _merge_results)
generate_response = _timed_node("generator", _generate_response)
enhance_with_vector = _timed_node("vector_enhancer", _enhance_with_vector)
```

### 6.2 병렬 실행 노드

```python
def _parallel_execution(state: AgentState) -> AgentState:
    """SQL과 RAG를 병렬 실행 (ThreadPoolExecutor 사용)"""
    sql_state = None
    rag_state = None
    errors = []

    # ThreadPoolExecutor로 병렬 실행
    with ThreadPoolExecutor(max_workers=2) as executor:
        sql_future = executor.submit(execute_sql, state)
        rag_future = executor.submit(retrieve_rag, state)

        try:
            sql_state = sql_future.result(timeout=60)
        except Exception as e:
            logger.error(f"SQL 실행 실패: {e}")
            errors.append(f"SQL: {str(e)}")
            sql_state = state

        try:
            rag_state = rag_future.result(timeout=60)
        except Exception as e:
            logger.error(f"RAG 검색 실패: {e}")
            errors.append(f"RAG: {str(e)}")
            rag_state = state

    logger.info("병렬 실행 완료 (SQL + RAG)")

    # 결과 병합
    merged_state = {
        **state,
        "sql_result": sql_state.get("sql_result"),
        "rag_results": rag_state.get("rag_results", []),
        "sources": sql_state.get("sources", []) + rag_state.get("sources", [])
    }

    return merged_state
```

---

## 7. 점검 체크리스트

### 7.1 analyzer.py

| 항목 | 상태 | 비고 |
|------|------|------|
| `_check_equipment_query()` 동작 | OK | Phase 98 추가 |
| LLM 분류 정확도 | OK | QUERY_CLASSIFICATION_PROMPT |
| 복합 질의 분해 | OK | is_compound, sub_queries |
| entity_types 비움 (Phase 96) | OK | ES Scout에서 결정 |

### 7.2 graph_rag.py

| 항목 | 상태 | 비고 |
|------|------|------|
| `get_graph_rag()` 자동 초기화 | OK | Phase 98 수정 |
| cuGraph PageRank 계산 | OK | |
| Qdrant 벡터 검색 | OK | |
| cross_validate_results() | OK | |

### 7.3 rag_retriever.py

| 항목 | 상태 | 비고 |
|------|------|------|
| graph_builder 초기화 확인 | OK | Phase 98: 2곳 수정 |
| ES 검색 통합 | OK | |
| RRF 융합 | OK | k=60 |
| SQL 보강 | OK | enrich_rag_with_sql() |

### 7.4 equipment_kpi_loader.py

| 항목 | 상태 | 비고 |
|------|------|------|
| 테이블명 수정 | OK | f_equipments |
| 컬럼명 수정 | OK | conts_klang_nm 등 |
| 지역 필터 수정 | OK | address_dosi 사용 |

---

## 8. 다음 단계

- [Part 3: 연결 및 흐름](./03_connections.md) - 데이터 흐름 분석
- [Part 4: 테스트 결과](./04_test_results.md) - 실제 테스트 실행
- [Part 5: 이슈 추적](./05_issues.md) - 발견된 문제점
