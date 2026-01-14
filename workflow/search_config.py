"""
Phase 89: 검색 전략 설정 매핑

query_subtype별 최적 검색 전략을 정의하고,
런타임에 SearchConfig를 반환합니다.
"""

import logging
from typing import Dict, Any, Optional, List
from copy import deepcopy

from workflow.state import (
    AgentState,
    SearchConfig,
    SearchSource,
    GraphRAGStrategy,
    ESMode,
)

logger = logging.getLogger(__name__)


# === Query Subtype별 검색 전략 매핑 ===

SUBTYPE_CONFIG_MAP: Dict[str, SearchConfig] = {
    # ========== list: 목록 조회 ==========
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

    # ========== aggregation: 통계/집계 ==========
    "aggregation": SearchConfig(
        primary_sources=[SearchSource.SQL],
        fallback_sources=[],
        graph_rag_strategy=GraphRAGStrategy.NONE,
        es_mode=ESMode.OFF,
        merge_priority={"sql": 0},
        sql_limit=1000,
        need_vector_enhancement=True,
        use_loader=False,
    ),

    # ========== trend_analysis: 동향 분석 ==========
    "trend_analysis": SearchConfig(
        primary_sources=[SearchSource.SQL],
        fallback_sources=[SearchSource.ES],
        graph_rag_strategy=GraphRAGStrategy.NONE,
        es_mode=ESMode.AGGREGATION,
        merge_priority={"sql": 0, "es": 1},
        sql_limit=500,
        es_limit=30,
        need_vector_enhancement=True,
        use_loader=False,
    ),

    # ========== simple_ranking: 단순 TOP N 순위 (ES/Vector 우선) ==========
    # Phase 90.2: 단순 ranking은 ES aggregation으로 빠르게 처리
    "simple_ranking": SearchConfig(
        primary_sources=[SearchSource.ES, SearchSource.VECTOR],
        fallback_sources=[SearchSource.SQL],  # SQL은 폴백
        graph_rag_strategy=GraphRAGStrategy.GRAPH_ENHANCED,
        es_mode=ESMode.AGGREGATION,  # ES terms aggregation 사용
        merge_priority={"es": 0, "vector": 1, "sql": 2, "graph": 3},
        es_limit=20,
        rag_limit=15,
        sql_limit=10,  # SQL 폴백 시 제한
        need_vector_enhancement=True,
        use_loader=False,
    ),

    # ========== complex_ranking: 복잡한 순위 계산 (SQL + ES 병합) ==========
    # Phase 90.2: 통계/비율 계산이 필요한 ranking은 SQL 필수
    "complex_ranking": SearchConfig(
        primary_sources=[SearchSource.SQL, SearchSource.ES],
        fallback_sources=[SearchSource.VECTOR],
        graph_rag_strategy=GraphRAGStrategy.NONE,  # 통계 쿼리는 Graph 불필요
        es_mode=ESMode.KEYWORD_BOOST,
        merge_priority={"sql": 0, "es": 1, "vector": 2},
        sql_limit=50,
        es_limit=20,
        need_vector_enhancement=True,
        use_loader=True,
        loader_name="PatentRankingLoader",
    ),

    # ========== ranking: 기본 순위 (simple_ranking과 동일) ==========
    # Phase 90.2: 하위 호환성을 위해 유지 (simple_ranking으로 동작)
    "ranking": SearchConfig(
        primary_sources=[SearchSource.ES, SearchSource.VECTOR],
        fallback_sources=[SearchSource.SQL],
        graph_rag_strategy=GraphRAGStrategy.GRAPH_ENHANCED,
        es_mode=ESMode.AGGREGATION,
        merge_priority={"es": 0, "vector": 1, "sql": 2, "graph": 3},
        es_limit=20,
        rag_limit=15,
        sql_limit=10,
        need_vector_enhancement=True,
        use_loader=False,
    ),

    # ========== impact_ranking: 영향력 순위 ==========
    "impact_ranking": SearchConfig(
        primary_sources=[SearchSource.SQL, SearchSource.GRAPH],
        fallback_sources=[],
        graph_rag_strategy=GraphRAGStrategy.GRAPH_ONLY,
        es_mode=ESMode.OFF,
        merge_priority={"sql": 0, "graph": 1},
        sql_limit=50,
        rag_limit=20,
        need_vector_enhancement=False,
        use_loader=False,
    ),

    # ========== concept: 개념 설명 ==========
    # Phase 102: Graph RAG 활성화 (HYBRID로 변경) - 관련 엔티티 연결 정보 제공
    "concept": SearchConfig(
        primary_sources=[SearchSource.VECTOR],
        fallback_sources=[SearchSource.ES, SearchSource.GRAPH],
        graph_rag_strategy=GraphRAGStrategy.HYBRID,  # VECTOR_ONLY → HYBRID
        es_mode=ESMode.KEYWORD_BOOST,
        merge_priority={"vector": 0, "graph": 1, "es": 2, "sql": 3},
        rag_limit=15,  # 10 → 15
        es_limit=10,
        need_vector_enhancement=False,
        use_loader=False,
    ),

    # ========== recommendation: 추천 ==========
    "recommendation": SearchConfig(
        primary_sources=[SearchSource.SQL, SearchSource.VECTOR],
        fallback_sources=[SearchSource.GRAPH],
        graph_rag_strategy=GraphRAGStrategy.GRAPH_ENHANCED,
        es_mode=ESMode.KEYWORD_BOOST,
        merge_priority={"sql": 0, "vector": 1, "graph": 2, "es": 3},
        sql_limit=50,
        rag_limit=20,
        es_limit=15,
        need_vector_enhancement=True,
        use_loader=True,
        loader_name="CollaborationLoader",
    ),

    # ========== comparison: 비교 ==========
    "comparison": SearchConfig(
        primary_sources=[SearchSource.SQL, SearchSource.VECTOR],
        fallback_sources=[],
        graph_rag_strategy=GraphRAGStrategy.HYBRID,
        es_mode=ESMode.KEYWORD_BOOST,
        merge_priority={"sql": 0, "vector": 1, "es": 2},
        sql_limit=100,
        rag_limit=15,
        es_limit=10,
        need_vector_enhancement=True,
        use_loader=False,
    ),

    # ========== compound: 복합 ==========
    "compound": SearchConfig(
        primary_sources=[SearchSource.SQL, SearchSource.VECTOR],
        fallback_sources=[SearchSource.ES],
        graph_rag_strategy=GraphRAGStrategy.HYBRID,
        es_mode=ESMode.KEYWORD_BOOST,
        merge_priority={"sql": 0, "vector": 1, "es": 2, "graph": 3},
        sql_limit=100,
        rag_limit=15,
        es_limit=15,
        need_vector_enhancement=True,
        use_loader=False,
    ),

    # ========== evalp_score: 배점표 조회 ==========
    "evalp_score": SearchConfig(
        primary_sources=[SearchSource.SQL],
        fallback_sources=[],
        graph_rag_strategy=GraphRAGStrategy.NONE,
        es_mode=ESMode.OFF,
        merge_priority={"sql": 0},
        sql_limit=100,
        need_vector_enhancement=False,
        use_loader=True,
        loader_name="AnnouncementScoringLoader",
    ),

    # ========== evalp_pref: 우대조건 조회 ==========
    "evalp_pref": SearchConfig(
        primary_sources=[SearchSource.SQL],
        fallback_sources=[],
        graph_rag_strategy=GraphRAGStrategy.NONE,
        es_mode=ESMode.OFF,
        merge_priority={"sql": 0},
        sql_limit=50,
        need_vector_enhancement=False,
        use_loader=True,
        loader_name="AnnouncementAdvantageLoader",
    ),
}

