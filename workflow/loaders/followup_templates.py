"""
Followup Question Templates
===========================

Intent/Subtype별 후속질문 템플릿
- 사용자 탐색 경험 향상
- {input_data}, {output_top1} 변수 치환 지원

RISE-GPT에서 이식
작성일: 2025-12-12
"""

from typing import List, Dict, Any, Optional
import logging
import re

logger = logging.getLogger(__name__)


# ============================================================================
# Subtype별 후속질문 템플릿
# ============================================================================

SUBTYPE_FOLLOWUP_MAP: Dict[str, List[str]] = {
    # ===== 특허 순위 =====
    "ranking": [
        "{input_data} 분야의 평균 피인용 순위 Top 10을 알려줘",
        "{input_data} 분야의 특허 영향력 순위 Top 10을 알려줘",
        "{input_data} 관련 국내 협업 가능한 기업을 추천해줘",
        "{output_top1}의 최근 5년간 특허 출원 추이를 알려줘",
    ],

    "citation_ranking": [
        "{input_data} 분야의 특허 출원기관 TOP 10을 알려줘",
        "{input_data} 분야의 특허 영향력 순위를 알려줘",
        "{output_top1}의 대표 특허 목록을 알려줘",
        "{input_data} 분야 협업 가능한 기업을 추천해줘",
    ],

    "impact_ranking": [
        "{input_data} 분야의 평균 피인용 순위를 알려줘",
        "{input_data} 분야의 출원기관 TOP 10을 알려줘",
        "{output_top1}과 협업 가능성이 높은 기관을 추천해줘",
    ],

    "nationality_ranking": [
        "{input_data} 분야의 국내 출원기관 순위를 알려줘",
        "{input_data} 분야의 해외 출원기관 순위를 알려줘",
        "한국과 미국의 {input_data} 특허 출원 비교를 알려줘",
    ],

    # ===== 협업 기업 추천 =====
    "collaboration": [
        "{output_top1}의 특허 포트폴리오를 분석해줘",
        "{output_top1}의 정부과제 수행 이력을 알려줘",
        "{input_data} 분야의 특허 출원기관 순위를 알려줘",
        "{input_data} 분야의 장비 보유 기관을 알려줘",
    ],

    "collaboration_patent": [
        "{output_top1}의 주요 특허 목록을 알려줘",
        "{input_data} 분야의 과제 기반 협업 기업을 추천해줘",
        "{output_top1}과 공동연구가 가능한 분야를 알려줘",
    ],

    "collaboration_project": [
        "{output_top1}의 정부과제 참여 이력을 알려줘",
        "{input_data} 분야의 특허 기반 협업 기업을 추천해줘",
        "{output_top1}의 연구 역량을 분석해줘",
    ],

    "collaboration_hybrid": [
        "{output_top1}의 종합 역량 분석을 해줘",
        "{input_data} 분야의 특허 출원 순위를 알려줘",
        "{input_data} 관련 공공장비 보유 기관을 알려줘",
    ],

    # ===== 장비 검색 =====
    "equipment_kpi": [
        "{input_data} 측정 장비를 보유한 기관 목록을 알려줘",
        "{output_top1} 기관의 다른 보유 장비를 알려줘",
        "{input_data} 관련 연구를 수행한 기관을 추천해줘",
    ],

    "equipment_by_name": [
        "{output_top1}의 다른 공공장비 목록을 알려줘",
        "{input_data} 장비를 활용한 연구과제를 알려줘",
        "{output_top1}의 연구 분야를 알려줘",
    ],

    "equipment_by_org": [
        "{output_top1}의 성능 사양을 자세히 알려줘",
        "이 기관과 유사한 장비를 보유한 다른 기관을 알려줘",
        "이 기관의 정부과제 수행 이력을 알려줘",
    ],

    "equipment_region": [
        "{input_data} 지역의 다른 유형 장비를 알려줘",
        "{output_top1} 장비의 상세 사양을 알려줘",
        "다른 지역의 동일 장비 보유 기관을 알려줘",
    ],

    # ===== 사업공고/배점표 =====
    "evalp_score": [
        "{output_top1} 사업의 우대조건을 알려줘",
        "{input_data} 관련 다른 사업공고를 검색해줘",
        "이 사업에 참여한 기관 이력을 알려줘",
    ],

    "evalp_pref": [
        "{input_data} 우대조건이 있는 다른 사업을 알려줘",
        "{output_top1} 사업의 전체 배점표를 알려줘",
        "여성기업 우대하는 사업공고를 알려줘",
    ],

    "pref_task_search": [
        "{output_top1} 사업의 배점표를 자세히 알려줘",
        "중소기업 가점이 있는 사업을 알려줘",
        "청년창업 우대 사업을 검색해줘",
    ],

    # ===== 기술분류 추천 =====
    "tech_classification_6t": [
        "{input_data} 분야의 신산업기술분류코드를 추천해줘",
        "{input_data} 분야의 NTIS 과학기술분류를 추천해줘",
        "{output_top1} 코드와 관련된 사업공고를 검색해줘",
    ],

    "tech_classification_industrial": [
        "{input_data} 분야의 6T_CODE를 추천해줘",
        "{input_data} 관련 정부과제를 검색해줘",
        "{output_top1} 분류의 특허 출원 현황을 알려줘",
    ],

    "tech_classification_ntis": [
        "{input_data} 분야의 6T_CODE를 추천해줘",
        "{input_data} 관련 연구개발 사업을 검색해줘",
        "{output_top1} 분류의 연구동향을 알려줘",
    ],

    "tech_classification_ksic": [
        "{input_data} 분야의 관련 산업 동향을 알려줘",
        "{output_top1} 산업의 주요 기업을 알려줘",
    ],

    # ===== 정부과제 =====
    "project_kpi": [
        "{output_top1} 과제의 상세 정보를 알려줘",
        "{input_data} KPI 관련 다른 과제를 검색해줘",
        "이 과제의 수행 기관 정보를 알려줘",
    ],

    "project_program": [
        "{output_top1} 사업의 참여 조건을 알려줘",
        "유사한 정부사업을 추천해줘",
        "이 사업의 최근 공고를 검색해줘",
    ],

    # ===== 기본 쿼리 타입 =====
    "list": [
        "{input_data} 관련 통계를 알려줘",
        "{output_top1}의 상세 정보를 알려줘",
        "유사한 항목을 더 검색해줘",
    ],

    "aggregation": [
        "{input_data} 분야의 연도별 추이를 알려줘",
        "{input_data} 분야의 기관별 현황을 알려줘",
        "다른 분야와 비교해줘",
    ],

    "comparison": [
        "더 자세한 비교 분석을 해줘",
        "연도별 비교 추이를 알려줘",
        "분야별 세부 비교를 알려줘",
    ],
}


