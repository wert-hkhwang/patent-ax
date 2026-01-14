"""
EXAONE Reasoning Mode 기반 다단계 추론 분석기
- <think> 태그를 활용한 Chain-of-Thought 추론
- 4단계 분석 파이프라인
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import re
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

from workflow.state import AgentState
from workflow.prompts.reasoning_prompts import build_unified_prompt, build_decomposition_prompt
from workflow.prompts.schema_context import get_dynamic_schema_context
from llm.llm_client import get_llm_client, ReasoningResult

logger = logging.getLogger(__name__)


@dataclass
class SubQuery:
    """하위 질의 정보"""
    query: str                          # 하위 질의 텍스트
    query_type: str = "rag"             # sql/rag
    entity_types: List[str] = field(default_factory=list)
    depends_on: Optional[int] = None    # 의존하는 하위 질의 인덱스
    priority: int = 0                   # 실행 우선순위


@dataclass
class DecompositionResult:
    """질의 분해 결과"""
    is_compound: bool = False
    sub_queries: List[SubQuery] = field(default_factory=list)
    merge_strategy: str = "parallel"    # parallel/sequential
    reasoning: str = ""                 # 분해 이유


@dataclass
class SQLElements:
    """SQL 쿼리 요소"""
    tables: List[str] = field(default_factory=list)
    fields: List[str] = field(default_factory=list)
    conditions: str = ""
    order_by: str = ""
    limit: Optional[int] = None
    aggregates: List[str] = field(default_factory=list)


@dataclass
class RAGElements:
    """RAG 검색 요소"""
    keywords: List[str] = field(default_factory=list)
    entity_types: List[str] = field(default_factory=list)
    filters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """다단계 분석 결과"""
    query_type: str = "rag"              # sql/rag/hybrid/simple
    intent: str = ""                      # 의도 설명
    strategy: str = "HYBRID"              # 검색 전략
    sql_elements: SQLElements = field(default_factory=SQLElements)
    rag_elements: RAGElements = field(default_factory=RAGElements)
    execution_steps: List[str] = field(default_factory=list)
    reasoning_trace: str = ""             # <think> 블록 내용
    confidence: float = 0.0               # 분석 신뢰도


def analyze_with_reasoning(state: AgentState) -> AgentState:
    """EXAONE Reasoning Mode를 활용한 다단계 분석

    4단계 추론:
    1. 의도 분석 (Intent Analysis)
    2. 전략 수립 (Strategy Planning)
    3. 요소 추출 (Element Extraction)
    4. 실행 계획 (Execution Plan)

    Args:
        state: 현재 에이전트 상태

    Returns:
        업데이트된 상태 (분석 결과 포함)
    """
    query = state.get("query", "")

    if not query.strip():
        return {
            **state,
            "query_type": "simple",
            "query_intent": "빈 질문",
            "error": "질문이 비어있습니다."
        }

    try:
        # 스키마 컨텍스트 생성
        schema_context = get_dynamic_schema_context(query)

        # 통합 추론 프롬프트 생성
        prompt = build_unified_prompt(query, schema_context)

        # LLM Reasoning Mode 호출
        llm = get_llm_client()
        reasoning_result = llm.generate_with_reasoning(
            prompt=prompt,
            system_prompt="당신은 사용자 질문을 분석하는 전문가입니다. 단계별로 신중하게 추론하세요.",
            max_tokens=2000
        )

        # 결과 파싱
        analysis = _parse_reasoning_result(reasoning_result)

        logger.info(
            f"추론 분석 완료: type={analysis.query_type}, "
            f"intent={analysis.intent[:50]}..."
        )

        # 상태 업데이트
        return {
            **state,
            "query_type": analysis.query_type,
            "query_intent": analysis.intent,
            "entity_types": analysis.rag_elements.entity_types,
            "related_tables": analysis.sql_elements.tables,
            "keywords": analysis.rag_elements.keywords,
            "reasoning_trace": analysis.reasoning_trace,
            # SQL 요소 저장 (sql_executor에서 활용)
            "sql_elements": {
                "tables": analysis.sql_elements.tables,
                "fields": analysis.sql_elements.fields,
                "conditions": analysis.sql_elements.conditions,
                "order_by": analysis.sql_elements.order_by,
                "limit": analysis.sql_elements.limit
            },
            # RAG 요소 저장 (rag_retriever에서 활용)
            "rag_elements": {
                "keywords": analysis.rag_elements.keywords,
                "entity_types": analysis.rag_elements.entity_types,
                "filters": analysis.rag_elements.filters
            },
            "search_strategy": analysis.strategy
        }

    except Exception as e:
        logger.error(f"추론 분석 실패: {e}")
        # 폴백: 기본 RAG 처리
        return {
            **state,
            "query_type": "rag",
            "query_intent": query,
            "error": f"추론 분석 실패: {str(e)}"
        }


def _parse_reasoning_result(result: ReasoningResult) -> AnalysisResult:
    """Reasoning 결과 파싱

    Args:
        result: LLM Reasoning Mode 결과

    Returns:
        파싱된 분석 결과
    """
    analysis = AnalysisResult()
    analysis.reasoning_trace = result.thinking

    # 답변에서 JSON 추출
    answer = result.answer

    # JSON 블록 찾기
    json_match = re.search(r'```json\s*(.*?)\s*```', answer, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # JSON 블록 없으면 전체 텍스트에서 JSON 추출 시도
        json_match = re.search(r'\{[^{}]*\}', answer, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            # JSON 없으면 텍스트 기반 파싱
            return _parse_text_result(answer, analysis)

    try:
        data = json.loads(json_str)
        return _parse_json_result(data, analysis)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON 파싱 실패: {e}, 텍스트 파싱 시도")
        return _parse_text_result(answer, analysis)


def _parse_json_result(data: Dict, analysis: AnalysisResult) -> AnalysisResult:
    """JSON 결과 파싱"""
    # 쿼리 유형
    query_type = data.get("query_type", "rag")
    if query_type in ["sql", "rag", "hybrid", "simple"]:
        analysis.query_type = query_type
    else:
        analysis.query_type = "rag"

    # 의도
    analysis.intent = data.get("intent", "")

    # 검색 전략
    strategy = data.get("strategy", "HYBRID")
    valid_strategies = ["VECTOR_ONLY", "GRAPH_ONLY", "GRAPH_ENHANCED", "HYBRID", "none"]
    analysis.strategy = strategy if strategy in valid_strategies else "HYBRID"

    # SQL 요소
    sql_elem = data.get("sql_elements", {})
    if sql_elem:
        analysis.sql_elements = SQLElements(
            tables=sql_elem.get("tables", []) or [],
            fields=sql_elem.get("fields", []) or [],
            conditions=sql_elem.get("conditions", "") or "",
            order_by=sql_elem.get("order_by", "") or "",
            limit=sql_elem.get("limit")
        )

    # RAG 요소
    rag_elem = data.get("rag_elements", {})
    if rag_elem:
        analysis.rag_elements = RAGElements(
            keywords=rag_elem.get("keywords", []) or [],
            entity_types=rag_elem.get("entity_types", []) or [],
            filters=rag_elem.get("filters", {}) or {}
        )

    # 실행 단계
    analysis.execution_steps = data.get("execution_steps", [])

    return analysis


def _parse_text_result(text: str, analysis: AnalysisResult) -> AnalysisResult:
    """텍스트 기반 결과 파싱 (JSON 실패 시 폴백)"""
    text_lower = text.lower()

    # 쿼리 유형 추론
    if "sql" in text_lower and ("select" in text_lower or "쿼리" in text_lower):
        analysis.query_type = "sql"
    elif "hybrid" in text_lower or ("sql" in text_lower and "rag" in text_lower):
        analysis.query_type = "hybrid"
    elif "simple" in text_lower or "인사" in text_lower:
        analysis.query_type = "simple"
    else:
        analysis.query_type = "rag"

    # 의도 추출 (첫 번째 줄 또는 "의도:" 이후)
    intent_match = re.search(r'의도[:\s]+([^\n]+)', text)
    if intent_match:
        analysis.intent = intent_match.group(1).strip()
    else:
        lines = text.strip().split('\n')
        analysis.intent = lines[0] if lines else ""

    # 테이블 추출
    table_match = re.findall(r'f_\w+', text)
    if table_match:
        analysis.sql_elements.tables = list(set(table_match))

    # 키워드 추출
    keyword_match = re.search(r'키워드[:\s]+\[([^\]]+)\]', text)
    if keyword_match:
        keywords = [k.strip().strip('"\'') for k in keyword_match.group(1).split(',')]
        analysis.rag_elements.keywords = keywords

    # 검색 전략 추출
    strategy_patterns = {
        "VECTOR_ONLY": ["vector_only", "벡터", "의미 검색"],
        "GRAPH_ONLY": ["graph_only", "그래프", "관계 탐색"],
        "GRAPH_ENHANCED": ["graph_enhanced", "그래프 확장"],
        "HYBRID": ["hybrid", "하이브리드", "복합"]
    }

    for strategy, patterns in strategy_patterns.items():
        if any(p in text_lower for p in patterns):
            analysis.strategy = strategy
            break

    return analysis


def quick_classify(query: str) -> Optional[Dict[str, Any]]:
    """빠른 규칙 기반 분류 (LLM 호출 절약)

    Args:
        query: 사용자 질문

    Returns:
        분류 결과 또는 None (LLM 분석 필요 시)
    """
    query_lower = query.lower().strip()

    # 인사말
    greetings = ["안녕", "hello", "hi", "반갑", "안녕하세요"]
    if any(g in query_lower for g in greetings):
        return {
            "query_type": "simple",
            "intent": "인사",
            "entity_types": [],
            "related_tables": [],
            "keywords": [],
            "search_strategy": "none"
        }

    # 도움말
    help_words = ["도움", "help", "사용법", "가이드", "뭘 할 수"]
    if any(h in query_lower for h in help_words):
        return {
            "query_type": "simple",
            "intent": "도움말 요청",
            "entity_types": [],
            "related_tables": [],
            "keywords": [],
            "search_strategy": "none"
        }

    # 명확한 SQL 패턴 (숫자 + 목록/개수)
    sql_patterns = [
        r'\d+\s*개',           # "10개", "5개"
        r'상위\s*\d+',         # "상위 10"
        r'가장\s*(큰|많은|높은|낮은|적은)',  # "가장 큰"
        r'몇\s*개',            # "몇 개"
        r'목록',               # "목록"
        r'리스트',             # "리스트"
        r'통계',               # "통계"
        r'순위',               # "순위"
    ]

    if any(re.search(p, query_lower) for p in sql_patterns):
        # SQL 가능성 높음, 하지만 LLM으로 세부 분석 필요
        return None  # LLM 분석으로 넘김

    return None  # LLM 분석 필요


def analyze_complex_query(state: AgentState, complexity_reason: str) -> AgentState:
    """복합 질의 분석 및 분해

    복합 질의를 LLM을 사용하여 하위 질의로 분해하고,
    각 하위 질의의 처리 방식을 결정합니다.

    Args:
        state: 현재 에이전트 상태
        complexity_reason: 복합 질의로 판단된 이유

    Returns:
        업데이트된 상태 (하위 질의 목록 포함)
    """
    query = state.get("query", "")

    if not query.strip():
        return {
            **state,
            "query_type": "simple",
            "query_intent": "빈 질문",
            "error": "질문이 비어있습니다."
        }

    try:
        # 질의 분해 프롬프트 생성
        prompt = build_decomposition_prompt(query, complexity_reason)

        # LLM Reasoning Mode 호출
        llm = get_llm_client()
        reasoning_result = llm.generate_with_reasoning(
            prompt=prompt,
            system_prompt="당신은 복합 질문을 분석하여 하위 질의로 분해하는 전문가입니다. 각 하위 질의가 독립적으로 처리될 수 있도록 명확하게 분해하세요.",
            max_tokens=2000
        )

        # 결과 파싱
        decomposition = _parse_decomposition_result(reasoning_result)

        logger.info(
            f"복합 질의 분해 완료: "
            f"is_compound={decomposition.is_compound}, "
            f"sub_queries={len(decomposition.sub_queries)}, "
            f"merge_strategy={decomposition.merge_strategy}"
        )

        if not decomposition.is_compound or len(decomposition.sub_queries) == 0:
            # 분해 결과가 없으면 일반 분석으로 폴백
            logger.info("분해 불필요, 일반 분석으로 폴백")
            return analyze_with_reasoning(state)

        # 하위 질의 정보를 직렬화 가능한 형태로 변환
        sub_queries_data = [
            {
                "query": sq.query,
                "query_type": sq.query_type,
                "entity_types": sq.entity_types,
                "depends_on": sq.depends_on,
                "priority": sq.priority
            }
            for sq in decomposition.sub_queries
        ]

        # 전체 쿼리 유형 결정
        query_types = [sq.query_type for sq in decomposition.sub_queries]
        if "sql" in query_types and "rag" in query_types:
            overall_type = "hybrid"
        elif all(t == "sql" for t in query_types):
            overall_type = "sql"
        else:
            overall_type = "rag"

        # 엔티티 타입 통합
        all_entity_types = []
        for sq in decomposition.sub_queries:
            all_entity_types.extend(sq.entity_types)
        all_entity_types = list(dict.fromkeys(all_entity_types))  # 중복 제거, 순서 유지

        # 상태 업데이트
        return {
            **state,
            "query_type": overall_type,
            "query_intent": f"복합 질의: {decomposition.reasoning}",
            "entity_types": all_entity_types,
            "is_compound": True,
            "sub_queries": sub_queries_data,
            "merge_strategy": decomposition.merge_strategy,
            "reasoning_trace": reasoning_result.thinking,
            "complexity_reason": complexity_reason
        }

    except Exception as e:
        logger.error(f"복합 질의 분석 실패: {e}")
        # 폴백: 일반 분석
        logger.info("복합 질의 분석 실패, 일반 분석으로 폴백")
        return analyze_with_reasoning(state)


def _parse_decomposition_result(result: ReasoningResult) -> DecompositionResult:
    """질의 분해 결과 파싱

    Args:
        result: LLM Reasoning Mode 결과

    Returns:
        파싱된 분해 결과
    """
    decomposition = DecompositionResult()
    answer = result.answer

    # JSON 블록 찾기
    json_match = re.search(r'```json\s*(.*?)\s*```', answer, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # JSON 블록 없으면 전체 텍스트에서 JSON 추출 시도
        json_match = re.search(r'\{[^{}]*"is_compound"[^{}]*\}', answer, re.DOTALL)
        if not json_match:
            # 더 넓은 패턴으로 시도
            json_match = re.search(r'\{.*"sub_queries".*\}', answer, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            logger.warning("JSON 블록을 찾을 수 없음, 기본값 반환")
            return decomposition

    try:
        data = json.loads(json_str)

        decomposition.is_compound = data.get("is_compound", False)
        decomposition.merge_strategy = data.get("merge_strategy", "parallel")
        decomposition.reasoning = data.get("reasoning", "")

        # 하위 질의 파싱
        sub_queries_data = data.get("sub_queries", [])
        for idx, sq_data in enumerate(sub_queries_data):
            sub_query = SubQuery(
                query=sq_data.get("query", ""),
                query_type=sq_data.get("type", sq_data.get("query_type", "rag")),
                entity_types=sq_data.get("entity_types", []),
                depends_on=sq_data.get("depends_on"),
                priority=sq_data.get("priority", idx)
            )
            if sub_query.query:  # 빈 쿼리는 제외
                decomposition.sub_queries.append(sub_query)

        return decomposition

    except json.JSONDecodeError as e:
        logger.warning(f"JSON 파싱 실패: {e}")
        return decomposition


if __name__ == "__main__":
    # 테스트
    from workflow.state import create_initial_state

    test_queries = [
        "안녕하세요",
        "예산이 가장 큰 연구과제 5개 알려줘",
        "인공지능 연구 동향은?",
        "특허 출원이 많은 기관 10개와 관련 연구 현황"
    ]

    print("=== 다단계 추론 분석기 테스트 ===\n")

    for q in test_queries:
        print(f"질문: {q}")

        # 빠른 분류 시도
        quick = quick_classify(q)
        if quick:
            print(f"  빠른 분류: {quick['query_type']}")
        else:
            print("  LLM 분석 필요")

            state = create_initial_state(query=q)
            result = analyze_with_reasoning(state)
            print(f"  쿼리 유형: {result.get('query_type')}")
            print(f"  의도: {result.get('query_intent', '')[:50]}")
            if result.get('reasoning_trace'):
                print(f"  추론 과정: {result['reasoning_trace'][:100]}...")

        print()