# 기본 설정 (매핑에 없는 경우)
DEFAULT_CONFIG = SearchConfig(
    primary_sources=[SearchSource.SQL, SearchSource.VECTOR],
    fallback_sources=[SearchSource.ES],
    graph_rag_strategy=GraphRAGStrategy.HYBRID,
    es_mode=ESMode.KEYWORD_BOOST,
    merge_priority={"sql": 0, "vector": 1, "es": 2, "graph": 3},
    sql_limit=100,
    rag_limit=15,
    es_limit=15,
    need_vector_enhancement=True,
    use_loader=False,
)


def get_search_config(state: AgentState) -> SearchConfig:
    """query_subtype 기반 검색 설정 반환

    Args:
        state: 에이전트 상태

    Returns:
        SearchConfig 인스턴스
    """
    query_subtype = state.get("query_subtype", "list")
    entity_types = state.get("entity_types", [])
    query_type = state.get("query_type", "rag")
    ranking_type = state.get("ranking_type", "simple")  # Phase 90.2

    # 1. 기본 설정 가져오기
    # Phase 90.2: ranking subtype일 때 ranking_type에 따라 config 선택
    if query_subtype == "ranking":
        if ranking_type == "complex":
            config_key = "complex_ranking"
        else:
            config_key = "simple_ranking"
        base_config = SUBTYPE_CONFIG_MAP.get(config_key, DEFAULT_CONFIG)
        logger.info(f"Phase 90.2: ranking_type={ranking_type} → config_key={config_key}")
    else:
        base_config = SUBTYPE_CONFIG_MAP.get(query_subtype, DEFAULT_CONFIG)
    config = deepcopy(base_config)

    # 2. entity_types 기반 동적 조정
    config = _adjust_for_entity_types(config, entity_types, query_subtype)

    # 3. query_type 기반 조정
    config = _adjust_for_query_type(config, query_type)

    # 4. Loader 존재 여부 확인
    if config.use_loader and config.loader_name:
        if not _loader_exists(config.loader_name):
            logger.warning(f"Loader '{config.loader_name}' 없음 - SQL Agent fallback")
            config.use_loader = False
            config.loader_name = None

    logger.info(
        f"SearchConfig 결정: subtype={query_subtype}, "
        f"primary={[s.value for s in config.primary_sources]}, "
        f"rag={config.graph_rag_strategy.value}, "
        f"es={config.es_mode.value}, "
        f"loader={config.loader_name}"
    )

    return config


