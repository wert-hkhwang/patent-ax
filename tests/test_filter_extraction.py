"""
Phase 16: 필터 조건 추출 테스트
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from workflow.prompts.filter_extraction import (
    extract_filter_conditions,
    extract_country_codes,
    extract_year_range,
    extract_limit,
    extract_preference_keywords,
    extract_entity_name,
    format_filters_for_prompt,
    FilterConditions
)


class TestExtractCountryCodes:
    """국가 코드 추출 테스트"""

    @pytest.mark.parametrize("query,expected", [
        ("KR 특허 출원 현황", ["KR"]),
        ("US 특허 TOP 10", ["US"]),
        ("한국 특허와 미국 특허", ["KR", "US"]),
        ("일본 특허 현황", ["JP"]),
        ("중국 특허", ["CN"]),
        ("인공지능 특허", []),  # 국가 없음
    ])
    def test_country_extraction(self, query, expected):
        result = extract_country_codes(query)
        assert set(result) == set(expected)


class TestExtractYearRange:
    """연도 범위 추출 테스트"""

    def test_recent_years(self):
        result = extract_year_range("최근 5년간 연구")
        assert result is not None
        start, end = result
        assert end - start == 5

    def test_year_range(self):
        result = extract_year_range("2020-2023 과제")
        assert result == (2020, 2023)

    def test_single_year(self):
        result = extract_year_range("2022년 특허")
        assert result == (2022, 2022)

    def test_no_year(self):
        result = extract_year_range("인공지능 연구")
        assert result is None


class TestExtractLimit:
    """LIMIT 추출 테스트"""

    @pytest.mark.parametrize("query,expected", [
        ("TOP 10 특허", 10),
        ("상위 5개 과제", 5),
        ("특허 20개", 20),
        ("특허 현황", None),
    ])
    def test_limit_extraction(self, query, expected):
        result = extract_limit(query)
        assert result == expected


class TestExtractPreferenceKeywords:
    """우대/가점 키워드 추출 테스트"""

    @pytest.mark.parametrize("query,expected_contains", [
        ("여성기업 유리한 과제", ["여성기업"]),  # "여성"도 매칭될 수 있음
        ("중소기업 가점", ["중소기업"]),  # "중소"도 매칭될 수 있음
        ("일반 과제 목록", []),
    ])
    def test_preference_extraction(self, query, expected_contains):
        result = extract_preference_keywords(query)
        # 예상 키워드가 결과에 포함되어 있는지 확인
        for expected in expected_contains:
            assert expected in result


class TestExtractEntityName:
    """엔티티명 추출 테스트"""

    @pytest.mark.parametrize("query,expected", [
        ("{전력반도체} 분야 특허", "전력반도체"),
        ("{구매조건부신제품개발사업} 배점표", "구매조건부신제품개발사업"),
        ("{AI 기반 해양자원 탐사} 사례", "AI 기반 해양자원 탐사"),
        ("일반 질문", None),
    ])
    def test_entity_extraction(self, query, expected):
        result = extract_entity_name(query)
        assert result == expected


class TestExtractFilterConditions:
    """통합 필터 조건 추출 테스트"""

    def test_complex_query_1(self):
        """특허 쿼리 테스트"""
        query = "{전력반도체} 분야의 KR 특허에 대해 주요 출원기관 TOP 10을 알려줘"
        conditions = extract_filter_conditions(query)

        assert conditions.entity_name == "전력반도체"
        assert "KR" in conditions.country_codes
        assert conditions.limit == 10

    def test_complex_query_2(self):
        """사업 배점표 쿼리 테스트"""
        query = "{구매조건부신제품개발사업} 관련 여성기업에게 유리한 배점기준이 있어?"
        conditions = extract_filter_conditions(query)

        assert conditions.entity_name == "구매조건부신제품개발사업"
        assert "여성기업" in conditions.preference_keywords

    def test_complex_query_3(self):
        """장비 쿼리 테스트"""
        query = "{초고속 원심분리기} 공공장비를 보유한 기관을 알려줘"
        conditions = extract_filter_conditions(query)

        assert conditions.entity_name == "초고속 원심분리기"


class TestFormatFiltersForPrompt:
    """프롬프트 포맷팅 테스트"""

    def test_format_with_all_conditions(self):
        conditions = FilterConditions(
            country_codes=["KR"],
            year_range=(2020, 2023),
            limit=10,
            preference_keywords=["여성기업"],
            entity_name="전력반도체"
        )
        result = format_filters_for_prompt(conditions)

        assert "전력반도체" in result
        assert "KR" in result
        assert "2020" in result
        assert "TOP 10" in result
        assert "여성기업" in result

    def test_format_empty_conditions(self):
        conditions = FilterConditions()
        result = format_filters_for_prompt(conditions)

        assert "추출된 필터 조건 없음" in result


class TestPhase16Queries:
    """Phase 16 15개 질의 필터 추출 테스트"""

    @pytest.mark.parametrize("query,expected_entity,expected_country,expected_limit", [
        (
            "{전력반도체} 분야의 KR 특허에 대해 주요 출원기관 TOP 10을 알려줘",
            "전력반도체", ["KR"], 10
        ),
        (
            "{전력반도체} 분야의 US 특허에 대해 주요 출원기관 TOP 10을 알려줘",
            "전력반도체", ["US"], 10
        ),
        (
            "{전력반도체} 분야의 KR 특허에 대해 TOP 5의 피인용 TOP 20 특허를 알려줘",
            "전력반도체", ["KR"], 5  # 첫 번째 TOP N 반환 (현재 동작)
        ),
    ])
    def test_patent_queries(self, query, expected_entity, expected_country, expected_limit):
        conditions = extract_filter_conditions(query)
        assert conditions.entity_name == expected_entity
        assert set(conditions.country_codes) == set(expected_country)
        assert conditions.limit == expected_limit

    @pytest.mark.parametrize("query,expected_entity,has_preference", [
        (
            "{구매조건부신제품개발사업} 관련 배점표를 알려줘",
            "구매조건부신제품개발사업", False
        ),
        (
            "{구매조건부신제품개발사업} 관련 여성기업에게 유리한 배점기준이 있어?",
            "구매조건부신제품개발사업", True
        ),
        (
            "{여성기업} 관련 유리한 과제를 알려줘",
            "여성기업", True
        ),
    ])
    def test_program_queries(self, query, expected_entity, has_preference):
        conditions = extract_filter_conditions(query)
        assert conditions.entity_name == expected_entity
        if has_preference:
            # 여성기업 또는 유리한 키워드 중 하나 있어야 함
            assert len(conditions.preference_keywords) > 0

    @pytest.mark.parametrize("query,expected_entity", [
        ("{AI 기반 해양자원 탐사} 기술개발 사례를 알려줘", "AI 기반 해양자원 탐사"),
        ("{초고속 원심분리기} 공공장비를 보유한 기관을 알려줘", "초고속 원심분리기"),
        ("{생물소재 유전체 해독 분석 장비} 추천해줘", "생물소재 유전체 해독 분석 장비"),
    ])
    def test_equipment_queries(self, query, expected_entity):
        conditions = extract_filter_conditions(query)
        assert conditions.entity_name == expected_entity


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
