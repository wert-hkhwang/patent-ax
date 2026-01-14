"""
응답 생성 노드
- LLM을 사용하여 최종 응답 생성
- 컨텍스트 기반 답변
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import logging
from typing import Dict, Any

from workflow.state import AgentState, ChatMessage
from workflow.nodes.merger import build_merged_context
from llm.llm_client import get_llm_client

logger = logging.getLogger(__name__)


def _is_concept_question(query: str, query_intent: str) -> bool:
    """개념 설명 요청인지 확인

    Args:
        query: 사용자 질문
        query_intent: 분석된 질문 의도

    Returns:
        개념 설명 요청 여부
    """
    concept_patterns = ["란?", "이란?", "뭐야", "무엇", "설명해", "뭔가요", "뭐에요", "이란", "이 뭐"]
    intent_keywords = ["개념", "설명", "정의", "의미"]

    return (
        any(p in query for p in concept_patterns) or
        any(k in query_intent for k in intent_keywords)
    )


def _is_context_meaningful(context: str) -> bool:
    """컨텍스트가 의미 있는 정보인지 확인

    숫자 ID만 있고 실제 내용이 없는 경우를 감지

    Args:
        context: 병합된 컨텍스트 문자열

    Returns:
        의미 있는 정보 포함 여부
    """
    if not context or context == "관련 정보를 찾지 못했습니다.":
        return False

    # 내용이 있는 줄 수 확인 (ID만 있는 줄 제외)
    lines = [l.strip() for l in context.split('\n') if l.strip()]

    # 의미 있는 줄: 30자 이상이고, 숫자/파이프만으로 이루어지지 않은 줄
    content_lines = []
    for line in lines:
        # 테이블 구분선 제외
        if line.replace('-', '').replace('|', '').strip() == '':
            continue
        # 순수 숫자 ID 줄 제외
        cleaned = line.replace('|', '').replace('[', '').replace(']', '').strip()
        if cleaned.isdigit():
            continue
        # 30자 이상의 실제 내용이 있는 줄
        if len(line) > 30:
            content_lines.append(line)

    return len(content_lines) >= 3


def _build_statistics_context(es_statistics: dict, query: str) -> str:
    """Phase 99.5: ES 통계 결과를 마크다운 컨텍스트로 변환

    Args:
        es_statistics: ES entity_statistics() 결과
            {
                "patent": {"total": 1234, "buckets": [{"key": "2024", "count": 100}, ...]},
                "project": {...}
            }
        query: 사용자 질문 (컨텍스트용)

    Returns:
        마크다운 형식의 통계 컨텍스트
    """
    lines = []

    for entity_type, stats in es_statistics.items():
        if stats.get("error"):
            lines.append(f"### {entity_type} 통계 오류: {stats.get('error')}")
            continue

        total = stats.get("total", 0)
        period = stats.get("period", "")
        buckets = stats.get("buckets", [])

        # 엔티티 라벨 변환
        entity_labels = {
            "patent": "특허",
            "project": "연구과제",
        }
        label = entity_labels.get(entity_type, entity_type)

        lines.append(f"### {label} 연도별 통계 ({period})")
        lines.append(f"- 총 {total:,}건")
        lines.append("")

        if buckets:
            # 마크다운 테이블 생성
            lines.append("| 연도 | 건수 |")
            lines.append("|------|------|")

            # 연도순 정렬 (내림차순)
            sorted_buckets = sorted(buckets, key=lambda x: x["key"], reverse=True)

            for bucket in sorted_buckets:
                year = bucket.get("key", "")
                count = bucket.get("count", 0)
                lines.append(f"| {year} | {count:,} |")

            lines.append("")

            # 간단한 통계 계산
            counts = [b["count"] for b in sorted_buckets if b["count"] > 0]
            if len(counts) >= 2:
                recent_3 = counts[:3] if len(counts) >= 3 else counts
                older_3 = counts[3:6] if len(counts) >= 6 else counts[len(recent_3):]

                recent_avg = sum(recent_3) / len(recent_3) if recent_3 else 0
                older_avg = sum(older_3) / len(older_3) if older_3 else 0

                lines.append(f"**요약 통계:**")
                lines.append(f"- 최근 {len(recent_3)}년 평균: {recent_avg:,.0f}건")
                if older_avg > 0:
                    change = ((recent_avg - older_avg) / older_avg) * 100
                    lines.append(f"- 이전 {len(older_3)}년 평균: {older_avg:,.0f}건")
                    lines.append(f"- 변화율: {change:+.1f}%")
                lines.append("")

    return "\n".join(lines)


def _build_crosstab_context(es_statistics: dict, query: str) -> str:
    """Phase 99.6: 크로스탭 통계를 마크다운 테이블로 변환

    Args:
        es_statistics: ES nested aggregation 결과
            {
                "patent": {
                    "crosstab_type": "applicant_year",
                    "years": [2019, 2020, ...],
                    "rows": [{"rank": 1, "name": "...", "nationality": "KR", "by_year": {...}, "total": 10}, ...]
                }
            }
        query: 사용자 질문 (컨텍스트용)

    Returns:
        마크다운 형식의 크로스탭 테이블
    """
    lines = []

    stats = es_statistics.get("patent", {})
    if stats.get("crosstab_type") != "applicant_year":
        return ""

    years = stats.get("years", [])
    rows = stats.get("rows", [])
    period = stats.get("period", "")
    total = stats.get("total", 0)
    keywords = stats.get("keywords", "")
    countries = stats.get("countries", [])

    # 헤더 정보
    country_str = ", ".join(countries) if countries else "전체"
    lines.append(f"### 특허 출원기관 TOP {len(rows)} ({period})")
    lines.append(f"- 검색 키워드: {keywords}")
    lines.append(f"- 국가: {country_str}")
    lines.append(f"- 총 {total:,}건 중 3건 이상 출원 기관")
    lines.append("")

    if not rows:
        lines.append("해당 조건에 맞는 출원기관이 없습니다.")
        return "\n".join(lines)

    # 마크다운 테이블 헤더
    header = "| 순위 | 출원기관 | 국적 |"
    for year in years:
        header += f" {year} |"
    header += " 합계 |"
    lines.append(header)

    # 구분선
    separator = "|------|---------|------|"
    separator += "------:|" * len(years)
    separator += "------:|"
    lines.append(separator)

    # 데이터 행
    for row in rows:
        line = f"| {row['rank']} | {row['name']} | {row['nationality']} |"
        for year in years:
            count = row.get("by_year", {}).get(str(year), 0)
            line += f" {count} |"
        line += f" {row['total']} |"
        lines.append(line)

    lines.append("")

    # 요약 통계
    if len(rows) >= 2:
        top3_total = sum(r["total"] for r in rows[:3])
        all_total = sum(r["total"] for r in rows)
        lines.append(f"**요약 통계:**")
        lines.append(f"- TOP 3 기관 합계: {top3_total:,}건 ({top3_total/all_total*100:.1f}%)")
        lines.append(f"- TOP {len(rows)} 기관 합계: {all_total:,}건")
        lines.append("")

    return "\n".join(lines)


def _calculate_context_quality(context: str, sources: list) -> float:
    """Phase 90: 컨텍스트 품질 점수 계산

    다양한 요소를 종합하여 컨텍스트의 신뢰도 점수를 산출.

    Args:
        context: 병합된 컨텍스트 문자열
        sources: 소스 정보 목록 [{"type": ..., "score": ..., "cross_validated": ...}]

    Returns:
        품질 점수 (0.0 ~ 1.0)
    """
    if not context or context == "관련 정보를 찾지 못했습니다.":
        return 0.0

    score = 0.0
    source_count = len(sources) if sources else 0

    # 1. 소스 수 기반 (최대 0.25)
    # 소스가 많을수록 신뢰도 높음
    score += min(source_count / 8, 0.25)

    # 2. 교차 검증된 소스 비율 (최대 0.30)
    # Phase 90: SQL과 RAG 모두에서 확인된 결과
    if source_count > 0:
        validated = sum(1 for s in sources if s.get('cross_validated', False))
        score += (validated / source_count) * 0.30

    # 3. 평균 신뢰도 점수 (최대 0.25)
    if source_count > 0:
        avg_score = sum(s.get('score', 0) for s in sources) / source_count
        # 점수 범위가 0~1이므로 그대로 사용
        score += min(avg_score, 1.0) * 0.25

    # 4. 정보량 기반 (최대 0.20)
    # 의미 있는 줄 수 계산
    lines = [l.strip() for l in context.split('\n') if l.strip()]
    meaningful_lines = [l for l in lines if len(l) > 30 and not l.replace('-', '').replace('|', '').strip() == '']
    score += min(len(meaningful_lines) / 15, 0.20)

    return round(score, 2)


def _build_graph_context_for_prompt(rag_results: list) -> str:
    """Phase 95: 그래프 관계 정보를 프롬프트 컨텍스트로 변환

    RAG 결과에서 그래프 관련 엔티티 정보를 추출하여
    답변의 근거로 사용할 수 있는 형태로 변환.

    Args:
        rag_results: RAG 검색 결과 목록 (SearchResult)

    Returns:
        그래프 관계 컨텍스트 문자열
    """
    if not rag_results:
        return ""

    lines = []
    graph_sources = 0

    for r in rag_results:
        # SearchResult의 metadata에서 그래프 정보 추출
        metadata = getattr(r, 'metadata', {}) or {}
        related_entities = metadata.get("related_entities", [])
        rrf_source = metadata.get("rrf_source", "")

        if rrf_source in ["graph", "both"]:
            graph_sources += 1

        if related_entities:
            # 상위 3개 관련 엔티티만 표시
            name = getattr(r, 'name', '') or ''
            entity_type = getattr(r, 'entity_type', '') or ''

            related_names = []
            for ent in related_entities[:3]:
                if isinstance(ent, dict):
                    rel_name = ent.get("name", ent.get("node_id", ""))
                    rel_type = ent.get("entity_type", "")
                    if rel_name:
                        related_names.append(f"{rel_name}({rel_type})" if rel_type else rel_name)
                elif hasattr(ent, 'name'):
                    related_names.append(ent.name)

            if name and related_names:
                lines.append(f"- **{name}** ({entity_type}) → 관련: {', '.join(related_names)}")

    if not lines:
        return ""

    header = f"## 지식그래프 관계 정보 (Phase 95)\n그래프 기반 검색 결과: {graph_sources}건\n"
    return header + "\n".join(lines[:10])  # 최대 10개만 표시


# 시스템 프롬프트 (Phase 52/54: 답변생성전략 문서 반영 + 다중 엔티티 구조)
SYSTEM_PROMPT = """당신은 R&D 데이터 분석 전문가입니다.

