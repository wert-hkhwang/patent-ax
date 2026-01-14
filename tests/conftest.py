"""
pytest 공통 fixture 정의
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from typing import Generator


@pytest.fixture(scope="session")
def workflow():
    """컴파일된 워크플로우 반환"""
    from workflow.graph import create_workflow
    return create_workflow()


@pytest.fixture(scope="session")
def workflow_agent():
    """워크플로우 에이전트 반환"""
    from workflow.graph import get_workflow_agent
    agent = get_workflow_agent()
    agent.clear_history()
    return agent


@pytest.fixture
def sample_queries():
    """테스트용 샘플 쿼리"""
    return {
        "simple": ["안녕하세요", "도움말", "hello"],
        "sql": ["특허 10개 알려줘", "예산이 큰 과제 5개", "서울에 있는 연구기관"],
        "rag": ["인공지능 연구 동향", "블록체인 기술이란", "최신 연구 분야"],
        "hybrid": ["인공지능 특허의 기술 동향", "AI 관련 과제와 특허 연결"]
    }


@pytest.fixture
def mock_llm_response(monkeypatch):
    """LLM 응답 모킹"""
    def mock_generate(*args, **kwargs):
        return '{"query_type": "rag", "intent": "테스트", "entity_types": [], "keywords": [], "related_tables": []}'

    def mock_chat(*args, **kwargs):
        return {
            "choices": [{
                "message": {
                    "content": "테스트 응답입니다."
                }
            }]
        }

    # LLMClient 모킹
    from llm.llm_client import LLMClient
    monkeypatch.setattr(LLMClient, "generate", mock_generate)
    monkeypatch.setattr(LLMClient, "chat", mock_chat)


@pytest.fixture
def mock_sql_agent(monkeypatch):
    """SQL Agent 모킹"""
    from sql.sql_agent import SQLAgentResponse, SQLResult

    def mock_query(*args, **kwargs):
        return SQLAgentResponse(
            question=kwargs.get("question", "테스트"),
            generated_sql="SELECT 1",
            result=SQLResult(
                success=True,
                columns=["id", "name"],
                rows=[[1, "테스트"]],
                row_count=1
            ),
            interpretation="테스트 결과",
            related_tables=["test_table"]
        )

    from sql.sql_agent import SQLAgent
    monkeypatch.setattr(SQLAgent, "query", mock_query)


@pytest.fixture
def mock_graph_rag(monkeypatch):
    """Graph RAG 모킹"""
    class MockSearchResult:
        def __init__(self):
            self.node_id = "test_node"
            self.name = "테스트 노드"
            self.entity_type = "project"
            self.score = 0.95
            self.content = "테스트 내용"
            self.metadata = {}

    def mock_search(*args, **kwargs):
        return [MockSearchResult()]

    from graph.graph_rag import GraphRAG
    monkeypatch.setattr(GraphRAG, "search", mock_search)
