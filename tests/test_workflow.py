"""
워크플로우 단위 테스트
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from workflow.state import AgentState, create_initial_state, SearchResult, SQLQueryResult
from workflow.nodes.analyzer import analyze_query, _check_simple_query
from workflow.edges import route_query, route_after_sql, route_after_rag


class TestState:
    """상태 관련 테스트"""

    def test_create_initial_state(self):
        """초기 상태 생성 테스트"""
        state = create_initial_state(query="테스트", session_id="test-123")

        assert state["query"] == "테스트"
        assert state["session_id"] == "test-123"
        assert state["query_type"] == "simple"
        assert state["rag_results"] == []
        assert state["sql_result"] is None

    def test_search_result_dataclass(self):
        """SearchResult 데이터클래스 테스트"""
        result = SearchResult(
            node_id="test_id",
            name="테스트",
            entity_type="project",
            score=0.95
        )

        assert result.node_id == "test_id"
        assert result.score == 0.95

    def test_sql_query_result_dataclass(self):
        """SQLQueryResult 데이터클래스 테스트"""
        result = SQLQueryResult(
            success=True,
            columns=["id", "name"],
            rows=[[1, "test"]],
            row_count=1
        )

        assert result.success is True
        assert result.row_count == 1


class TestAnalyzer:
    """쿼리 분석 노드 테스트"""

    def test_check_simple_query_greeting(self):
        """인사말 감지 테스트"""
        result = _check_simple_query("안녕하세요")
        assert result is not None
        assert result["query_type"] == "simple"
        assert result["query_intent"] == "인사"

    def test_check_simple_query_help(self):
        """도움말 요청 감지 테스트"""
        result = _check_simple_query("도움말 보여줘")
        assert result is not None
        assert result["query_type"] == "simple"
        assert result["query_intent"] == "도움말 요청"

    def test_check_simple_query_normal(self):
        """일반 쿼리는 None 반환"""
        result = _check_simple_query("인공지능 특허 알려줘")
        assert result is None

    def test_analyze_empty_query(self):
        """빈 쿼리 분석 테스트"""
        state = create_initial_state(query="")
        result = analyze_query(state)

        assert result["query_type"] == "simple"
        assert result.get("error") is not None


class TestEdges:
    """라우팅 함수 테스트"""

    def test_route_query_sql(self):
        """SQL 쿼리 라우팅 테스트"""
        state = {"query_type": "sql"}
        assert route_query(state) == "sql_node"

    def test_route_query_rag(self):
        """RAG 쿼리 라우팅 테스트"""
        state = {"query_type": "rag"}
        assert route_query(state) == "rag_node"

    def test_route_query_hybrid(self):
        """하이브리드 쿼리 라우팅 테스트"""
        state = {"query_type": "hybrid"}
        assert route_query(state) == "parallel"

    def test_route_query_simple(self):
        """간단 쿼리 라우팅 테스트"""
        state = {"query_type": "simple"}
        assert route_query(state) == "generator"

    def test_route_after_sql_hybrid(self):
        """SQL 후 하이브리드 라우팅"""
        state = {"query_type": "hybrid"}
        assert route_after_sql(state) == "merger"

    def test_route_after_sql_pure(self):
        """SQL 후 순수 SQL 라우팅"""
        state = {"query_type": "sql"}
        assert route_after_sql(state) == "generator"

    def test_route_after_rag_hybrid(self):
        """RAG 후 하이브리드 라우팅"""
        state = {"query_type": "hybrid"}
        assert route_after_rag(state) == "merger"

    def test_route_after_rag_pure(self):
        """RAG 후 순수 RAG 라우팅"""
        state = {"query_type": "rag"}
        assert route_after_rag(state) == "generator"


class TestQueryRouting:
    """쿼리 라우팅 통합 테스트"""

    @pytest.mark.parametrize("query,expected_type", [
        ("안녕하세요", "simple"),
        ("hello", "simple"),
        ("도움말", "simple"),
    ])
    def test_simple_queries(self, query, expected_type):
        """간단한 쿼리 라우팅 테스트"""
        state = create_initial_state(query=query)
        result = analyze_query(state)
        assert result["query_type"] == expected_type