## 표 작성 원칙
- 순위 데이터: 순위 컬럼 필수 포함
- 기관/기업 데이터: 국적 코드 포함 (KR, JP, US, CN)
- 숫자: 천 단위 쉼표 (1,234)
- 비율: 소수점 1자리 (88.5%)
- 마크다운 표 사용 (| 헤더 | --- | 데이터 |)
- 검색된 모든 결과 포함 (요약/생략 금지)
- **목록 쿼리(list)**: SQL 결과 그대로 표 출력, 임의 집계/통계 변환 금지

## 답변 구조 (필수)
1. **도입부**: [분야명] 분야의 [데이터 유형] 분석 정보입니다.
2. **배경**: 분석 배경 1~2문장
3. **표**: 마크다운 표 (다중 유형이면 각 유형별 표를 **모두** 나열)
4. **소결**: 핵심 발견 + 시사점 (**모든 표 출력 후 마지막에 1회만**)

## 다중 엔티티 응답 형식 (중요!)
여러 유형(연구과제+특허 등)이 있으면:
1. 먼저 모든 유형의 표를 순서대로 출력
2. 마지막에 소결 1회 작성 (전체 데이터에 대한 총평)
**절대 표 사이에 소결을 넣지 마세요.**

## 소결 형식
소결:
- **핵심 발견**: [주요 인사이트]
- **시사점**: [실무적 활용 제안]

