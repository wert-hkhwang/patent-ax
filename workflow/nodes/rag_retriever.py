"""
RAG 검색 노드
- 기존 GraphRAG 래핑
- 하이브리드 검색 (벡터 + 그래프 + ES)
- 동적 전략 선택
- Phase 88: Elasticsearch 키워드 검색 통합
- Phase 89: SearchConfig 기반 전략 선택
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import logging
from typing import Dict, Any, List, Optional

from workflow.state import (
    AgentState, SearchResult, SearchConfig,
    GraphRAGStrategy, ESMode, SearchSource
)
from workflow.errors import RAGRetrievalError
# Patent-AX: domain_mapping 제거 (특허만 처리)
from graph.graph_rag import get_graph_rag, initialize_graph_rag, SearchStrategy

# Patent-AX: 특허 컬렉션 고정
PATENT_COLLECTIONS = ["patents_v3_collection"]

logger = logging.getLogger(__name__)

# ============================================================================
# Phase 90: Confidence Threshold 설정
# ============================================================================
# 환각 방지를 위한 최소 신뢰도 임계값
MIN_VECTOR_SCORE = 0.35     # 벡터 검색 최소 점수 (Qdrant: 0~1)
MIN_GRAPH_SCORE = 0.25      # 그래프 검색 최소 점수 (PageRank 정규화)
MIN_ES_SCORE = 3.0          # ES 검색 최소 점수 (BM25 raw score)
MIN_ES_NORMALIZED = 0.1     # ES 정규화 후 최소 점수

def _filter_by_confidence(
    results: List['SearchResult'],
    source_type: str = "vector"
) -> List['SearchResult']:
    """Phase 90: 신뢰도 기반 결과 필터링

    낮은 점수의 결과를 필터링하여 환각 방지.

    Args:
        results: 검색 결과 목록
        source_type: 소스 타입 ("vector", "graph", "es")

    Returns:
        임계값 이상의 결과만 포함된 목록
    """
    thresholds = {
        "vector": MIN_VECTOR_SCORE,
        "graph": MIN_GRAPH_SCORE,
        "es": MIN_ES_NORMALIZED,
    }
    min_score = thresholds.get(source_type, 0.25)

    filtered = [r for r in results if r.score >= min_score]

    if len(filtered) < len(results):
        logger.info(f"Phase 90: 신뢰도 필터 [{source_type}] {len(results)} → {len(filtered)}건 (threshold: {min_score})")

    return filtered


def _cross_validate_with_sql(
    rag_results: List['SearchResult'],
    sql_ids: set
) -> List['SearchResult']:
    """Phase 90: SQL 결과와 RAG 결과 교차 검증

    SQL에서도 조회된 엔티티는 점수 부스트,
    SQL에 없는 엔티티는 cross_validated=False 표시.

    Args:
        rag_results: RAG 검색 결과 목록
        sql_ids: SQL에서 조회된 ID 집합 (conts_id, document_id 등)

    Returns:
        교차 검증 정보가 추가된 결과 목록
    """
    if not sql_ids:
        return rag_results

    validated_count = 0
    for r in rag_results:
        # node_id에서 엔티티 ID 추출 (예: project_S3269017 → S3269017)
        entity_id = r.node_id.split('_', 1)[-1] if '_' in r.node_id else r.node_id

        # metadata에서도 ID 확인
        doc_id = r.metadata.get('documentid') or r.metadata.get('conts_id') or r.metadata.get('sbjt_id')

        if entity_id in sql_ids or (doc_id and doc_id in sql_ids):
            r.metadata['cross_validated'] = True
            r.score *= 1.15  # 교차 검증된 결과 15% 점수 부스트
            validated_count += 1
        else:
            r.metadata['cross_validated'] = False

    if validated_count > 0:
        logger.info(f"Phase 90: 교차 검증 완료 - {validated_count}/{len(rag_results)}건 검증됨")

    return rag_results


# ============================================================================
# Phase 95: 벡터+그래프 RRF 병합 함수
# ============================================================================

def _merge_vector_and_graph_results(
    vector_results: List[Any],
    graph_results: List[Any],
    limit: int = 15,
    k: int = 60
) -> List['SearchResult']:
    """Phase 95: 벡터 + 그래프 검색 결과 RRF 병합

    벡터 검색: 의미론적 유사도 기반 (Qdrant)
    그래프 검색: PageRank + 커뮤니티 기반 (cuGraph)

    RRF 공식: score = Σ (1 / (k + rank + 1))

    Args:
        vector_results: 벡터 검색 결과 목록 (CachedResult 또는 SearchResult)
        graph_results: 그래프 검색 결과 목록 (GraphSearchResult)
        limit: 반환할 최대 결과 수
        k: RRF 상수 (default: 60)

    Returns:
        RRF 병합된 SearchResult 목록
    """
    combined_scores = {}

    # 1. 벡터 결과 처리
    for rank, r in enumerate(vector_results):
        node_id = getattr(r, 'node_id', str(r.get('id', ''))) if isinstance(r, dict) else r.node_id
        if not node_id:
            continue

        combined_scores[node_id] = {
            "result": r,
            "vector_rrf": 1.0 / (k + rank + 1),
            "graph_rrf": 0.0,
            "source": "vector",
            "related_entities": [],
        }

    # 2. 그래프 결과 처리
    for rank, r in enumerate(graph_results):
        node_id = getattr(r, 'node_id', '')
        if not node_id:
            continue

        related_entities = getattr(r, 'related_entities', []) or []

        if node_id in combined_scores:
            # 이미 벡터에서 발견됨 - 그래프 점수 추가
            combined_scores[node_id]["graph_rrf"] = 1.0 / (k + rank + 1)
            combined_scores[node_id]["source"] = "both"
            # 그래프 관련 엔티티 정보 추가
            if related_entities:
                combined_scores[node_id]["related_entities"] = related_entities
        else:
            # 그래프에서만 발견됨
            combined_scores[node_id] = {
                "result": r,
                "vector_rrf": 0.0,
                "graph_rrf": 1.0 / (k + rank + 1),
                "source": "graph",
                "related_entities": related_entities,
            }

    # 3. RRF 총점 계산 및 정렬
    for item in combined_scores.values():
        item["total_rrf"] = item["vector_rrf"] + item["graph_rrf"]

    sorted_items = sorted(combined_scores.values(), key=lambda x: x["total_rrf"], reverse=True)

    # 4. SearchResult로 변환
    merged_results = []
    for item in sorted_items[:limit]:
        r = item["result"]

        # 기존 속성 추출
        node_id = getattr(r, 'node_id', '') or str(getattr(r, 'id', ''))
        name = getattr(r, 'name', '') or ''
        entity_type = getattr(r, 'entity_type', '') or ''
        score = getattr(r, 'score', 0.0)
        content = getattr(r, 'content', '') or getattr(r, 'description', '') or ''
        metadata = getattr(r, 'metadata', {}) or {}

        # Phase 95: 그래프 관련 정보 추가
        if item["related_entities"]:
            metadata["related_entities"] = item["related_entities"]
        metadata["rrf_source"] = item["source"]
        metadata["rrf_score"] = item["total_rrf"]

        merged_results.append(SearchResult(
            node_id=node_id,
            name=name,
            entity_type=entity_type,
            score=score,
            content=content,
            metadata=metadata
        ))

    # 로그
    vector_count = sum(1 for item in sorted_items if item["source"] in ["vector", "both"])
    graph_only_count = sum(1 for item in sorted_items if item["source"] == "graph")
    both_count = sum(1 for item in sorted_items if item["source"] == "both")

    logger.info(
        f"Phase 95: RRF 병합 완료 - "
        f"벡터: {len(vector_results)}, 그래프: {len(graph_results)} → "
        f"결과: {len(merged_results)} (양쪽: {both_count}, 벡터만: {vector_count - both_count}, 그래프만: {graph_only_count})"
    )

    return merged_results


# ES 클라이언트 (lazy import)
_es_client = None

def _get_es_client():
    """ES 클라이언트 싱글톤 (lazy initialization)"""
    global _es_client
    if _es_client is None:
        try:
            from search.es_client import ESSearchClient
            _es_client = ESSearchClient()
            if _es_client.is_available():
                logger.info("Elasticsearch 클라이언트 초기화 완료")
            else:
                logger.warning("Elasticsearch 연결 불가 - ES 검색 비활성화")
                _es_client = None
        except Exception as e:
            logger.warning(f"Elasticsearch 클라이언트 초기화 실패: {e}")
            _es_client = None
    return _es_client


def _select_search_strategy(state: AgentState) -> SearchStrategy:
    """SearchConfig 기반 검색 전략 선택 (Phase 89)

    Args:
        state: 현재 에이전트 상태

    Returns:
        선택된 검색 전략
    """
    # Phase 89: SearchConfig에서 전략 가져오기
    search_config = state.get("search_config")
    if search_config and hasattr(search_config, 'graph_rag_strategy'):
        strategy_map = {
            GraphRAGStrategy.VECTOR_ONLY: SearchStrategy.VECTOR_ONLY,
            GraphRAGStrategy.GRAPH_ONLY: SearchStrategy.GRAPH_ONLY,
            GraphRAGStrategy.HYBRID: SearchStrategy.HYBRID,
            GraphRAGStrategy.GRAPH_ENHANCED: SearchStrategy.GRAPH_ENHANCED,
            GraphRAGStrategy.NONE: SearchStrategy.VECTOR_ONLY,  # fallback
        }
        selected = strategy_map.get(search_config.graph_rag_strategy, SearchStrategy.HYBRID)
        logger.info(f"전략 선택 (SearchConfig): {selected.value}")
        return selected

    # Fallback: 기존 키워드 기반 로직
    return _select_search_strategy_legacy(state)


def _select_search_strategy_legacy(state: AgentState) -> SearchStrategy:
    """기존 키워드 기반 전략 선택 (fallback)"""
    query_intent = state.get("query_intent", "").lower()

    # 벡터 검색 우선 (의미 검색)
    semantic_indicators = ["동향", "트렌드", "개념", "설명", "의미", "정의", "관련", "사례", "현황"]
    if any(kw in query_intent for kw in semantic_indicators):
        logger.info("전략 선택: VECTOR_ONLY (의미 기반 검색)")
        return SearchStrategy.VECTOR_ONLY

    # 그래프 탐색 우선
    graph_indicators = ["연결", "관계", "연관", "네트워크", "협력"]
    if any(kw in query_intent for kw in graph_indicators):
        logger.info("전략 선택: GRAPH_ONLY (그래프 탐색)")
        return SearchStrategy.GRAPH_ONLY

    # 그래프 확장 검색
    entity_indicators = ["이름", "번호", "코드", "id", "검색"]
    if any(kw in query_intent for kw in entity_indicators):
        logger.info("전략 선택: GRAPH_ENHANCED (그래프 확장 검색)")
        return SearchStrategy.GRAPH_ENHANCED

    # 기본값
    logger.info("전략 선택: HYBRID (기본값)")
    return SearchStrategy.HYBRID


# 엔티티 타입 -> ES 엔티티 타입 매핑
ENTITY_TO_ES_TYPE = {
    "patent": "patent",
    "project": "project",
    "equipment": "equipment",
    "equip": "equipment",
    "proposal": "proposal",
    "evaluation": "evaluation",
    "eval": "evaluation",
}

# Phase 90.1: ES ranking 필드 매핑 (엔티티별 그룹화 필드)
ES_RANKING_FIELD_MAP = {
    "patent": "patent_frst_appn.keyword",
    "project": "conts_rspns_nm.keyword",
    "proposal": "orgn_nm.keyword",
    "equipment": "org_nm.keyword",
}


def _search_es_ranking(
    query: str,
    keywords: List[str],
    entity_types: List[str],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Phase 90.1: ES ranking 검색 (aggregation 기반)

    특정 엔티티 타입의 출원기관/수행기관 순위를 ES aggregation으로 조회

    Args:
        query: 검색어
        keywords: 키워드 목록
        entity_types: 검색할 엔티티 타입 목록
        limit: 상위 N개

    Returns:
        [{"key": "기관명", "doc_count": 건수}, ...]
    """
    es_client = _get_es_client()
    if not es_client:
        return []

    results = []

    for entity_type in entity_types:
        es_type = ENTITY_TO_ES_TYPE.get(entity_type)
        group_field = ES_RANKING_FIELD_MAP.get(es_type)

        if not es_type or not group_field:
            continue

        try:
            import asyncio

            # 키워드 합성 검색어
            search_query = " ".join(keywords[:3]) if keywords else query[:50]

            async def _do_ranking():
                return await es_client.async_client.search(
                    index=es_client.INDEX_MAP.get(es_type, f"ax_{es_type}s"),
                    body={
                        "size": 0,
                        "query": {
                            "multi_match": {
                                "query": search_query,
                                "fields": es_client.SEARCH_FIELDS.get(es_type, ["*"]),
                                "type": "best_fields"
                            }
                        },
                        "aggs": {
                            "ranking": {
                                "terms": {
                                    "field": group_field,
                                    "size": limit
                                }
                            }
                        }
                    }
                )

            # 비동기 실행
            try:
                loop = asyncio.get_running_loop()
                import nest_asyncio
                nest_asyncio.apply()
                response = asyncio.run(_do_ranking())
            except RuntimeError:
                response = asyncio.run(_do_ranking())

            buckets = response.get("aggregations", {}).get("ranking", {}).get("buckets", [])

            for bucket in buckets:
                results.append({
                    "key": bucket["key"],
                    "doc_count": bucket["doc_count"],
                    "entity_type": entity_type,
                })

            logger.info(f"Phase 90.1: ES ranking [{es_type}] → {len(buckets)}건")

        except Exception as e:
            logger.error(f"Phase 90.1: ES ranking 검색 실패 [{entity_type}]: {e}")
            continue

    return results


