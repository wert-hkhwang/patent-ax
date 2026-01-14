"""
E2E (End-to-End) 통합 테스트
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from workflow.graph import run_workflow, get_workflow_agent, create_workflow


class TestWorkflowCreation:
    """워크플로우 생성 테스트"""

    def test_create_workflow(self):
        """워크플로우 생성 테스트"""
        workflow = create_workflow()
        assert workflow is not None

    def test_get_workflow_agent(self):
        """에이전트 싱글톤 테스트"""
        agent = get_workflow_agent()
        assert agent is not None
        assert hasattr(agent, "chat")
        assert hasattr(agent, "clear_history")


class TestSimpleQueries:
    """간단한 쿼리 E2E 테스트"""

    def test_greeting(self):
        """인사말 테스트"""
        result = run_workflow(query="안녕하세요")

        assert result is not None
        assert result.get("query_type") == "simple"
        assert result.get("response") is not None
        assert len(result.get("response", "")) > 0

    def test_help_request(self):
        """도움말 요청 테스트"""
        result = run_workflow(query="도움말")

        assert result is not None
        assert result.get("query_type") == "simple"


class TestSQLQueries:
    """SQL 쿼리 E2E 테스트"""

    @pytest.mark.slow
    def test_sql_query_patents(self):
        """특허 조회 테스트"""
        result = run_workflow(query="특허 5개 알려줘")

        assert result is not None
        # query_type이 sql이거나 분석 결과에 따라 다를 수 있음
        assert result.get("response") is not None

    @pytest.mark.slow
    def test_sql_query_projects(self):
        """과제 조회 테스트"""
        result = run_workflow(query="연구과제 목록 3개")

        assert result is not None
        assert result.get("response") is not None


class TestRAGQueries:
    """RAG 쿼리 E2E 테스트"""

    @pytest.mark.slow
    def test_rag_query_trend(self):
        """연구 동향 쿼리 테스트"""
        result = run_workflow(query="인공지능 연구 동향에 대해 알려줘")

        assert result is not None
        assert result.get("response") is not None


class TestHybridQueries:
    """하이브리드 쿼리 E2E 테스트"""

    @pytest.mark.slow
    def test_hybrid_query(self):
        """하이브리드 쿼리 테스트"""
        result = run_workflow(query="AI 관련 특허와 연구과제를 연결해서 설명해줘")

        assert result is not None
        assert result.get("response") is not None


class TestWorkflowAgent:
    """워크플로우 에이전트 클래스 테스트"""

    def test_agent_chat(self):
        """에이전트 chat 메서드 테스트"""
        agent = get_workflow_agent()
        agent.clear_history()

        result = agent.chat(query="안녕하세요")

        assert result is not None
        assert "response" in result
        assert "query_type" in result

    def test_agent_history(self):
        """에이전트 대화 기록 테스트"""
        agent = get_workflow_agent()
        agent.clear_history()

        agent.chat(query="안녕")

        history = agent.get_history()
        assert len(history) > 0

    def test_agent_clear_history(self):
        """에이전트 기록 초기화 테스트"""
        agent = get_workflow_agent()
        agent.chat(query="테스트")
        agent.clear_history()

        history = agent.get_history()
        assert len(history) == 0


class TestErrorHandling:
    """에러 처리 테스트"""

    def test_empty_query(self):
        """빈 쿼리 처리 테스트"""
        result = run_workflow(query="")

        assert result is not None
        # 에러가 있거나 기본 응답이 있어야 함
        assert result.get("response") is not None or result.get("error") is not None

    def test_very_long_query(self):
        """매우 긴 쿼리 처리 테스트"""
        long_query = "테스트 " * 1000
        result = run_workflow(query=long_query)

        assert result is not None


class TestPerformance:
    """성능 테스트"""

    def test_simple_query_performance(self):
        """간단한 쿼리 응답 시간 테스트"""
        result = run_workflow(query="안녕")

        # 간단한 쿼리는 10초 이내 응답
        assert result.get("elapsed_ms", float("inf")) < 10000


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
