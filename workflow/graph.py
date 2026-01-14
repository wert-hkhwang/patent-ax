"""
LangGraph StateGraph 조립
- 노드 연결
- 조건부 엣지 설정
- 워크플로우 컴파일
- 병렬 실행 지원
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import time
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from langgraph.graph import StateGraph, END

from workflow.state import AgentState, create_initial_state
from workflow.nodes.analyzer import analyze_query as _analyze_query
from workflow.nodes.sql_executor import execute_sql as _execute_sql
from workflow.nodes.rag_retriever import retrieve_rag as _retrieve_rag
from workflow.nodes.merger import merge_results as _merge_results
from workflow.nodes.generator import generate_response as _generate_response
from workflow.nodes.vector_enhancer import enhance_with_vector as _enhance_with_vector
from workflow.nodes.es_scout import es_scout as _es_scout  # Phase 100
from workflow.edges import route_query, route_after_sql, route_after_rag, route_after_analyzer, route_after_es_scout

logger = logging.getLogger(__name__)


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
es_scout = _timed_node("es_scout", _es_scout)  # Phase 100
execute_sql = _timed_node("sql_node", _execute_sql)
retrieve_rag = _timed_node("rag_node", _retrieve_rag)
merge_results = _timed_node("merger", _merge_results)
generate_response = _timed_node("generator", _generate_response)
enhance_with_vector = _timed_node("vector_enhancer", _enhance_with_vector)

# 싱글톤 워크플로우
_workflow = None


def create_workflow():
    """LangGraph 워크플로우 생성

    Returns:
        컴파일된 StateGraph
    """
    # StateGraph 생성
    workflow = StateGraph(AgentState)

    # === 노드 추가 ===
    workflow.add_node("analyzer", analyze_query)
    workflow.add_node("es_scout", es_scout)  # Phase 100: 동의어 확장 + ES Scout
    workflow.add_node("vector_enhancer", enhance_with_vector)  # 벡터 강화 노드 추가
    workflow.add_node("sql_node", execute_sql)
    workflow.add_node("rag_node", retrieve_rag)
    workflow.add_node("merger", merge_results)
    workflow.add_node("generator", generate_response)

    # 병렬 실행 노드 (SQL + RAG 동시 실행)
    workflow.add_node("parallel", _parallel_execution)

    # Phase 90.2: complex_ranking용 병렬 실행 노드 (SQL + ES)
    workflow.add_node("parallel_ranking", _parallel_ranking_execution)

    # 복합 질의 하위 질의 실행 노드 (Phase 20)
    workflow.add_node("sub_queries", _execute_sub_queries)

    # === 엣지 설정 ===

    # 시작점: analyzer
    workflow.set_entry_point("analyzer")

    # Phase 100: analyzer -> es_scout (동의어 확장 + ES Scout)
    workflow.add_edge("analyzer", "es_scout")

    # Phase 100: es_scout -> 조건부 라우팅
    # simple 쿼리는 generator 직행, 통계 분석은 sql_node, 나머지는 vector_enhancer
    workflow.add_conditional_edges(
        "es_scout",
        route_after_es_scout,
        {
            "vector_enhancer": "vector_enhancer",
            "sql_node": "sql_node",
            "rag_node": "rag_node",
            "parallel": "parallel",
            "sub_queries": "sub_queries",
            "generator": "generator"
        }
    )

    # vector_enhancer -> 조건부 라우팅
    workflow.add_conditional_edges(
        "vector_enhancer",
        route_query,
        {
            "sql_node": "sql_node",
            "rag_node": "rag_node",
            "parallel": "parallel",
            "parallel_ranking": "parallel_ranking",  # Phase 90.2: complex_ranking 라우팅
            "sub_queries": "sub_queries",  # 복합 질의 라우팅 (Phase 20)
            "generator": "generator"
        }
    )

    # sql_node -> 조건부 라우팅
    workflow.add_conditional_edges(
        "sql_node",
        route_after_sql,
        {
            "merger": "merger",
            "generator": "generator"
        }
    )

    # rag_node -> 조건부 라우팅
    workflow.add_conditional_edges(
        "rag_node",
        route_after_rag,
        {
            "merger": "merger",
            "generator": "generator"
        }
    )

    # parallel -> merger
    workflow.add_edge("parallel", "merger")

    # Phase 90.2: parallel_ranking -> merger (complex_ranking RRF 통합)
    workflow.add_edge("parallel_ranking", "merger")

    # sub_queries -> merger (복합 질의 결과 병합)
    workflow.add_edge("sub_queries", "merger")

    # merger -> generator
    workflow.add_edge("merger", "generator")

    # generator -> END
    workflow.add_edge("generator", END)

    # 컴파일
    compiled = workflow.compile()

    logger.info("LangGraph 워크플로우 컴파일 완료")

    return compiled


def _parallel_execution(state: AgentState) -> AgentState:
    """SQL과 RAG를 병렬 실행 (ThreadPoolExecutor 사용)

    Args:
        state: 현재 에이전트 상태

    Returns:
        SQL과 RAG 결과가 병합된 상태
    """
    sql_state = None
    rag_state = None
    errors = []

    # ThreadPoolExecutor로 병렬 실행
    with ThreadPoolExecutor(max_workers=2) as executor:
        sql_future = executor.submit(execute_sql, state)
        rag_future = executor.submit(retrieve_rag, state)

        # 결과 수집
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
        "multi_sql_results": sql_state.get("multi_sql_results"),  # Phase 19
        "generated_sql": sql_state.get("generated_sql"),
        "rag_results": rag_state.get("rag_results", []),
        "search_strategy": rag_state.get("search_strategy", ""),
        "sources": sql_state.get("sources", []) + rag_state.get("sources", [])
    }

    # 에러 병합
    if errors:
        existing_error = state.get("error", "")
        merged_state["error"] = "; ".join([existing_error] + errors) if existing_error else "; ".join(errors)

    return merged_state


def _parallel_ranking_execution(state: AgentState) -> AgentState:
    """Phase 90.2: complex_ranking용 SQL + ES 병렬 실행

    복잡한 ranking 쿼리 (통계/계산 필요)를 SQL과 ES로 병렬 처리 후 RRF로 통합.

    Args:
        state: 현재 에이전트 상태

    Returns:
        SQL + ES ranking 결과가 병합된 상태
    """
    logger.info("Phase 90.2: complex_ranking 병렬 실행 시작 (SQL + ES)")

    sql_result = None
    es_ranking_results = []
    errors = []

    # ThreadPoolExecutor로 병렬 실행
    with ThreadPoolExecutor(max_workers=2) as executor:
        # SQL ranking 실행
        sql_future = executor.submit(execute_sql, state)

        # ES ranking 실행 (RAG retriever에서 es_ranking_results 반환)
        es_future = executor.submit(retrieve_rag, state)

        # SQL 결과 수집
        try:
            sql_state = sql_future.result(timeout=60)
            sql_result = sql_state.get("sql_result")
            logger.info(f"Phase 90.2: SQL ranking 완료 - {sql_result.row_count if sql_result and sql_result.success else 0}건")
        except Exception as e:
            logger.error(f"Phase 90.2: SQL ranking 실패: {e}")
            errors.append(f"SQL: {str(e)}")

        # ES 결과 수집
        try:
            rag_state = es_future.result(timeout=30)
            es_ranking_results = rag_state.get("es_ranking_results", [])
            logger.info(f"Phase 90.2: ES ranking 완료 - {len(es_ranking_results)}건")
        except Exception as e:
            logger.error(f"Phase 90.2: ES ranking 실패: {e}")
            errors.append(f"ES: {str(e)}")

    logger.info(f"Phase 90.2: complex_ranking 병렬 실행 완료")

    # 결과를 merger로 전달하기 위해 상태에 저장
    merged_state = {
        **state,
        "sql_result": sql_result,
        "es_ranking_results": es_ranking_results,
        "ranking_sources": [],
    }

    # 성공한 소스 기록
    if sql_result and sql_result.success:
        merged_state["ranking_sources"].append("sql")
    if es_ranking_results:
        merged_state["ranking_sources"].append("es")

    # 에러 병합
    if errors:
        existing_error = state.get("error", "")
        merged_state["error"] = "; ".join([existing_error] + errors) if existing_error else "; ".join(errors)

    return merged_state


def _execute_sub_queries(state: AgentState) -> AgentState:
    """복합 질의의 하위 질의들을 병렬/순차 실행 (Phase 20/37)

    Phase 37: analyzer의 sub_queries 형식 지원
    - intent → query로 변환
    - subtype → query_type으로 변환 (aggregation/ranking→sql, list→sql, concept→rag)
    - 부모 state의 keywords/entity_types 상속

    Args:
        state: 현재 에이전트 상태 (sub_queries 포함)

    Returns:
        하위 질의 결과가 병합된 상태
    """
    sub_queries = state.get("sub_queries", [])
    merge_strategy = state.get("merge_strategy", "parallel")
    parent_query = state.get("query", "")
    parent_keywords = state.get("keywords", [])
    parent_entity_types = state.get("entity_types", [])
    expanded_keywords = state.get("expanded_keywords", [])

    if not sub_queries:
        logger.warning("하위 질의가 없음, 일반 처리로 폴백")
        return state

    logger.info(f"복합 질의 실행 시작: {len(sub_queries)}개 하위 질의, 전략={merge_strategy}")

    sub_query_results = []
    all_rag_results = []
    all_sql_results = []
    all_sources = []
    errors = []

    def _subtype_to_query_type(subtype: str) -> str:
        """subtype을 query_type으로 변환 (Phase 37)"""
        # SQL 타입: 목록, 통계, 랭킹 → 데이터베이스 조회 필요
        sql_subtypes = ["list", "aggregation", "ranking", "recommendation"]
        # RAG 타입: 개념 설명, 맥락 분석 → 벡터 검색 필요
        rag_subtypes = ["concept"]

        if subtype in sql_subtypes:
            return "sql"
        elif subtype in rag_subtypes:
            return "rag"
        else:
            # 기본값: sql (데이터 조회가 더 일반적)
            return "sql"

    def execute_single_sub_query(sub_query: Dict[str, Any], index: int) -> Dict[str, Any]:
        """단일 하위 질의 실행"""
        # Phase 37: analyzer 형식 지원 (intent/subtype)
        # 기존 형식(query/query_type)도 하위 호환성 유지
        sq_query = sub_query.get("query") or sub_query.get("intent", "")
        sq_subtype = sub_query.get("subtype", sub_query.get("query_type", "list"))
        sq_type = _subtype_to_query_type(sq_subtype)
        sq_keywords = sub_query.get("keywords", [])
        sq_entity_types = sub_query.get("entity_types", parent_entity_types)

        # 하위 쿼리가 없으면 부모 쿼리에서 subtype에 맞는 쿼리 생성
        if not sq_query:
            sq_query = parent_query

        # 키워드 병합: 하위 쿼리 키워드 + 부모 키워드
        merged_keywords = list(sq_keywords) if sq_keywords else list(parent_keywords)
        for kw in parent_keywords:
            if kw not in merged_keywords:
                merged_keywords.append(kw)

        logger.info(f"하위 질의 #{index} 실행: type={sq_type}, subtype={sq_subtype}, query={sq_query[:50]}...")

        # 하위 질의를 위한 임시 상태 생성
        # Phase 104.1: sub_query의 entity_types에 맞게 es_doc_ids 비우기
        # 부모의 es_doc_ids는 다른 entity_type일 수 있으므로 SQL Executor가 직접 검색하도록 함
        sub_state = {
            **state,
            "query": sq_query,
            "query_type": sq_type,
            "query_subtype": sq_subtype,  # Phase 37: subtype 전달
            "entity_types": sq_entity_types,
            "keywords": merged_keywords,
            "expanded_keywords": expanded_keywords,  # 부모의 확장 키워드 상속
            # 복합 질의 플래그 제거 (무한 루프 방지)
            "is_compound": False,
            "sub_queries": [],
            # Phase 104.1: es_doc_ids 비우기 - SQL Executor가 entity_types로 직접 검색
            "es_doc_ids": {},
            "domain_hits": {},
        }

        result = {
            "index": index,
            "query": sq_query,
            "query_type": sq_type,
            "query_subtype": sq_subtype,  # Phase 37: subtype 추가
            "entity_types": sq_entity_types,
            "keywords": merged_keywords,  # Phase 37: 키워드 추가
            "success": False,
            "rag_results": [],
            "sql_result": None,
            "sources": [],
            "error": None
        }

        try:
            if sq_type == "sql":
                executed_state = execute_sql(sub_state)
                sql_result = executed_state.get("sql_result")
                multi_sql_results = executed_state.get("multi_sql_results")

                # Phase 104: multi_sql_results에서 해당 entity_type 결과 추출
                if not sql_result and multi_sql_results and sq_entity_types:
                    entity_type = sq_entity_types[0]
                    sql_result = multi_sql_results.get(entity_type)
                    if sql_result:
                        print(f"[SUB_QUERY #{index}] multi_sql_results에서 추출: entity={entity_type}")

                result["sql_result"] = sql_result
                result["generated_sql"] = executed_state.get("generated_sql")
                result["sources"] = executed_state.get("sources", [])
                result["success"] = sql_result is not None and (hasattr(sql_result, 'success') and sql_result.success)
                # Phase 104 디버그
                if sql_result and hasattr(sql_result, 'row_count'):
                    print(f"[SUB_QUERY #{index}] SQL 성공: entity={sq_entity_types}, rows={sql_result.row_count}")
                else:
                    print(f"[SUB_QUERY #{index}] SQL 결과 없음: entity={sq_entity_types}, multi_sql_results={list(multi_sql_results.keys()) if multi_sql_results else 'None'}")
            else:  # rag
                executed_state = retrieve_rag(sub_state)
                result["rag_results"] = executed_state.get("rag_results", [])
                result["sources"] = executed_state.get("sources", [])
                result["success"] = len(result["rag_results"]) > 0

        except Exception as e:
            logger.error(f"하위 질의 #{index} 실행 실패: {e}")
            result["error"] = str(e)

        return result

    if merge_strategy == "parallel":
        # 병렬 실행 (의존성 없는 하위 질의들)
        independent_queries = [sq for sq in sub_queries if sq.get("depends_on") is None]
        dependent_queries = [sq for sq in sub_queries if sq.get("depends_on") is not None]

        # 독립 하위 질의 병렬 실행
        with ThreadPoolExecutor(max_workers=min(3, len(independent_queries) or 1)) as executor:
            futures = {
                executor.submit(execute_single_sub_query, sq, i): i
                for i, sq in enumerate(independent_queries)
            }

            for future in as_completed(futures):
                try:
                    result = future.result(timeout=60)
                    sub_query_results.append(result)

                    if result.get("rag_results"):
                        all_rag_results.extend(result["rag_results"])
                    if result.get("sql_result"):
                        all_sql_results.append(result["sql_result"])
                    if result.get("sources"):
                        all_sources.extend(result["sources"])
                    if result.get("error"):
                        errors.append(f"#{result['index']}: {result['error']}")

                except Exception as e:
                    errors.append(f"병렬 실행 오류: {str(e)}")

        # 의존성 있는 하위 질의 순차 실행
        for i, sq in enumerate(dependent_queries, start=len(independent_queries)):
            depends_on = sq.get("depends_on")
            if depends_on is not None and depends_on < len(sub_query_results):
                # 이전 결과를 컨텍스트로 추가
                sq["context"] = sub_query_results[depends_on]

            result = execute_single_sub_query(sq, i)
            sub_query_results.append(result)

            if result.get("rag_results"):
                all_rag_results.extend(result["rag_results"])
            if result.get("sql_result"):
                all_sql_results.append(result["sql_result"])
            if result.get("sources"):
                all_sources.extend(result["sources"])
            if result.get("error"):
                errors.append(f"#{i}: {result['error']}")

    else:  # sequential
        # 순차 실행
        for i, sq in enumerate(sub_queries):
            result = execute_single_sub_query(sq, i)
            sub_query_results.append(result)

            if result.get("rag_results"):
                all_rag_results.extend(result["rag_results"])
            if result.get("sql_result"):
                all_sql_results.append(result["sql_result"])
            if result.get("sources"):
                all_sources.extend(result["sources"])
            if result.get("error"):
                errors.append(f"#{i}: {result['error']}")

    # Phase 104.7: sub_query_results를 원래 index 순으로 정렬
    # as_completed()는 완료 순서대로 반환하므로 index 기준 정렬 필요
    sub_query_results.sort(key=lambda x: x.get("index", 0))

    logger.info(f"복합 질의 실행 완료: {len(sub_query_results)}개 결과")
    print(f"[SUB_QUERIES] 실행 완료: sql_results={len(all_sql_results)}개, rag_results={len(all_rag_results)}개, sources={len(all_sources)}개")

    # 결과 병합 (중복 제거)
    unique_sources = []
    seen_sources = set()
    for source in all_sources:
        source_key = str(source.get("node_id") or source.get("id", ""))
        if source_key and source_key not in seen_sources:
            seen_sources.add(source_key)
            unique_sources.append(source)

    # 상태 업데이트
    merged_state = {
        **state,
        "sub_query_results": sub_query_results,
        "rag_results": all_rag_results,
        "sql_result": all_sql_results[0] if len(all_sql_results) == 1 else None,
        "sources": unique_sources
    }

    # 여러 SQL 결과가 있으면 병합 정보 추가
    if len(all_sql_results) > 1:
        merged_state["sql_results_list"] = all_sql_results
        # Phase 104: generator 호환 - multi_sql_results 형식으로 변환
        multi_sql_results = {}
        for i, sql_res in enumerate(all_sql_results):
            # sub_query_results에서 entity_types 가져오기
            if i < len(sub_query_results):
                entity_type = sub_query_results[i].get("entity_types", ["unknown"])[0]
                multi_sql_results[entity_type] = sql_res
        merged_state["multi_sql_results"] = multi_sql_results
        logger.info(f"Phase 104: multi_sql_results 생성 - {list(multi_sql_results.keys())}")

    if errors:
        merged_state["error"] = "; ".join(errors)

    return merged_state


def get_workflow():
    """워크플로우 싱글톤 반환"""
    global _workflow
    if _workflow is None:
        _workflow = create_workflow()
    return _workflow


def run_workflow(
    query: str,
    session_id: str = "default",
    level: str = "일반인",
    entity_types: List[str] = None
) -> Dict[str, Any]:
    """워크플로우 실행

    Args:
        query: 사용자 질문
        session_id: 세션 ID
        level: 사용자 리터러시 수준 (초등/일반인/전문가)
        entity_types: 검색할 엔티티 타입 (None이면 자동 결정, 예: ["patent"])

    Returns:
        최종 상태 딕셔너리
    """
    start_time = time.time()

    # 초기 상태 생성
    initial_state = create_initial_state(
        query=query,
        session_id=session_id,
        level=level,
        entity_types=entity_types
    )

    # 워크플로우 실행
    workflow = get_workflow()
    final_state = workflow.invoke(initial_state)

    # 처리 시간 추가
    elapsed_ms = (time.time() - start_time) * 1000
    final_state["elapsed_ms"] = round(elapsed_ms, 2)

    logger.info(f"워크플로우 완료: {elapsed_ms:.2f}ms, type={final_state.get('query_type')}")

    return final_state


class WorkflowAgent:
    """워크플로우 에이전트 래퍼 클래스"""

    def __init__(self):
        self.workflow = get_workflow()
        self.conversation_history = []

    def chat(
        self,
        query: str,
        session_id: str = "default"
    ) -> Dict[str, Any]:
        """채팅 실행

        Args:
            query: 사용자 질문
            session_id: 세션 ID

        Returns:
            응답 딕셔너리
        """
        result = run_workflow(query=query, session_id=session_id)

        # 대화 기록 업데이트
        if result.get("conversation_history"):
            self.conversation_history.extend(result["conversation_history"])

        return {
            "query": query,
            "query_type": result.get("query_type", "unknown"),
            "response": result.get("response", ""),
            "sources": result.get("sources", []),
            "generated_sql": result.get("generated_sql"),
            "elapsed_ms": result.get("elapsed_ms", 0),
            "error": result.get("error")
        }

    def clear_history(self):
        """대화 기록 초기화"""
        self.conversation_history = []

    def get_history(self):
        """대화 기록 반환"""
        return self.conversation_history


# 싱글톤 에이전트
_agent: Optional[WorkflowAgent] = None


def get_workflow_agent() -> WorkflowAgent:
    """워크플로우 에이전트 싱글톤"""
    global _agent
    if _agent is None:
        _agent = WorkflowAgent()
    return _agent


async def astream_workflow(
    query: str,
    session_id: str = "default"
):
    """워크플로우 비동기 스트리밍 실행

    LangGraph의 astream을 사용하여 노드별 업데이트를 스트리밍합니다.

    Args:
        query: 사용자 질문
        session_id: 세션 ID

    Yields:
        Dict: 노드별 상태 업데이트
            - key: 노드 이름 (analyzer, sql_node, rag_node, generator 등)
            - value: 해당 노드의 출력 상태

    Example:
        async for event in astream_workflow("AI 특허 알려줘"):
            for node_name, output in event.items():
                print(f"{node_name}: {output}")
    """
    # 초기 상태 생성
    initial_state = create_initial_state(query=query, session_id=session_id)

    # 워크플로우 가져오기
    workflow = get_workflow()

    # 스트리밍 실행 (updates 모드: 노드별 상태 변경만 전송)
    async for event in workflow.astream(initial_state, stream_mode="updates"):
        yield event


async def arun_workflow(
    query: str,
    session_id: str = "default"
) -> Dict[str, Any]:
    """워크플로우 비동기 실행 (스트리밍 없음)

    Args:
        query: 사용자 질문
        session_id: 세션 ID

    Returns:
        최종 상태 딕셔너리
    """
    import time
    start_time = time.time()

    # 초기 상태 생성
    initial_state = create_initial_state(query=query, session_id=session_id)

    # 워크플로우 실행
    workflow = get_workflow()
    final_state = await workflow.ainvoke(initial_state)

    # 처리 시간 추가
    elapsed_ms = (time.time() - start_time) * 1000
    final_state["elapsed_ms"] = round(elapsed_ms, 2)

    logger.info(f"비동기 워크플로우 완료: {elapsed_ms:.2f}ms, type={final_state.get('query_type')}")

    return final_state


if __name__ == "__main__":
    # 테스트
    print("LangGraph 워크플로우 테스트")
    print("=" * 50)

    # 워크플로우 생성
    workflow = create_workflow()
    print("워크플로우 생성 완료")

    # 테스트 쿼리
    test_queries = [
        ("안녕하세요", "simple"),
        ("특허 10개 알려줘", "sql"),
        ("인공지능 연구 동향", "rag"),
        ("AI 특허와 관련 연구과제", "hybrid"),
    ]

    for query, expected_type in test_queries:
        print(f"\n질문: {query}")
        print(f"예상 유형: {expected_type}")

        result = run_workflow(query=query)

        print(f"실제 유형: {result.get('query_type')}")
        print(f"응답: {result.get('response', '')[:100]}...")
        print(f"처리 시간: {result.get('elapsed_ms', 0):.2f}ms")