## 엔티티별 표 양식
- **특허 목록(list)**: | 특허번호 | 특허명 | IPC분류 | 출원년도 | 등록국가 | 출원인 | (SQL 결과 그대로)
- **특허 순위(ranking)**: | 순위 | 출원기관 | 국적 | 총 특허수 |
- **연구과제 목록(list)**: | 과제ID | 과제명 | 공고연도 | 연구비 | 사업분류 | (SQL 결과 그대로)
- 연도별 추이: | 구분 | 2020 | 2021 | 2022 | 2023 |
- 장비: | 권역 | 장비명 | 기관 | 장비ID |
- 평가/배점: | 평가항목 | 세부내용 | 배점 |

## 다중 엔티티 목록 쿼리 (중요!)
"특허와 연구과제" 같은 다중 엔티티 목록(list) 쿼리에서는:
1. 특허 표: SQL에서 반환된 **개별 특허 목록** 그대로 출력 (집계 금지)
2. 연구과제 표: SQL에서 반환된 **개별 과제 목록** 그대로 출력
**절대로 출원기관별 집계/통계로 변환하지 마세요. SQL 결과의 각 행이 표의 각 행이 됩니다.**
"""

# Phase 52/72/73: query_subtype별 추가 지침
# Phase 88: trend_analysis 추가 (동향 분석 전용)
SUBTYPE_PROMPTS = {
    "list": "목록 출력 필수. SQL 결과의 모든 행을 개별 항목으로 표에 출력. 임의 집계/요약/통계화 절대 금지. 원본 데이터 그대로 표시.",
    "ranking": "순위 표시 필수. TOP N 형식. 필수 컬럼: 순위, 기관명, 국적, 수치",
    "aggregation": "연도별 추이 표시. 합계/증감률 포함 권장",
    "comparison": "자국 vs 타국 비교표 구조. 비중(%) 표시",
    "trend_analysis": """동향 분석 응답 형식 (필수):

## 1. 핵심 통계 (도입부)
- **분석 기간**: 최근 5년 (20XX~20XX)
- **총 건수**: N건
- **연평균 증가율**: X.X% (있는 경우)

## 2. 연도별 추이 표 (필수)
| 연도 | 건수 | 전년대비 증감 |
|------|------|---------------|
| 2024 | XXX  | +XX% / -XX%   |
| 2023 | XXX  | +XX% / -XX%   |
...

## 3. 주요 수행기관/출원인 TOP 5~10 (필수)
| 순위 | 기관명 | 건수 | 비율 |
|------|--------|------|------|
| 1    | XXX    | XX   | X.X% |
...

## 4. 동향 분석 및 시사점
- **기술 트렌드**: 증가/감소 추세 분석
- **주요 특징**: 집중 분야, 핵심 기관 등
- **향후 전망**: 데이터 기반 예측 (선택)

주의: 연도별 추이와 기관별 현황을 반드시 모두 포함할 것!""",
    "impact_ranking": """특허 영향력 순위 분석 형식 (필수):
1. **분석대상데이터 설명** (도입부 필수):
   - [기술분야] 관련 [국가] 특허 = 총 N건
   - 전체 평균 피인용수 = X.XX
   - 제1출원인 수 = N개