def _convert_es_ranking_to_sql_result(es_ranking: List[Dict[str, Any]]) -> Optional['SQLQueryResult']:
    """Phase 90.2: ES ranking 결과를 SQLQueryResult 형태로 변환

    simple_ranking 쿼리에서 ES aggregation 결과를 generator에서 사용할 수 있도록 변환.

    Args:
        es_ranking: [{"key": "기관명", "doc_count": 건수, "entity_type": "patent"}, ...]

    Returns:
        SQLQueryResult 형태의 결과
    """
    from workflow.state import SQLQueryResult

    if not es_ranking:
        return None

    # 컬럼 정의 (엔티티 타입에 따라 동적으로 결정)
    first_entity = es_ranking[0].get("entity_type", "unknown")
    if first_entity == "patent":
        columns = ["출원기관", "특허수"]
    elif first_entity == "project":
        columns = ["수행기관", "과제수"]
    else:
        columns = ["기관명", "건수"]

    # 행 데이터 생성
    rows = []
    for item in es_ranking:
        rows.append([
            item.get("key", ""),
            item.get("doc_count", 0),
        ])

    logger.info(f"Phase 90.2: ES ranking → SQLQueryResult 변환: {len(rows)}건")

    return SQLQueryResult(
        success=True,
        columns=columns,
        rows=rows,
        row_count=len(rows),
    )


