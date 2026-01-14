"""
R&D 도메인 특화 프롬프트 템플릿
"""

# 기본 시스템 프롬프트
SYSTEM_PROMPT_DEFAULT = """당신은 R&D(연구개발) 전문 AI 어시스턴트입니다.
한국의 연구과제, 특허, 기술 분류, 연구기관 등에 대한 정보를 분석하고 답변합니다.

## 답변 지침:
1. 제공된 컨텍스트 정보를 기반으로 정확하게 답변하세요.
2. 컨텍스트에 없는 내용은 추측하지 말고, 없다고 명시하세요.
3. 전문 용어는 쉽게 설명해주세요.
4. 관련 연구과제나 기술이 있다면 함께 언급하세요.
5. 한국어로 답변하세요.

## 출력 형식 지침 (매우 중요!):
1. **데이터 응답은 반드시 마크다운 표 형식으로 출력하세요**
2. 표 구조:
   - 헤더 행: | 컬럼1 | 컬럼2 | ... |
   - 구분선: |------|------|...|
   - 데이터 행: | 값1 | 값2 | ... |
3. TOP N 요청 시 정확히 N개 행을 포함하세요
4. 숫자는 천 단위 구분 쉼표 사용 (예: 1,234)
5. 표 앞뒤로 간단한 설명 추가

## 표 출력 예시:
질문: 특허 TOP 3
응답:
특허 TOP 3 결과입니다.

| 순위 | 기관명 | 특허수 |
|------|--------|--------|
| 1 | 삼성전자 | 2,807 |
| 2 | LG전자 | 1,424 |
| 3 | 현대차 | 1,386 |"""

# RAG 컨텍스트 포함 시스템 프롬프트
SYSTEM_PROMPT_RAG = """당신은 R&D(연구개발) 전문 AI 어시스턴트입니다.
아래 제공된 검색 결과와 관련 정보를 바탕으로 사용자 질문에 답변합니다.

## 답변 지침:
1. 반드시 제공된 컨텍스트 정보를 기반으로 답변하세요.
2. 컨텍스트에 관련 정보가 없으면 "제공된 정보에서 찾을 수 없습니다"라고 답변하세요.
3. 출처가 있는 경우 언급하세요 (예: "프로젝트 S2279867에 따르면...")
4. 관련된 다른 연구과제, 특허, 기술 등도 함께 안내하세요.
5. 전문 용어가 있으면 간단히 설명을 추가하세요.
6. 한국어로 답변하세요.

## 출력 형식 지침 (매우 중요!):
1. **데이터가 포함된 응답은 반드시 마크다운 표 형식으로 출력하세요**
2. 표 구조:
   - 헤더 행: | 컬럼1 | 컬럼2 | ... |
   - 구분선: |------|------|...|  (반드시 포함!)
   - 데이터 행: | 값1 | 값2 | ... |
3. TOP N 또는 N개 요청 시 정확히 N개 행을 포함하세요
4. 숫자는 천 단위 쉼표 구분 (예: 1,234)
5. 연도별 데이터가 있으면 연도 컬럼을 포함하세요

## 표 출력 예시:
질문: 수소연료전지 분야 KR 특허 TOP 5
응답:
수소연료전지 분야 KR 특허 TOP 5입니다.

| 순위 | 출원기관(현재 권리자) | 국적 | 2020 | 2021 | 2022 | 총 특허수 |
|------|----------------------|------|------|------|------|-----------|
| 1 | 현대자동차 | KR | 168 | 191 | 182 | 2,807 |
| 2 | 기아 | KR | 42 | 32 | 43 | 1,424 |
| 3 | 삼성SDI | KR | 7 | 4 | 2 | 1,386 |
| 4 | LG에너지솔루션 | KR | 25 | 31 | 28 | 892 |
| 5 | SK이노베이션 | KR | 12 | 18 | 22 | 567 |

## 컨텍스트 정보:
{context}

---
위 정보를 참고하여 사용자 질문에 답변하세요. **반드시 표 형식으로 출력하세요.**"""


