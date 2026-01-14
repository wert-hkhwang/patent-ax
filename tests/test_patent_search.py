"""
Patent-AX 통합 테스트
- 특허 검색 기능 검증
- entity_types=["patent"] 강제 확인
- 서비스 연동 확인
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from workflow.state import create_initial_state, AgentState
from workflow.nodes.analyzer import analyze_query


class TestPatentSearch:
    """특허 검색 기능 테스트"""

    def test_entity_types_hardcoded(self):
        """entity_types가 항상 ["patent"]로 고정되는지 확인"""
        # Given
        state = create_initial_state(
            query="수소연료전지 특허",
            session_id="test-001"
        )

        # Then
        assert state["entity_types"] == ["patent"], "entity_types가 ['patent']로 고정되어야 함"
        assert state["query_type"] == "simple", "초기 query_type은 'simple'이어야 함"

    def test_analyzer_forces_patent_entity(self):
        """Analyzer가 항상 patent entity를 반환하는지 확인"""
        # Given
        state = create_initial_state(
            query="인공지능 특허 TOP 10 출원기관",
            session_id="test-002"
        )

        # When
        result = analyze_query(state)

        # Then
        assert result["entity_types"] == ["patent"], "Analyzer가 ['patent']를 반환해야 함"
        assert "f_patents" in result["related_tables"], "f_patents 테이블이 포함되어야 함"
        assert result["query_subtype"] in ["list", "ranking", "aggregation"], "유효한 subtype이어야 함"

    def test_patent_ranking_query(self):
        """특허 랭킹 쿼리 분석 테스트"""
        # Given
        queries = [
            "수소연료전지 특허 TOP 10 출원기관",
            "반도체 분야 상위 5개 기업",
            "인공지능 특허 출원 상위 기관",
        ]

        for query in queries:
            # When
            state = create_initial_state(query=query, session_id="test-ranking")
            result = analyze_query(state)

            # Then
            assert result["entity_types"] == ["patent"], f"쿼리 '{query}'의 entity_types는 ['patent']여야 함"
            assert result["query_subtype"] in ["ranking", "list"], "ranking 또는 list subtype이어야 함"

    def test_patent_trend_query(self):
        """특허 동향 분석 쿼리 테스트"""
        # Given
        queries = [
            "수소연료전지 특허 동향",
            "반도체 특허 연도별 추이",
            "인공지능 특허 증가 추세",
        ]

        for query in queries:
            # When
            state = create_initial_state(query=query, session_id="test-trend")
            result = analyze_query(state)

            # Then
            assert result["entity_types"] == ["patent"], f"쿼리 '{query}'의 entity_types는 ['patent']여야 함"
            assert len(result["keywords"]) > 0, "키워드가 추출되어야 함"

    def test_literacy_level_support(self):
        """리터러시 레벨 지원 확인"""
        # Given
        levels = ["초등", "일반인", "전문가"]

        for level in levels:
            # When
            state = create_initial_state(
                query="특허란 무엇인가요?",
                level=level,
                session_id=f"test-level-{level}"
            )

            # Then
            assert state["level"] == level, f"리터러시 레벨 {level}이 유지되어야 함"
            assert state["entity_types"] == ["patent"], "entity_types는 ['patent']여야 함"

    def test_related_tables_always_patent(self):
        """related_tables가 항상 특허 테이블만 포함하는지 확인"""
        # Given
        state = create_initial_state(
            query="자율주행 특허",
            session_id="test-tables"
        )

        # When
        result = analyze_query(state)

        # Then
        tables = result.get("related_tables", [])
        assert "f_patents" in tables or "f_patent_applicants" in tables, "특허 테이블이 포함되어야 함"

        # 다른 도메인 테이블이 포함되지 않아야 함
        forbidden_tables = ["f_projects", "f_equipments", "f_proposal_profile", "f_ancm_evalp"]
        for table in forbidden_tables:
            assert table not in tables, f"비특허 테이블 {table}이 포함되지 않아야 함"


class TestServiceConnectivity:
    """외부 서비스 연결 테스트"""

    def test_qdrant_collection_exists(self):
        """Qdrant patents_v3_collection 존재 확인"""
        import requests

        # When
        response = requests.get("http://210.109.80.106:6333/collections/patents_v3_collection")

        # Then
        assert response.status_code == 200, "Qdrant 컬렉션이 존재해야 함"

        data = response.json()
        assert data["result"]["status"] == "green", "컬렉션 상태가 green이어야 함"
        assert data["result"]["points_count"] > 1000000, "최소 100만 개 이상의 points가 있어야 함"

    def test_qdrant_vector_dimension(self):
        """Qdrant 벡터 차원 확인 (1024-dim)"""
        import requests

        # When
        response = requests.get("http://210.109.80.106:6333/collections/patents_v3_collection")
        data = response.json()

        # Then
        vector_size = data["result"]["config"]["params"]["vectors"]["size"]
        assert vector_size == 1024, "벡터 차원은 1024여야 함"

        distance = data["result"]["config"]["params"]["vectors"]["distance"]
        assert distance == "Cosine", "거리 메트릭은 Cosine이어야 함"

    def test_vllm_health(self):
        """vLLM 서비스 헬스체크"""
        import requests

        # When
        response = requests.get("http://210.109.80.106:12288/health", timeout=5)

        # Then
        assert response.status_code == 200, "vLLM 서비스가 응답해야 함"

    def test_kure_health(self):
        """KURE 임베딩 API 헬스체크"""
        import requests

        # When
        response = requests.get("http://210.109.80.106:7000/health", timeout=5)

        # Then
        assert response.status_code == 200, "KURE API가 응답해야 함"


class TestPatentOnlyEnforcement:
    """특허만 처리하도록 강제되는지 확인"""

    def test_no_project_keywords(self):
        """프로젝트 관련 키워드로 검색해도 patent만 반환"""
        # Given: 원래는 project 엔티티를 유발하는 쿼리
        state = create_initial_state(
            query="국책과제 수소연료전지",
            session_id="test-project"
        )

        # When
        result = analyze_query(state)

        # Then
        assert result["entity_types"] == ["patent"], "프로젝트 키워드가 있어도 ['patent']만 반환해야 함"

    def test_no_equipment_keywords(self):
        """장비 관련 키워드로 검색해도 patent만 반환"""
        # Given
        state = create_initial_state(
            query="연구장비 반도체",
            session_id="test-equipment"
        )

        # When
        result = analyze_query(state)

        # Then
        assert result["entity_types"] == ["patent"], "장비 키워드가 있어도 ['patent']만 반환해야 함"

    def test_no_announcement_keywords(self):
        """공고 관련 키워드로 검색해도 patent만 반환"""
        # Given
        state = create_initial_state(
            query="연구개발과제 공고",
            session_id="test-announcement"
        )

        # When
        result = analyze_query(state)

        # Then
        assert result["entity_types"] == ["patent"], "공고 키워드가 있어도 ['patent']만 반환해야 함"


if __name__ == "__main__":
    # 단독 실행 시
    pytest.main([__file__, "-v", "--tb=short"])