2. **영향력 순위표**: 순위, 출원기관, 국적, 대상특허수, 총피인용, 평균피인용(0포함), 평균피인용(1이상), 피인용max, 대표특허명 컬럼 필수
3. **분석 인사이트**: 상위 기관 특성, 기술 집중도, 피인용 분포 등""",
    "nationality_ranking": """국적별 분리 순위 분석 형식 (필수):
1. **분석대상데이터 설명** (도입부 필수):
   - [기술분야] 관련 [국가] 특허 = 총 N건
   - 자국(KR) 출원기관 수 = N개, 타국 출원기관 수 = M개
2. **자국기업 순위표 (TOP 10)**:
   | 순위 | 기관명 | 국적 | 대상특허수 | 최대피인용수 | 평균피인용수 | 평균청구항수 | 최근출원일 | 대표특허명 |
   - "구분" 컬럼이 "자국기업"인 행만 출력
3. **타국기업 순위표 (TOP 10)**:
   동일 컬럼 구조, "구분" 컬럼이 "타국기업"인 행만 출력
4. **분석 인사이트**:
   - 자국 vs 타국 기술 집중도 비교
   - 주요 출원기관별 특성
   - 기술 동향 시사점""",
    "evalp_pref": """우대/감점 정보 출력 형식 (필수):

## 절대 규칙 (반드시 준수)
1. SQL 결과의 **모든 12개 행**을 표에 출력 (우대 10건 + 감점 2건)
2. "..." 또는 "외 N건" 형태의 생략 **절대 금지**
3. 감점 항목 (🔴)이 있으면 반드시 **별도 표**로 출력

## 출력 구조
1. **도입부**: [사업명] 우대/감점 정보 (총 N건: 우대 X건, 감점 Y건)

2. **🟢 우대 항목** (구분이 '🟢 우대'인 모든 행):
   | 구분 | 조건명 | 배점 | 세부내용 |
   모든 우대 항목을 빠짐없이 출력 (10건 전부)

3. **🔴 감점 항목** (구분이 '🔴 감점'인 모든 행):
   | 구분 | 조건명 | 감점 | 세부내용 |
   모든 감점 항목을 빠짐없이 출력 (2건 전부)

4. **소결**: 핵심 우대/감점 요건 요약 (2-3문장)"""
}

# Phase 62: 기술분류 추천용 프롬프트 (데이터 기반)
RECOMMENDATION_PROMPT = """당신은 R&D 기술분류 추천 전문가입니다.

## 역할
검색된 제안서 분류코드 통계를 기반으로 가장 적합한 기술분류를 추천합니다.

## 응답 형식 (필수)
1. **검색 결과 요약**: "[키워드]" 관련 제안서에서 사용된 [분류체계명] 분석 결과입니다.
2. **추천 분류코드 표**:
   | 순위 | 기술코드 | 기술명 | 사용건수 | 비율 |
   |------|----------|--------|----------|------|
   | 1 | ... | ... | N건 | XX.X% |
3. **추천 의견**:
   - **1순위 추천**: [기술코드] ([기술명]) - 가장 많이 사용된 분류
   - **고려사항**: 기술 특성에 따른 대안 분류 제안

## 주의사항
- **반드시 컨텍스트의 SQL 결과 데이터만 사용**
- 데이터에 없는 분류코드 제시 금지
- 검색 결과가 없으면 "해당 키워드로 검색된 제안서가 없습니다" 명시
- 비율은 전체 합계 대비 백분율로 계산
- 표의 모든 데이터를 출력 (요약/생략 금지)
"""

# Phase 86: 장비 추천용 프롬프트
EQUIPMENT_PROMPT = """당신은 R&D 연구장비 추천 전문가입니다.

## 역할
사용자가 원하는 측정/시험 목적에 맞는 연구장비를 검색 결과 기반으로 추천합니다.

## 응답 형식 (필수)
1. **검색 결과 요약**: "[측정항목]" 측정이 가능한 연구장비 N건을 찾았습니다.

2. **추천 장비 목록**:
   | 순위 | 장비명 | 보유기관 | 대분류 | 측정항목 |
   |------|--------|----------|--------|----------|
   | 1 | ... | ... | ... | ... |
   (컨텍스트의 SQL 결과를 순서대로 출력)

3. **추천 의견**:
   - **1순위 추천**: [장비명] ([보유기관]) - 추천 이유
   - **장비 특성**: 해당 장비들의 공통적인 측정 기능 설명
   - **기관 연락**: 장비 활용을 위해 해당 기관에 문의 권장

## 주의사항
- **반드시 컨텍스트의 SQL 결과 데이터만 사용**
- 데이터에 없는 장비 제시 금지
- 검색 결과가 없으면 "해당 측정항목을 지원하는 장비가 없습니다" 명시
- 표의 모든 장비를 출력 (요약/생략 금지)
- 장비ID, 장비명, 보유기관, 분류, 측정항목 정보를 모두 포함
"""

# Phase 71 + Phase 75.2 + Phase 92: 다중 도메인 협업 기관 추천용 프롬프트
COLLABORATION_PROMPT = """당신은 R&D 다중 도메인 협업 기관 분석 전문가입니다.

