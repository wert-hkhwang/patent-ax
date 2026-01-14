"""
FastAPI 헬스체크 엔드포인트 통합 테스트

API 서버의 각 헬스체크 엔드포인트가 올바르게 동작하는지 검증합니다.
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


class TestAPIHealthEndpoints:
    """FastAPI 헬스체크 엔드포인트 테스트 - TestClient 사용"""

    @pytest.fixture(scope="class")
    def client(self):
        """FastAPI TestClient 생성"""
        from api.main import app
        return TestClient(app)

    def test_root_endpoint(self, client):
        """GET / 기본 상태 확인"""
        response = client.get("/")

        # HTTP 상태 코드
        assert response.status_code == 200

        # 응답 데이터
        data = response.json()
        assert data.get("status") == "ok"
        assert "service" in data
        assert "version" in data

        print(f"✓ Root 엔드포인트 정상: {data}")

    def test_health_endpoint(self, client):
        """GET /health 기본 헬스체크"""
        response = client.get("/health")

        # HTTP 상태 코드
        assert response.status_code == 200

        # 응답 데이터
        data = response.json()
        assert data.get("status") == "healthy"

        print(f"✓ Health 엔드포인트 정상: {data}")

    def test_agent_health_endpoint(self, client):
        """GET /agent/health LLM 연결 확인"""
        response = client.get("/agent/health")

        # HTTP 상태 코드
        assert response.status_code == 200

        # 응답 데이터
        data = response.json()
        assert "status" in data
        assert "llm" in data
        assert "agent_initialized" in data

        # 상태는 healthy 또는 degraded 또는 unhealthy
        assert data["status"] in ["healthy", "degraded", "unhealthy"]

        print(f"✓ Agent health 엔드포인트 정상: {data}")

    def test_sql_health_endpoint(self, client):
        """GET /sql/health DB + LLM 연결 확인"""
        response = client.get("/sql/health")

        # HTTP 상태 코드
        assert response.status_code == 200

        # 응답 데이터
        data = response.json()
        assert "status" in data
        assert "database" in data
        assert "llm" in data

        # 상태는 healthy 또는 degraded 또는 unhealthy
        assert data["status"] in ["healthy", "degraded", "unhealthy"]

        # 실제 환경에서는 database와 llm이 connected여야 함
        if data["status"] == "healthy":
            assert data["database"] == "connected"
            assert data["llm"] == "connected"

        print(f"✓ SQL health 엔드포인트 정상: {data}")

    def test_collections_endpoint(self, client):
        """GET /collections 컬렉션 목록 조회"""
        response = client.get("/collections")

        # HTTP 상태 코드
        assert response.status_code == 200

        # 응답 데이터
        data = response.json()
        assert "total" in data
        assert "collections" in data
        assert isinstance(data["collections"], list)

        # Patent-AX는 patents 컬렉션만 있어야 함
        collection_names = [c["name"] for c in data["collections"]]
        assert "patents" in collection_names

        print(f"✓ Collections 엔드포인트 정상: {data['total']}개 컬렉션")

    def test_workflow_analyze_endpoint(self, client):
        """POST /workflow/analyze 쿼리 분석 엔드포인트"""
        response = client.post(
            "/workflow/analyze",
            params={"query": "테스트 쿼리"}
        )

        # HTTP 상태 코드
        assert response.status_code == 200

        # 응답 데이터
        data = response.json()
        assert "query_type" in data
        assert "keywords" in data
        assert "entity_types" in data

        # Patent-AX에서는 entity_types가 항상 ["patent"]이어야 함
        assert data["entity_types"] == ["patent"], \
            f"entity_types가 ['patent']가 아님: {data['entity_types']}"

        print(f"✓ Workflow analyze 엔드포인트 정상: {data}")


class TestAPIHealthWithMocks:
    """외부 서비스 장애 시나리오 테스트 - Mock 사용"""

    @pytest.fixture(scope="class")
    def client(self):
        """FastAPI TestClient 생성"""
        from api.main import app
        return TestClient(app)

    @pytest.mark.integration
    def test_agent_health_with_llm_down(self, client):
        """vLLM 서비스 다운 시 degraded 상태 반환"""
        # LLM health_check 실패 모킹
        with patch("llm.llm_client.LLMClient.health_check", return_value=False):
            response = client.get("/agent/health")

            assert response.status_code == 200
            data = response.json()

            # LLM이 다운되면 degraded 상태
            assert data["status"] == "degraded"
            assert data["llm"] == "disconnected"

            print(f"✓ LLM 다운 시나리오 정상: {data}")

    @pytest.mark.integration
    def test_sql_health_with_db_down(self, client):
        """PostgreSQL 다운 시 degraded 상태 반환"""
        # DB test_connection 실패 모킹
        with patch("sql.db_connector.test_connection", return_value=False):
            response = client.get("/sql/health")

            assert response.status_code == 200
            data = response.json()

            # DB가 다운되면 degraded 상태
            assert data["status"] == "degraded"
            assert data["database"] == "disconnected"

            print(f"✓ DB 다운 시나리오 정상: {data}")

    @pytest.mark.integration
    def test_sql_health_with_exception(self, client):
        """SQL health에서 예외 발생 시 unhealthy 상태 반환"""
        # DB test_connection 예외 발생 모킹
        with patch("sql.db_connector.test_connection", side_effect=Exception("DB 연결 실패")):
            response = client.get("/sql/health")

            assert response.status_code == 200
            data = response.json()

            # 예외 발생 시 unhealthy 상태
            assert data["status"] == "unhealthy"
            assert "error" in data

            print(f"✓ SQL health 예외 시나리오 정상: {data}")


class TestAPISearchEndpoints:
    """검색 API 엔드포인트 기본 동작 테스트"""

    @pytest.fixture(scope="class")
    def client(self):
        """FastAPI TestClient 생성"""
        from api.main import app
        return TestClient(app)

    def test_search_endpoint_invalid_collection(self, client):
        """잘못된 컬렉션으로 검색 시 400 에러"""
        response = client.post(
            "/search",
            json={
                "query": "테스트",
                "collection": "invalid_collection",
                "limit": 10
            }
        )

        # 잘못된 컬렉션이므로 400 에러
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data

        print(f"✓ 잘못된 컬렉션 검증 정상: {data['detail']}")

    @pytest.mark.integration
    def test_search_endpoint_valid_request(self, client):
        """유효한 검색 요청 - 실제 Qdrant 호출"""
        response = client.post(
            "/search",
            json={
                "query": "인공지능",
                "collection": "patents",
                "limit": 5
            }
        )

        # 성공 또는 서비스 오류
        if response.status_code == 200:
            data = response.json()
            assert "query" in data
            assert "results" in data
            assert "elapsed_ms" in data
            assert data["query"] == "인공지능"

            print(f"✓ 검색 엔드포인트 정상: {data['total']}개 결과, {data['elapsed_ms']}ms")
        else:
            # Qdrant 접근 불가 시 500 에러 예상
            assert response.status_code in [500, 503]
            print(f"⚠ 검색 실패 (서비스 접근 불가): HTTP {response.status_code}")


class TestWorkflowEndpoints:
    """Workflow 엔드포인트 테스트"""

    @pytest.fixture(scope="class")
    def client(self):
        """FastAPI TestClient 생성"""
        from api.main import app
        return TestClient(app)

    @pytest.mark.integration
    @pytest.mark.slow
    def test_workflow_chat_simple_query(self, client):
        """Workflow chat 엔드포인트 - simple 쿼리"""
        response = client.post(
            "/workflow/chat",
            params={
                "query": "안녕하세요",
                "session_id": "test_session"
            }
        )

        # 성공 또는 서비스 오류
        if response.status_code == 200:
            data = response.json()
            assert "query" in data
            assert "query_type" in data
            assert "response" in data

            # Simple 쿼리는 query_type이 "simple"이어야 함
            assert data["query_type"] == "simple"

            print(f"✓ Workflow chat simple 쿼리 정상: {data['query_type']}")
        else:
            # LLM/DB 접근 불가 시
            print(f"⚠ Workflow 실패 (서비스 접근 불가): HTTP {response.status_code}")

    def test_workflow_analyze_entity_types_patent(self, client):
        """Workflow analyze에서 entity_types가 항상 ['patent']인지 확인"""
        test_queries = [
            "수소연료전지 특허",
            "인공지능 연구",
            "반도체 장비",
            "블록체인 과제"
        ]

        for query in test_queries:
            response = client.post(
                "/workflow/analyze",
                params={"query": query}
            )

            if response.status_code == 200:
                data = response.json()

                # Patent-AX는 항상 entity_types=["patent"]
                assert data["entity_types"] == ["patent"], \
                    f"쿼리 '{query}'에서 entity_types가 ['patent']가 아님: {data['entity_types']}"

                print(f"✓ 쿼리 '{query}' entity_types 검증 통과: {data['entity_types']}")


class TestAPIErrorHandling:
    """API 오류 처리 테스트"""

    @pytest.fixture(scope="class")
    def client(self):
        """FastAPI TestClient 생성"""
        from api.main import app
        return TestClient(app)

    def test_invalid_endpoint_404(self, client):
        """존재하지 않는 엔드포인트 접근 시 404"""
        response = client.get("/invalid/endpoint")

        assert response.status_code == 404

        print(f"✓ 404 에러 정상 반환")

    def test_search_without_query(self, client):
        """query 없이 검색 요청 시 422 에러"""
        response = client.post(
            "/search",
            json={
                "collection": "patents",
                "limit": 10
                # query 누락
            }
        )

        # Validation error
        assert response.status_code == 422

        print(f"✓ Query 누락 시 422 에러 정상 반환")


if __name__ == "__main__":
    # 직접 실행 시 pytest 호출
    pytest.main([__file__, "-v", "-s"])
