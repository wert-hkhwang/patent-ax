"""
LangGraph 스트리밍 API 유틸리티
- assistant-stream 연동
- SSE 응답 생성
- AI SDK 호환 데이터 스트림
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import logging
from datetime import datetime, date
from decimal import Decimal
from typing import AsyncGenerator, Optional, Dict, Any, List, Literal
from pydantic import BaseModel


class CustomJSONEncoder(json.JSONEncoder):
    """datetime, date, Decimal 등을 처리하는 커스텀 JSON 인코더"""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def safe_json_dumps(obj, **kwargs):
    """datetime 등을 안전하게 직렬화하는 JSON dumps"""
    return json.dumps(obj, cls=CustomJSONEncoder, **kwargs)

from sse_starlette.sse import EventSourceResponse
from assistant_stream import create_run, RunController
from assistant_stream.serialization import DataStreamResponse

from workflow.graph import get_workflow, create_workflow
from workflow.state import create_initial_state
from graph.graph_builder import NODE_TYPES  # Phase 102: 노드 타입 색상
from graph.cugraph_client import CuGraphClient  # Phase 104.6: cuGraph 그래프 생성

logger = logging.getLogger(__name__)


def _infer_node_type(node_id: str) -> str:
    """노드 ID prefix에서 노드 유형 추론"""
    if node_id.startswith("applicant_"):
        return "organization"
    elif node_id.startswith("org_"):
        return "organization"
    elif node_id.startswith("patent_"):
        return "patent"
    elif node_id.startswith("project_"):
        return "project"
    elif node_id.startswith("ipc_"):
        return "ipc"
    elif node_id.startswith("keyword_"):
        return "keyword"
    return "unknown"


def build_graph_from_ranking_results(
    multi_sql_results: Dict,
    keywords: List[str],
    expanded_keywords: List[str] = None,
    query_subtype: str = "ranking",
    graph_id: str = "713365bb"
) -> Optional[Dict]:
    """Phase 104.6: 기관 역량 검색 결과에서 그래프 데이터 생성

    계층 구조: 키워드(중심) ← 확장키워드들
                  ↓
              도메인(특허/과제)
                  ↓
              기관들

    Args:
        multi_sql_results: 엔티티별 SQL 결과 (patent, project 등)
        keywords: 검색 키워드 목록
        expanded_keywords: 확장 키워드 목록
        query_subtype: 쿼리 서브타입
        graph_id: cuGraph 그래프 ID

    Returns:
        그래프 데이터 (nodes, edges) 또는 None
    """
    if not multi_sql_results or query_subtype != "ranking":
        return None

    all_nodes = []
    all_edges = []
    seen_nodes = set()

    # 1. 키워드 노드 생성 (최상위 중심 노드)
    keyword_text = keywords[0] if keywords else "검색어"
    keyword_node_id = f"keyword_{keyword_text}"
    keyword_color = NODE_TYPES.get("keyword", {}).get("color", "#FF9800")
    keyword_node = {
        "id": keyword_node_id,
        "name": keyword_text,
        "type": "keyword",
        "score": 1.0,
        "color": keyword_color
    }
    all_nodes.append(keyword_node)
    seen_nodes.add(keyword_node_id)

    # 1-1. 확장 키워드 노드 생성 (중심 키워드에 연결)
    if expanded_keywords:
        # 중복 제거하고 원본 키워드 제외
        unique_expanded = [kw for kw in expanded_keywords if kw and kw != keyword_text and kw not in keywords][:8]
        for idx, exp_kw in enumerate(unique_expanded):
            exp_node_id = f"expanded_{exp_kw}"
            if exp_node_id in seen_nodes:
                continue
            seen_nodes.add(exp_node_id)

            exp_node = {
                "id": exp_node_id,
                "name": exp_kw,
                "type": "expanded_keyword",
                "score": 0.7 - (idx * 0.05),
                "color": "#FFC107"  # 연한 노란색 (확장 키워드)
            }
            all_nodes.append(exp_node)

            # 확장 키워드 → 중심 키워드 엣지
            all_edges.append({
                "from_id": exp_node_id,
                "to_id": keyword_node_id,
                "relation": "확장"
            })

    # 도메인별 색상 및 라벨 매핑
    DOMAIN_CONFIG = {
        "patent": {
            "label": "특허",
            "color": "#2196F3",  # 파란색
            "node_prefix": "applicant_",
            "relation_to_keyword": "특허출원",
            "relation_to_org": "출원기관"
        },
        "project": {
            "label": "과제",
            "color": "#9C27B0",  # 보라색
            "node_prefix": "org_",
            "relation_to_keyword": "연구과제",
            "relation_to_org": "수행기관"
        }
    }

    # 2. 도메인별 처리
    for entity_type, sql_result in multi_sql_results.items():
        config = DOMAIN_CONFIG.get(entity_type)
        if not config:
            continue

        rows = []
        if isinstance(sql_result, dict):
            rows = sql_result.get("rows", [])
        elif hasattr(sql_result, "rows"):
            rows = sql_result.rows or []

        if not rows:
            continue

        # 2-1. 도메인 노드 생성 (특허/과제)
        domain_node_id = f"domain_{entity_type}"
        total_count = sum(row[1] for row in rows if len(row) > 1 and row[1])
        domain_node = {
            "id": domain_node_id,
            "name": f"{config['label']} ({len(rows)}개 기관)",
            "type": "domain",
            "score": 0.9,
            "color": config["color"],
            "properties": {
                "entity_type": entity_type,
                "org_count": len(rows),
                "total_count": total_count
            }
        }
        all_nodes.append(domain_node)
        seen_nodes.add(domain_node_id)

        # 키워드 → 도메인 엣지
        all_edges.append({
            "from_id": keyword_node_id,
            "to_id": domain_node_id,
            "relation": config["relation_to_keyword"]
        })

        # 2-2. 기관 노드 생성 (상위 10개)
        for idx, row in enumerate(rows[:10]):
            if not row or len(row) < 2:
                continue

            org_name = str(row[0]) if row[0] else ""
            count = row[1] if len(row) > 1 else 0

            if not org_name:
                continue

            # 같은 기관이 특허/과제 양쪽에 있을 수 있으므로 도메인별 ID 사용
            node_id = f"{config['node_prefix']}{org_name}"

            # 중복 노드 방지 (같은 기관이 양쪽 도메인에 있는 경우)
            if node_id in seen_nodes:
                # 이미 있는 노드면 엣지만 추가
                all_edges.append({
                    "from_id": domain_node_id,
                    "to_id": node_id,
                    "relation": config["relation_to_org"]
                })
                continue

            seen_nodes.add(node_id)

            # 순위 기반 점수 (상위일수록 높음)
            rank_score = 0.8 - (idx * 0.06)

            org_color = NODE_TYPES.get("organization", {}).get("color", "#4CAF50")
            org_node = {
                "id": node_id,
                "name": org_name[:25] if len(org_name) > 25 else org_name,  # 이름 길이 제한
                "type": "organization",
                "score": round(rank_score, 2),
                "color": org_color,
                "properties": {
                    "entity_type": entity_type,
                    "count": count,
                    "rank": idx + 1
                }
            }
            all_nodes.append(org_node)

            # 도메인 → 기관 엣지
            all_edges.append({
                "from_id": domain_node_id,
                "to_id": node_id,
                "relation": config["relation_to_org"]
            })

    return {
        "nodes": all_nodes,
        "edges": all_edges
    }


class StreamChatRequest(BaseModel):
    """스트리밍 채팅 요청 모델"""
    query: str
    session_id: str = "default"
    system_prompt: Optional[str] = None
    level: Literal["L1", "L2", "L3", "L4", "L5", "L6", "초등", "일반인", "전문가"] = "L2"  # Phase 103 v1.3: V3 리터러시 레벨 지원
    entity_types: Optional[List[str]] = None  # Phase 103: 엔티티 타입 필터


class StreamChatEvent(BaseModel):
    """스트리밍 이벤트 모델"""
    event: str  # "text", "tool_call", "done", "error"
    data: Dict[str, Any]


async def stream_workflow_sse(request: StreamChatRequest) -> EventSourceResponse:
    """
    워크플로우 SSE 스트리밍 (순수 SSE 방식)

    단계별 진행 상황과 최종 응답을 스트리밍합니다.

    Args:
        request: 스트리밍 채팅 요청

    Returns:
        EventSourceResponse: SSE 스트림
    """
    async def event_generator() -> AsyncGenerator[dict, None]:
        try:
            # 워크플로우 가져오기
            workflow = get_workflow()
            initial_state = create_initial_state(
                query=request.query,
                session_id=request.session_id,
                level=request.level  # Phase 103 v1.3: V3 리터러시 레벨
            )
            # Patent-AX: entity_types는 state.py에서 ["patent"]로 고정

            # 분석 단계 시작 알림
            yield {
                "event": "status",
                "data": safe_json_dumps({
                    "status": "analyzing",
                    "message": "쿼리를 분석하고 있습니다..."
                }, ensure_ascii=False)
            }

            # 워크플로우 스트리밍 실행
            final_state = None
            stage_timing = {}
            import time
            stage_start = time.time()

            async for event in workflow.astream(initial_state, stream_mode="updates"):
                # 노드별 상태 업데이트 전송
                for node_name, node_output in event.items():
                    # 단계 타이밍 기록
                    current_time = time.time()
                    stage_timing[f"{node_name}_ms"] = round((current_time - stage_start) * 1000, 2)
                    stage_start = current_time

                    # 분석 완료 (상세 정보 포함)
                    if node_name == "analyzer":
                        query_type = node_output.get("query_type", "unknown")
                        query_subtype = node_output.get("query_subtype", "list")  # Phase 99.5
                        is_compound = node_output.get("is_compound", False)
                        entity_types = node_output.get("entity_types", [])
                        keywords = node_output.get("keywords", [])
                        query_intent = node_output.get("query_intent", "")
                        related_tables = node_output.get("related_tables", [])
                        sub_queries = node_output.get("sub_queries", [])
                        merge_strategy = node_output.get("merge_strategy", "")
                        complexity_reason = node_output.get("complexity_reason", "")

                        # 기본 분석 완료 이벤트
                        yield {
                            "event": "status",
                            "data": safe_json_dumps({
                                "status": "analyzed",
                                "query_type": query_type,
                                "is_compound": is_compound,
                                "message": f"쿼리 유형: {query_type}"
                            }, ensure_ascii=False)
                        }

                        # 상세 분석 결과 이벤트 (시각화용)
                        yield {
                            "event": "analysis_complete",
                            "data": safe_json_dumps({
                                "query_type": query_type,
                                "query_subtype": query_subtype,  # Phase 99.5
                                "query_intent": query_intent,
                                "entity_types": entity_types,
                                "keywords": keywords,
                                "related_tables": related_tables,
                                "is_compound": is_compound
                            }, ensure_ascii=False)
                        }

                        # 복합 질의 분해 정보 (Phase 20)
                        if is_compound and sub_queries:
                            yield {
                                "event": "subquery_info",
                                "data": safe_json_dumps({
                                    "sub_queries": [
                                        {
                                            "index": i,
                                            # Phase 92: intent 필드 우선 사용 (query 폴백)
                                            "query": sq.get("intent") or sq.get("query", f"하위 질의 {i+1}"),
                                            "type": sq.get("subtype") or sq.get("query_type", "rag"),
                                            "entity_types": sq.get("entity_types", []),
                                            "keywords": sq.get("keywords", []),
                                            "status": "pending"
                                        }
                                        for i, sq in enumerate(sub_queries)
                                    ],
                                    "merge_strategy": merge_strategy,
                                    "complexity_reason": complexity_reason
                                }, ensure_ascii=False)
                            }

                    # Vector Enhancement 완료 (Phase 4)
                    elif node_name == "vector_enhancer":
                        vector_doc_ids = node_output.get("vector_doc_ids", [])
                        expanded_keywords = node_output.get("expanded_keywords", [])
                        vector_result_count = node_output.get("vector_result_count", 0)

                        yield {
                            "event": "status",
                            "data": safe_json_dumps({
                                "status": "vector_enhanced",
                                "message": f"벡터 검색 완료: {vector_result_count}개 관련 문서"
                            }, ensure_ascii=False)
                        }

                        yield {
                            "event": "vector_complete",
                            "data": safe_json_dumps({
                                "doc_count": len(vector_doc_ids),
                                "expanded_keywords": expanded_keywords[:10],
                                "sample_doc_ids": vector_doc_ids[:5]
                            }, ensure_ascii=False)
                        }

                    # SQL 실행 완료 (상세 결과 포함)
                    # Phase 10: parallel 노드에서도 SQL 결과 처리 (hybrid 쿼리)
                    elif node_name in ["sql_node", "parallel"]:
                        generated_sql = node_output.get("generated_sql")
                        sql_result = node_output.get("sql_result")
                        multi_sql_results = node_output.get("multi_sql_results")  # Phase 19

                        if generated_sql:
                            yield {
                                "event": "status",
                                "data": safe_json_dumps({
                                    "status": "executing_sql",
                                    "sql": generated_sql,
                                    "message": "SQL을 실행하고 있습니다..."
                                }, ensure_ascii=False)
                            }

                            # 복합 질의 하위 쿼리 진행 상태 업데이트
                            if is_compound and sub_queries:
                                for i, sq in enumerate(sub_queries):
                                    if sq.get("query_type") == "sql":
                                        yield {
                                            "event": "subquery_progress",
                                            "data": safe_json_dumps({
                                                "index": i,
                                                "status": "executing"
                                            }, ensure_ascii=False)
                                        }

                        # Phase 19: 다중 엔티티 SQL 결과 전송
                        if multi_sql_results:
                            multi_results_serialized = {}
                            for entity_type, result in multi_sql_results.items():
                                if isinstance(result, dict):
                                    multi_results_serialized[entity_type] = {
                                        "generated_sql": result.get("generated_sql", ""),
                                        "columns": result.get("columns", [])[:10],
                                        "row_count": result.get("row_count", 0),
                                        "rows": result.get("rows", [])[:10],
                                        "execution_time_ms": result.get("execution_time_ms", 0)
                                    }
                                else:
                                    multi_results_serialized[entity_type] = {
                                        "generated_sql": getattr(result, "generated_sql", "") if hasattr(result, "generated_sql") else "",
                                        "columns": getattr(result, "columns", [])[:10],
                                        "row_count": getattr(result, "row_count", 0),
                                        "rows": getattr(result, "rows", [])[:10],
                                        "execution_time_ms": getattr(result, "execution_time_ms", 0)
                                    }

                            yield {
                                "event": "multi_sql_complete",
                                "data": safe_json_dumps({
                                    "multi_sql_results": multi_results_serialized
                                }, ensure_ascii=False)
                            }

                            # 복합 질의 SQL 하위 쿼리 완료 상태 업데이트
                            if is_compound and sub_queries:
                                for i, sq in enumerate(sub_queries):
                                    if sq.get("query_type") == "sql":
                                        yield {
                                            "event": "subquery_progress",
                                            "data": safe_json_dumps({
                                                "index": i,
                                                "status": "completed"
                                            }, ensure_ascii=False)
                                        }

                        # 단일 SQL 실행 완료 상세 이벤트 (시각화용)
                        elif sql_result:
                            columns = sql_result.get("columns", []) if isinstance(sql_result, dict) else getattr(sql_result, "columns", [])
                            rows = sql_result.get("rows", []) if isinstance(sql_result, dict) else getattr(sql_result, "rows", [])
                            row_count = sql_result.get("row_count", 0) if isinstance(sql_result, dict) else getattr(sql_result, "row_count", 0)
                            execution_time = sql_result.get("execution_time_ms", 0) if isinstance(sql_result, dict) else getattr(sql_result, "execution_time_ms", 0)

                            yield {
                                "event": "sql_complete",
                                "data": safe_json_dumps({
                                    "generated_sql": generated_sql or "",
                                    "columns": columns[:10] if columns else [],  # 최대 10개 컬럼
                                    "row_count": row_count,
                                    "rows": rows[:5] if rows else [],  # 미리보기 5행
                                    "execution_time_ms": execution_time
                                }, ensure_ascii=False)
                            }

                            # 복합 질의 SQL 하위 쿼리 완료 상태 업데이트
                            if is_compound and sub_queries:
                                for i, sq in enumerate(sub_queries):
                                    if sq.get("query_type") == "sql":
                                        yield {
                                            "event": "subquery_progress",
                                            "data": safe_json_dumps({
                                                "index": i,
                                                "status": "completed"
                                            }, ensure_ascii=False)
                                        }

                        # Phase 50: parallel 노드에서 SQL 결과 전송 (hybrid 쿼리)
                        # hybrid 쿼리 시 sql_result가 있으면 sql_complete 이벤트 전송
                        if node_name == "parallel" and not sql_result and not multi_sql_results:
                            # parallel 노드의 다른 형태 SQL 결과 확인
                            parallel_sql = node_output.get("sql_result")
                            if parallel_sql:
                                p_columns = parallel_sql.get("columns", []) if isinstance(parallel_sql, dict) else getattr(parallel_sql, "columns", [])
                                p_rows = parallel_sql.get("rows", []) if isinstance(parallel_sql, dict) else getattr(parallel_sql, "rows", [])
                                p_row_count = parallel_sql.get("row_count", 0) if isinstance(parallel_sql, dict) else getattr(parallel_sql, "row_count", 0)
                                p_sql = parallel_sql.get("generated_sql", "") if isinstance(parallel_sql, dict) else getattr(parallel_sql, "generated_sql", "")
                                p_exec_time = parallel_sql.get("execution_time_ms", 0) if isinstance(parallel_sql, dict) else getattr(parallel_sql, "execution_time_ms", 0)

                                yield {
                                    "event": "sql_complete",
                                    "data": safe_json_dumps({
                                        "generated_sql": p_sql,
                                        "columns": p_columns[:10] if p_columns else [],
                                        "row_count": p_row_count,
                                        "rows": p_rows[:5] if p_rows else [],
                                        "execution_time_ms": p_exec_time,
                                        "source": "parallel"
                                    }, ensure_ascii=False)
                                }

                        # Phase 10: parallel 노드에서 RAG 결과도 전송 (hybrid 쿼리)
                        if node_name == "parallel":
                            rag_results = node_output.get("rag_results", [])
                            if rag_results:
                                search_strategy = node_output.get("search_strategy", "")
                                rag_count = len(rag_results)

                                yield {
                                    "event": "status",
                                    "data": safe_json_dumps({
                                        "status": "searching",
                                        "result_count": rag_count,
                                        "message": f"관련 정보 {rag_count}개 검색됨 (parallel)"
                                    }, ensure_ascii=False)
                                }

                                # RAG 검색 결과 상세 이벤트 - Phase 99.3: metadata 추가
                                top_results = []
                                for r in rag_results[:5]:
                                    if isinstance(r, dict):
                                        metadata = r.get("metadata", {}) or {}
                                        top_results.append({
                                            "node_id": r.get("node_id", ""),
                                            "name": r.get("name", ""),
                                            "entity_type": r.get("entity_type", ""),
                                            "score": round(r.get("score", 0), 3),
                                            "metadata": {
                                                "community": metadata.get("community"),
                                                "pagerank": metadata.get("pagerank"),
                                                "connections": metadata.get("connections"),
                                                "content": (r.get("content", "") or "")[:200]
                                            }
                                        })
                                    else:
                                        metadata = getattr(r, "metadata", {}) or {}
                                        content = getattr(r, "content", "") or ""
                                        top_results.append({
                                            "node_id": getattr(r, "node_id", ""),
                                            "name": getattr(r, "name", ""),
                                            "entity_type": getattr(r, "entity_type", ""),
                                            "score": round(getattr(r, "score", 0), 3),
                                            "metadata": {
                                                "community": metadata.get("community") if isinstance(metadata, dict) else None,
                                                "pagerank": metadata.get("pagerank") if isinstance(metadata, dict) else None,
                                                "connections": metadata.get("connections") if isinstance(metadata, dict) else None,
                                                "content": content[:200] if content else None
                                            }
                                        })

                                yield {
                                    "event": "rag_complete",
                                    "data": safe_json_dumps({
                                        "search_strategy": search_strategy,
                                        "result_count": rag_count,
                                        "top_results": top_results,
                                        "source": "parallel"
                                    }, ensure_ascii=False)
                                }

                    # RAG 검색 완료 (상세 결과 포함)
                    elif node_name == "rag_node":
                        rag_results = node_output.get("rag_results", [])
                        search_strategy = node_output.get("search_strategy", "")
                        rag_count = len(rag_results)

                        # 복합 질의 RAG 하위 쿼리 실행 중 상태
                        if is_compound and sub_queries:
                            for i, sq in enumerate(sub_queries):
                                if sq.get("query_type") == "rag":
                                    yield {
                                        "event": "subquery_progress",
                                        "data": safe_json_dumps({
                                            "index": i,
                                            "status": "executing"
                                        }, ensure_ascii=False)
                                    }

                        yield {
                            "event": "status",
                            "data": safe_json_dumps({
                                "status": "searching",
                                "result_count": rag_count,
                                "message": f"관련 정보 {rag_count}개 검색됨"
                            }, ensure_ascii=False)
                        }

                        # RAG 검색 완료 상세 이벤트 (시각화용) - Phase 99.3: metadata 추가
                        top_results = []
                        for r in rag_results[:5]:  # 상위 5개
                            if isinstance(r, dict):
                                metadata = r.get("metadata", {}) or {}
                                top_results.append({
                                    "node_id": r.get("node_id", ""),
                                    "name": r.get("name", ""),
                                    "entity_type": r.get("entity_type", ""),
                                    "score": round(r.get("score", 0), 3),
                                    "metadata": {
                                        "community": metadata.get("community"),
                                        "pagerank": metadata.get("pagerank"),
                                        "connections": metadata.get("connections"),
                                        "content": (r.get("content", "") or "")[:200]
                                    }
                                })
                            else:
                                metadata = getattr(r, "metadata", {}) or {}
                                content = getattr(r, "content", "") or ""
                                top_results.append({
                                    "node_id": getattr(r, "node_id", ""),
                                    "name": getattr(r, "name", ""),
                                    "entity_type": getattr(r, "entity_type", ""),
                                    "score": round(getattr(r, "score", 0), 3),
                                    "metadata": {
                                        "community": metadata.get("community") if isinstance(metadata, dict) else None,
                                        "pagerank": metadata.get("pagerank") if isinstance(metadata, dict) else None,
                                        "connections": metadata.get("connections") if isinstance(metadata, dict) else None,
                                        "content": content[:200] if content else None
                                    }
                                })

                        yield {
                            "event": "rag_complete",
                            "data": safe_json_dumps({
                                "search_strategy": search_strategy,
                                "result_count": rag_count,
                                "top_results": top_results
                            }, ensure_ascii=False)
                        }

                        # 복합 질의 RAG 하위 쿼리 완료 상태 업데이트
                        if is_compound and sub_queries:
                            for i, sq in enumerate(sub_queries):
                                if sq.get("query_type") == "rag":
                                    yield {
                                        "event": "subquery_progress",
                                        "data": safe_json_dumps({
                                            "index": i,
                                            "status": "completed"
                                        }, ensure_ascii=False)
                                    }

                    # Phase 50: merger 노드에서 compound 쿼리 하위 결과 전송
                    elif node_name == "merger":
                        sub_query_results = node_output.get("sub_query_results", [])
                        if sub_query_results:
                            for i, sub_result in enumerate(sub_query_results):
                                # 하위 쿼리별 결과 이벤트 전송
                                sub_sql_result = sub_result.get("sql_result")
                                sub_rag_result = sub_result.get("rag_result")

                                event_data = {
                                    "index": sub_result.get("index", i),  # Phase 104.7: sub_result의 원래 index 사용
                                    "subtype": sub_result.get("subtype") or sub_result.get("query_subtype", ""),
                                    "intent": sub_result.get("intent") or sub_result.get("query", "")
                                }

                                if sub_sql_result:
                                    if isinstance(sub_sql_result, dict):
                                        event_data["sql_result"] = {
                                            "generated_sql": sub_sql_result.get("generated_sql", ""),
                                            "columns": sub_sql_result.get("columns", [])[:10],
                                            "row_count": sub_sql_result.get("row_count", 0),
                                            "rows": sub_sql_result.get("rows", [])[:5]
                                        }
                                    else:
                                        event_data["sql_result"] = {
                                            "generated_sql": getattr(sub_sql_result, "generated_sql", ""),
                                            "columns": getattr(sub_sql_result, "columns", [])[:10],
                                            "row_count": getattr(sub_sql_result, "row_count", 0),
                                            "rows": getattr(sub_sql_result, "rows", [])[:5]
                                        }

                                if sub_rag_result:
                                    if isinstance(sub_rag_result, dict):
                                        event_data["rag_result"] = {
                                            "result_count": sub_rag_result.get("result_count", 0),
                                            "results": sub_rag_result.get("results", [])[:5]
                                        }
                                    else:
                                        event_data["rag_result"] = {
                                            "result_count": getattr(sub_rag_result, "result_count", 0),
                                            "results": getattr(sub_rag_result, "results", [])[:5]
                                        }

                                yield {
                                    "event": "sub_query_complete",
                                    "data": safe_json_dumps(event_data, ensure_ascii=False)
                                }

                    # 응답 생성 중
                    elif node_name == "generator":
                        response = node_output.get("response", "")
                        if response:
                            # 응답 텍스트 스트리밍 (줄바꿈 이스케이프)
                            yield {
                                "event": "text",
                                "data": response.replace("\n", "\\n")
                            }
                            final_state = node_output

                        # Phase 104: 관점별 요약 이벤트 전송 (목적/소재/공법/효과)
                        # 새 구조: {purpose: {original, explanation}, material: {original, explanation}, ...}
                        perspective_summary = node_output.get("perspective_summary", {})
                        if perspective_summary and isinstance(perspective_summary, dict):
                            # 필수 필드 존재 확인 (새 구조)
                            required_keys = ["purpose", "material", "method", "effect"]
                            if all(key in perspective_summary for key in required_keys):
                                # 새 구조 형식으로 전송 (original + explanation)
                                yield {
                                    "event": "perspective_summary",
                                    "data": safe_json_dumps({
                                        "purpose": perspective_summary.get("purpose", {"original": "", "explanation": ""}),
                                        "material": perspective_summary.get("material", {"original": "", "explanation": ""}),
                                        "method": perspective_summary.get("method", {"original": "", "explanation": ""}),
                                        "effect": perspective_summary.get("effect", {"original": "", "explanation": ""})
                                    }, ensure_ascii=False)
                                }
                                logger.info(f"Phase 104: perspective_summary SSE 이벤트 전송 완료 (원본+설명 구조)")

            # 완료 이벤트
            if final_state:
                # 단계별 타이밍 이벤트 (시각화용)
                yield {
                    "event": "stage_timing",
                    "data": safe_json_dumps(stage_timing, ensure_ascii=False)
                }

                # Phase 99.3: sources 구성
                sources = []

                # SQL 결과가 있으면 추가
                sql_result = final_state.get("sql_result")
                if sql_result:
                    if isinstance(sql_result, dict):
                        if sql_result.get("success") or sql_result.get("row_count", 0) > 0:
                            sources.append({
                                "type": "sql",
                                "count": sql_result.get("row_count", 0),
                                "tables": final_state.get("related_tables", [])
                            })
                    elif hasattr(sql_result, "success") and sql_result.success:
                        sources.append({
                            "type": "sql",
                            "count": getattr(sql_result, "row_count", 0),
                            "tables": final_state.get("related_tables", [])
                        })

                # 다중 SQL 결과 (multi_sql_results)
                multi_sql_results = final_state.get("multi_sql_results", {})
                if multi_sql_results and isinstance(multi_sql_results, dict):
                    for entity_type, result in multi_sql_results.items():
                        if result:
                            row_count = 0
                            if isinstance(result, dict):
                                row_count = result.get("row_count", 0)
                            elif hasattr(result, "row_count"):
                                row_count = result.row_count
                            if row_count > 0:
                                sources.append({
                                    "type": f"sql_{entity_type}",
                                    "count": row_count,
                                    "entity_type": entity_type
                                })

                # RAG 결과가 있으면 추가
                rag_results = final_state.get("rag_results", [])
                if rag_results and len(rag_results) > 0:
                    sources.append({
                        "type": "rag",
                        "count": len(rag_results),
                        "strategy": final_state.get("search_strategy", "hybrid")
                    })

                # Graph 결과가 있으면 추가
                graph_results = final_state.get("graph_enhanced_results", [])
                if graph_results and len(graph_results) > 0:
                    sources.append({
                        "type": "graph",
                        "count": len(graph_results)
                    })

                # Phase 102: confidence_score 계산
                confidence_score = final_state.get("context_quality", 0.0)
                if confidence_score == 0.0:
                    # context_quality가 없으면 sources 기반 추정
                    source_count = len(sources)
                    rag_count = len(rag_results) if rag_results else 0
                    confidence_score = min(0.25 * min(source_count, 3) + 0.05 * min(rag_count, 10), 1.0)

                # Phase 102: graph_data 추출 (특허 + 1-hop 관련 엔티티)
                graph_nodes = []
                graph_edges = []
                seen_nodes = set()

                for rag_item in (rag_results or [])[:15]:
                    if isinstance(rag_item, dict):
                        node_id = rag_item.get("node_id", "")
                        entity_type = rag_item.get("entity_type", "patent")
                        name = rag_item.get("name", "")
                        score = rag_item.get("score", 0.5)
                        metadata = rag_item.get("metadata", {}) or {}
                    else:
                        node_id = getattr(rag_item, "node_id", "")
                        entity_type = getattr(rag_item, "entity_type", "patent")
                        name = getattr(rag_item, "name", "")
                        score = getattr(rag_item, "score", 0.5)
                        metadata = getattr(rag_item, "metadata", {}) or {}

                    if node_id and node_id not in seen_nodes:
                        seen_nodes.add(node_id)
                        node_color = NODE_TYPES.get(entity_type, {}).get("color", "#9E9E9E")
                        graph_nodes.append({
                            "id": node_id,
                            "name": name,
                            "type": entity_type,
                            "score": round(score, 3) if isinstance(score, float) else score,
                            "color": node_color
                        })

                    # 1-hop 관련 엔티티
                    related_entities = metadata.get("related_entities", []) if isinstance(metadata, dict) else []
                    for rel in related_entities[:5]:
                        rel_id = rel.get("node_id", "")
                        rel_type = rel.get("entity_type", "org")
                        rel_name = rel.get("name", "")
                        rel_score = rel.get("score", 0.3)

                        if rel_id and rel_id not in seen_nodes:
                            seen_nodes.add(rel_id)
                            rel_color = NODE_TYPES.get(rel_type, {}).get("color", "#9E9E9E")
                            graph_nodes.append({
                                "id": rel_id,
                                "name": rel_name,
                                "type": rel_type,
                                "score": round(rel_score, 3) if isinstance(rel_score, float) else rel_score,
                                "color": rel_color
                            })

                        if rel_id:
                            graph_edges.append({
                                "from_id": node_id,
                                "to_id": rel_id,
                                "relation": rel.get("relation", "related")
                            })

                # graph_data 구성
                graph_data = None
                if graph_nodes:
                    graph_data = {
                        "nodes": graph_nodes,
                        "edges": graph_edges
                    }

                # Phase 104.6: RAG 결과가 없고 ranking 쿼리인 경우 SQL 결과에서 그래프 생성
                if not graph_data and multi_sql_results:
                    query_subtype = final_state.get("query_subtype", "")
                    keywords = final_state.get("keywords", [])
                    expanded_keywords = final_state.get("expanded_keywords", [])
                    if query_subtype == "ranking" or (final_state.get("is_compound") and multi_sql_results):
                        graph_data = build_graph_from_ranking_results(
                            multi_sql_results=multi_sql_results,
                            keywords=keywords,
                            expanded_keywords=expanded_keywords,
                            query_subtype="ranking"  # compound도 ranking처럼 처리
                        )

                yield {
                    "event": "done",
                    "data": safe_json_dumps({
                        "query_type": final_state.get("query_type", "unknown"),
                        "sources": sources if sources else final_state.get("sources", []),
                        "elapsed_ms": final_state.get("elapsed_ms", 0),
                        "timing": stage_timing,
                        "confidence_score": round(confidence_score, 2),  # Phase 102
                        "graph_data": graph_data  # Phase 102
                    }, ensure_ascii=False)
                }
            else:
                yield {
                    "event": "error",
                    "data": safe_json_dumps({
                        "error": "응답을 생성할 수 없습니다."
                    }, ensure_ascii=False)
                }

        except Exception as e:
            logger.error(f"스트리밍 오류: {e}")
            yield {
                "event": "error",
                "data": safe_json_dumps({
                    "error": str(e)
                }, ensure_ascii=False)
            }

    return EventSourceResponse(event_generator())


async def stream_workflow_datastream(request: StreamChatRequest):
    """
    워크플로우 스트리밍 (assistant-stream DataStream 방식)

    AI SDK와 호환되는 데이터 스트림을 반환합니다.
    assistant-ui와 연동 가능.

    Args:
        request: 스트리밍 채팅 요청

    Returns:
        DataStreamResponse: AI SDK 호환 스트림
    """
    async def run(controller: RunController):
        try:
            # 워크플로우 가져오기
            workflow = get_workflow()
            initial_state = create_initial_state(
                query=request.query,
                session_id=request.session_id,
                level=request.level
            )

            # 워크플로우 스트리밍 실행
            async for event in workflow.astream(initial_state, stream_mode="updates"):
                for node_name, node_output in event.items():
                    # generator 노드에서 응답 텍스트 추출
                    if node_name == "generator":
                        response = node_output.get("response", "")
                        if response:
                            # assistant-stream으로 텍스트 스트리밍
                            controller.append_text(response)

        except Exception as e:
            logger.error(f"DataStream 오류: {e}")
            controller.append_text(f"\n\n오류가 발생했습니다: {str(e)}")

    return DataStreamResponse(create_run(run))


async def stream_workflow_chunks(request: StreamChatRequest) -> AsyncGenerator[str, None]:
    """
    워크플로우 청크 스트리밍 (LLM 토큰 단위)

    LLM 생성 응답을 토큰 단위로 스트리밍합니다.
    현재 구현에서는 최종 응답만 반환합니다.

    Args:
        request: 스트리밍 채팅 요청

    Yields:
        str: 응답 텍스트 청크
    """
    try:
        workflow = get_workflow()
        initial_state = create_initial_state(
            query=request.query,
            session_id=request.session_id,
            level=request.level
        )

        # 워크플로우 실행 (현재는 전체 응답 후 반환)
        # TODO: generator 노드에서 LLM 스트리밍 지원 시 토큰 단위 yield
        final_state = await workflow.ainvoke(initial_state)

        response = final_state.get("response", "")
        if response:
            # 응답을 청크로 분할하여 스트리밍 효과
            chunk_size = 50  # 약 50자씩 전송
            for i in range(0, len(response), chunk_size):
                yield response[i:i+chunk_size]
        else:
            yield "응답을 생성할 수 없습니다."

    except Exception as e:
        logger.error(f"청크 스트리밍 오류: {e}")
        yield f"오류: {str(e)}"