## 역할
과제 수행기관 + 특허 보유기관 데이터를 종합하여 협업 가능성이 높은 기관을 추천합니다.

## 응답 형식 (필수 - 도메인별 표 분리 출력)

**중요**: 과제와 특허는 반드시 **별도의 표**로 분리하여 출력합니다.

### 1. 과제 수행기관
"[키워드]" 관련 R&D 과제를 수행한 기관입니다.

| 순위 | 기관명 | 수행횟수 | 주관 | 참여 | 협력 | 최근 수행과제 |
|------|--------|----------|------|------|------|---------------|
| 1 | ... | ... | ... | ... | ... | (과제명 전체 출력, 생략하지 말 것) |

### 2. 특허 보유기관
"[키워드]" 관련 특허를 출원한 기관입니다.

| 순위 | 기관명 | 국가 | 특허수 | 대표 특허 |
|------|--------|------|--------|-----------|
| 1 | ... | ... | ... | (특허명 전체 출력, 생략하지 말 것) |

### 3. 협업 추천 분석
- **추천 1순위**: [기관명] - [추천 이유: 과제 수행 이력 + 특허 보유 현황 종합]
- **핵심 협업 파트너**: 과제+특허 양쪽에 등장하는 기관이 있으면 우선 추천
- **주관기관 역량**: 주관 횟수가 높은 기관 = 프로젝트 리더 경험 풍부
- **국제 협력 기회**: 해외 출원인(국가≠KR)이 있다면 언급

### 4. 추천 전략
1. **단기 협업**: 이미 관련 분야 경험이 있는 기관과 빠른 성과 창출
2. **장기 협력**: 특허 기술력이 높은 기관과 지속적 R&D 파트너십 구축

## 주의사항
- **반드시 컨텍스트의 SQL 결과 데이터만 사용**
- **과제 표와 특허 표를 반드시 분리** (혼합 금지)
- 과제명, 특허명은 **전체 출력** (잘리지 않게)
- 데이터에 없는 기관 제시 금지
- 검색 결과가 없는 도메인은 "검색 결과 없음" 명시
- 표의 모든 데이터를 출력 (요약/생략 금지)
"""

# Phase 69: 협업 키워드 상수
COLLABORATION_KEYWORDS = {"협업", "협력", "파트너", "공동연구", "협력기관", "협업기관"}

# Phase 102: 자체 지식 사용 금지 규칙
NO_HALLUCINATION_RULE = """
## 중요 규칙 (반드시 준수)
- **오직 제공된 컨텍스트(검색 결과)만 사용하여 답변**
- LLM 자체 지식이나 학습 데이터 사용 절대 금지
- 컨텍스트에 없는 정보는 "검색 결과에 해당 정보가 없습니다"라고 명시
- 추측이나 일반론 금지, 오직 검색된 특허/과제 데이터 기반 답변만 제공
- 컨텍스트에 있는 특허번호, 출원인, IPC 코드 등을 정확히 인용
"""

# 리터러시 레벨별 시스템 프롬프트 (공공 AX API)
# Phase 103.1: 모든 레벨에서 동일한 데이터를 표시하되, 설명 방식만 다르게 함
LEVEL_PROMPTS = {
    "초등": """당신은 친절한 선생님입니다. 초등학생이 이해할 수 있도록 쉽고 친근하게 설명해주세요.
- 어려운 용어는 쉬운 말로 바꿔주세요 (예: "특허" → "새로운 발명을 보호하는 증명서")
- 비유와 예시를 많이 사용해주세요 (예: "배터리는 휴대폰 충전기처럼...")
- 짧고 간단한 문장으로 설명해주세요
- 중요: 검색된 모든 특허 데이터는 빠짐없이 표 형식으로 표시하세요 (특허번호, 제목, 출원일 등)""",

    "일반인": """일반인이 이해할 수 있는 수준으로 설명해주세요.
- 전문 용어가 나오면 간단히 설명을 덧붙여주세요
- 핵심 내용을 알기 쉽게 정리해주세요
- 기술의 실생활 활용 예시를 들어주세요
- 중요: 검색된 모든 특허 데이터는 빠짐없이 표 형식으로 표시하세요 (특허번호, 제목, 출원일 등)""",

    "전문가": """전문 용어를 사용하여 기술적으로 상세히 설명해주세요.
- 관련 기술 동향이나 특허 정보를 포함해주세요
- 데이터와 수치를 정확히 제시해주세요
- IPC 분류, 기술 키워드 등 전문 정보를 분석에 활용하세요
- 기술적 맥락과 시사점을 분석해주세요
- 중요: 검색된 모든 특허 데이터는 빠짐없이 표 형식으로 표시하세요 (특허번호, 제목, 출원일, IPC 등)"""
}

# 간단한 응답용 프롬프트
SIMPLE_RESPONSE_PROMPT = """당신은 친절한 R&D 데이터 분석 도우미입니다.