def _search_elasticsearch(
    query: str,
    entity_types: List[str],
    limit: int = 10,
    filters: Optional[Dict[str, Any]] = None,
) -> List[SearchResult]:
    """Elasticsearch 키워드 검색 수행

    Args:
        query: 검색어
        entity_types: 검색할 엔티티 타입 목록
        limit: 타입당 최대 결과 수
        filters: 추가 필터 (선택)

    Returns:
        SearchResult 목록
    """
    es_client = _get_es_client()
    if not es_client:
        return []

    results = []

    for entity_type in entity_types:
        es_type = ENTITY_TO_ES_TYPE.get(entity_type)
        if not es_type:
            continue

        try:
            es_results = es_client.search_sync(
                query=query,
                entity_type=es_type,
                limit=limit,
                filters=filters,
                include_highlight=True,
            )

            for r in es_results:
                # ES 결과를 SearchResult로 변환
                source = r.source

                # 엔티티별 이름 필드
                name = ""
                if es_type == "patent":
                    name = source.get("conts_klang_nm", "")
                elif es_type == "project":
                    name = source.get("conts_klang_nm", "")
                elif es_type == "equipment":
                    name = source.get("conts_klang_nm", "")
                elif es_type == "proposal":
                    name = source.get("sbjt_nm", "")
                elif es_type == "evaluation":
                    name = source.get("ancm_nm", "") or source.get("eval_idx_nm", "")

                # 컨텐츠 (하이라이트 또는 요약)
                content = ""
                if r.highlight:
                    # 하이라이트된 텍스트 사용
                    for field, fragments in r.highlight.items():
                        if fragments:
                            content = " ... ".join(fragments[:2])
                            break
                if not content:
                    # 하이라이트 없으면 본문 일부
                    if es_type == "patent":
                        content = source.get("patent_abstc_ko", "")[:300]
                    elif es_type == "proposal":
                        content = source.get("dvlp_gole", "")[:300]
                    elif es_type == "equipment":
                        content = source.get("equip_desc", "")[:300]

                results.append(SearchResult(
                    node_id=f"es_{es_type}_{r.id}",
                    name=name,
                    entity_type=entity_type,
                    score=r.score,
                    content=content,
                    metadata={
                        "source": "elasticsearch",
                        "es_index": r.index,
                        **source,  # 전체 문서 데이터 포함
                    }
                ))

            logger.info(f"ES 검색 [{es_type}]: {len(es_results)}건")

        except Exception as e:
            logger.warning(f"ES 검색 실패 [{es_type}]: {e}")
            continue

    # 점수순 정렬
    results.sort(key=lambda x: x.score, reverse=True)
    return results