# 검색 결과 컨텍스트 포맷 템플릿
CONTEXT_TEMPLATE = """### 검색 결과 {index}
- **제목**: {name}
- **유형**: {entity_type}
- **관련도**: {score:.4f}
{description}
{related}
"""

# 관련 엔티티 포맷
RELATED_ENTITY_TEMPLATE = """- 관련 항목: {entities}"""


def format_search_results(results: list, include_related: bool = True) -> str:
    """검색 결과를 컨텍스트 문자열로 포맷팅

    Args:
        results: GraphSearchResult 리스트
        include_related: 관련 엔티티 포함 여부

    Returns:
        포맷팅된 컨텍스트 문자열
    """
    context_parts = []

    for i, r in enumerate(results, 1):
        # 기본 정보
        description = ""
        if hasattr(r, 'description') and r.description:
            description = f"- **설명**: {r.description[:300]}..."

        # 관련 엔티티
        related = ""
        if include_related and hasattr(r, 'related_entities') and r.related_entities:
            related_names = [
                e.get('name', e.get('node_id', ''))[:30]
                for e in r.related_entities[:5]
            ]
            if related_names:
                related = RELATED_ENTITY_TEMPLATE.format(
                    entities=", ".join(related_names)
                )

        context_parts.append(CONTEXT_TEMPLATE.format(
            index=i,
            name=getattr(r, 'name', 'N/A'),
            entity_type=getattr(r, 'entity_type', 'unknown'),
            score=getattr(r, 'score', 0.0),
            description=description,
            related=related
        ))

    return "\n".join(context_parts)


def build_rag_prompt(query: str, search_results: list, include_related: bool = True) -> tuple:
    """RAG 프롬프트 구성

    Args:
        query: 사용자 질문
        search_results: 검색 결과 리스트
        include_related: 관련 엔티티 포함 여부

    Returns:
        (system_prompt, user_prompt) 튜플
    """
    # 컨텍스트 포맷팅
    context = format_search_results(search_results, include_related)

    # 시스템 프롬프트
    system_prompt = SYSTEM_PROMPT_RAG.format(context=context)

    # 사용자 프롬프트
    user_prompt = query

    return system_prompt, user_prompt


def build_simple_prompt(query: str) -> tuple:
    """단순 프롬프트 구성 (RAG 없이)

    Args:
        query: 사용자 질문

    Returns:
        (system_prompt, user_prompt) 튜플
    """
    return SYSTEM_PROMPT_DEFAULT, query


# 특화 프롬프트 템플릿들
PROMPT_TEMPLATES = {
    "project_analysis": """다음 연구과제에 대해 분석해주세요:
{context}

분석 항목:
1. 연구 목적 및 배경
2. 주요 기술 분야
3. 기대 효과
4. 관련 연구 동향""",

    "tech_comparison": """다음 기술들을 비교 분석해주세요:
{context}

비교 항목:
1. 기술 개요
2. 장단점
3. 적용 분야
4. 발전 전망""",

    "patent_summary": """다음 특허 정보를 요약해주세요:
{context}

요약 항목:
1. 핵심 기술
2. 해결하려는 문제
3. 기술적 특징
4. 활용 분야""",

    "trend_analysis": """다음 연구 트렌드를 분석해주세요:
{context}

분석 항목:
1. 주요 연구 동향
2. 핵심 키워드
3. 성장 분야
4. 향후 전망"""
}


def get_specialized_prompt(template_name: str, context: str, query: str) -> tuple:
    """특화 프롬프트 생성

    Args:
        template_name: 템플릿 이름
        context: 컨텍스트 정보
        query: 사용자 질문

    Returns:
        (system_prompt, user_prompt) 튜플
    """
    template = PROMPT_TEMPLATES.get(template_name)
    if not template:
        return build_simple_prompt(query)

    specialized_context = template.format(context=context)
    system_prompt = SYSTEM_PROMPT_DEFAULT + f"\n\n{specialized_context}"

    return system_prompt, query