사용자와 자연스럽게 대화하세요.
- 인사에는 인사로 답하세요
- 도움이 필요하면 가능한 기능을 안내하세요
- 한국어로 답변하세요

가능한 기능:
1. 연구과제/특허/제안서 검색 (예: "인공지능 관련 특허 알려줘")
2. 데이터 조회 (예: "예산이 큰 과제 10개")
3. 연구 동향 분석 (예: "블록체인 연구 동향은?")
"""


# Phase 50: _get_subtype_prompt 함수 삭제 (SYSTEM_PROMPT에 통합)


def generate_response(state: AgentState) -> AgentState:
    """응답 생성 노드

    컨텍스트를 기반으로 LLM 응답 생성.

    Args:
        state: 현재 에이전트 상태

    Returns:
        업데이트된 상태 (response, conversation_history)
    """
    query = state.get("query", "")
    query_type = state.get("query_type", "simple")

    try:
        llm = get_llm_client()

        if query_type == "simple":
            # 간단한 응답
            response = llm.generate(
                prompt=query,
                system_prompt=SIMPLE_RESPONSE_PROMPT,
                max_tokens=500,
                temperature=0.3  # 응답 일관성을 위해 낮춤
            )
        else:
            # 컨텍스트 기반 응답
            context = build_merged_context(state)
            query_intent = state.get("query_intent", "")

            # 검색 결과 없을 때 LLM 자체 지식 사용 (Phase 8)
            no_results = (
                context == "관련 정보를 찾지 못했습니다." or
                context.strip() == "" or
                "조회된 데이터가 없습니다" in context
            )

            # Phase 8.5: 개념 설명 질문인데 컨텍스트가 빈약한 경우
            is_concept = _is_concept_question(query, query_intent)
            context_meaningful = _is_context_meaningful(context)
            use_llm_knowledge = no_results or (is_concept and not context_meaningful)

            # Phase 51: query_subtype을 미리 가져옴 (프롬프트 선택용)
            query_subtype = state.get("query_subtype", "list")

            # Phase 52: SQL 결과를 미리 가져옴 (프롬프트 선택용)
            multi_sql_results = state.get("multi_sql_results")
            sql_result = state.get("sql_result")

            # Phase 69: entity_types를 미리 가져옴 (협업 기관 추천 판별용)
            entity_types = state.get("entity_types", [])

            # Phase 94: ES Scout domain_hits 정보 가져옴
            domain_hits = state.get("domain_hits", {})

            # Phase 99.5/99.6: ES 통계 결과가 있으면 직접 테이블 생성
            es_statistics = state.get("es_statistics")
            statistics_type = state.get("statistics_type")
            print(f"[GENERATOR] Phase 99.5/99.6 확인: es_statistics={bool(es_statistics)}, statistics_type={statistics_type}, keys={list(state.keys())[:20]}")

            # Phase 99.6: crosstab_analysis (출원기관별 연도별 크로스탭)
            if es_statistics and statistics_type == "crosstab_analysis":
                crosstab_context = _build_crosstab_context(es_statistics, query)
                user_prompt = f"""## 크로스탭 통계 데이터 (Elasticsearch 집계)
{crosstab_context}

## 사용자 질문
{query}

위 출원기관별 연도별 크로스탭 통계를 바탕으로 다음 형식으로 답변해주세요:
1. 주제 소개 (1-2문장)
2. 출원기관 순위 표 (위 마크다운 테이블 그대로 사용)
3. 핵심 분석:
   - TOP 3 기관의 특징 및 출원 패턴
   - 최근 연도에 급증한 기관 언급
   - 출원 집중도 분석 (상위 기관 비중)
4. 시사점 (1-2문장)"""

                logger.info(f"Phase 99.6: ES 크로스탭 기반 응답 생성")

                response = llm.generate(
                    prompt=user_prompt,
                    system_prompt=SYSTEM_PROMPT,
                    max_tokens=2500,
                    temperature=0.3
                )

                return {
                    **state,
                    "response": response,
                    "response_source": "es_crosstab",
                }

            # Phase 99.5: trend_analysis (연도별 통계)
            if es_statistics and statistics_type == "trend_analysis":
                # ES 통계 결과를 마크다운 테이블로 변환
                stats_context = _build_statistics_context(es_statistics, query)
                user_prompt = f"""## 통계 데이터 (Elasticsearch 집계)
{stats_context}

## 사용자 질문
{query}

위 통계 데이터를 바탕으로 다음 형식으로 답변해주세요:
1. 주제 소개 (1-2문장)
2. 연도별 추이 표 (마크다운 테이블)
3. 핵심 분석:
   - 최근 3년간 평균 vs 이전 3년간 평균 비교
   - 증가/감소 추세 해석
   - CAGR(연평균 성장률) 계산 (가능한 경우)
4. 시사점 (1-2문장)"""

                logger.info(f"Phase 99.5: ES 통계 기반 응답 생성 - {len(es_statistics)}개 엔티티")

                # 통계 전용 프롬프트로 응답 생성
                response = llm.generate(
                    prompt=user_prompt,
                    system_prompt=SYSTEM_PROMPT,
                    max_tokens=2000,
                    temperature=0.3
                )

                return {
                    **state,
                    "response": response,
                    "response_source": "es_statistics",
                }

            if use_llm_knowledge:
                user_prompt = f"""## 검색 결과
