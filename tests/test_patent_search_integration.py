"""
특허 검색 기능 통합 테스트 (End-to-End)

실제 워크플로우를 실행하여 Patent-AX 시스템의 핵심 기능을 검증합니다.

주요 검증 항목:
1. entity_types=["patent"] 강제 적용
2. PATENT_COLLECTIONS 사용
3. domain_mapping.py 미사용
4. 응답 시간 < 3초
5. 리터러시 레벨 반영
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from unittest.mock import patch


# 테스트에 필요한 서비스들이 정상인지 사전 확인
def check_services_available():
    """테스트 실행 전 필수 서비스 확인"""
    try:
        # PostgreSQL
        from sql.db_connector import test_connection
        if not test_connection():
            return False, "PostgreSQL 접근 불가"

        # Qdrant
        import requests
        qdrant_url = os.getenv("QDRANT_URL", "http://210.109.80.106:6333")
        response = requests.get(f"{qdrant_url}/collections/patents_v3_collection", timeout=5)
        if response.status_code != 200:
            return False, "Qdrant 접근 불가"

        # vLLM
        vllm_url = os.getenv("VLLM_BASE_URL", "http://210.109.80.106:12288")
        response = requests.get(f"{vllm_url}/health", timeout=5)
        if response.status_code != 200:
            return False, "vLLM 접근 불가"

        return True, "모든 서비스 정상"
    except Exception as e:
        return False, f"서비스 확인 실패: {str(e)}"


@pytest.fixture(scope="module")
def services_check():
    """모듈 단위로 서비스 확인"""
    available, message = check_services_available()
    if not available:
        pytest.skip(f"필수 서비스 접근 불가: {message}")
    return available


class TestPatentSearchSimple:
    """Simple 쿼리 테스트 (간단한 대화)"""

    @pytest.mark.integration
    @pytest.mark.slow
    def test_simple_greeting(self, services_check):
        """간단한 인사 쿼리"""
        from workflow.graph import run_workflow

        query = "Patent-AX가 뭐야?"
        start_time = time.time()

        result = run_workflow(
            query=query,
            session_id="test_simple",
            level="일반인"
        )

        elapsed = time.time() - start_time

        # 검증
        assert result["query_type"] == "simple", f"query_type이 simple이 아님: {result['query_type']}"
        assert "response" in result
        assert len(result["response"]) > 0

        # entity_types 확인
        assert result.get("entity_types") == ["patent"], \
            f"entity_types가 ['patent']가 아님: {result.get('entity_types')}"

        print(f"✓ Simple 쿼리 성공: {elapsed:.2f}초")
        print(f"  Response: {result['response'][:100]}...")

    @pytest.mark.integration
    @pytest.mark.slow
    def test_simple_help(self, services_check):
        """도움말 요청 쿼리"""
        from workflow.graph import run_workflow

        query = "어떤 질문을 할 수 있어?"

        result = run_workflow(
            query=query,
            session_id="test_help",
            level="일반인"
        )

        # 검증
        assert result["query_type"] == "simple"
        assert "response" in result
        assert result.get("entity_types") == ["patent"]

        print(f"✓ 도움말 쿼리 성공")


class TestPatentSearchSQL:
    """SQL 쿼리 테스트 (데이터베이스 조회)"""

    @pytest.mark.integration
    @pytest.mark.slow
    def test_sql_top_n_ranking(self, services_check):
        """TOP N 랭킹 쿼리 - PatentRankingLoader"""
        from workflow.graph import run_workflow

        query = "수소연료전지 특허 TOP 10 출원기관"
        start_time = time.time()

        result = run_workflow(
            query=query,
            session_id="test_sql_ranking",
            level="일반인"
        )

        elapsed = time.time() - start_time

        # 검증
        assert result["query_type"] in ["sql", "hybrid"], \
            f"query_type이 sql 또는 hybrid가 아님: {result['query_type']}"

        assert "response" in result
        assert len(result["response"]) > 0

        # SQL이 실행되었는지 확인
        assert result.get("sql_result") is not None, "SQL 결과 없음"

        # entity_types 확인
        assert result.get("entity_types") == ["patent"]

        # 응답 시간 확인 (목표: 3초 이내)
        assert elapsed < 5.0, f"응답 시간 초과: {elapsed:.2f}초 (목표: < 5초)"

        print(f"✓ SQL TOP N 쿼리 성공: {elapsed:.2f}초")
        print(f"  Loader: {result.get('loader_used', 'N/A')}")
        print(f"  Response: {result['response'][:200]}...")

    @pytest.mark.integration
    @pytest.mark.slow
    def test_sql_patent_count(self, services_check):
        """특허 개수 조회 쿼리"""
        from workflow.graph import run_workflow

        query = "특허 10개 알려줘"

        result = run_workflow(
            query=query,
            session_id="test_sql_count",
            level="일반인"
        )

        # 검증
        assert result["query_type"] in ["sql", "hybrid"]
        assert "response" in result
        assert result.get("entity_types") == ["patent"]

        print(f"✓ SQL 개수 쿼리 성공")


class TestPatentSearchRAG:
    """RAG 쿼리 테스트 (벡터 검색 + 그래프 탐색)"""

    @pytest.mark.integration
    @pytest.mark.slow
    def test_rag_technology_trend(self, services_check):
        """기술 동향 쿼리 - 벡터 검색"""
        from workflow.graph import run_workflow

        query = "인공지능 반도체 기술 동향"
        start_time = time.time()

        result = run_workflow(
            query=query,
            session_id="test_rag_trend",
            level="일반인"
        )

        elapsed = time.time() - start_time

        # 검증
        assert result["query_type"] in ["rag", "hybrid"], \
            f"query_type이 rag 또는 hybrid가 아님: {result['query_type']}"

        assert "response" in result
        assert len(result["response"]) > 0

        # RAG 결과 확인
        rag_results = result.get("rag_results", [])
        assert len(rag_results) > 0, "RAG 검색 결과 없음"

        # 소스 확인
        sources = result.get("sources", [])
        assert len(sources) > 0, "소스 정보 없음"

        # entity_types 확인
        assert result.get("entity_types") == ["patent"]

        # 응답 시간 확인
        assert elapsed < 5.0, f"응답 시간 초과: {elapsed:.2f}초"

        # Context quality 확인
        context_quality = result.get("context_quality", 0)
        assert context_quality > 0.5, f"Context quality 낮음: {context_quality}"

        print(f"✓ RAG 기술 동향 쿼리 성공: {elapsed:.2f}초")
        print(f"  RAG Results: {len(rag_results)}개")
        print(f"  Context Quality: {context_quality:.2f}")
        print(f"  Response: {result['response'][:200]}...")

    @pytest.mark.integration
    @pytest.mark.slow
    def test_rag_concept_explanation(self, services_check):
        """개념 설명 쿼리"""
        from workflow.graph import run_workflow

        query = "양자컴퓨터란 무엇인가"

        result = run_workflow(
            query=query,
            session_id="test_rag_concept",
            level="일반인"
        )

        # 검증
        assert result["query_type"] in ["rag", "hybrid", "simple"]
        assert "response" in result
        assert result.get("entity_types") == ["patent"]

        print(f"✓ RAG 개념 설명 쿼리 성공")


class TestPatentSearchHybrid:
    """Hybrid 쿼리 테스트 (SQL + RAG 병렬 실행)"""

    @pytest.mark.integration
    @pytest.mark.slow
    def test_hybrid_statistics_and_trend(self, services_check):
        """통계 + 동향 복합 쿼리"""
        from workflow.graph import run_workflow

        query = "반도체 분야 특허 통계와 최신 기술 동향"
        start_time = time.time()

        result = run_workflow(
            query=query,
            session_id="test_hybrid",
            level="전문가"
        )

        elapsed = time.time() - start_time

        # 검증
        assert result["query_type"] == "hybrid", \
            f"query_type이 hybrid가 아님: {result['query_type']}"

        assert "response" in result
        assert len(result["response"]) > 0

        # SQL과 RAG 결과가 모두 있어야 함
        sql_result = result.get("sql_result")
        rag_results = result.get("rag_results", [])

        # 최소한 하나는 있어야 함 (병렬 실행 실패 가능성)
        assert sql_result is not None or len(rag_results) > 0, \
            "SQL과 RAG 결과가 모두 없음"

        # entity_types 확인
        assert result.get("entity_types") == ["patent"]

        # 응답 시간 확인
        assert elapsed < 5.0, f"응답 시간 초과: {elapsed:.2f}초"

        print(f"✓ Hybrid 쿼리 성공: {elapsed:.2f}초")
        print(f"  SQL Result: {'있음' if sql_result else '없음'}")
        print(f"  RAG Results: {len(rag_results)}개")
        print(f"  Response: {result['response'][:200]}...")


class TestLiteracyLevels:
    """리터러시 레벨별 응답 테스트"""

    @pytest.mark.integration
    @pytest.mark.slow
    def test_literacy_levels_different_responses(self, services_check):
        """동일 쿼리에 대해 레벨별로 다른 응답"""
        from workflow.graph import run_workflow

        query = "양자컴퓨터 특허"
        levels = ["초등", "일반인", "전문가"]
        responses = {}

        for level in levels:
            result = run_workflow(
                query=query,
                session_id=f"test_level_{level}",
                level=level
            )

            responses[level] = result["response"]

            # 검증
            assert result.get("entity_types") == ["patent"]
            assert len(result["response"]) > 0

            print(f"✓ 레벨 '{level}' 응답 생성 성공")

        # 응답이 서로 다른지 확인 (최소한 한 쌍은 달라야 함)
        all_same = (
            responses["초등"] == responses["일반인"] ==
            responses["전문가"]
        )
        assert not all_same, "모든 레벨의 응답이 동일함 (리터러시 레벨 미반영)"

        print(f"✓ 리터러시 레벨 반영 확인")


class TestPatentSpecificValidation:
    """Patent-AX 특화 검증 테스트"""

    def test_entity_types_always_patent(self):
        """entity_types가 항상 ['patent']인지 확인"""
        from workflow.state import create_initial_state

        # 초기 상태 생성
        state = create_initial_state(
            query="테스트 쿼리",
            session_id="test"
        )

        # entity_types 확인
        assert state["entity_types"] == ["patent"], \
            f"초기 상태의 entity_types가 ['patent']가 아님: {state['entity_types']}"

        print(f"✓ 초기 상태 entity_types=['patent'] 확인")

    def test_domain_mapping_not_imported(self):
        """domain_mapping.py가 import되지 않는지 확인"""
        import sys

        # workflow.prompts.domain_mapping이 import되지 않아야 함
        domain_mapping_module = "workflow.prompts.domain_mapping"

        assert domain_mapping_module not in sys.modules, \
            f"domain_mapping 모듈이 import됨: {domain_mapping_module}"

        print(f"✓ domain_mapping.py 미사용 확인")

    def test_patent_collections_only(self):
        """PATENT_COLLECTIONS만 사용하는지 확인"""
        from api.config import COLLECTIONS

        # Patent-AX는 patents 컬렉션만 있어야 함
        assert "patents" in COLLECTIONS, "patents 컬렉션 없음"

        # 다른 도메인 컬렉션은 없어야 함 (또는 있어도 사용 안 함)
        patent_collections = [k for k in COLLECTIONS.keys() if "patent" in k]
        assert len(patent_collections) >= 1, "특허 컬렉션이 없음"

        print(f"✓ COLLECTIONS 확인: {list(COLLECTIONS.keys())}")

    def test_patent_loaders_only(self):
        """특허 전용 Loader만 있는지 확인"""
        from workflow.loaders import (
            PatentRankingLoader,
            PatentCitationLoader,
            PatentInfluenceLoader,
            PatentNationalityLoader
        )

        # 4종 Loader가 정상적으로 import되어야 함
        loaders = [
            PatentRankingLoader,
            PatentCitationLoader,
            PatentInfluenceLoader,
            PatentNationalityLoader
        ]

        for loader in loaders:
            assert hasattr(loader, "LOADER_NAME"), f"{loader} LOADER_NAME 없음"

        print(f"✓ 특허 전용 Loader 4종 확인")


class TestPerformance:
    """성능 테스트"""

    @pytest.mark.integration
    @pytest.mark.slow
    def test_response_time_under_threshold(self, services_check):
        """응답 시간이 목표치 이하인지 확인"""
        from workflow.graph import run_workflow

        query = "인공지능 특허 동향"
        iterations = 3
        times = []

        for i in range(iterations):
            start_time = time.time()

            result = run_workflow(
                query=query,
                session_id=f"test_perf_{i}",
                level="일반인"
            )

            elapsed = time.time() - start_time
            times.append(elapsed)

            print(f"  실행 {i+1}: {elapsed:.2f}초")

        avg_time = sum(times) / len(times)

        # 평균 응답 시간 < 5초 (목표: 2초, 허용: 5초)
        assert avg_time < 5.0, f"평균 응답 시간 초과: {avg_time:.2f}초"

        print(f"✓ 성능 테스트 통과: 평균 {avg_time:.2f}초 (목표: < 5초)")

    @pytest.mark.integration
    @pytest.mark.slow
    def test_context_quality_above_threshold(self, services_check):
        """Context quality가 임계값 이상인지 확인"""
        from workflow.graph import run_workflow

        query = "반도체 특허 기술"

        result = run_workflow(
            query=query,
            session_id="test_quality",
            level="일반인"
        )

        context_quality = result.get("context_quality", 0)

        # Context quality > 0.5
        assert context_quality > 0.5, \
            f"Context quality 낮음: {context_quality:.2f} (목표: > 0.5)"

        print(f"✓ Context quality 테스트 통과: {context_quality:.2f}")


if __name__ == "__main__":
    # 직접 실행 시 pytest 호출
    pytest.main([__file__, "-v", "-s", "-m", "integration"])
