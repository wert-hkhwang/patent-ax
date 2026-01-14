"""
외부 서비스 헬스체크 통합 테스트

모든 의존 서비스(PostgreSQL, Qdrant, vLLM, KURE, cuGraph)의 연결 상태를 검증합니다.
"""

import pytest
import os
import sys
import psycopg2
import requests
from qdrant_client import QdrantClient
from typing import Dict, Any

# .env 파일 로드
from dotenv import load_dotenv
load_dotenv()


class TestExternalServices:
    """외부 서비스 헬스체크 테스트 - 실제 서비스에 연결"""

    def test_postgresql_connection(self):
        """PostgreSQL 연결 및 특허 테이블 확인"""
        db_config = {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": os.getenv("DB_PORT", "5432"),
            "database": os.getenv("DB_NAME", "ax"),
            "user": os.getenv("DB_USER", "postgres"),
            "password": os.getenv("DB_PASSWORD", "postgres"),
        }

        # DB 연결 테스트
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()

        # f_patents 테이블 확인
        cursor.execute("SELECT COUNT(*) FROM f_patents")
        patent_count = cursor.fetchone()[0]

        # f_patent_applicants 테이블 확인
        cursor.execute("SELECT COUNT(*) FROM f_patent_applicants")
        applicant_count = cursor.fetchone()[0]

        conn.close()

        # 검증
        assert patent_count > 1_000_000, f"특허 데이터 부족: {patent_count} (예상: > 1M)"
        assert applicant_count > 300_000, f"출원인 데이터 부족: {applicant_count} (예상: > 300K)"

        print(f"✓ PostgreSQL 연결 성공: f_patents={patent_count:,}, f_patent_applicants={applicant_count:,}")

    def test_qdrant_collection_exists(self):
        """Qdrant patents_v3_collection 존재 및 point 수 확인"""
        qdrant_url = os.getenv("QDRANT_URL", "http://210.109.80.106:6333")
        collection_name = "patents_v3_collection"

        client = QdrantClient(url=qdrant_url, timeout=10)

        # 컬렉션 정보 조회
        collection_info = client.get_collection(collection_name=collection_name)

        points_count = collection_info.points_count
        vectors_count = collection_info.vectors_count or 0  # None 처리

        # 검증
        assert points_count > 1_800_000, f"벡터 point 부족: {points_count:,} (예상: > 1.8M)"

        print(f"✓ Qdrant 연결 성공: {collection_name} - {points_count:,} points, vectors_count={vectors_count}")

    def test_vllm_service_health(self):
        """vLLM 서비스 응답 확인"""
        vllm_url = os.getenv("VLLM_BASE_URL", "http://210.109.80.106:12288")
        health_endpoint = f"{vllm_url}/health"

        # Health check
        response = requests.get(health_endpoint, timeout=5)

        # 검증
        assert response.status_code == 200, f"vLLM 서비스 응답 실패: HTTP {response.status_code}"

        print(f"✓ vLLM 서비스 정상: {vllm_url}")

    def test_kure_api_health(self):
        """KURE 임베딩 API 응답 확인"""
        kure_url = os.getenv("KURE_API_URL", "http://210.109.80.106:7000/api/embedding")
        # KURE health는 7000/health (API gateway)
        gateway_health_url = kure_url.replace("/api/embedding", "/health")

        # Health check
        response = requests.get(gateway_health_url, timeout=5)

        # 검증
        assert response.status_code == 200, f"KURE API 응답 실패: HTTP {response.status_code}"

        data = response.json()
        assert data.get("gateway") == "healthy", f"KURE Gateway 비정상: {data}"

        # GPU 서버 상태 확인
        services = data.get("services", {})
        kure_healthy = any(
            "kure" in k and v == "healthy"
            for k, v in services.items()
        )
        assert kure_healthy, f"KURE GPU 서버 비정상: {services}"

        print(f"✓ KURE API 정상: {gateway_health_url}")
        print(f"  Services: {services}")

    @pytest.mark.skip(reason="cuGraph service currently unreachable (포트 8000)")
    def test_cugraph_health(self):
        """cuGraph 서비스 상태 (현재 비활성화)"""
        cugraph_url = os.getenv("CUGRAPH_API_URL", "http://210.109.80.106:8000")
        health_endpoint = f"{cugraph_url}/health"

        # Health check
        response = requests.get(health_endpoint, timeout=5)

        # 검증
        assert response.status_code == 200, f"cuGraph 서비스 응답 실패: HTTP {response.status_code}"

        print(f"✓ cuGraph 서비스 정상: {cugraph_url}")

    def test_all_env_vars_loaded(self):
        """필수 환경변수 로드 확인"""
        required_vars = {
            "DB_HOST": "localhost",
            "DB_NAME": "ax",
            "DB_USER": "postgres",
            "DB_PASSWORD": None,  # 값 체크 생략
            "QDRANT_URL": None,
            "VLLM_BASE_URL": None,
            "KURE_API_URL": None,
        }

        missing = []
        for var_name, expected_value in required_vars.items():
            value = os.getenv(var_name)

            if value is None:
                missing.append(var_name)
            elif expected_value is not None and value != expected_value:
                missing.append(f"{var_name} (expected: {expected_value}, got: {value})")

        assert len(missing) == 0, f"필수 환경변수 누락 또는 잘못된 값: {missing}"

        print(f"✓ 환경변수 로드 성공: {len(required_vars)}개 확인")