def _adjust_for_entity_types(
    config: SearchConfig,
    entity_types: List[str],
    query_subtype: str
) -> SearchConfig:
    """엔티티 타입에 따른 설정 조정"""

    # 배점표/평가표 관련 엔티티는 SQL만 사용
    if any(et in entity_types for et in ["evalp", "evalp_detail", "evalp_pref"]):
        config.graph_rag_strategy = GraphRAGStrategy.NONE
        config.es_mode = ESMode.OFF
        config.use_loader = True
        if "evalp_pref" in entity_types:
            config.loader_name = "AnnouncementAdvantageLoader"
        else:
            config.loader_name = "AnnouncementScoringLoader"

    # Phase 99: 장비 검색 - ES/Qdrant 먼저 → SQL 확장 패턴
    if "equip" in entity_types or "equipment" in entity_types:
        if query_subtype in ["list", "recommendation"]:
            # ES 다중 필드 검색 (장비명, 설명, 스펙, KPI, 기관명)
            config.es_mode = ESMode.KEYWORD_BOOST
            # Qdrant 벡터 유사도 검색도 병행
            config.graph_rag_strategy = GraphRAGStrategy.HYBRID
            # ES/Qdrant 결과를 SQL로 상세 조회
            config.primary_sources = [SearchSource.ES, SearchSource.VECTOR]
            config.fallback_sources = [SearchSource.SQL]
            config.use_loader = True
            config.loader_name = "EquipmentKPILoader"

    # 특허 검색은 ES 우선 고려
    if "patent" in entity_types:
        if query_subtype in ["list", "ranking"]:
            # 특허는 ES 키워드 검색이 효과적
            if config.es_mode == ESMode.OFF:
                config.es_mode = ESMode.KEYWORD_BOOST

    # 협업 기관 추천
    if "proposal" in entity_types and query_subtype == "recommendation":
        config.use_loader = True
        config.loader_name = "CollaborationLoader"
        config.graph_rag_strategy = GraphRAGStrategy.GRAPH_ENHANCED

    return config


def _adjust_for_query_type(config: SearchConfig, query_type: str) -> SearchConfig:
    """query_type에 따른 설정 조정"""

    if query_type == "simple":
        # 단순 질문은 검색 불필요
        config.primary_sources = []
        config.graph_rag_strategy = GraphRAGStrategy.NONE
        config.es_mode = ESMode.OFF

    elif query_type == "sql":
        # SQL 전용
        config.primary_sources = [SearchSource.SQL]
        config.graph_rag_strategy = GraphRAGStrategy.NONE

    elif query_type == "rag":
        # RAG 전용 - SQL 제거
        if SearchSource.SQL in config.primary_sources:
            config.primary_sources.remove(SearchSource.SQL)
        if not config.primary_sources:
            config.primary_sources = [SearchSource.VECTOR]
        if config.graph_rag_strategy == GraphRAGStrategy.NONE:
            config.graph_rag_strategy = GraphRAGStrategy.HYBRID

    elif query_type == "hybrid":
        # SQL + RAG 모두 사용
        if SearchSource.SQL not in config.primary_sources:
            config.primary_sources.insert(0, SearchSource.SQL)
        if config.graph_rag_strategy == GraphRAGStrategy.NONE:
            config.graph_rag_strategy = GraphRAGStrategy.HYBRID

    return config


def _loader_exists(loader_name: str) -> bool:
    """Loader 존재 여부 확인"""
    try:
        from workflow.loaders.registry import get_loader_class
        return get_loader_class(loader_name) is not None
    except ImportError:
        return False
    except Exception:
        return False


def get_merge_priority_order(config: SearchConfig) -> List[str]:
    """병합 우선순위 순서 반환"""
    return sorted(config.merge_priority.keys(), key=lambda x: config.merge_priority.get(x, 99))
