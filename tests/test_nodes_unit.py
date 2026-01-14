"""
워크플로우 노드 단위 테스트 (Mock 기반)
- LLM, DB, 외부 서비스 없이 실행 가능
- CI/CD 환경에서 실행 가능
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import Mock, patch, MagicMock

from workflow.state import (
    AgentState, create_initial_state,
    history_reducer, MAX_HISTORY_LENGTH,
    ChatMessage, SearchResult, SQLQueryResult
)
from workflow.errors import (
    WorkflowError, QueryAnalysisError, SQLExecutionError,
    RAGRetrievalError, EmptyQueryError
)


class TestHistoryReducer:
    """대화 기록 리듀서 테스트"""

    def test_empty_lists(self):
        """빈 리스트 병합"""
        result = history_reducer([], [])
        assert result == []

    def test_append_new(self):
        """새 기록 추가"""
        existing = [ChatMessage(role="user", content="a")]
        new = [ChatMessage(role="assistant", content="b")]
        result = history_reducer(existing, new)
        assert len(result) == 2

    def test_truncate_at_max(self):
        """최대 길이 초과 시 잘림"""
        existing = [ChatMessage(role="user", content=f"{i}") for i in range(15)]
        new = [ChatMessage(role="assistant", content=f"{i}") for i in range(10)]
        result = history_reducer(existing, new)
        assert len(result) == MAX_HISTORY_LENGTH

    def test_keeps_recent(self):
        """최신 기록 유지"""
        existing = [ChatMessage(role="user", content=f"old_{i}") for i in range(15)]
        new = [ChatMessage(role="assistant", content=f"new_{i}") for i in range(10)]
        result = history_reducer(existing, new)
        # 마지막 요소가 new 리스트의 마지막이어야 함
        assert result[-1].content == "new_9"

    def test_none_handling(self):
        """None 입력 처리"""
        result = history_reducer(None, [ChatMessage(role="user", content="test")])
        assert len(result) == 1


class TestCreateInitialState:
    """초기 상태 생성 테스트"""

    def test_basic_creation(self):
        """기본 상태 생성"""
        state = create_initial_state(query="테스트 질문")
        assert state["query"] == "테스트 질문"
        assert state["session_id"] == "default"
        assert state["query_type"] == "simple"

    def test_with_session_id(self):
        """세션 ID 지정"""
        state = create_initial_state(query="테스트", session_id="user123")
        assert state["session_id"] == "user123"

    def test_initial_lists_empty(self):
        """리스트 필드 초기화"""
        state = create_initial_state(query="테스트")
        assert state["rag_results"] == []
        assert state["sources"] == []
        assert state["conversation_history"] == []


class TestWorkflowErrors:
    """워크플로우 예외 테스트"""

    def test_base_error(self):
        """기본 예외"""
        error = WorkflowError("테스트 에러")
        assert error.message == "테스트 에러"
        assert error.node is None

    def test_query_analysis_error(self):
        """쿼리 분석 예외"""
        error = QueryAnalysisError("분석 실패", query="테스트")
        assert error.node == "analyzer"
        assert error.query == "테스트"

    def test_sql_execution_error(self):
        """SQL 실행 예외"""
        error = SQLExecutionError("실행 실패", sql="SELECT * FROM test")
        assert error.node == "sql_executor"
        assert error.sql == "SELECT * FROM test"

    def test_rag_retrieval_error(self):
        """RAG 검색 예외"""
        error = RAGRetrievalError("검색 실패", strategy="hybrid")
        assert error.node == "rag_retriever"
        assert error.strategy == "hybrid"

    def test_empty_query_error(self):
        """빈 쿼리 예외"""
        error = EmptyQueryError()
        assert "비어있습니다" in error.message
        assert error.details["error_code"] == "EMPTY_QUERY"

    def test_error_to_dict(self):
        """예외 딕셔너리 변환"""
        error = WorkflowError("테스트", node="test_node", details={"key": "value"})
        d = error.to_dict()
        assert d["error_type"] == "WorkflowError"
        assert d["message"] == "테스트"
        assert d["node"] == "test_node"
        assert d["details"]["key"] == "value"


class TestAnalyzerNode:
    """Query Analyzer 노드 테스트"""

    def test_greeting_detection(self):
        """인사말 감지 (LLM 없이)"""
        from workflow.nodes.analyzer import _check_simple_query

        # 인사말 -> simple로 분류
        result = _check_simple_query("안녕하세요")
        assert result is not None
        assert result["query_type"] == "simple"

        # 도움말 -> simple로 분류
        result = _check_simple_query("도움말")
        assert result is not None
        assert result["query_type"] == "simple"

        # 일반 질문 -> None (LLM 필요)
        result = _check_simple_query("특허 10개 알려줘")
        assert result is None

    def test_empty_query_handling(self):
        """빈 쿼리 처리"""
        from workflow.nodes.analyzer import analyze_query

        state = create_initial_state(query="")
        result = analyze_query(state)

        assert result["query_type"] == "simple"
        assert "error" in result or result["query_intent"] != ""

    @patch('workflow.nodes.analyzer.get_llm_client')
    def test_llm_failure_fallback(self, mock_llm_getter):
        """LLM 실패 시 폴백"""
        from workflow.nodes.analyzer import analyze_query

        mock_llm = Mock()
        mock_llm.generate.side_effect = Exception("LLM 연결 실패")
        mock_llm_getter.return_value = mock_llm

        state = create_initial_state(query="테스트 질문")
        result = analyze_query(state)

        # 에러가 있어도 상태는 반환되어야 함
        assert "query_type" in result


class TestRAGRetrieverNode:
    """RAG Retriever 노드 테스트"""

    def test_strategy_selection_vector(self):
        """벡터(의미) 검색 전략 선택"""
        from workflow.nodes.rag_retriever import _select_search_strategy
        from graph.graph_rag import SearchStrategy

        state = create_initial_state(query="인공지능 연구 동향")
        state["query_intent"] = "인공지능 연구 동향 파악"

        strategy = _select_search_strategy(state)
        assert strategy == SearchStrategy.VECTOR_ONLY

    def test_strategy_selection_graph_enhanced(self):
        """그래프 확장 검색 전략 선택"""
        from workflow.nodes.rag_retriever import _select_search_strategy
        from graph.graph_rag import SearchStrategy

        state = create_initial_state(query="과제번호 검색")
        state["query_intent"] = "특정 과제 번호로 검색"

        strategy = _select_search_strategy(state)
        assert strategy == SearchStrategy.GRAPH_ENHANCED

    def test_strategy_selection_graph_only(self):
        """그래프 탐색 전략 선택"""
        from workflow.nodes.rag_retriever import _select_search_strategy
        from graph.graph_rag import SearchStrategy

        state = create_initial_state(query="연구 네트워크")
        state["query_intent"] = "연구자 간 협력 네트워크 분석"

        strategy = _select_search_strategy(state)
        assert strategy == SearchStrategy.GRAPH_ONLY

    def test_empty_query_returns_empty(self):
        """빈 쿼리는 빈 결과 반환"""
        from workflow.nodes.rag_retriever import retrieve_rag

        state = create_initial_state(query="  ")
        result = retrieve_rag(state)

        assert result["rag_results"] == []
        assert result["search_strategy"] == "none"


class TestMergerNode:
    """Merger 노드 테스트"""

    def test_deduplicate_sources(self):
        """소스 중복 제거"""
        from workflow.nodes.merger import _deduplicate_sources

        sources = [
            {"type": "sql", "sql": "SELECT * FROM test"},
            {"type": "sql", "sql": "SELECT * FROM test"},  # 중복
            {"type": "rag", "node_id": "node1"},
            {"type": "rag", "node_id": "node1"},  # 중복
            {"type": "rag", "node_id": "node2"},
        ]

        unique = _deduplicate_sources(sources)
        assert len(unique) == 3

    def test_hybrid_merge(self):
        """하이브리드 병합"""
        from workflow.nodes.merger import merge_results

        state = create_initial_state(query="테스트")
        state["query_type"] = "hybrid"
        state["sql_result"] = SQLQueryResult(success=True, row_count=5)
        state["rag_results"] = [SearchResult("id1", "name1", "project", 0.9)]
        state["sources"] = []

        result = merge_results(state)
        assert "sources" in result


class TestGeneratorNode:
    """Generator 노드 테스트"""

    @patch('workflow.nodes.generator.get_llm_client')
    def test_simple_response(self, mock_llm_getter):
        """간단한 응답 생성"""
        from workflow.nodes.generator import generate_response

        mock_llm = Mock()
        mock_llm.generate.return_value = "안녕하세요! 무엇을 도와드릴까요?"
        mock_llm_getter.return_value = mock_llm

        state = create_initial_state(query="안녕하세요")
        state["query_type"] = "simple"

        result = generate_response(state)

        assert "response" in result
        assert len(result["conversation_history"]) == 2  # user + assistant

    @patch('workflow.nodes.generator.get_llm_client')
    def test_context_response(self, mock_llm_getter):
        """컨텍스트 기반 응답 생성"""
        from workflow.nodes.generator import generate_response

        mock_llm = Mock()
        mock_llm.generate.return_value = "검색된 정보를 바탕으로 답변드립니다."
        mock_llm_getter.return_value = mock_llm

        state = create_initial_state(query="인공지능 특허")
        state["query_type"] = "rag"
        state["rag_results"] = [SearchResult("id1", "AI 특허", "patent", 0.9)]

        result = generate_response(state)

        assert "response" in result
        # 컨텍스트 기반 응답은 더 긴 max_tokens 사용
        call_args = mock_llm.generate.call_args
        assert call_args.kwargs.get("max_tokens", 0) > 500


class TestParallelExecution:
    """병렬 실행 테스트"""

    @patch('workflow.graph.execute_sql')
    @patch('workflow.graph.retrieve_rag')
    def test_parallel_both_success(self, mock_rag, mock_sql):
        """양쪽 모두 성공"""
        from workflow.graph import _parallel_execution

        mock_sql.return_value = {
            "sql_result": SQLQueryResult(success=True, row_count=5),
            "generated_sql": "SELECT * FROM test",
            "sources": [{"type": "sql"}]
        }
        mock_rag.return_value = {
            "rag_results": [SearchResult("id1", "name1", "project", 0.9)],
            "search_strategy": "hybrid",
            "sources": [{"type": "rag"}]
        }

        state = create_initial_state(query="테스트")
        result = _parallel_execution(state)

        assert result["sql_result"] is not None
        assert len(result["rag_results"]) > 0
        assert len(result["sources"]) == 2

    @patch('workflow.graph.execute_sql')
    @patch('workflow.graph.retrieve_rag')
    def test_parallel_sql_fails(self, mock_rag, mock_sql):
        """SQL 실패 시에도 RAG 결과 반환"""
        from workflow.graph import _parallel_execution

        mock_sql.side_effect = Exception("SQL 실패")
        mock_rag.return_value = {
            "rag_results": [SearchResult("id1", "name1", "project", 0.9)],
            "search_strategy": "hybrid",
            "sources": [{"type": "rag"}]
        }

        state = create_initial_state(query="테스트")
        result = _parallel_execution(state)

        assert len(result["rag_results"]) > 0
        assert "error" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