# ============================================================================
# Phase 90.1: RRF (Reciprocal Rank Fusion) 유틸리티
# ============================================================================

def merge_ranking_with_rrf(
    sql_ranking: List[Dict[str, Any]],
    es_ranking: List[Dict[str, Any]],
    k: int = 60
) -> List[Dict[str, Any]]:
    """SQL과 ES ranking 결과를 RRF로 통합

    RRF 공식: score = Σ (1 / (k + rank))
    k는 smoothing factor (기본값: 60)

    Args:
        sql_ranking: SQL 결과 [{"출원기관": str, "특허수": int, ...}, ...]
        es_ranking: ES 결과 [{"key": str, "doc_count": int}, ...]
        k: RRF smoothing factor

    Returns:
        통합된 랭킹 [{"org": str, "sql_count": int, "es_count": int, "rrf_score": float}, ...]
    """
    combined = {}

    # SQL 결과 처리
    for rank, item in enumerate(sql_ranking):
        org = item.get("출원기관") or item.get("기관명") or item.get("org", "")
        if not org:
            continue

        if org not in combined:
            combined[org] = {
                "org": org,
                "sql_count": 0,
                "es_count": 0,
                "sql_rrf": 0,
                "es_rrf": 0,
                "total_rrf": 0,
            }

        combined[org]["sql_count"] = item.get("특허수") or item.get("count", 0)
        combined[org]["sql_rrf"] = 1 / (k + rank + 1)
        combined[org]["total_rrf"] += combined[org]["sql_rrf"]

    # ES 결과 처리
    for rank, item in enumerate(es_ranking):
        org = item.get("key", "")
        if not org:
            continue

        if org not in combined:
            combined[org] = {
                "org": org,
                "sql_count": 0,
                "es_count": 0,
                "sql_rrf": 0,
                "es_rrf": 0,
                "total_rrf": 0,
            }

        combined[org]["es_count"] = item.get("doc_count", 0)
        combined[org]["es_rrf"] = 1 / (k + rank + 1)
        combined[org]["total_rrf"] += combined[org]["es_rrf"]

    # RRF 점수 기준 정렬
    ranked = sorted(
        combined.values(),
        key=lambda x: x["total_rrf"],
        reverse=True
    )

    logger.info(f"Phase 90.1: RRF 통합 - SQL {len(sql_ranking)}건 + ES {len(es_ranking)}건 → 상위 {min(10, len(ranked))}건")

    return ranked[:10]


def merge_ranking_with_rrf_multi_source(
    sql_ranking: List[Dict[str, Any]],
    es_ranking: List[Dict[str, Any]],
    graph_ranking: List[Dict[str, Any]] = None,
    k: int = 60
) -> List[Dict[str, Any]]:
    """Phase 90.2: SQL + ES + Graph ranking을 RRF로 통합

    RRF 공식: score = Σ (1 / (k + rank_in_source))

    Args:
        sql_ranking: SQL 결과 [{"출원기관": str, "특허수": int}, ...]
        es_ranking: ES 결과 [{"key": str, "doc_count": int}, ...]
        graph_ranking: Graph 결과 [{"name": str, "pagerank": float}, ...]
        k: RRF smoothing factor

    Returns:
        통합된 랭킹 [{"org": str, "sql_count": int, "es_count": int, "graph_score": float, "total_rrf": float}, ...]
    """
    if graph_ranking is None:
        graph_ranking = []

    combined = {}

    # 1. SQL 결과 처리
    for rank, item in enumerate(sql_ranking):
        org = item.get("출원기관") or item.get("기관명") or item.get("org", "")
        if not org:
            continue
        if org not in combined:
            combined[org] = {"org": org, "sql_count": 0, "es_count": 0,
                           "graph_score": 0, "total_rrf": 0}
        combined[org]["sql_count"] = item.get("특허수") or item.get("count", 0)
        combined[org]["total_rrf"] += 1 / (k + rank + 1)

    # 2. ES 결과 처리
    for rank, item in enumerate(es_ranking):
        org = item.get("key", "")
        if not org:
            continue
        if org not in combined:
            combined[org] = {"org": org, "sql_count": 0, "es_count": 0,
                           "graph_score": 0, "total_rrf": 0}
        combined[org]["es_count"] = item.get("doc_count", 0)
        combined[org]["total_rrf"] += 1 / (k + rank + 1)

    # 3. Graph 결과 처리
    for rank, item in enumerate(graph_ranking):
        org = item.get("name", "")
        if not org:
            continue
        if org not in combined:
            combined[org] = {"org": org, "sql_count": 0, "es_count": 0,
                           "graph_score": 0, "total_rrf": 0}
        combined[org]["graph_score"] = item.get("pagerank", 0)
        combined[org]["total_rrf"] += 1 / (k + rank + 1)

    # RRF 점수 기준 정렬
    ranked = sorted(combined.values(), key=lambda x: x["total_rrf"], reverse=True)

    logger.info(f"Phase 90.2: RRF 통합 - SQL {len(sql_ranking)} + ES {len(es_ranking)} + Graph {len(graph_ranking)} → {len(ranked[:10])}건")

    return ranked[:10]


