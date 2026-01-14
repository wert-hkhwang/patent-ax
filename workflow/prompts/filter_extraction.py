"""
필터 조건 추출기
- 자연어 질문에서 SQL 필터 조건 추출
- 국가 코드, 연도, 금액, TOP N 등 인식
"""

import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FilterConditions:
    """추출된 필터 조건"""
    country_codes: List[str] = field(default_factory=list)
    year_range: Optional[Tuple[int, int]] = None
    amount_min: Optional[int] = None
    amount_max: Optional[int] = None
    limit: Optional[int] = None
    order_by: Optional[str] = None
    order_direction: str = "DESC"
    preference_keywords: List[str] = field(default_factory=list)
    entity_name: Optional[str] = None  # {중괄호} 내 엔티티명
    raw_filters: Dict[str, Any] = field(default_factory=dict)


# 국가 코드 매핑
COUNTRY_CODES = {
    "KR": ["한국", "국내", "대한민국", "KR"],
    "US": ["미국", "US", "USA", "America"],
    "JP": ["일본", "JP", "Japan"],
    "CN": ["중국", "CN", "China"],
    "EU": ["유럽", "EU", "Europe"],
    "DE": ["독일", "DE", "Germany"],
    "GB": ["영국", "GB", "UK", "Britain"],
    "FR": ["프랑스", "FR", "France"],
}

# 우대/가점 키워드
PREFERENCE_KEYWORDS = [
    "여성기업", "여성", "중소기업", "중소", "벤처", "스타트업",
    "지역기업", "지역", "청년", "장애인", "사회적기업",
    "소기업", "소상공인", "혁신기업"
]

# 연도 패턴
YEAR_PATTERNS = [
    (r"(\d{4})년(?:부터|이후|~)", "start"),  # 2020년부터
    (r"(?:~|까지)(\d{4})년", "end"),  # ~2023년
    (r"(\d{4})\s*[-~]\s*(\d{4})", "range"),  # 2020-2023
    (r"최근\s*(\d+)\s*년", "recent"),  # 최근 5년
    (r"(\d{4})년도?(?:\s|$|의|에)", "single"),  # 2023년
]

