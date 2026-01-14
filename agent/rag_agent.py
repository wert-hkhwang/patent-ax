"""
RAG 에이전트
- Graph RAG 검색 + LLM 응답 생성 파이프라인
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from typing import Dict, List, Optional, Generator, Any
from dataclasses import dataclass

from llm.llm_client import LLMClient, get_llm_client, LLMConfig
from graph.graph_rag import GraphRAG, SearchStrategy, get_graph_rag, initialize_graph_rag
from agent.prompts import build_rag_prompt, build_simple_prompt, format_search_results

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    """채팅 메시지"""
    role: str  # "user", "assistant", "system"
    content: str


@dataclass
class AgentResponse:
    """에이전트 응답"""
    answer: str
    sources: List[Dict]
    search_strategy: str
    elapsed_ms: float


class RAGAgent:
    """RAG 에이전트 - Graph RAG + LLM 통합"""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        graph_rag: Optional[GraphRAG] = None,
        search_limit: int = 10,
        include_context: bool = True
    ):
        self.llm = llm_client or get_llm_client()
        self.graph_rag = graph_rag
        self.search_limit = search_limit
        self.include_context = include_context
        self.conversation_history: List[ChatMessage] = []

    def initialize(self, graph_id: str = "713365bb", project_limit: int = 500):
        """Graph RAG 초기화"""
        if not self.graph_rag:
            self.graph_rag = initialize_graph_rag(
                graph_id=graph_id,
                project_limit=project_limit
            )
        return self

    def chat(
        self,
        query: str,
        search_strategy: str = "hybrid",
        max_tokens: int = 2048,
        temperature: float = 0.7,
        stream: bool = False,
        use_history: bool = True
    ) -> AgentResponse:
        """RAG 기반 채팅

        Args:
            query: 사용자 질문
            search_strategy: 검색 전략 (hybrid, graph_only, vector_only, graph_enhanced)
            max_tokens: 최대 응답 토큰
            temperature: 생성 온도
            stream: 스트리밍 여부
            use_history: 대화 기록 사용 여부

        Returns:
            AgentResponse 또는 스트리밍 Generator
        """
        import time
        start_time = time.time()

        # Graph RAG 초기화 확인
        if not self.graph_rag:
            self.initialize()

        # 검색 전략 매핑
        strategy_map = {
            "hybrid": SearchStrategy.HYBRID,
            "graph_only": SearchStrategy.GRAPH_ONLY,
            "vector_only": SearchStrategy.VECTOR_ONLY,
            "graph_enhanced": SearchStrategy.GRAPH_ENHANCED
        }
        strategy = strategy_map.get(search_strategy, SearchStrategy.HYBRID)

        # Graph RAG 검색
        search_results = self.graph_rag.search(
            query=query,
            strategy=strategy,
            limit=self.search_limit,
            include_context=self.include_context
        )

        # 프롬프트 구성
        if search_results:
            system_prompt, user_prompt = build_rag_prompt(
                query=query,
                search_results=search_results,
                include_related=self.include_context
            )
        else:
            system_prompt, user_prompt = build_simple_prompt(query)

        # 메시지 구성
        messages = [{"role": "system", "content": system_prompt}]

        # 대화 기록 추가
        if use_history and self.conversation_history:
            for msg in self.conversation_history[-6:]:  # 최근 6개 메시지
                messages.append({"role": msg.role, "content": msg.content})

        messages.append({"role": "user", "content": user_prompt})

        # LLM 응답 생성
        if stream:
            return self._stream_response(
                messages=messages,
                search_results=search_results,
                search_strategy=search_strategy,
                max_tokens=max_tokens,
                temperature=temperature,
                start_time=start_time
            )
        else:
            response = self.llm.chat(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )

            answer = response.get("choices", [{}])[0].get("message", {}).get("content", "")

            # 대화 기록 업데이트
            self.conversation_history.append(ChatMessage(role="user", content=query))
            self.conversation_history.append(ChatMessage(role="assistant", content=answer))

            elapsed_ms = (time.time() - start_time) * 1000

            # 소스 정보 추출
            sources = self._extract_sources(search_results)

            return AgentResponse(
                answer=answer,
                sources=sources,
                search_strategy=search_strategy,
                elapsed_ms=round(elapsed_ms, 2)
            )

    def _stream_response(
        self,
        messages: List[Dict],
        search_results: list,
        search_strategy: str,
        max_tokens: int,
        temperature: float,
        start_time: float
    ) -> Generator[Dict, None, None]:
        """스트리밍 응답 생성"""
        import time

        full_response = ""
        for chunk in self.llm.chat_stream(messages, max_tokens, temperature):
            full_response += chunk
            yield {"type": "content", "content": chunk}

        # 완료 후 메타데이터
        elapsed_ms = (time.time() - start_time) * 1000
        sources = self._extract_sources(search_results)

        # 대화 기록 업데이트
        self.conversation_history.append(
            ChatMessage(role="user", content=messages[-1]["content"])
        )
        self.conversation_history.append(
            ChatMessage(role="assistant", content=full_response)
        )

        yield {
            "type": "done",
            "sources": sources,
            "search_strategy": search_strategy,
            "elapsed_ms": round(elapsed_ms, 2)
        }

    def _extract_sources(self, search_results: list) -> List[Dict]:
        """검색 결과에서 소스 정보 추출"""
        sources = []
        for r in search_results[:5]:
            sources.append({
                "node_id": getattr(r, 'node_id', ''),
                "name": getattr(r, 'name', ''),
                "entity_type": getattr(r, 'entity_type', ''),
                "score": getattr(r, 'score', 0.0)
            })
        return sources

    def clear_history(self):
        """대화 기록 초기화"""
        self.conversation_history = []

    def get_history(self) -> List[Dict]:
        """대화 기록 반환"""
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self.conversation_history
        ]

    def simple_chat(
        self,
        query: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.7
    ) -> str:
        """RAG 없이 단순 채팅"""
        return self.llm.generate(
            prompt=query,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature
        )


# 싱글톤 인스턴스
_rag_agent: Optional[RAGAgent] = None


def get_rag_agent() -> RAGAgent:
    """RAG 에이전트 싱글톤"""
    global _rag_agent
    if _rag_agent is None:
        _rag_agent = RAGAgent()
    return _rag_agent


def initialize_rag_agent(
    graph_id: str = "713365bb",
    project_limit: int = 500,
    search_limit: int = 10
) -> RAGAgent:
    """RAG 에이전트 초기화"""
    global _rag_agent
    _rag_agent = RAGAgent(search_limit=search_limit)
    _rag_agent.initialize(graph_id=graph_id, project_limit=project_limit)
    return _rag_agent


if __name__ == "__main__":
    print("RAG 에이전트 테스트")

    try:
        # 초기화
        print("\n1. 초기화 중...")
        agent = initialize_rag_agent(graph_id="713365bb", project_limit=100)
        print("   완료")

        # 테스트 질문
        query = "인공지능 관련 연구과제에 대해 알려주세요"
        print(f"\n2. 질문: {query}")

        # RAG 채팅
        print("\n3. RAG 응답 생성 중...")
        response = agent.chat(query, search_strategy="hybrid", max_tokens=500)

        print(f"\n4. 응답:")
        print(f"   {response.answer[:500]}...")
        print(f"\n5. 소스 ({len(response.sources)}개):")
        for src in response.sources[:3]:
            print(f"   - {src['name']} ({src['entity_type']}): {src['score']:.4f}")
        print(f"\n6. 처리 시간: {response.elapsed_ms:.2f}ms")

    except Exception as e:
        print(f"오류: {e}")
        import traceback
        traceback.print_exc()