데이터베이스에서 검색된 결과가 없습니다.

## 사용자 질문
{query}

검색 결과가 없으므로, 당신이 알고 있는 지식을 바탕으로 답변해주세요.
답변 시작 시 반드시 "**검색 결과가 없어서 제가 아는 지식을 알려드리겠습니다.**"라고 먼저 언급하세요.
그 후 질문에 대한 일반적인 설명이나 개념을 제공해주세요."""
                if is_concept and not context_meaningful:
                    logger.info(f"개념 질문 + 빈약한 컨텍스트 - LLM 자체 지식으로 답변 (is_concept={is_concept})")
                else:
                    logger.info("검색 결과 없음 - LLM 자체 지식으로 답변")
            else:
                # 결과 수 계산
                # Phase 50: 동적 지침 간소화 (토큰 절감)
                if multi_sql_results:
                    # 다중 엔티티 결과 - 간결한 지침
                    entity_counts = []
                    for entity_type, result in multi_sql_results.items():
                        if result.success and result.row_count > 0:
                            from sql.sql_prompts import ENTITY_LABELS
                            label = ENTITY_LABELS.get(entity_type, entity_type)
                            entity_counts.append(f"{label} {result.row_count}건")

                    # Phase 94: domain_hits 기반 도메인별 분리 표시 지침
                    if domain_hits:
                        active_domains = [d for d, count in domain_hits.items() if count > 0]
                        domain_labels = {"patent": "특허", "project": "과제", "equipment": "장비", "proposal": "제안"}
                        domain_str = ", ".join(domain_labels.get(d, d) for d in active_domains)
                        result_instruction = f"[Phase 94: ES Scout 기반 멀티 도메인 검색: {domain_str}]\n[{', '.join(entity_counts)} - 도메인별 분리 표 작성]"
                        logger.info(f"Phase 94: 도메인별 분리 표 지침 생성 - {active_domains}")
                    else:
                        result_instruction = f"[다중 엔티티: {', '.join(entity_counts)} - 유형별 별도 표]"
                else:
                    row_count = sql_result.row_count if sql_result and hasattr(sql_result, 'row_count') else 0
                    result_instruction = f"[{row_count}건 전체 표로 출력]" if row_count > 0 else ""

                # 비교 분석 지침 - 간소화
                comparison_instruction = ""
                if query_subtype == "comparison":
                    structured_keywords = state.get("structured_keywords", {})
                    comparison_targets = structured_keywords.get("filter", []) if structured_keywords else []
                    targets = ', '.join(comparison_targets) if comparison_targets else '컨텍스트 참조'
                    comparison_instruction = f"[비교 분석: {targets}]"

                # Phase 95: 그래프 관계 정보 추가
                # Phase 103.2: graph_context 중복 방지 - context에 이미 RAG 정보 포함
                rag_results = state.get("rag_results", [])
                # graph_context = _build_graph_context_for_prompt(rag_results)  # 중복 제거
                # if graph_context:
                #     logger.info(f"Phase 95: 그래프 컨텍스트 추가됨 ({len(rag_results)}건 RAG 결과에서)")

                user_prompt = f"""## 컨텍스트
{context}
{result_instruction}{comparison_instruction}