def _merge_search_results(
    rag_results: List[SearchResult],
    es_results: List[SearchResult],
    max_results: int = 15,
    priority: Optional[Dict[str, int]] = None,
) -> List[SearchResult]:
    """RAG와 ES 검색 결과 병합 (Phase 89: 우선순위 기반)

    중복 제거 및 점수 기반 재랭킹 수행.

    Args:
        rag_results: GraphRAG 검색 결과
        es_results: ES 검색 결과
        max_results: 최대 반환 결과 수
        priority: 소스별 우선순위 {"sql": 0, "vector": 1, "es": 2, "graph": 3}

    Returns:
        병합된 SearchResult 목록
    """
    # 기본 우선순위: vector > es
    if priority is None:
        priority = {"sql": 0, "vector": 1, "es": 2, "graph": 3}

    # ID 기반 중복 체크용 맵
    seen_ids = set()
    merged = []

    # 소스별 우선순위에 따른 가중치 계산
    vector_boost = 1.0 - (priority.get("vector", 1) * 0.1)  # 우선순위 0이면 1.0, 1이면 0.9
    es_boost = 1.0 - (priority.get("es", 2) * 0.1)  # 우선순위 2이면 0.8

    # RAG 결과 추가
    for r in rag_results:
        # node_id에서 실제 ID 추출
        key = r.node_id.replace("patent_", "").replace("project_", "").replace("equip_", "")
        if key not in seen_ids:
            seen_ids.add(key)
            # 우선순위에 따른 점수 부스트
            r.score = r.score * vector_boost
            merged.append(r)

    # ES 결과 추가 (키워드 매칭 보완)
    for r in es_results:
        # ES 결과에서 실제 문서 ID 추출
        doc_id = r.metadata.get("documentid") or r.metadata.get("conts_id") or r.metadata.get("sbjt_id") or r.node_id
        if doc_id and doc_id not in seen_ids:
            seen_ids.add(doc_id)
            # ES 점수를 RAG 스케일로 정규화 (ES는 보통 0-30, RAG는 0-1)
            normalized_score = min(r.score / 30.0, 1.0)
            # 우선순위에 따른 점수 부스트
            r.score = normalized_score * es_boost
            merged.append(r)

    # 점수순 재정렬
    merged.sort(key=lambda x: x.score, reverse=True)

    logger.info(f"검색 결과 병합: RAG {len(rag_results)}건 + ES {len(es_results)}건 → {len(merged[:max_results])}건 (priority: {priority})")
    return merged[:max_results]


def _extract_results_from_cache(
    cached_results: Dict[str, List[Dict]],
    limit: int = 10
) -> List[Any]:
    """Phase 35: 캐시된 벡터 결과에서 상위 결과 추출

    Args:
        cached_results: 컬렉션별 캐시된 벡터 검색 결과
        limit: 반환할 최대 결과 수

    Returns:
        SearchResult 호환 객체 목록
    """
    from dataclasses import dataclass

    @dataclass
    class CachedResult:
        """캐시된 결과를 SearchResult 호환 형태로 변환"""
        node_id: str
        name: str
        entity_type: str
        score: float
        content: str = ""
        metadata: Dict = None

        def __post_init__(self):
            if self.metadata is None:
                self.metadata = {}

    all_results = []

    for collection, results in cached_results.items():
        # 컬렉션 이름에서 엔티티 타입 추론
        entity_type = "unknown"
        if "patent" in collection:
            entity_type = "patent"
        elif "project" in collection:
            entity_type = "project"
        elif "equipment" in collection:
            entity_type = "equip"
        elif "proposal" in collection:
            entity_type = "proposal"
        elif "tech" in collection:
            entity_type = "tech"

        for r in results:
            payload = r.get("payload", {})
            # 제목 또는 text 필드에서 이름 추출
            name = payload.get("title") or payload.get("conts_klang_nm") or payload.get("text", "")[:100]
            content = payload.get("text", "")

            all_results.append(CachedResult(
                node_id=r.get("id", ""),
                name=name,
                entity_type=entity_type,
                score=r.get("score", 0.0),
                content=content,
                metadata=payload
            ))

    # 점수 기준 정렬 후 상위 limit개 반환
    all_results.sort(key=lambda x: x.score, reverse=True)
    return all_results[:limit]


