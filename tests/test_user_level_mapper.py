"""
UserLevelMapper 테스트

사용자 리터러시 레벨 매핑 로직 검증
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflow.user.level_mapper import UserLevelMapper


class TestUserLevelMapper:
    """UserLevelMapper 단위 테스트"""

    def test_get_initial_level_by_occupation(self):
        """직업 기반 레벨 매핑 테스트"""
        mapper = UserLevelMapper()

        # L3: 중소기업 실무자
        assert mapper.get_initial_level(occupation="중소기업_실무자") == "L3"

        # L4: 연구원
        assert mapper.get_initial_level(occupation="연구원") == "L4"

        # L5: 변리사
        assert mapper.get_initial_level(occupation="변리사") == "L5"

        # L6: 정책담당자
        assert mapper.get_initial_level(occupation="정책담당자") == "L6"

    def test_get_initial_level_by_education(self):
        """학력 기반 레벨 매핑 테스트"""
        mapper = UserLevelMapper()

        # L1: 초등학생, 중학생
        assert mapper.get_initial_level(education_level="초등학생") == "L1"
        assert mapper.get_initial_level(education_level="중학생") == "L1"

        # L2: 고등학생, 대학생
        assert mapper.get_initial_level(education_level="고등학생") == "L2"
        assert mapper.get_initial_level(education_level="대학생") == "L2"

        # L4: 박사
        assert mapper.get_initial_level(education_level="박사") == "L4"

    def test_occupation_priority_over_education(self):
        """직업이 학력보다 우선하는지 테스트"""
        mapper = UserLevelMapper()

        # 고등학생(L2)이지만 연구원(L4) 직업 → L4
        result = mapper.get_initial_level(
            education_level="고등학생",
            occupation="연구원"
        )
        assert result == "L4", "직업이 학력보다 우선해야 함"

    def test_default_level_when_no_match(self):
        """매핑 안 되는 경우 기본값 L2 반환"""
        mapper = UserLevelMapper()

        # 매핑 테이블에 없는 값
        assert mapper.get_initial_level(education_level="기타") == "L2"
        assert mapper.get_initial_level(occupation="기타직업") == "L2"
        assert mapper.get_initial_level() == "L2"  # 둘 다 None

    def test_get_level_description(self):
        """레벨 설명 조회 테스트"""
        assert "학생" in UserLevelMapper.get_level_description("L1")
        assert "대학생" in UserLevelMapper.get_level_description("L2")
        assert "중소기업" in UserLevelMapper.get_level_description("L3")
        assert "연구자" in UserLevelMapper.get_level_description("L4")
        assert "변리사" in UserLevelMapper.get_level_description("L5")
        assert "정책" in UserLevelMapper.get_level_description("L6")

    def test_get_all_mappings(self):
        """전체 매핑 테이블 조회 테스트"""
        mappings = UserLevelMapper.get_all_mappings()

        # 필수 매핑 존재 확인
        assert "초등학생" in mappings
        assert "연구원" in mappings
        assert "변리사" in mappings

        # 레벨 값 확인
        assert mappings["초등학생"] == "L1"
        assert mappings["연구원"] == "L4"
        assert mappings["변리사"] == "L5"


class TestUserProfileDatabase:
    """사용자 프로필 DB 연동 테스트 (실제 DB 필요)"""

    @pytest.fixture
    def mapper(self):
        """Mapper 인스턴스 생성"""
        return UserLevelMapper()

    @pytest.fixture
    def test_user_id(self):
        """테스트용 user_id"""
        return "test_user_level_mapper_123"

    def test_create_user_profile(self, mapper, test_user_id):
        """사용자 프로필 생성 테스트"""
        profile = mapper.create_user_profile(
            user_id=test_user_id,
            education_level="대학생",
            occupation="연구원"
        )

        # 프로필 생성 확인
        assert profile["user_id"] == test_user_id
        assert profile["education_level"] == "대학생"
        assert profile["occupation"] == "연구원"
        assert profile["registered_level"] == "L4"  # 연구원 → L4
        assert profile["current_level"] == "L4"

        print(f"✓ 프로필 생성 성공: {profile}")

    def test_get_user_profile(self, mapper, test_user_id):
        """사용자 프로필 조회 테스트"""
        # 먼저 생성
        mapper.create_user_profile(
            user_id=test_user_id,
            education_level="대학생",
            occupation="연구원"
        )

        # 조회
        profile = mapper.get_user_profile(test_user_id)

        assert profile is not None
        assert profile["user_id"] == test_user_id
        assert profile["current_level"] == "L4"

        print(f"✓ 프로필 조회 성공: {profile}")

    def test_update_current_level(self, mapper, test_user_id):
        """레벨 변경 테스트"""
        # 먼저 생성
        mapper.create_user_profile(
            user_id=test_user_id,
            education_level="대학생",
            occupation="연구원"
        )

        # 레벨 변경: L4 → L5
        updated = mapper.update_current_level(
            user_id=test_user_id,
            new_level="L5",
            reason="변리사 자격 취득"
        )

        assert updated["current_level"] == "L5"
        assert len(updated["change_history"]) >= 1

        # 이력 확인
        last_change = updated["change_history"][-1]
        assert last_change["from"] == "L4"
        assert last_change["to"] == "L5"
        assert last_change["reason"] == "변리사 자격 취득"

        print(f"✓ 레벨 변경 성공: L4 → L5")
        print(f"  이력: {updated['change_history']}")

    def test_update_level_invalid(self, mapper, test_user_id):
        """잘못된 레벨 변경 시 에러"""
        mapper.create_user_profile(
            user_id=test_user_id,
            education_level="대학생"
        )

        with pytest.raises(ValueError):
            mapper.update_current_level(
                user_id=test_user_id,
                new_level="L99"  # 잘못된 레벨
            )

    def test_get_level_statistics(self, mapper):
        """레벨별 통계 조회 테스트"""
        stats = mapper.get_level_statistics()

        # 6개 레벨 모두 존재
        assert "L1" in stats
        assert "L2" in stats
        assert "L3" in stats
        assert "L4" in stats
        assert "L5" in stats
        assert "L6" in stats

        print(f"✓ 레벨 통계: {stats}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