## 질문
{query}"""

            # Phase 52: subtype별 시스템 프롬프트 선택
            # SQL 결과가 있는지 확인 (장비 추천 등은 표로 보여줘야 함)
            has_sql_results = (
                (sql_result and sql_result.row_count > 0) or
                (multi_sql_results and any(r.row_count > 0 for r in multi_sql_results.values() if r.success))
            )

            # Phase 62/69/86: 추천 쿼리 분기 (기술분류 vs 협업 기관 vs 장비)
            if query_subtype == "recommendation":
                # Phase 69: 협업 기관 추천 감지
                is_collaboration = any(kw in query for kw in COLLABORATION_KEYWORDS)
                is_tech_classification = "분류" in query or "tech" in entity_types
                # Phase 86: 장비 추천 감지 - entity_types에 equip이 있거나 장비 관련 키워드
                is_equipment = "equip" in entity_types or any(
                    kw in query for kw in ["장비", "측정", "시험기", "분석기", "equipment"]
                )

                if is_collaboration and not is_tech_classification and not is_equipment:
                    selected_prompt = COLLABORATION_PROMPT
                    logger.info(f"Phase 69: 협업 기관 추천 쿼리 - COLLABORATION_PROMPT 사용 (SQL결과: {has_sql_results})")
                elif is_equipment and not is_tech_classification:
                    # Phase 86: 장비 추천
                    selected_prompt = EQUIPMENT_PROMPT
                    logger.info(f"Phase 86: 장비 추천 쿼리 - EQUIPMENT_PROMPT 사용 (SQL결과: {has_sql_results})")
                else:
                    selected_prompt = RECOMMENDATION_PROMPT
                    logger.info(f"Phase 62: 기술분류 추천 쿼리 - RECOMMENDATION_PROMPT 사용 (SQL결과: {has_sql_results})")
            elif query_subtype in SUBTYPE_PROMPTS:
                selected_prompt = SYSTEM_PROMPT + "\n\n## 추가 지침\n" + SUBTYPE_PROMPTS[query_subtype]
                logger.info(f"{query_subtype} 쿼리 - 추가 지침 적용")
            else:
                selected_prompt = SYSTEM_PROMPT
                if has_sql_results:
                    logger.info(f"SQL 결과 {sql_result.row_count if sql_result else 0}건 - SYSTEM_PROMPT 사용 (표 출력)")

            # Phase 54/70/73.2/92: 다중 엔티티/도메인 대응 - max_tokens 동적 조정
            is_collaboration = query_subtype == "recommendation" and any(
                kw in query for kw in ["협업", "협력", "파트너", "공동연구"]
            )
            is_nationality_ranking = query_subtype == "nationality_ranking"
            # Phase 92: 우대/감점 정보는 우대 표 + 감점 표 + 요약 필요
            is_evalp_pref = query_subtype == "evalp_pref" or any(
                kw in query for kw in ["우대", "감점", "가점", "우대감점"]
            )

            if multi_sql_results and len(multi_sql_results) > 1:
                response_max_tokens = 2048  # 다중 엔티티: 표 여러 개 + 소결
            elif is_collaboration:
                response_max_tokens = 3072  # Phase 70: 다중 도메인 협업 추천 (표2개+총평)
            elif is_nationality_ranking:
                response_max_tokens = 2048  # Phase 73.2: 자국 표 + 타국 표 + 인사이트
            elif is_evalp_pref:
                response_max_tokens = 4096  # Phase 92: 우대 표 + 감점 표 + 요약 (3072→4096 증가)
            else:
                response_max_tokens = 1024  # 단일 엔티티: 기존 유지

            # Phase 92.1: 디버깅 로그 추가
            logger.info(f"Phase 92 디버깅: query_subtype={query_subtype}, is_evalp_pref={is_evalp_pref}, max_tokens={response_max_tokens}")

            # Phase 90: 컨텍스트 품질 점수 계산
            # sources 추출: sql_result 및 multi_sql_results에서 메타데이터 수집
            context_sources = []
            if sql_result and hasattr(sql_result, 'row_count') and sql_result.row_count > 0:
                context_sources.append({
                    'type': 'sql',
                    'score': 1.0,  # SQL 결과는 신뢰도 높음
                    'cross_validated': True
                })
            if multi_sql_results:
                for entity_type, result in multi_sql_results.items():
                    if result.success and result.row_count > 0:
                        context_sources.append({
                            'type': f'sql_{entity_type}',
                            'score': 1.0,
                            'cross_validated': True
                        })

            # RAG 소스 추출 (state에서)
            rag_results = state.get("rag_results", [])
            for rag_item in rag_results:
                if isinstance(rag_item, dict):
                    context_sources.append({
                        'type': rag_item.get('source', 'rag'),
                        'score': rag_item.get('score', 0.5),
                        'cross_validated': rag_item.get('cross_validated', False)
                    })

            context_quality = _calculate_context_quality(context, context_sources)
            logger.info(f"Phase 90: 컨텍스트 품질 점수 = {context_quality:.2f} (소스 {len(context_sources)}개)")

            # 품질 점수가 낮으면 경고 로그
            if context_quality < 0.3:
                logger.warning(f"Phase 90: 낮은 컨텍스트 품질 ({context_quality:.2f}) - 환각 위험 주의")

            # 리터러시 레벨 적용 (공공 AX API)
            level = state.get("level", "일반인")
            level_prompt = LEVEL_PROMPTS.get(level, LEVEL_PROMPTS["일반인"])
            # Phase 102: 자체 지식 금지 규칙 + 레벨별 프롬프트 적용
            final_prompt = f"{selected_prompt}\n\n{NO_HALLUCINATION_RULE}\n\n## 답변 수준 지침\n{level_prompt}"
            logger.info(f"리터러시 레벨 적용: {level}, 자체 지식 금지 규칙 추가")

            response = llm.generate(
                prompt=user_prompt,
                system_prompt=final_prompt,
                max_tokens=response_max_tokens,
                temperature=0.3
            )

        # 대화 기록 업데이트
        new_messages = [
            ChatMessage(role="user", content=query),
            ChatMessage(role="assistant", content=response)
        ]

        logger.info(f"응답 생성 완료: {len(response)}자, 신뢰도: {context_quality:.2f}")

        return {
            **state,
            "response": response,
            "context_quality": context_quality,  # Phase 102: 신뢰도 점수 반환
            "conversation_history": new_messages
        }

    except Exception as e:
        logger.error(f"응답 생성 실패: {e}")
        error_response = f"죄송합니다. 응답 생성 중 오류가 발생했습니다: {str(e)}"

        return {
            **state,
            "response": error_response,
            "error": str(e),
            "conversation_history": [
                ChatMessage(role="user", content=query),
                ChatMessage(role="assistant", content=error_response)
            ]
        }