def retrieve_rag(state: AgentState) -> AgentState:
    """RAG 검색 노드

    Graph RAG + Elasticsearch 하이브리드 검색.
    - GraphRAG: 벡터(Qdrant) + 그래프(cuGraph) 검색
    - Elasticsearch: 키워드 기반 BM25 검색
    Phase 88: ES 검색 통합으로 키워드 매칭 강화.
    Phase 89: SearchConfig 기반 조건부 검색.

    Args:
        state: 현재 에이전트 상태

    Returns:
        업데이트된 상태 (rag_results, sources, search_strategy, entity_types)
    """
    query = state.get("query", "")
    state_entity_types = state.get("entity_types", [])
    cached_vector_results = state.get("cached_vector_results")  # Phase 35: 캐시 확인
    keywords = state.get("keywords", [])

    if not query.strip():
        return {
            **state,
            "rag_results": [],
            "search_strategy": "none"
        }

    # Phase 89: SearchConfig 가져오기 또는 생성
    search_config = state.get("search_config")
    if not search_config:
        from workflow.search_config import get_search_config
        search_config = get_search_config(state)

    try:
        # Phase 36: analyzer의 entity_types 우선 사용
        if state_entity_types:
            entity_types = state_entity_types
            logger.info(f"analyzer entity_types 사용: {entity_types}")
        else:
            entity_types = ["patent"]  # Patent-AX: 특허로 고정
            logger.warning(f"analyzer entity_types 없음, 특허로 고정")

        collections = PATENT_COLLECTIONS  # Patent-AX: 특허 컬렉션만
        logger.info(f"Patent-AX: entity_types={entity_types} -> 컬렉션: {collections}")

        # 검색 전략 결정 (Phase 89: SearchConfig 기반)
        strategy = _select_search_strategy(state)
        rag_limit = search_config.rag_limit if search_config else 15
        es_limit = search_config.es_limit if search_config else 10

        # Phase 89: GraphRAG 검색 여부 결정
        rag_results = []
        should_use_rag = (
            search_config.should_use_rag() if search_config
            else True  # fallback: 항상 RAG 사용
        )

        if should_use_rag:
            # Graph RAG 초기화 확인
            graph_rag = get_graph_rag()
            if not graph_rag:
                graph_rag = initialize_graph_rag(
                    graph_id="713365bb",
                    project_limit=500
                )

            # Phase 95: 캐시 있어도 그래프 검색은 별도로 수행
            # 1. 벡터 검색 결과 (캐시 사용 가능)
            vector_results = []
            if cached_vector_results:
                logger.info(f"캐시된 벡터 결과 재사용: {len(cached_vector_results)}개 컬렉션")
                vector_results = _extract_results_from_cache(cached_vector_results, limit=rag_limit)
            else:
                # 캐시 없으면 벡터 검색 수행
                vector_raw = graph_rag._vector_search(
                    query=query,
                    entity_types=entity_types,
                    limit=rag_limit,
                    collections=collections
                )
                vector_results = vector_raw
                logger.debug(f"Phase 102: 벡터 검색 완료 {len(vector_results)}건")

            # 2. 그래프 검색 (cuGraph 사용) - 캐시와 무관하게 항상 실행
            graph_results = []
            graph_strategy = search_config.graph_rag_strategy if search_config else GraphRAGStrategy.HYBRID
            logger.debug(f"Phase 102: graph_strategy={graph_strategy.value if hasattr(graph_strategy, 'value') else graph_strategy}")

            if graph_strategy in [GraphRAGStrategy.GRAPH_ONLY, GraphRAGStrategy.HYBRID, GraphRAGStrategy.GRAPH_ENHANCED]:
                try:
                    # Phase 98: graph_builder 초기화 상태 명시적 확인
                    if not graph_rag.graph_builder:
                        logger.info("Phase 98: graph_builder 미초기화 감지, 초기화 수행...")
                        try:
                            graph_rag.initialize(graph_id="713365bb", project_limit=500)
                            logger.info("Phase 98: graph_builder 초기화 완료")
                        except Exception as init_e:
                            logger.warning(f"Phase 98: graph_builder 초기화 실패: {init_e}")

                    if graph_rag.graph_builder:
                        graph_results = graph_rag._graph_search(
                            query=query,
                            entity_types=entity_types,
                            max_depth=2,
                            limit=rag_limit,
                            include_context=True
                        )
                        logger.info(f"Phase 95: cuGraph 검색 완료: {len(graph_results)}건")
                    else:
                        logger.warning("Phase 98: graph_builder 초기화 불가, 그래프 검색 스킵")
                except Exception as e:
                    logger.warning(f"Phase 95: cuGraph 검색 실패 (벡터만 사용): {e}")
                    graph_results = []

            # 3. 벡터 + 그래프 결과 RRF 병합
            if graph_results:
                results = _merge_vector_and_graph_results(
                    vector_results=vector_results,
                    graph_results=graph_results,
                    limit=rag_limit
                )
            else:
                # 그래프 결과 없으면 벡터만 사용 (기존 방식)
                results = vector_results

            # Phase 102: 그래프 검색 결과 없을 때, 벡터 결과에서 그래프 관련 엔티티 추출
            if not graph_results and graph_rag.graph_builder:
                logger.debug(f"Phase 102: 벡터 결과에서 그래프 관련 엔티티 추출 시도 ({len(results)}건)")
                for r in results[:5]:  # 상위 5개에 대해서만
                    node_id = getattr(r, 'node_id', '')
                    if not node_id:
                        continue
                    try:
                        # Phase 102: related_entities에서 document_id 추출 (벡터 검색에서 저장됨)
                        rel_entities = getattr(r, 'related_entities', None)
                        doc_id = None
                        if rel_entities and len(rel_entities) > 0:
                            doc_id = rel_entities[0].get("document_id", "")

                        # document_id가 있으면 그것을 사용, 없으면 node_id에서 추출 시도
                        if doc_id:
                            raw_id = doc_id.lower()  # 특허번호는 소문자로 정규화
                        else:
                            raw_id = node_id.replace("patent_", "").replace("es_patent_", "")

                        graph_node_id = graph_rag.graph_builder._doc_id_to_node_id(
                            raw_id,
                            entity_types
                        )
                        if graph_node_id:
                            related = graph_rag.graph_builder.find_related_entities(
                                graph_node_id,
                                relation_types=None,  # 모든 타입
                                max_depth=1
                            )[:5]
                            if related:
                                # metadata에 related_entities 추가 (기존 document_id 정보 대체)
                                if hasattr(r, 'metadata') and r.metadata is not None:
                                    r.metadata["related_entities"] = related
                                else:
                                    r.metadata = {"related_entities": related}
                                # GraphSearchResult의 related_entities도 업데이트
                                if hasattr(r, 'related_entities'):
                                    r.related_entities = related
                                logger.debug(f"Phase 102: {node_id} → related_entities {len(related)}건")
                    except Exception as rel_e:
                        logger.debug(f"Phase 102: 관련 엔티티 추출 실패: {node_id}, {rel_e}")

            # SearchResult로 변환
            for r in results:
                # 이미 SearchResult인 경우 (RRF 병합 후) 바로 추가
                if isinstance(r, SearchResult):
                    rag_results.append(r)
                else:
                    rag_results.append(SearchResult(
                        node_id=getattr(r, 'node_id', ''),
                        name=getattr(r, 'name', ''),
                        entity_type=getattr(r, 'entity_type', ''),
                        score=getattr(r, 'score', 0.0),
                        content=getattr(r, 'description', '') or getattr(r, 'content', ''),
                        metadata=getattr(r, 'metadata', {})
                    ))

            logger.info(f"GraphRAG 검색 완료: {len(rag_results)}건 (벡터: {len(vector_results)}, 그래프: {len(graph_results)})")

            # Phase 90: 신뢰도 필터 적용 (벡터 검색 결과)
            rag_results = _filter_by_confidence(rag_results, "vector")
        else:
            logger.info("GraphRAG 검색 생략 (SearchConfig: should_use_rag=False)")

        # Phase 89: ES 검색 여부 결정
        es_results = []
        should_use_es = (
            search_config.should_use_es() if search_config
            else True  # fallback
        )

        # Phase 90.2: simple_ranking인 경우 ES ranking 검색 우선 수행
        query_subtype = state.get("query_subtype", "")
        ranking_type = state.get("ranking_type", "simple")

        if query_subtype == "ranking" and should_use_es:
            es_ranking_results = _search_es_ranking(
                query=query,
                keywords=keywords,
                entity_types=entity_types,
                limit=es_limit,
            )

            if es_ranking_results:
                # ES ranking 결과를 별도 필드에 저장
                logger.info(f"Phase 90.2: ES ranking 검색 완료: {len(es_ranking_results)}건")

                # Phase 90.2: simple_ranking인 경우 ES 결과를 SQL 결과 형태로 변환
                if ranking_type == "simple":
                    sql_result = _convert_es_ranking_to_sql_result(es_ranking_results)
                    if sql_result:
                        logger.info(f"Phase 90.2: simple_ranking ES→SQL 변환 완료: {sql_result.row_count}건")
                        return {
                            **state,
                            "sql_result": sql_result,
                            "rag_results": rag_results,
                            "es_ranking_results": es_ranking_results,
                            "sources": [{"type": "es_ranking", "count": len(es_ranking_results)}],
                            "search_strategy": "es_ranking",
                            "entity_types": entity_types,
                            "es_enabled": True,
                            "search_config": search_config,
                        }

                # complex_ranking은 es_ranking_results만 저장 (parallel_ranking에서 사용)
                state["es_ranking_results"] = es_ranking_results

        if should_use_es:
            es_client = _get_es_client()
            if es_client:
                es_query = query
                if keywords:
                    es_query = f"{query} {' '.join(keywords[:5])}"

                # Phase 89: ES 모드에 따른 검색
                es_mode = search_config.es_mode if search_config else ESMode.KEYWORD_BOOST

                if es_mode == ESMode.AGGREGATION:
                    # 집계 검색 (동향 분석용)
                    logger.info("ES 집계 검색 모드")
                    # TODO: ES trend_analysis 메서드 호출
                    es_results = _search_elasticsearch(
                        query=es_query,
                        entity_types=entity_types,
                        limit=es_limit,
                    )
                else:
                    # 일반 키워드 검색
                    es_results = _search_elasticsearch(
                        query=es_query,
                        entity_types=entity_types,
                        limit=es_limit,
                    )

                logger.info(f"ES 검색 완료: {len(es_results)}건 (mode: {es_mode.value})")

                # Phase 90: ES 결과 신뢰도 필터 (raw score 기준)
                es_results = [r for r in es_results if r.score >= MIN_ES_SCORE]
                logger.info(f"Phase 90: ES 신뢰도 필터 후 {len(es_results)}건 (threshold: {MIN_ES_SCORE})")
        else:
            logger.info("ES 검색 생략 (SearchConfig: es_mode=OFF)")

        # Phase 89: 결과 병합 (우선순위 기반)
        if es_results:
            merge_priority = search_config.merge_priority if search_config else None
            rag_results = _merge_search_results(
                rag_results, es_results,
                max_results=rag_limit + 5,
                priority=merge_priority
            )

        # SQL로 상세 정보 보강 (Phase 6)
        rag_results = enrich_rag_with_sql(rag_results)

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

        # 소스 정보
        sources = []
        for r in rag_results[:5]:
            source_type = "es" if r.metadata.get("source") == "elasticsearch" else "rag"
            sources.append({
                "type": source_type,
                "node_id": r.node_id,
                "name": r.name,
                "entity_type": r.entity_type,
                "score": r.score,
                "graph_validated": r.metadata.get("graph_validated", False)  # Phase 96
            })

        logger.info(f"RAG+ES 검색 완료: {len(rag_results)}개 결과, 엔티티: {entity_types}")

        return {
            **state,
            "rag_results": rag_results,
            "sources": state.get("sources", []) + sources,
            "search_strategy": strategy.value,
            "entity_types": entity_types,
            "es_enabled": should_use_es and _get_es_client() is not None,
            "search_config": search_config,
        }

    except Exception as e:
        logger.error(f"RAG 검색 실패: {e}")
        return {
            **state,
            "rag_results": [],
            "search_strategy": "error",
            "error": f"RAG 검색 실패: {str(e)}"
        }