# 금액 패턴
AMOUNT_PATTERNS = [
    (r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*억(?:\s*원)?", 100000000),  # 10억
    (r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*천만(?:\s*원)?", 10000000),  # 5천만원
    (r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*백만(?:\s*원)?", 1000000),  # 100백만원
    (r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*만(?:\s*원)?", 10000),  # 1만원
]

# TOP N 패턴
LIMIT_PATTERNS = [
    r"(?:TOP|top|Top)\s*(\d+)",
    r"상위\s*(\d+)",
    r"(\d+)\s*개",
    r"(\d+)\s*건",
]

# 정렬 키워드
ORDER_KEYWORDS = {
    "예산": ("tot_rsrh_blgn_amt", "DESC"),
    "연구비": ("tot_rsrh_blgn_amt", "DESC"),
    "금액": ("tot_rsrh_blgn_amt", "DESC"),
    "최신": ("created_at", "DESC"),
    "최근": ("created_at", "DESC"),
    "오래된": ("created_at", "ASC"),
    "피인용": ("citation_count", "DESC"),
    "인용": ("citation_count", "DESC"),
    "출원": ("ptnaplc_ymd", "DESC"),
}


def extract_country_codes(query: str) -> List[str]:
    """국가 코드 추출"""
    found_codes = []
    query_upper = query.upper()

    for code, keywords in COUNTRY_CODES.items():
        for kw in keywords:
            if kw.upper() in query_upper or kw in query:
                if code not in found_codes:
                    found_codes.append(code)
                break

    return found_codes


def extract_year_range(query: str) -> Optional[Tuple[int, int]]:
    """연도 범위 추출"""
    current_year = datetime.now().year

    for pattern, ptype in YEAR_PATTERNS:
        match = re.search(pattern, query)
        if match:
            if ptype == "range":
                start_year = int(match.group(1))
                end_year = int(match.group(2))
                return (start_year, end_year)
            elif ptype == "start":
                start_year = int(match.group(1))
                return (start_year, current_year)
            elif ptype == "end":
                end_year = int(match.group(1))
                return (2000, end_year)
            elif ptype == "recent":
                years = int(match.group(1))
                return (current_year - years, current_year)
            elif ptype == "single":
                year = int(match.group(1))
                return (year, year)

    return None


def extract_amount_condition(query: str) -> Tuple[Optional[int], Optional[int]]:
    """금액 조건 추출"""
    amount_min = None
    amount_max = None

    for pattern, multiplier in AMOUNT_PATTERNS:
        matches = re.findall(pattern, query)
        for match in matches:
            amount_str = match.replace(",", "")
            amount = int(float(amount_str) * multiplier)

            # "이상", "초과" → min
            if re.search(rf"{match}.*(?:이상|초과|넘는)", query):
                amount_min = amount
            # "이하", "미만" → max
            elif re.search(rf"{match}.*(?:이하|미만|아래)", query):
                amount_max = amount
            else:
                # 기본: min으로 해석
                amount_min = amount

    return (amount_min, amount_max)


def extract_limit(query: str) -> Optional[int]:
    """LIMIT 추출"""
    for pattern in LIMIT_PATTERNS:
        match = re.search(pattern, query)
        if match:
            return int(match.group(1))
    return None


def extract_order_by(query: str) -> Tuple[Optional[str], str]:
    """정렬 조건 추출"""
    for keyword, (column, direction) in ORDER_KEYWORDS.items():
        if keyword in query:
            # "가장 큰", "가장 많은" → DESC
            if "가장" in query:
                return (column, "DESC")
            # "가장 작은", "가장 적은" → ASC
            if re.search(r"가장\s*(작|적|낮)", query):
                return (column, "ASC")
            return (column, direction)
    return (None, "DESC")


def extract_preference_keywords(query: str) -> List[str]:
    """우대/가점 키워드 추출"""
    found = []
    for kw in PREFERENCE_KEYWORDS:
        if kw in query:
            found.append(kw)
    return found


def extract_entity_name(query: str) -> Optional[str]:
    """중괄호 내 엔티티명 추출"""
    match = re.search(r"\{([^}]+)\}", query)
    if match:
        return match.group(1)
    return None


def extract_filter_conditions(query: str) -> FilterConditions:
    """질문에서 모든 필터 조건 추출

    Args:
        query: 사용자 질문

    Returns:
        FilterConditions 객체
    """
    # 국가 코드
    country_codes = extract_country_codes(query)

    # 연도 범위
    year_range = extract_year_range(query)

    # 금액 조건
    amount_min, amount_max = extract_amount_condition(query)

    # LIMIT
    limit = extract_limit(query)

    # 정렬
    order_by, order_direction = extract_order_by(query)

    # 우대 키워드
    preference_keywords = extract_preference_keywords(query)

    # 엔티티명
    entity_name = extract_entity_name(query)

    return FilterConditions(
        country_codes=country_codes,
        year_range=year_range,
        amount_min=amount_min,
        amount_max=amount_max,
        limit=limit,
        order_by=order_by,
        order_direction=order_direction,
        preference_keywords=preference_keywords,
        entity_name=entity_name
    )


def format_filters_for_prompt(conditions: FilterConditions) -> str:
    """필터 조건을 프롬프트용 텍스트로 포맷"""
    lines = []

    if conditions.entity_name:
        lines.append(f"- 대상 엔티티: {conditions.entity_name}")

    if conditions.country_codes:
        lines.append(f"- 국가 필터: {', '.join(conditions.country_codes)}")

    if conditions.year_range:
        start, end = conditions.year_range
        if start == end:
            lines.append(f"- 연도: {start}년")
        else:
            lines.append(f"- 연도 범위: {start}년 ~ {end}년")

    if conditions.amount_min:
        lines.append(f"- 최소 금액: {conditions.amount_min:,}원")

    if conditions.amount_max:
        lines.append(f"- 최대 금액: {conditions.amount_max:,}원")

    if conditions.limit:
        lines.append(f"- 결과 제한: TOP {conditions.limit}")

    if conditions.order_by:
        direction = "내림차순" if conditions.order_direction == "DESC" else "오름차순"
        lines.append(f"- 정렬: {conditions.order_by} {direction}")

    if conditions.preference_keywords:
        lines.append(f"- 우대/가점 조건: {', '.join(conditions.preference_keywords)}")

    return "\n".join(lines) if lines else "추출된 필터 조건 없음"


def conditions_to_sql_where(conditions: FilterConditions, table_alias: str = "") -> str:
    """필터 조건을 SQL WHERE 절로 변환

    Args:
        conditions: 필터 조건
        table_alias: 테이블 별칭 (예: "p.")

    Returns:
        WHERE 절 문자열 (WHERE 제외)
    """
    clauses = []
    prefix = f"{table_alias}." if table_alias else ""

    # 국가 코드 (특허용)
    if conditions.country_codes:
        codes_str = ", ".join([f"'{c}'" for c in conditions.country_codes])
        clauses.append(f"{prefix}applicant_country IN ({codes_str})")

    # 연도 범위
    if conditions.year_range:
        start, end = conditions.year_range
        clauses.append(f"EXTRACT(YEAR FROM {prefix}created_at) BETWEEN {start} AND {end}")

    # 금액
    if conditions.amount_min:
        clauses.append(f"{prefix}tot_rsrh_blgn_amt >= {conditions.amount_min}")
    if conditions.amount_max:
        clauses.append(f"{prefix}tot_rsrh_blgn_amt <= {conditions.amount_max}")

    return " AND ".join(clauses) if clauses else ""


# 테스트용
if __name__ == "__main__":
    test_queries = [
        "{전력반도체} 분야의 KR 특허에 대해 주요 출원기관 TOP 10을 알려줘",
        "최근 5년간 예산이 10억 이상인 과제",
        "2020년부터 2023년까지의 인공지능 연구",
        "{구매조건부신제품개발사업} 관련 여성기업 가점 기준",
        "미국 특허 상위 20개",
    ]

    print("=== 필터 조건 추출 테스트 ===\n")
    for query in test_queries:
        print(f"질문: {query}")
        conditions = extract_filter_conditions(query)
        print(f"엔티티: {conditions.entity_name}")
        print(f"국가: {conditions.country_codes}")
        print(f"연도: {conditions.year_range}")
        print(f"금액: min={conditions.amount_min}, max={conditions.amount_max}")
        print(f"LIMIT: {conditions.limit}")
        print(f"우대: {conditions.preference_keywords}")
        print(f"\n포맷:\n{format_filters_for_prompt(conditions)}")
        print("-" * 50)
