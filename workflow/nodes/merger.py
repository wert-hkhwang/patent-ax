"""
결과 병합 노드
- SQL + RAG 결과 병합
- 중복 제거 및 순위화
- Phase 19: 다중 엔티티 결과 분리 포맷팅
- Phase 89: SearchConfig.merge_priority 기반 소스 우선순위 적용
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import logging
from typing import Dict, Any, List, Optional

from workflow.state import AgentState, SearchResult, SQLQueryResult, SearchConfig

logger = logging.getLogger(__name__)


def merge_results(state: AgentState) -> AgentState:
    """결과 병합 노드

    SQL과 RAG 결과를 병합하여 통합 컨텍스트 생성.
    Phase 19: 다중 엔티티 결과도 처리
    Phase 89: SearchConfig.merge_priority 기반 소스 우선순위 적용
    Phase 90.2: complex_ranking RRF 통합

    Args:
        state: 현재 에이전트 상태

    Returns:
        업데이트된 상태 (merged context in state)
    """
    query_subtype = state.get("query_subtype", "list")
    ranking_sources = state.get("ranking_sources", [])

    # Phase 90.2: complex_ranking인 경우 RRF 통합 수행
    if query_subtype == "ranking" and ranking_sources:
        logger.info(f"Phase 90.2: ranking RRF 통합 시작 - sources={ranking_sources}")
        return _merge_ranking_with_rrf(state)

    query_type = state.get("query_type", "simple")
    sql_result = state.get("sql_result")
    multi_sql_results = state.get("multi_sql_results")  # Phase 19
    rag_results = state.get("rag_results", [])

    # Phase 89: SearchConfig에서 merge_priority 가져오기
    search_config = state.get("search_config")
    merge_priority = None
    if search_config and hasattr(search_config, 'merge_priority'):
        merge_priority = search_config.merge_priority
        logger.info(f"Phase 89: merge_priority 적용 - {merge_priority}")

    # 병합된 소스 정보 업데이트
    merged_sources = state.get("sources", [])

    # query_type에 따른 처리
    if query_type == "sql":
        # SQL 결과만 사용
        if multi_sql_results:
            # Phase 19: 다중 엔티티 결과
            total_rows = sum(r.row_count for r in multi_sql_results.values() if r.success)
            logger.info(f"SQL 전용 (다중 엔티티): {len(multi_sql_results)}개 타입, 총 {total_rows}행")
        elif sql_result and sql_result.success:
            logger.info(f"SQL 전용: {sql_result.row_count}행 결과")

    elif query_type == "rag":
        # RAG 결과만 사용
        if rag_results:
            logger.info(f"RAG 전용: {len(rag_results)}개 결과")

    elif query_type == "hybrid":
        # SQL + RAG 병합
        if multi_sql_results:
            total_rows = sum(r.row_count for r in multi_sql_results.values() if r.success)
            logger.info(f"하이브리드 (다중 엔티티): SQL {total_rows}행 + RAG {len(rag_results)}개")
        else:
            logger.info(f"하이브리드: SQL {sql_result.row_count if sql_result else 0}행 + RAG {len(rag_results)}개")

        # 중복 체크 및 순위화
        merged_sources = _deduplicate_sources(merged_sources)

        # Phase 89: merge_priority 기반 소스 정렬
        if merge_priority:
            merged_sources = _sort_sources_by_priority(merged_sources, merge_priority)

    # 상태 반환
    return {
        **state,
        "sources": merged_sources
    }


def _merge_ranking_with_rrf(state: AgentState) -> AgentState:
    """Phase 90.2: complex_ranking RRF 통합

    SQL + ES ranking 결과를 RRF로 통합하여 SQLQueryResult 형태로 반환.

    Args:
        state: 현재 에이전트 상태

    Returns:
        RRF 통합된 sql_result가 포함된 상태
    """
    sql_result = state.get("sql_result")
    es_ranking = state.get("es_ranking_results", [])
    graph_ranking = state.get("graph_ranking_results", [])

    # SQL 결과를 ranking 형식으로 변환
    sql_ranking = _convert_sql_to_ranking_format(sql_result)

    # RRF 통합
    from workflow.nodes.rag_retriever import merge_ranking_with_rrf_multi_source
    merged = merge_ranking_with_rrf_multi_source(sql_ranking, es_ranking, graph_ranking)

    # 통합 결과를 SQLQueryResult로 변환
    merged_sql = _convert_ranking_to_sql_result(merged)

    logger.info(f"Phase 90.2: RRF 통합 완료 - SQL {len(sql_ranking)}건 + ES {len(es_ranking)}건 → {merged_sql.row_count}건")

    return {
        **state,
        "sql_result": merged_sql,
        "sources": state.get("sources", []) + [{"type": "rrf_merged", "count": merged_sql.row_count}]
    }


def _convert_sql_to_ranking_format(sql_result: Optional[SQLQueryResult]) -> List[Dict[str, Any]]:
    """SQLQueryResult → ranking 형식으로 변환

    Args:
        sql_result: SQL 조회 결과

    Returns:
        [{"출원기관": str, "특허수": int}, ...] 형태의 리스트
    """
    if not sql_result or not sql_result.success or not sql_result.rows:
        return []

    ranking = []
    columns = sql_result.columns if sql_result.columns else []

    # 컬럼명에서 기관명과 건수 컬럼 인덱스 찾기
    org_idx = 0
    count_idx = 1

    for i, col in enumerate(columns):
        col_lower = str(col).lower()
        if any(kw in col_lower for kw in ["기관", "org", "출원인", "수행기관"]):
            org_idx = i
        if any(kw in col_lower for kw in ["수", "count", "건수", "특허"]):
            count_idx = i

    for row in sql_result.rows:
        if len(row) >= 2:
            ranking.append({
                "출원기관": row[org_idx] if len(row) > org_idx else "",
                "특허수": row[count_idx] if len(row) > count_idx else 0,
            })

    return ranking


def _convert_ranking_to_sql_result(merged_ranking: List[Dict[str, Any]]) -> SQLQueryResult:
    """RRF 통합 결과 → SQLQueryResult로 변환

    Args:
        merged_ranking: RRF 통합된 결과 리스트

    Returns:
        SQLQueryResult 형태의 결과
    """
    columns = ["순위", "기관명", "SQL건수", "ES건수", "RRF점수"]
    rows = []

    for rank, item in enumerate(merged_ranking, 1):
        rows.append([
            rank,
            item.get("org", ""),
            item.get("sql_count", 0),
            item.get("es_count", 0),
            round(item.get("total_rrf", 0), 4)
        ])

    return SQLQueryResult(
        success=True,
        columns=columns,
        rows=rows,
        row_count=len(rows),
    )


def _deduplicate_sources(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """소스 중복 제거"""
    seen = set()
    unique_sources = []

    for src in sources:
        # 고유 키 생성
        if src.get("type") == "sql":
            key = f"sql:{src.get('sql', '')[:100]}"
        else:
            key = f"rag:{src.get('node_id', '')}"

        if key not in seen:
            seen.add(key)
            unique_sources.append(src)

    return unique_sources


def _sort_sources_by_priority(
    sources: List[Dict[str, Any]],
    merge_priority: Dict[str, int]
) -> List[Dict[str, Any]]:
    """Phase 89: merge_priority 기반 소스 정렬

    Args:
        sources: 소스 목록
        merge_priority: 소스별 우선순위 (숫자가 작을수록 높음)
            예: {"sql": 0, "vector": 1, "es": 2, "graph": 3}

    Returns:
        우선순위에 따라 정렬된 소스 목록
    """
    # 소스 타입 → merge_priority 키 매핑
    TYPE_TO_PRIORITY_KEY = {
        "sql": "sql",
        "rag": "vector",
        "vector": "vector",
        "es": "es",
        "elasticsearch": "es",
        "graph": "graph",
    }

    def get_priority(src: Dict[str, Any]) -> int:
        src_type = src.get("type", "unknown")
        priority_key = TYPE_TO_PRIORITY_KEY.get(src_type, "unknown")
        return merge_priority.get(priority_key, 99)

    sorted_sources = sorted(sources, key=get_priority)
    logger.debug(f"소스 우선순위 정렬: {[s.get('type') for s in sorted_sources]}")
    return sorted_sources


def _format_multi_sql_results(multi_sql_results: Dict[str, SQLQueryResult]) -> str:
    """다중 엔티티 SQL 결과를 분리 포맷팅 (Phase 19/92)

    Args:
        multi_sql_results: 엔티티별 SQL 결과 딕셔너리

    Returns:
        각 엔티티별로 분리된 결과 문자열
    """
    from sql.sql_prompts import ENTITY_LABELS

    # Phase 92: 협업 기관 추천용 라벨 확장
    COLLABORATION_LABELS = {
        "proposal": "과제 수행기관",
        "patent": "특허 보유기관",
    }

    parts = []

    for entity_type, result in multi_sql_results.items():
        # Phase 92: 협업 기관용 라벨 우선, 없으면 기본 ENTITY_LABELS 사용
        entity_label = COLLABORATION_LABELS.get(entity_type) or ENTITY_LABELS.get(entity_type, entity_type)

        if not result.success:
            parts.append(f"## {entity_label} 검색 결과")
            parts.append(f"검색 실패: {result.error}")
            continue

        if not result.rows:
            parts.append(f"## {entity_label} 검색 결과 (0건)")
            parts.append("조회된 데이터가 없습니다.")
            continue

        # 헤더
        parts.append(f"## {entity_label} 검색 결과 ({result.row_count}건)")

        # 테이블 형식으로 출력
        lines = []

        # 컬럼 헤더
        if result.columns:
            header = " | ".join(str(col) for col in result.columns)
            lines.append(header)
            lines.append("-" * len(header))

        # 데이터 행 (Phase 92: 200자로 확대하여 과제명/특허명 전체 보존)
        for row in result.rows:
            row_str = " | ".join(str(cell)[:200] if cell else "" for cell in row)
            lines.append(row_str)

        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def _format_sub_query_results(sub_query_results: List[Dict[str, Any]], sql_results_list: List = None) -> str:
    """복합 질의 하위 결과를 분리 포맷팅 (Phase 37)

    Args:
        sub_query_results: 하위 질의별 실행 결과 목록
        sql_results_list: 여러 SQL 결과 목록 (optional)

    Returns:
        각 하위 질의별로 분리된 결과 문자열
    """
    from workflow.nodes.sql_executor import format_sql_result_for_llm
    from workflow.nodes.rag_retriever import format_rag_results_for_llm

    # subtype 한글 라벨
    SUBTYPE_LABELS = {
        "aggregation": "통계/집계",
        "list": "목록 조회",
        "ranking": "순위",
        "concept": "개념 설명",
        "recommendation": "추천"
    }

    parts = []

    for i, result in enumerate(sub_query_results):
        subtype = result.get("query_subtype", result.get("query_type", "list"))
        subtype_label = SUBTYPE_LABELS.get(subtype, subtype)
        query = result.get("query", "")[:50]

        parts.append(f"## 하위 질의 {i+1}: {subtype_label}")
        parts.append(f"질의: {query}...")

        # SQL 결과
        sql_result = result.get("sql_result")
        if sql_result:
            if hasattr(sql_result, 'success') and sql_result.success:
                parts.append(f"\n### 조회 결과 ({sql_result.row_count}건)")
                parts.append(format_sql_result_for_llm(sql_result))
            elif hasattr(sql_result, 'error'):
                parts.append(f"\n검색 실패: {sql_result.error}")

        # RAG 결과
        rag_results = result.get("rag_results", [])
        if rag_results:
            parts.append(f"\n### 관련 정보 ({len(rag_results)}건)")
            parts.append(format_rag_results_for_llm(rag_results))

        # 둘 다 없는 경우
        if not sql_result and not rag_results:
            parts.append("\n조회된 결과가 없습니다.")

        parts.append("")  # 빈 줄로 구분

    # sql_results_list가 있으면 추가 (Phase 20 호환)
    if sql_results_list:
        for i, sql_result in enumerate(sql_results_list):
            if hasattr(sql_result, 'success') and sql_result.success and sql_result.rows:
                parts.append(f"## 추가 SQL 결과 {i+1} ({sql_result.row_count}건)")
                parts.append(format_sql_result_for_llm(sql_result))

    return "\n".join(parts)


def build_merged_context(state: AgentState) -> str:
    """병합된 컨텍스트 문자열 생성

    Phase 19: 다중 엔티티 결과를 각각 별도 섹션으로 표시
    Phase 37: 복합 질의(compound) 하위 결과 처리 추가
    """
    from workflow.nodes.sql_executor import format_sql_result_for_llm
    from workflow.nodes.rag_retriever import format_rag_results_for_llm

    query_type = state.get("query_type", "simple")
    parts = []

    # Phase 37: 복합 질의 하위 결과 (최우선 처리)
    sub_query_results = state.get("sub_query_results", [])
    sql_results_list = state.get("sql_results_list", [])
    if sub_query_results:
        parts.append(_format_sub_query_results(sub_query_results, sql_results_list))

    # Phase 19: 다중 엔티티 SQL 결과
    elif state.get("multi_sql_results"):
        multi_sql_results = state.get("multi_sql_results")
        parts.append(_format_multi_sql_results(multi_sql_results))

    else:
        # 기존 단일 SQL 결과
        sql_result = state.get("sql_result")
        if sql_result and sql_result.success and sql_result.rows:
            parts.append("## 데이터베이스 조회 결과")
            # Phase 70: 협업 기관 추천은 다중 도메인이므로 max_rows 확대
            query_subtype = state.get("query_subtype", "")
            query = state.get("query", "")
            is_collaboration = any(kw in query for kw in ["협업", "협력", "파트너", "공동연구"])
            if query_subtype == "recommendation" and is_collaboration:
                parts.append(format_sql_result_for_llm(sql_result, max_rows=25))
            else:
                parts.append(format_sql_result_for_llm(sql_result))
            if state.get("generated_sql"):
                parts.append(f"\n사용된 SQL: {state['generated_sql']}")

    # RAG 결과 (sub_query_results가 없을 때만)
    if not sub_query_results:
        rag_results = state.get("rag_results", [])
        if rag_results:
            parts.append("\n## 관련 정보")
            parts.append(format_rag_results_for_llm(rag_results))

    if not parts:
        return "관련 정보를 찾지 못했습니다."

    return "\n\n".join(parts)