def enrich_rag_with_sql(rag_results: List[SearchResult]) -> List[SearchResult]:
    """RAG 검색 결과를 SQL로 보강

    node_id를 파싱하여 DB에서 상세 정보를 가져옴
    node_id 형식: {entity_type}_{id} (예: patent_KR12345, project_67890)

    Args:
        rag_results: RAG 검색 결과 목록

    Returns:
        상세 정보가 추가된 검색 결과
    """
    if not rag_results:
        return rag_results

    try:
        from sql.db_connector import get_db_connection

        # 엔티티 타입별 ID 수집
        patent_ids = []
        project_ids = []

        for r in rag_results:
            node_id = r.node_id
            # node_id 파싱 (예: "patent_KR12345" -> ("patent", "KR12345"))
            # Phase 103.2: es_patent_ 접두사도 처리
            if "_" in node_id:
                # es_patent_xxx 형태 처리
                if node_id.startswith("es_patent_"):
                    entity_id = node_id[10:]  # "es_patent_" 제거
                    if entity_id:
                        patent_ids.append(entity_id)
                else:
                    parts = node_id.split("_", 1)
                    if len(parts) == 2:
                        entity_type, entity_id = parts
                        if entity_type == "patent" and entity_id:
                            patent_ids.append(entity_id)
                        elif entity_type == "project" and entity_id:
                            project_ids.append(entity_id)

        # 배치 SQL 조회 (N+1 문제 방지)
        details_map = {}
        conn = None

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # 특허 상세 조회 (Phase 103: 초록/해결과제/해결수단 추가)
            # Phase 103.2: 제한 10→30 확장 (모든 특허에 상세정보 추가)
            if patent_ids:
                query_ids = patent_ids[:30]  # 최대 30개까지 확장
                placeholders = ",".join(["%s"] * len(query_ids))
                sql = f'''
                    SELECT p.documentid, p.conts_klang_nm, p.ipc_main,
                           p.ptnaplc_ymd, a.applicant_name,
                           p.patent_abstc_ko, p.objectko, p.solutionko
                    FROM f_patents p
                    LEFT JOIN f_patent_applicants a ON p.documentid = a.document_id
                    WHERE p.documentid IN ({placeholders})
                '''
                cursor.execute(sql, query_ids)
                for row in cursor.fetchall():
                    doc_id = row[0]
                    details = {
                        "documentid": doc_id,
                        "conts_klang_nm": row[1],
                        "ipc_main": row[2],
                        "ptnaplc_ymd": row[3],
                        "applicant_name": row[4],
                        "patent_abstc_ko": row[5],  # Phase 103: 한글 초록
                        "objectko": row[6],         # Phase 103: 해결과제
                        "solutionko": row[7]        # Phase 103: 해결수단
                    }
                    # Phase 103.2: 두 가지 node_id 형태 모두 지원
                    details_map[f"patent_{doc_id}"] = details
                    details_map[f"es_patent_{doc_id}"] = details

            # 과제/제안서 상세 조회
            if project_ids:
                placeholders = ",".join(["%s"] * len(project_ids[:10]))
                sql = f'''
                    SELECT sbjt_id, sbjt_nm, orgn_nm, ancm_yy, dev_period_months
                    FROM f_proposal_profile
                    WHERE sbjt_id IN ({placeholders})
                '''
                cursor.execute(sql, project_ids[:10])
                for row in cursor.fetchall():
                    sbjt_id = row[0]
                    details_map[f"project_{sbjt_id}"] = {
                        "sbjt_id": sbjt_id,
                        "sbjt_nm": row[1],
                        "orgn_nm": row[2],
                        "ancm_yy": row[3],
                        "dev_period_months": row[4]
                    }

        finally:
            if conn:
                conn.close()

        # 결과에 상세 정보 추가
        for r in rag_results:
            if r.node_id in details_map:
                r.metadata["sql_details"] = details_map[r.node_id]

        logger.info(f"RAG 결과 SQL 보강 완료: {len(details_map)}건")

        # Phase 90: 교차 검증 적용
        # SQL에서 조회된 ID 집합 생성
        sql_ids = set()
        for key in details_map.keys():
            # key 형식: "patent_KR12345" 또는 "project_S3269017"
            if "_" in key:
                entity_id = key.split("_", 1)[-1]
                sql_ids.add(entity_id)

        if sql_ids:
            rag_results = _cross_validate_with_sql(rag_results, sql_ids)

    except Exception as e:
        logger.warning(f"RAG 결과 SQL 보강 실패 (계속 진행): {e}")

    return rag_results