# ============================================================================
# 후속질문 생성 함수
# ============================================================================

def get_followup_questions(
    query_subtype: str,
    input_data: str = "",
    output_top1: str = "",
    max_questions: int = 3
) -> List[str]:
    """
    Subtype에 맞는 후속질문 생성

    Args:
        query_subtype: 쿼리 서브타입
        input_data: 사용자 입력 데이터 (기술분야, 키워드 등)
        output_top1: 결과 1위 항목 (기관명, 기업명 등)
        max_questions: 최대 질문 수 (default: 3)

    Returns:
        후속질문 리스트
    """
    templates = SUBTYPE_FOLLOWUP_MAP.get(query_subtype, [])

    if not templates:
        # fallback: 기본 질문
        templates = SUBTYPE_FOLLOWUP_MAP.get("list", [])

    # 변수 치환
    questions = []
    for template in templates[:max_questions]:
        question = template
        if input_data:
            question = question.replace("{input_data}", input_data)
        if output_top1:
            question = question.replace("{output_top1}", output_top1)

        # 치환되지 않은 변수가 있으면 스킵
        if "{input_data}" not in question and "{output_top1}" not in question:
            questions.append(question)
        elif input_data and "{output_top1}" in question:
            # output_top1이 없어도 input_data가 있으면 부분 치환
            question = question.replace("{output_top1}", "해당 기관")
            questions.append(question)

    return questions


def get_followup_from_result(
    query_subtype: str,
    keywords: List[str],
    sql_result_rows: List[Dict[str, Any]],
    max_questions: int = 3
) -> List[str]:
    """
    SQL 결과에서 후속질문 생성

    Args:
        query_subtype: 쿼리 서브타입
        keywords: 검색 키워드 리스트
        sql_result_rows: SQL 결과 행 리스트
        max_questions: 최대 질문 수

    Returns:
        후속질문 리스트
    """
    # input_data: 첫 번째 키워드
    input_data = keywords[0] if keywords else ""

    # output_top1: 결과의 첫 번째 행에서 주요 필드 추출
    output_top1 = ""
    if sql_result_rows:
        first_row = sql_result_rows[0]
        # 우선순위: company_name > org_name > name > 첫 번째 값
        for key in ["company_name", "org_name", "name", "announcement_name", "equipment_name"]:
            if key in first_row and first_row[key]:
                output_top1 = str(first_row[key])
                break
        if not output_top1:
            # 첫 번째 문자열 값 사용
            for value in first_row.values():
                if isinstance(value, str) and value:
                    output_top1 = value
                    break

    return get_followup_questions(
        query_subtype=query_subtype,
        input_data=input_data,
        output_top1=output_top1,
        max_questions=max_questions
    )


# ============================================================================
# 유틸리티 함수
# ============================================================================

def list_supported_subtypes() -> List[str]:
    """지원하는 모든 subtype 목록 반환"""
    return list(SUBTYPE_FOLLOWUP_MAP.keys())


def has_followup_template(query_subtype: str) -> bool:
    """해당 subtype에 후속질문 템플릿이 있는지 확인"""
    return query_subtype in SUBTYPE_FOLLOWUP_MAP
