"""
Phase 14: Reasoning Mode 분석기 테스트
- EXAONE <think> 태그 기반 다단계 추론 검증
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import Mock, patch, MagicMock

from workflow.state import create_initial_state
from workflow.nodes.analyzer import analyze_query, _check_simple_query
from workflow.nodes.reasoning_analyzer import (
    analyze_with_reasoning,
    quick_classify,
    _parse_reasoning_result,
    SQLElements,
    RAGElements,
    AnalysisResult
)
from llm.llm_client import ReasoningResult


class TestQuickClassify:
    """빠른 규칙 기반 분류 테스트"""

    def test_greeting_detection(self):
        """인사말 감지"""
        greetings = ["안녕하세요", "hello", "hi there", "반갑습니다"]
        for g in greetings:
            result = quick_classify(g)
            assert result is not None
            assert result["query_type"] == "simple"

    def test_help_detection(self):
        """도움말 감지"""
        help_queries = ["도움말", "help me", "사용법 알려줘", "가이드"]
        for h in help_queries:
            result = quick_classify(h)
            assert result is not None
            assert result["query_type"] == "simple"

    def test_complex_query_returns_none(self):
        """복잡한 쿼리는 None 반환 (LLM 필요)"""
        complex_queries = [
            "예산이 가장 큰 연구과제 5개",
            "인공지능 연구 동향",
            "특허 출원이 많은 기관"
        ]
        for q in complex_queries:
            result = quick_classify(q)
            # None 반환 = LLM 분석 필요
            # 숫자 패턴이 있으면 None 반환 가능
            assert result is None or result.get("query_type") != "simple"


class TestParseReasoningResult:
    """Reasoning 결과 파싱 테스트"""

    def test_json_parsing(self):
        """JSON 응답 파싱"""
        result = ReasoningResult(
            thinking="단계별 추론 내용...",
            answer="""```json
{
    "query_type": "sql",
    "intent": "예산 상위 과제 조회",
    "strategy": "none",
    "sql_elements": {
        "tables": ["f_projects"],
        "fields": ["conts_klang_nm", "tot_rsrh_blgn_amt"],
        "order_by": "tot_rsrh_blgn_amt DESC",
        "limit": 5
    },
    "rag_elements": {}
}
```""",
            raw_response=""
        )

        analysis = _parse_reasoning_result(result)
        assert analysis.query_type == "sql"
        assert "f_projects" in analysis.sql_elements.tables
        assert analysis.sql_elements.limit == 5

    def test_text_fallback_parsing(self):
        """텍스트 기반 폴백 파싱"""
        result = ReasoningResult(
            thinking="추론...",
            answer="쿼리 유형: sql, 의도: 과제 조회, 테이블: f_projects",
            raw_response=""
        )

        analysis = _parse_reasoning_result(result)
        assert analysis.query_type == "sql"

    def test_invalid_json_fallback(self):
        """잘못된 JSON 폴백"""
        result = ReasoningResult(
            thinking="추론...",
            answer="{invalid json}",
            raw_response=""
        )

        analysis = _parse_reasoning_result(result)
        # 기본값으로 폴백
        assert analysis.query_type in ["sql", "rag", "hybrid", "simple"]


class TestAnalyzeQuery:
    """쿼리 분석 노드 테스트"""

    def test_empty_query(self):
        """빈 쿼리 처리"""
        state = create_initial_state(query="")
        result = analyze_query(state)
        assert result["query_type"] == "simple"
        assert "error" in result

    def test_whitespace_query(self):
        """공백 쿼리 처리"""
        state = create_initial_state(query="   ")
        result = analyze_query(state)
        assert result["query_type"] == "simple"

    def test_greeting_query(self):
        """인사말 쿼리 - LLM 호출 없이 처리"""
        state = create_initial_state(query="안녕하세요")
        result = analyze_query(state)
        assert result["query_type"] == "simple"
        assert result["query_intent"] == "인사"

    def test_help_query(self):
        """도움말 쿼리 - LLM 호출 없이 처리"""
        state = create_initial_state(query="도움말")
        result = analyze_query(state)
        assert result["query_type"] == "simple"
        assert "도움" in result["query_intent"]


class TestSQLElements:
    """SQL 요소 데이터클래스 테스트"""

    def test_default_values(self):
        """기본값 확인"""
        elem = SQLElements()
        assert elem.tables == []
        assert elem.fields == []
        assert elem.conditions == ""
        assert elem.limit is None

    def test_with_values(self):
        """값 할당 확인"""
        elem = SQLElements(
            tables=["f_projects"],
            fields=["conts_klang_nm"],
            order_by="tot_rsrh_blgn_amt DESC",
            limit=5
        )
        assert len(elem.tables) == 1
        assert elem.limit == 5


class TestRAGElements:
    """RAG 요소 데이터클래스 테스트"""

    def test_default_values(self):
        """기본값 확인"""
        elem = RAGElements()
        assert elem.keywords == []
        assert elem.entity_types == []
        assert elem.filters == {}

    def test_with_values(self):
        """값 할당 확인"""
        elem = RAGElements(
            keywords=["인공지능", "딥러닝"],
            entity_types=["project", "patent"]
        )
        assert len(elem.keywords) == 2
        assert "project" in elem.entity_types


class TestAnalysisResult:
    """분석 결과 데이터클래스 테스트"""

    def test_default_values(self):
        """기본값 확인"""
        result = AnalysisResult()
        assert result.query_type == "rag"
        assert result.strategy == "HYBRID"
        assert result.confidence == 0.0

    def test_with_reasoning_trace(self):
        """추론 과정 포함"""
        result = AnalysisResult(
            query_type="sql",
            intent="과제 조회",
            reasoning_trace="<think>단계별 추론...</think>"
        )
        assert result.query_type == "sql"
        assert "<think>" in result.reasoning_trace


@pytest.mark.slow
class TestIntegrationWithLLM:
    """LLM 연동 통합 테스트 (실제 LLM 호출)"""

    def test_sql_query_classification(self):
        """SQL 쿼리 분류 - 실제 LLM"""
        state = create_initial_state(query="예산이 가장 큰 연구과제 5개 알려줘")
        result = analyze_query(state)
        assert result["query_type"] == "sql"

    def test_rag_query_classification(self):
        """RAG 쿼리 분류 - 실제 LLM"""
        state = create_initial_state(query="블록체인 기술이란 무엇인가요?")
        result = analyze_query(state)
        assert result["query_type"] in ["rag", "hybrid"]

    def test_hybrid_query_classification(self):
        """하이브리드 쿼리 분류 - 실제 LLM"""
        state = create_initial_state(query="인공지능 관련 특허의 기술 동향과 상위 10개")
        result = analyze_query(state)
        assert result["query_type"] in ["hybrid", "sql"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