class TestDatabaseSchema:
    """데이터베이스 스키마 검증"""

    def test_patents_table_schema(self):
        """f_patents 테이블 스키마 확인"""
        db_config = {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": os.getenv("DB_PORT", "5432"),
            "database": os.getenv("DB_NAME", "ax"),
            "user": os.getenv("DB_USER", "postgres"),
            "password": os.getenv("DB_PASSWORD", "postgres"),
        }

        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()

        # 테이블 존재 확인
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'f_patents'
            )
        """)
        exists = cursor.fetchone()[0]
        assert exists, "f_patents 테이블이 존재하지 않음"

        # 핵심 컬럼 존재 확인
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = 'f_patents'
        """)
        columns = [row[0] for row in cursor.fetchall()]

        # 실제 Patent-AX 스키마에 맞는 컬럼명
        required_columns = [
            "conts_id",  # 콘텐츠 ID
            "conts_klang_nm",  # 특허 한글명
            "ptnaplc_no",  # 출원 번호
            "ptnaplc_ymd",  # 출원일
        ]

        missing_columns = [col for col in required_columns if col not in columns]

        conn.close()

        assert len(missing_columns) == 0, f"필수 컬럼 누락: {missing_columns}"

        print(f"✓ f_patents 테이블 스키마 정상: {len(columns)}개 컬럼")

    def test_applicants_table_schema(self):
        """f_patent_applicants 테이블 스키마 확인"""
        db_config = {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": os.getenv("DB_PORT", "5432"),
            "database": os.getenv("DB_NAME", "ax"),
            "user": os.getenv("DB_USER", "postgres"),
            "password": os.getenv("DB_PASSWORD", "postgres"),
        }

        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()

        # 테이블 존재 확인
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'f_patent_applicants'
            )
        """)
        exists = cursor.fetchone()[0]

        conn.close()

        assert exists, "f_patent_applicants 테이블이 존재하지 않음"

        print(f"✓ f_patent_applicants 테이블 존재 확인")


class TestServiceIntegration:
    """서비스 간 통합 테스트"""

    def test_embedding_generation(self):
        """KURE API를 통한 임베딩 생성 테스트"""
        kure_url = os.getenv("KURE_API_URL", "http://210.109.80.106:7000/api/embedding")

        # 테스트 텍스트
        test_text = "인공지능 기반 반도체 제조 기술"

        # 임베딩 생성 요청
        response = requests.post(
            kure_url,
            json={"text": test_text},
            timeout=30
        )

        # 검증
        assert response.status_code == 200, f"임베딩 생성 실패: HTTP {response.status_code}"

        data = response.json()
        embedding = data.get("embedding")

        assert embedding is not None, "임베딩 벡터 없음"
        assert len(embedding) == 1024, f"임베딩 차원 불일치: {len(embedding)} (예상: 1024)"

        print(f"✓ 임베딩 생성 성공: {len(embedding)}-dim vector")

    def test_qdrant_vector_search(self):
        """Qdrant 벡터 검색 테스트"""
        qdrant_url = os.getenv("QDRANT_URL", "http://210.109.80.106:6333")
        collection_name = "patents_v3_collection"

        client = QdrantClient(url=qdrant_url, timeout=30)

        # 더미 벡터로 검색 (1024-dim, 모두 0.1)
        dummy_vector = [0.1] * 1024

        # 검색 실행
        search_result = client.search(
            collection_name=collection_name,
            query_vector=dummy_vector,
            limit=5
        )

        # 검증
        assert len(search_result) > 0, "검색 결과 없음"
        assert hasattr(search_result[0], "score"), "검색 결과에 score 없음"
        assert hasattr(search_result[0], "payload"), "검색 결과에 payload 없음"

        print(f"✓ Qdrant 벡터 검색 성공: {len(search_result)}개 결과")


if __name__ == "__main__":
    # 직접 실행 시 pytest 호출
    pytest.main([__file__, "-v", "-s"])
