"""
Patent-AX 서비스 헬스체크
- GPU 서버 외부 서비스 접근성 확인
- 데이터베이스 연결 확인
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import requests
from typing import Dict, Any


class TestExternalServices:
    """외부 서비스 (GPU 서버) 헬스체크"""

    @pytest.fixture
    def service_urls(self) -> Dict[str, str]:
        """서비스 URL 목록"""
        return {
            "qdrant": "http://210.109.80.106:6333",
            "vllm": "http://210.109.80.106:12288",
            "kure": "http://210.109.80.106:7000",
            "cugraph": "http://210.109.80.106:8000"
        }

    def test_qdrant_patents_collection(self, service_urls):
        """Qdrant patents_v3_collection 상태 확인"""
        # When
        response = requests.get(
            f"{service_urls['qdrant']}/collections/patents_v3_collection",
            timeout=10
        )

        # Then
        assert response.status_code == 200, "Qdrant 컬렉션 접근 실패"

        data = response.json()
        result = data["result"]

        assert result["status"] == "green", f"컬렉션 상태: {result['status']}"
        assert result["points_count"] > 1800000, f"Points 수 부족: {result['points_count']}"
        assert result["indexed_vectors_count"] > 1800000, "인덱싱된 벡터 수 부족"

        # 벡터 설정 확인
        config = result["config"]["params"]["vectors"]
        assert config["size"] == 1024, f"벡터 차원: {config['size']} (예상: 1024)"
        assert config["distance"] == "Cosine", f"거리 메트릭: {config['distance']}"

        print(f"✅ Qdrant: {result['points_count']:,} points, status={result['status']}")

    def test_qdrant_scroll_api(self, service_urls):
        """Qdrant Scroll API 동작 확인"""
        # When
        response = requests.post(
            f"{service_urls['qdrant']}/collections/patents_v3_collection/points/scroll",
            json={"limit": 1, "with_vector": False},
            timeout=10
        )

        # Then
        assert response.status_code == 200, "Scroll API 호출 실패"

        data = response.json()
        assert len(data["result"]["points"]) > 0, "검색 결과 없음"

        point = data["result"]["points"][0]
        assert "id" in point, "Point에 id 없음"
        assert "payload" in point, "Point에 payload 없음"

        print(f"✅ Qdrant Scroll: ID={point['id']}")

    def test_vllm_health(self, service_urls):
        """vLLM 서비스 헬스체크"""
        # When
        response = requests.get(
            f"{service_urls['vllm']}/health",
            timeout=10
        )

        # Then
        assert response.status_code == 200, "vLLM 서비스 응답 없음"
        print(f"✅ vLLM: Health OK")

    def test_kure_health(self, service_urls):
        """KURE 임베딩 API 헬스체크"""
        # When
        response = requests.get(
            f"{service_urls['kure']}/health",
            timeout=10
        )

        # Then
        assert response.status_code == 200, "KURE API 응답 없음"
        print(f"✅ KURE: Health OK")

    @pytest.mark.skip(reason="cuGraph 서비스 재구축 필요")
    def test_cugraph_health(self, service_urls):
        """cuGraph 서비스 헬스체크 (현재 비활성)"""
        # When
        response = requests.get(
            f"{service_urls['cugraph']}/health",
            timeout=10
        )

        # Then
        assert response.status_code == 200, "cuGraph 서비스 응답 없음"


class TestDatabaseConnection:
    """PostgreSQL 데이터베이스 연결 테스트"""

    def test_postgres_connection(self):
        """PostgreSQL 연결 확인"""
        from sql.db_connector import get_db_connection

        # When
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT version();")
            version = cursor.fetchone()

        # Then
        assert version is not None, "PostgreSQL 버전 조회 실패"
        assert "PostgreSQL" in version[0], "PostgreSQL이 아님"
        print(f"✅ PostgreSQL: {version[0][:50]}")

    def test_patents_table_exists(self):
        """f_patents 테이블 존재 확인"""
        from sql.db_connector import get_db_connection

        # When
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_name = 'f_patents';
            """)
            count = cursor.fetchone()[0]

        # Then
        assert count == 1, "f_patents 테이블이 존재하지 않음"
        print(f"✅ f_patents 테이블 존재")

    def test_patents_row_count(self):
        """f_patents 데이터 개수 확인"""
        from sql.db_connector import get_db_connection

        # When
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM f_patents;")
            count = cursor.fetchone()[0]

        # Then
        assert count > 1000000, f"f_patents 데이터 부족: {count:,} rows"
        print(f"✅ f_patents: {count:,} rows")

    def test_patent_applicants_table_exists(self):
        """f_patent_applicants 테이블 존재 확인"""
        from sql.db_connector import get_db_connection

        # When
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_name = 'f_patent_applicants';
            """)
            count = cursor.fetchone()[0]

        # Then
        assert count == 1, "f_patent_applicants 테이블이 존재하지 않음"
        print(f"✅ f_patent_applicants 테이블 존재")


class TestConfigFiles:
    """설정 파일 검증"""

    def test_env_example_exists(self):
        """환경변수 예제 파일 존재 확인"""
        import os

        # When
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env.example")

        # Then
        assert os.path.exists(env_path), ".env.example 파일이 없음"

        with open(env_path) as f:
            content = f.read()
            assert "QDRANT_URL" in content, "QDRANT_URL 설정 없음"
            assert "VLLM_BASE_URL" in content, "VLLM_BASE_URL 설정 없음"
            assert "KURE_API_URL" in content, "KURE_API_URL 설정 없음"
            assert "DB_NAME" in content, "DB_NAME 설정 없음"

        print(f"✅ .env.example 파일 검증 완료")

    def test_api_config_collections(self):
        """api/config.py COLLECTIONS 설정 확인"""
        from api.config import COLLECTIONS

        # Then
        assert len(COLLECTIONS) == 1, f"COLLECTIONS 개수: {len(COLLECTIONS)} (예상: 1)"
        assert "patents" in COLLECTIONS, "patents 키가 없음"
        assert COLLECTIONS["patents"] == "patents_v3_collection", "컬렉션 이름 불일치"

        print(f"✅ COLLECTIONS: {COLLECTIONS}")


if __name__ == "__main__":
    # 단독 실행 시
    pytest.main([__file__, "-v", "--tb=short", "-s"])
