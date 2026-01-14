"""
LangGraph 라우팅 함수
- 조건부 엣지 정의
- 쿼리 유형별 라우팅
- Phase 35: 선택적 벡터 강화 라우팅
- Phase 89: SearchConfig 기반 의도별 라우팅
- Phase 94: ES Scout는 vector_enhancer에서 처리 (simple 쿼리 제외)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from typing import Literal

from workflow.state import AgentState, SearchSource

logger = logging.getLogger(__name__)


def route_after_es_scout(state: AgentState) -> Literal["vector_enhancer", "sql_node", "rag_node", "parallel", "sub_queries", "generator"]:
    """Phase 100: ES Scout 후 조건부 라우팅

    동의어 확장 및 ES Scout 완료 후 다음 노드 결정.

    라우팅 규칙:
    1. simple + 검색 의도 없음 → generator 직행
    2. concept → rag_node (개념 설명)
    3. trend_analysis/crosstab_analysis → sql_node (ES aggregations)
    4. Loader 사용 가능 → sql_node
    5. 복합 질의 → sub_queries
    6. 나머지 → vector_enhancer (Qdrant 확장)

    Args:
        state: 현재 에이전트 상태

    Returns:
        다음 노드 이름
    """
    query_type = state.get("query_type", "simple")
    query_subtype = state.get("query_subtype", "list")
    is_compound = state.get("is_compound", False)
    sub_queries = state.get("sub_queries", [])
    keywords = state.get("keywords", [])
    entity_types = state.get("entity_types", [])
    search_config = state.get("search_config")

    print(f"[ROUTE_ES_SCOUT] Phase 100: query_type={query_type}, query_subtype={query_subtype}, entity_types={entity_types}, is_compound={is_compound}, sub_queries_len={len(sub_queries)}")

    # 1. Simple + 검색 의도 없음 (인사/잡담) → generator 직행
    if query_type == "simple" and not entity_types and not keywords:
        logger.info("라우팅: es_scout → generator (simple, 검색 의도 없음)")
        return "generator"

    # 2. Concept → rag_node (개념 설명, DB 검색 불필요)
    if query_subtype == "concept":
        logger.info("라우팅: es_scout → rag_node (concept)")
        return "rag_node"

    # 3. Phase 99.5: trend_analysis → sql_node 직행 (ES aggregations 사용)
    if query_subtype == "trend_analysis":
        logger.info("라우팅: es_scout → sql_node (Phase 99.5: trend_analysis)")
        return "sql_node"

    # 4. Phase 99.6: crosstab_analysis → sql_node 직행
    if query_subtype == "crosstab_analysis":
        logger.info("라우팅: es_scout → sql_node (Phase 99.6: crosstab_analysis)")
        return "sql_node"

    # 5. Phase 104.2: 복합 질의도 vector_enhancer 거쳐야 함 (키워드 확장 필요)
    # compound 분기를 route_query()로 이동 (vector_enhancer 이후 호출됨)
    # 기존: es_scout → sub_queries (키워드 확장 스킵)
    # 변경: es_scout → vector_enhancer → route_query → sub_queries
    if is_compound and sub_queries:
        print(f"[ROUTE_ES_SCOUT] Phase 104.2: compound 쿼리도 vector_enhancer 거침 ({len(sub_queries)}개 하위 질의)")
        logger.info(f"Phase 104.2: compound 쿼리 → vector_enhancer (키워드 확장 필요)")
        # return "sub_queries"  # Phase 104.2: vector_enhancer로 변경
        return "vector_enhancer"

    # 6. Phase 89: Loader 사용 가능 → sql_node
    if search_config and getattr(search_config, 'use_loader', False):
        logger.info(f"라우팅: es_scout → sql_node (Loader: {getattr(search_config, 'loader_name', 'unknown')})")
        return "sql_node"

    # 7. 기본: vector_enhancer (Qdrant 벡터 확장)
    logger.info("라우팅: es_scout → vector_enhancer (Phase 100: 기본 경로)")
    return "vector_enhancer"


def route_after_analyzer(state: AgentState) -> Literal["vector_enhancer", "sql_node", "rag_node", "parallel", "sub_queries", "generator"]:
    """Phase 36/89: Analyzer 이후 조건부 라우팅

    검색 의도 유무와 쿼리 유형에 따라 최적 경로로 라우팅.
    Phase 89: SearchConfig 기반 의도별 최적화된 라우팅.

    Args:
        state: 현재 에이전트 상태

    Returns:
        다음 노드 이름
    """
    query_type = state.get("query_type", "simple")
    query_subtype = state.get("query_subtype", "list")
    is_compound = state.get("is_compound", False)
    sub_queries = state.get("sub_queries", [])
    is_aggregation = state.get("is_aggregation", False)
    keywords = state.get("keywords", [])
    entity_types = state.get("entity_types", [])

    # Phase 89: SearchConfig 가져오기 (analyzer에서 생성됨)
    search_config = state.get("search_config")
    if not search_config:
        # fallback: analyzer에서 생성되지 않은 경우
        from workflow.search_config import get_search_config
        search_config = get_search_config(state)

    # 1. Simple + 검색 의도 없음 (인사/잡담) → generator 직행
    if query_type == "simple" and not entity_types and not keywords:
        logger.info("라우팅: simple (검색 의도 없음) → generator")
        return "generator"

    # 2. Concept → rag_node (개념 설명, DB 검색 불필요)
    # "~란 무엇인가?" 형태는 엔티티와 무관하게 개념 설명
    if query_subtype == "concept":
        logger.info("라우팅: concept → rag_node (벡터 스킵)")
        return "rag_node"

    # Phase 99.5: trend_analysis → sql_node 직행 (ES aggregations 사용)
    # 벡터 확장 불필요, ES aggregations로 직접 통계 집계
    if query_subtype == "trend_analysis":
        logger.info("라우팅: trend_analysis → sql_node (Phase 99.5: ES aggregations)")
        return "sql_node"

    # Phase 99.6: crosstab_analysis → sql_node 직행 (ES nested aggregations 사용)
    # 출원기관별 연도별 크로스탭 통계
    if query_subtype == "crosstab_analysis":
        logger.info("라우팅: crosstab_analysis → sql_node (Phase 99.6: ES nested aggregations)")
        return "sql_node"

    # Phase 89: Loader 사용 가능 시 SQL 우선 라우팅
    if search_config.use_loader and search_config.loader_name:
        logger.info(f"라우팅: Loader 사용 ({search_config.loader_name}) → sql_node")
        return "sql_node"

    # Phase 89: SearchConfig primary_sources 기반 라우팅
    primary_sources = search_config.primary_sources

    # SQL만 필요한 경우 (list, aggregation 등)
    if primary_sources == [SearchSource.SQL]:
        if search_config.need_vector_enhancement:
            logger.info("라우팅: SQL 전용 + 벡터 확장 → vector_enhancer")
            return "vector_enhancer"
        else:
            logger.info("라우팅: SQL 전용 (벡터 확장 불필요) → sql_node")
            return "sql_node"

    # Vector만 필요한 경우
    if primary_sources == [SearchSource.VECTOR]:
        logger.info("라우팅: Vector 전용 → rag_node")
        return "rag_node"

    # Phase 47/48: evalp/evalp_detail/ancm 엔티티는 SQL 라우팅 강제 (concept 제외)
    sql_priority_entities = {"evalp", "evalp_detail", "ancm"}
    if any(et in sql_priority_entities for et in entity_types):
        logger.info(f"라우팅: SQL 우선 엔티티 {entity_types} → vector_enhancer (SQL 경로)")
        return "vector_enhancer"

    # 3. 모든 검색 쿼리 → vector_enhancer (키워드 확장 기본 적용)
    # - list, ranking, aggregation, compound 등 모두 벡터 확장 필요
    # - 정확한 키워드 매칭보다 의미론적 확장으로 검색 품질 향상
    # - Phase 94: vector_enhancer에서 ES Scout (전체 도메인 스캔)도 수행
    logger.info("라우팅: 검색 쿼리 → vector_enhancer (Phase 94: ES Scout 포함)")
    return "vector_enhancer"


def route_query(state: AgentState) -> Literal["sql_node", "rag_node", "parallel", "parallel_ranking", "sub_queries", "generator"]:
    """쿼리 유형에 따른 라우팅

    Args:
        state: 현재 에이전트 상태

    Returns:
        다음 노드 이름
    """
    query_type = state.get("query_type", "simple")
    query_subtype = state.get("query_subtype", "list")
    is_compound = state.get("is_compound", False)
    sub_queries = state.get("sub_queries", [])
    entity_types = state.get("entity_types", [])
    ranking_type = state.get("ranking_type", "simple")  # Phase 90.2

    # Phase 90.2: ranking 유형별 분기
    if query_subtype == "ranking":
        if ranking_type == "complex":
            # 복잡한 ranking: SQL + ES 병렬 실행
            logger.info("라우팅: complex_ranking → parallel_ranking (SQL + ES 병렬)")
            return "parallel_ranking"
        else:
            # 단순 ranking: ES/Vector 우선 (ES aggregation)
            logger.info("라우팅: simple_ranking → rag_node (ES aggregation)")
            return "rag_node"

    # Phase 20: 복합 질의 처리 우선
    if is_compound and sub_queries:
        logger.info(f"라우팅: 복합 질의 실행 ({len(sub_queries)}개 하위 질의)")
        return "sub_queries"

    # Phase 91: recommendation 라우팅 - entity_types 기반 (키워드 기반 분류 제거)
    if query_subtype == "recommendation":
        keywords = state.get("keywords", [])
        query = state.get("query", "")

        # Phase 91: LLM이 분류한 entity_types 기반으로 라우팅 결정
        # 1. 장비 추천 (equip) → rag_node (ES 장비 검색)
        if "equip" in entity_types:
            logger.info("라우팅: recommendation (장비) → rag_node (Phase 91)")
            return "rag_node"

        # 2. 기술분류 추천 (tech 또는 "분류" 키워드)
        is_tech_classification = (
            "tech" in entity_types or
            any("분류" in kw for kw in keywords) or
            "분류" in query
        )
        if is_tech_classification:
            logger.info("라우팅: recommendation (기술분류) → sql_node")
            return "sql_node"

        # 3. 협업 기관 추천 (proposal/patent 또는 협업 키워드)
        # Phase 91: 협업 키워드는 보조 조건으로만 사용 (entity_types 우선)
        COLLABORATION_KEYWORDS = {"협업", "협력", "파트너", "공동연구", "협력기관", "협업기관"}
        is_collaboration = (
            "proposal" in entity_types or
            "patent" in entity_types or
            any(kw in query for kw in COLLABORATION_KEYWORDS)
        )
        if is_collaboration:
            logger.info("라우팅: recommendation (협업 기관) → sql_node (Phase 91)")
            return "sql_node"

        # 4. query_type 기반 폴백
        if query_type == "hybrid":
            logger.info("라우팅: recommendation (hybrid) → parallel")
            return "parallel"
        elif query_type == "rag":
            logger.info("라우팅: recommendation → rag_node")
            return "rag_node"
        else:
            # 폴백: rag_node (Phase 91: 장비 등 일반 추천은 RAG로)
            logger.info("라우팅: recommendation → rag_node (폴백)")
            return "rag_node"

    # Phase 47/48: evalp/evalp_detail/ancm 엔티티는 SQL 라우팅 강제
    sql_priority_entities = {"evalp", "evalp_detail", "ancm"}
    if any(et in sql_priority_entities for et in entity_types):
        logger.info(f"라우팅: SQL 우선 엔티티 {entity_types} → sql_node")
        return "sql_node"

    if query_type == "sql":
        logger.info("라우팅: SQL 노드로 이동")
        return "sql_node"
    elif query_type == "rag":
        logger.info("라우팅: RAG 노드로 이동")
        return "rag_node"
    elif query_type == "hybrid":
        logger.info("라우팅: 병렬 실행 (SQL + RAG)")
        return "parallel"
    else:
        logger.info("라우팅: 직접 응답 생성")
        return "generator"


def route_after_sql(state: AgentState) -> Literal["merger", "generator"]:
    """Phase 36: SQL 실행 후 라우팅

    Args:
        state: 현재 에이전트 상태

    Returns:
        다음 노드 이름
    """
    query_type = state.get("query_type", "sql")
    multi_sql_results = state.get("multi_sql_results")

    # Phase 99.5/99.6: ES 통계 결과가 있으면 바로 generator로
    es_statistics = state.get("es_statistics")
    statistics_type = state.get("statistics_type")
    if es_statistics and statistics_type in ("trend_analysis", "crosstab_analysis"):
        logger.info(f"라우팅: sql → generator (Phase 99.5/99.6: ES 통계 결과 - {statistics_type})")
        return "generator"

    # hybrid 또는 다중 엔티티 SQL → merger 필수
    if query_type == "hybrid" or multi_sql_results:
        logger.info("라우팅: sql → merger (multi_sql 또는 hybrid)")
        return "merger"

    # sql 전용 (단일 엔티티) → 바로 generator
    return "generator"


def route_after_rag(state: AgentState) -> Literal["merger", "generator"]:
    """RAG 검색 후 라우팅

    Args:
        state: 현재 에이전트 상태

    Returns:
        다음 노드 이름
    """
    query_type = state.get("query_type", "rag")

    # hybrid인 경우 merger로
    if query_type == "hybrid":
        return "merger"

    # rag 전용인 경우 바로 generator로
    return "generator"


def should_continue(state: AgentState) -> Literal["continue", "end"]:
    """워크플로우 계속 여부 결정

    Args:
        state: 현재 에이전트 상태

    Returns:
        "continue" 또는 "end"
    """
    # 에러가 있으면 종료
    if state.get("error"):
        logger.warning(f"에러로 인해 워크플로우 종료: {state.get('error')}")
        return "end"

    # 응답이 생성되었으면 종료
    if state.get("response"):
        return "end"

    return "continue"
