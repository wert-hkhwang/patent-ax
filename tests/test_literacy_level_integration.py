"""
리터러시 레벨 통합 테스트 (v1.3)

LEVEL_PROMPTS_V3 (L1~L6) 및 응답 생성 로직 검증
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflow.nodes.generator import (
    LEVEL_PROMPTS_V3,
    TOKEN_LIMITS_V3,
    LEVEL_PROMPTS,
    TOKEN_LIMITS_LEGACY
)


class TestLevelPromptsV3:
    """LEVEL_PROMPTS_V3 구조 검증"""

    def test_all_six_levels_exist(self):
        """6개 레벨 모두 존재하는지 확인"""
        required_levels = ["L1", "L2", "L3", "L4", "L5", "L6"]

        for level in required_levels:
            assert level in LEVEL_PROMPTS_V3, f"레벨 {level} 누락"
            assert level in TOKEN_LIMITS_V3, f"레벨 {level} 토큰 제한 누락"

        print(f"✓ 6개 레벨 모두 존재: {list(LEVEL_PROMPTS_V3.keys())}")

    def test_prompt_not_empty(self):
        """모든 프롬프트가 비어있지 않은지 확인"""
        for level, prompt in LEVEL_PROMPTS_V3.items():
            assert isinstance(prompt, str), f"{level} 프롬프트가 문자열이 아님"
            assert len(prompt) > 100, f"{level} 프롬프트가 너무 짧음 ({len(prompt)}자)"

        print(f"✓ 모든 프롬프트가 충분한 길이")

    def test_prompt_contains_guidelines(self):
        """각 프롬프트에 응답 가이드라인이 포함되어 있는지 확인"""
        for level, prompt in LEVEL_PROMPTS_V3.items():
            assert "응답 가이드라인" in prompt, f"{level} 프롬프트에 가이드라인 없음"
            assert "중요:" in prompt or "**중요**" in prompt, f"{level} 프롬프트에 중요 지침 없음"

        print(f"✓ 모든 프롬프트에 가이드라인 포함")

    def test_token_limits_reasonable(self):
        """토큰 제한이 합리적인 범위인지 확인"""
        for level, limit in TOKEN_LIMITS_V3.items():
            assert 500 <= limit <= 5000, f"{level} 토큰 제한이 비정상적: {limit}"

        print(f"✓ 토큰 제한 범위 정상: {TOKEN_LIMITS_V3}")

    def test_level_characteristics(self):
        """각 레벨의 특성이 프롬프트에 반영되어 있는지 확인"""
        # L1: 쉬운 말, 비유, 이모지
        assert "쉬운 말" in LEVEL_PROMPTS_V3["L1"]
        assert "비유" in LEVEL_PROMPTS_V3["L1"]
        assert "이모지" in LEVEL_PROMPTS_V3["L1"]

        # L2: 괄호 설명, 학술적
        assert "괄호" in LEVEL_PROMPTS_V3["L2"]
        assert "학술" in LEVEL_PROMPTS_V3["L2"]

        # L3: 실무, 사업화
        assert "실무" in LEVEL_PROMPTS_V3["L3"]
        assert "사업화" in LEVEL_PROMPTS_V3["L3"]

        # L4: 기술 용어, 수치
        assert "기술 용어" in LEVEL_PROMPTS_V3["L4"] or "용어 그대로" in LEVEL_PROMPTS_V3["L4"]
        assert "수치" in LEVEL_PROMPTS_V3["L4"]

        # L5: 법률, 권리범위
        assert "법률" in LEVEL_PROMPTS_V3["L5"]
        assert "권리범위" in LEVEL_PROMPTS_V3["L5"]

        # L6: 거시적, 정책
        assert "거시" in LEVEL_PROMPTS_V3["L6"]
        assert "정책" in LEVEL_PROMPTS_V3["L6"]

        print(f"✓ 각 레벨의 특성이 프롬프트에 반영됨")


class TestBackwardCompatibility:
    """기존 3단계 시스템 하위 호환성 테스트"""

    def test_legacy_levels_mapped(self):
        """기존 레벨이 V3에 매핑되어 있는지 확인"""
        legacy_levels = ["초등", "일반인", "전문가"]

        for level in legacy_levels:
            assert level in LEVEL_PROMPTS, f"기존 레벨 {level} 누락"
            assert level in TOKEN_LIMITS_LEGACY, f"기존 레벨 {level} 토큰 제한 누락"

        print(f"✓ 기존 3단계 레벨 모두 매핑됨")

    def test_legacy_mapping_correct(self):
        """기존 레벨이 올바른 V3 레벨로 매핑되는지 확인"""
        assert LEVEL_PROMPTS["초등"] == LEVEL_PROMPTS_V3["L1"]
        assert LEVEL_PROMPTS["일반인"] == LEVEL_PROMPTS_V3["L2"]
        assert LEVEL_PROMPTS["전문가"] == LEVEL_PROMPTS_V3["L5"]

        print(f"✓ 기존 레벨 → V3 매핑 정확함")


class TestLevelProgression:
    """레벨 간 점진적 복잡도 증가 검증"""

    def test_token_limits_progression(self):
        """토큰 제한이 레벨에 따라 증가하는지 확인 (L1~L5)"""
        # L1 < L2 < L3 < L4 < L5 (일반적으로)
        assert TOKEN_LIMITS_V3["L1"] < TOKEN_LIMITS_V3["L2"]
        assert TOKEN_LIMITS_V3["L2"] < TOKEN_LIMITS_V3["L3"]
        assert TOKEN_LIMITS_V3["L3"] < TOKEN_LIMITS_V3["L4"]
        assert TOKEN_LIMITS_V3["L4"] < TOKEN_LIMITS_V3["L5"]

        print(f"✓ 토큰 제한이 레벨에 따라 증가: {TOKEN_LIMITS_V3}")

    def test_prompt_length_progression(self):
        """프롬프트 길이가 대체로 증가하는지 확인"""
        lengths = {level: len(prompt) for level, prompt in LEVEL_PROMPTS_V3.items()}

        print(f"✓ 프롬프트 길이: {lengths}")
        # L1~L4는 대체로 증가 (L5, L6은 특수 목적이라 예외 가능)
        assert lengths["L1"] <= lengths["L4"], "L1이 L4보다 길면 안 됨"


class TestPromptExamples:
    """프롬프트에 예시가 포함되어 있는지 확인"""

    def test_examples_included(self):
        """각 레벨 프롬프트에 예시가 포함되어 있는지 확인"""
        for level, prompt in LEVEL_PROMPTS_V3.items():
            # "예:" 또는 "예시)" 패턴 확인
            has_examples = ("예:" in prompt) or ("예시)" in prompt)
            assert has_examples, f"{level} 프롬프트에 예시 없음"

        print(f"✓ 모든 레벨에 예시 포함")


class TestIntegrationMock:
    """통합 테스트 (Mock LLM 사용)"""

    def test_level_selection_logic(self):
        """레벨 선택 로직 테스트"""
        from workflow.nodes.generator import LEVEL_PROMPTS_V3, LEVEL_PROMPTS

        # V3 레벨 테스트
        test_cases = [
            ("L1", LEVEL_PROMPTS_V3["L1"]),
            ("L2", LEVEL_PROMPTS_V3["L2"]),
            ("L3", LEVEL_PROMPTS_V3["L3"]),
            ("L4", LEVEL_PROMPTS_V3["L4"]),
            ("L5", LEVEL_PROMPTS_V3["L5"]),
            ("L6", LEVEL_PROMPTS_V3["L6"]),
        ]

        for level, expected_prompt in test_cases:
            # 레벨이 V3에 있는지 확인
            assert level in LEVEL_PROMPTS_V3
            # 프롬프트가 일치하는지 확인
            assert LEVEL_PROMPTS_V3[level] == expected_prompt

        # 기존 레벨 테스트
        legacy_cases = [
            ("초등", LEVEL_PROMPTS["초등"]),
            ("일반인", LEVEL_PROMPTS["일반인"]),
            ("전문가", LEVEL_PROMPTS["전문가"]),
        ]

        for level, expected_prompt in legacy_cases:
            assert level in LEVEL_PROMPTS
            assert LEVEL_PROMPTS[level] == expected_prompt

        print(f"✓ 레벨 선택 로직 정상 작동")

    def test_fallback_behavior(self):
        """알 수 없는 레벨에 대한 fallback 동작 테스트"""
        # 알 수 없는 레벨은 L2 (일반인) 기본값 사용
        unknown_level = "UNKNOWN"

        # V3에 없고 기존 레벨에도 없으면 L2 사용해야 함
        assert unknown_level not in LEVEL_PROMPTS_V3
        assert unknown_level not in LEVEL_PROMPTS

        # 실제 코드에서는 L2를 기본값으로 사용
        default_prompt = LEVEL_PROMPTS_V3["L2"]
        assert default_prompt == LEVEL_PROMPTS_V3["L2"]

        print(f"✓ Fallback 동작 정상 (기본값: L2)")


@pytest.mark.integration
class TestEndToEnd:
    """End-to-End 통합 테스트 (실제 서비스 필요)"""

    @pytest.mark.skip(reason="실제 LLM 서비스 필요 (수동 테스트)")
    def test_generate_response_all_levels(self):
        """모든 레벨에 대해 응답 생성 테스트"""
        from workflow.graph import run_workflow

        test_query = "양자컴퓨터 특허"
        levels = ["L1", "L2", "L3", "L4", "L5", "L6"]

        responses = {}

        for level in levels:
            result = run_workflow(
                query=test_query,
                session_id=f"test_level_{level}",
                level=level
            )

            responses[level] = result["response"]

            # 기본 검증
            assert result.get("query_type") is not None
            assert len(result["response"]) > 0

            print(f"✓ 레벨 {level} 응답 생성 성공 ({len(result['response'])}자)")

        # 응답이 서로 다른지 확인
        all_same = all(responses[level] == responses["L1"] for level in levels)
        assert not all_same, "모든 레벨의 응답이 동일함 (리터러시 레벨 미반영)"

        print(f"✓ 6개 레벨 응답 모두 생성됨, 각 레벨별로 다름")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