def format_rag_results_for_llm(rag_results: List[SearchResult], max_results: int = 10) -> str:
    """RAG 결과를 LLM 컨텍스트용으로 포맷팅"""
    if not rag_results:
        return "검색된 정보가 없습니다."

    lines = []
    lines.append(f"총 {len(rag_results)}개 관련 정보 검색됨")
    lines.append("")

    for i, r in enumerate(rag_results[:max_results], 1):
        lines.append(f"[{i}] {r.name} ({r.entity_type})")
        lines.append(f"    관련도: {r.score:.4f}")

        # SQL 상세 정보 표시 (있는 경우)
        if r.metadata.get("sql_details"):
            details = r.metadata["sql_details"]
            if r.entity_type == "patent":
                if details.get("ipc_main"):
                    lines.append(f"    IPC분류: {details['ipc_main']}")
                if details.get("ptnaplc_ymd"):
                    lines.append(f"    출원일: {details['ptnaplc_ymd']}")
                if details.get("applicant_name"):
                    lines.append(f"    출원인: {details['applicant_name']}")
                # Phase 103: 초록/해결과제/해결수단 추가
                if details.get("patent_abstc_ko"):
                    abstc = details['patent_abstc_ko'][:500] if len(details['patent_abstc_ko']) > 500 else details['patent_abstc_ko']
                    lines.append(f"    초록: {abstc}")
                if details.get("objectko"):
                    obj = details['objectko'][:300] if len(details['objectko']) > 300 else details['objectko']
                    lines.append(f"    해결과제: {obj}")
                if details.get("solutionko"):
                    sol = details['solutionko'][:300] if len(details['solutionko']) > 300 else details['solutionko']
                    lines.append(f"    해결수단: {sol}")
            elif r.entity_type == "project":
                if details.get("orgn_nm"):
                    lines.append(f"    기관: {details['orgn_nm']}")
                if details.get("ancm_yy"):
                    lines.append(f"    연도: {details['ancm_yy']}")
                if details.get("ttl_rsch_expn"):
                    lines.append(f"    예산: {details['ttl_rsch_expn']}")

        if r.content:
            content_preview = r.content[:200] + "..." if len(r.content) > 200 else r.content
            lines.append(f"    내용: {content_preview}")
        lines.append("")

    return "\n".join(lines)
