"""
Phase 15: 도메인 매칭 테스트
- 질문에서 엔티티 타입 추론 검증
- 컬렉션 매핑 검증
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from workflow.prompts.domain_mapping import (
    infer_entity_types,
    infer_entity_types_with_confidence,
    get_collections_for_entity_types,
    get_primary_entity_type,
    has_explicit_entity_mention,
    ENTITY_TYPE_KEYWORDS,
    ENTITY_TO_COLLECTION,
    DEFAULT_COLLECTIONS
)


class TestInferEntityTypes:
    """엔티티 타입 추론 테스트"""

    @pytest.mark.parametrize("query,expected", [
        # 프로젝트/과제 관련
        ("블록체인 연구 사례가 있나요?", ["project"]),
        ("인공지능 관련 연구과제", ["project"]),
        ("AI R&D 현황", ["project"]),
        ("연구개발 동향", ["project"]),

        # 특허 관련
        ("AI 특허 출원 현황", ["patent"]),
        ("딥러닝 발명 특허", ["patent"]),
        ("IPC 분류별 특허", ["patent"]),

        # 복합 (과제 + 특허)
        ("인공지능 과제와 특허", ["project", "patent"]),
        ("연구과제와 특허 출원 현황", ["project", "patent"]),  # "및" 대신 명시적 키워드 사용

        # 제안서
        ("연구제안서 목록", ["proposal"]),
        ("공모 현황", ["proposal"]),

        # 장비
        ("연구장비 현황", ["equipment"]),
        ("실험장비 목록", ["equipment"]),

        # 기관
        ("참여기관 현황", ["organization"]),
        ("대학 연구소", ["organization"]),
    ])
    def test_entity_type_inference(self, query, expected):
        """질문에서 엔티티 타입 추론"""
        result = infer_entity_types(query)
        assert set(result) == set(expected), f"Expected {expected}, got {result}"

    def test_empty_query(self):
        """빈 쿼리"""
        assert infer_entity_types("") == []
        assert infer_entity_types(None) == []

    def test_ambiguous_query(self):
        """모호한 쿼리는 기본값 또는 복합 타입"""
        # "연구"만 있으면 project
        result = infer_entity_types("연구")
        assert "project" in result

        # "기술"은 복합 가능
        result = infer_entity_types("기술 동향")
        assert len(result) >= 1


class TestGetCollectionsForEntityTypes:
    """엔티티 타입 → 컬렉션 매핑 테스트"""

    def test_project_collection(self):
        """프로젝트 → projects_v3_collection"""
        collections = get_collections_for_entity_types(["project"])
        assert "projects_v3_collection" in collections
        assert "patents_v3_collection" not in collections

    def test_patent_collection(self):
        """특허 → patents_v3_collection"""
        collections = get_collections_for_entity_types(["patent"])
        assert "patents_v3_collection" in collections
        assert "projects_v3_collection" not in collections

    def test_multiple_entity_types(self):
        """복합 엔티티 타입 → 복합 컬렉션"""
        collections = get_collections_for_entity_types(["project", "patent"])
        assert "projects_v3_collection" in collections
        assert "patents_v3_collection" in collections

    def test_empty_entity_types(self):
        """빈 엔티티 타입 → 기본 컬렉션"""
        collections = get_collections_for_entity_types([])
        assert collections == DEFAULT_COLLECTIONS

    def test_unknown_entity_type(self):
        """알 수 없는 엔티티 타입 → 기본 컬렉션"""
        collections = get_collections_for_entity_types(["unknown"])
        assert collections == DEFAULT_COLLECTIONS


class TestGetPrimaryEntityType:
    """주요 엔티티 타입 테스트"""

    def test_single_type(self):
        """단일 타입"""
        assert get_primary_entity_type("연구과제") == "project"
        assert get_primary_entity_type("특허 출원") == "patent"

    def test_multiple_types_returns_first(self):
        """복합 타입은 첫 번째 반환"""
        primary = get_primary_entity_type("연구과제와 특허")
        assert primary in ["project", "patent"]

    def test_no_type(self):
        """타입 없음"""
        assert get_primary_entity_type("안녕하세요") is None


class TestHasExplicitEntityMention:
    """명시적 엔티티 언급 테스트"""

    def test_explicit_project(self):
        """과제 명시적 언급"""
        assert has_explicit_entity_mention("연구과제 목록", "project") is True
        assert has_explicit_entity_mention("특허 목록", "project") is False

    def test_explicit_patent(self):
        """특허 명시적 언급"""
        assert has_explicit_entity_mention("특허 출원", "patent") is True
        assert has_explicit_entity_mention("연구과제", "patent") is False


class TestInferEntityTypesWithConfidence:
    """신뢰도 포함 추론 테스트"""

    def test_high_confidence_project(self):
        """프로젝트 높은 신뢰도"""
        scores = infer_entity_types_with_confidence("연구과제 현황")
        assert "project" in scores
        assert scores["project"] > 0

    def test_multiple_scores(self):
        """복합 스코어"""
        scores = infer_entity_types_with_confidence("연구과제와 특허")
        assert "project" in scores
        assert "patent" in scores


class TestDomainMappingIntegration:
    """통합 테스트 - 실제 질문 시나리오"""

    @pytest.mark.parametrize("query,expected_primary,expected_collection", [
        (
            "블록체인 기술을 활용한 연구 사례가 있나요?",
            "project",
            "projects_v3_collection"
        ),
        (
            "AI 관련 특허 출원 현황은?",
            "patent",
            "patents_v3_collection"
        ),
        (
            "딥러닝 연구개발 프로젝트",
            "project",
            "projects_v3_collection"
        ),
        (
            "바이오 분야 R&D 사례",
            "project",
            "projects_v3_collection"
        ),
    ])
    def test_end_to_end_mapping(self, query, expected_primary, expected_collection):
        """E2E 도메인 매핑"""
        # 엔티티 타입 추론
        entity_types = infer_entity_types(query)
        primary = get_primary_entity_type(query)

        # 컬렉션 매핑
        collections = get_collections_for_entity_types(entity_types)

        assert primary == expected_primary
        assert expected_collection in collections


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
