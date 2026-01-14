"""
추천 노드
- 장비 → 과제 추천
- 과제 → 장비 추천
- 키워드 기반 매칭
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from workflow.state import AgentState
from sql.db_connector import get_db_connection

logger = logging.getLogger(__name__)


@dataclass
class RecommendationResult:
    """추천 결과"""
    item_id: str
    item_name: str
    item_type: str  # "equipment" or "project"
    score: float
    org_name: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


def recommend_equipment_for_keywords(
    keywords: List[str],
    limit: int = 10
) -> List[RecommendationResult]:
    """키워드 기반 장비 추천

    Args:
        keywords: 검색 키워드 목록
        limit: 최대 결과 수

    Returns:
        추천 장비 목록
    """
    if not keywords:
        return []

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 키워드를 AND 조건으로 검색
        keyword_conditions = " AND ".join([
            f"conts_klang_nm ILIKE %s" for _ in keywords
        ])
        params = [f"%{kw}%" for kw in keywords]
        params.append(limit)

        cursor.execute(f"""
            SELECT conts_id, conts_klang_nm, org_nm,
                   equip_grp_lv1_nm, equip_grp_lv2_nm, equip_grp_lv3_nm,
                   kpi_nm_list
            FROM f_equipments
            WHERE {keyword_conditions}
            ORDER BY org_nm
            LIMIT %s
        """, params)

        results = []
        for row in cursor.fetchall():
            # 매칭 점수 계산 (키워드 매칭 수)
            equipment_name = row[1] or ""
            match_count = sum(1 for kw in keywords if kw.lower() in equipment_name.lower())
            score = match_count / len(keywords) if keywords else 0

            results.append(RecommendationResult(
                item_id=row[0] or "",
                item_name=equipment_name,
                item_type="equipment",
                score=score,
                org_name=row[2],
                keywords=keywords,
                metadata={
                    "category_lv1": row[3],
                    "category_lv2": row[4],
                    "category_lv3": row[5],
                    "kpi_list": row[6]
                }
            ))

        conn.close()

        # 점수 순으로 정렬
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    except Exception as e:
        logger.error(f"장비 추천 실패: {e}")
        return []


def recommend_projects_for_equipment(
    equipment_name: str,
    limit: int = 10
) -> List[RecommendationResult]:
    """장비 관련 과제 추천

    장비명 또는 장비 분류를 기반으로 관련 연구과제 추천

    Args:
        equipment_name: 장비명
        limit: 최대 결과 수

    Returns:
        추천 과제 목록
    """
    if not equipment_name:
        return []

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 장비명에서 주요 키워드 추출
        keywords = equipment_name.split()

        # 과제 검색 (키워드 매칭)
        keyword_conditions = " AND ".join([
            f"conts_klang_nm ILIKE %s" for _ in keywords
        ])
        params = [f"%{kw}%" for kw in keywords]
        params.append(limit)

        cursor.execute(f"""
            SELECT conts_id, conts_klang_nm, org_nm,
                   tot_rsrh_blgn_amt, rsrh_bgnv_ymd, rsrh_endv_ymd
            FROM f_projects
            WHERE {keyword_conditions}
            ORDER BY tot_rsrh_blgn_amt DESC NULLS LAST
            LIMIT %s
        """, params)

        results = []
        for row in cursor.fetchall():
            project_name = row[1] or ""
            match_count = sum(1 for kw in keywords if kw.lower() in project_name.lower())
            score = match_count / len(keywords) if keywords else 0

            results.append(RecommendationResult(
                item_id=row[0] or "",
                item_name=project_name,
                item_type="project",
                score=score,
                org_name=row[2],
                keywords=keywords,
                metadata={
                    "budget": row[3],
                    "start_date": str(row[4]) if row[4] else None,
                    "end_date": str(row[5]) if row[5] else None
                }
            ))

        conn.close()

        # 점수 순으로 정렬
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    except Exception as e:
        logger.error(f"과제 추천 실패: {e}")
        return []


def recommend_equipment_for_project(
    project_name: str,
    limit: int = 10
) -> List[RecommendationResult]:
    """과제 관련 장비 추천

    과제명을 기반으로 관련 연구장비 추천

    Args:
        project_name: 과제명
        limit: 최대 결과 수

    Returns:
        추천 장비 목록
    """
    if not project_name:
        return []

    # 과제명에서 키워드 추출
    keywords = [kw for kw in project_name.split() if len(kw) >= 2]
    return recommend_equipment_for_keywords(keywords, limit)


def get_equipment_by_organization(
    org_name: str,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """기관별 보유 장비 조회

    Args:
        org_name: 기관명 (부분 일치)
        limit: 최대 결과 수

    Returns:
        장비 목록
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT conts_id, conts_klang_nm, org_nm,
                   equip_grp_lv1_nm, equip_grp_lv2_nm
            FROM f_equipments
            WHERE org_nm ILIKE %s
            ORDER BY equip_grp_lv1_nm, conts_klang_nm
            LIMIT %s
        """, (f"%{org_name}%", limit))

        results = []
        for row in cursor.fetchall():
            results.append({
                "conts_id": row[0],
                "equipment_name": row[1],
                "org_name": row[2],
                "category_lv1": row[3],
                "category_lv2": row[4]
            })

        conn.close()
        return results

    except Exception as e:
        logger.error(f"기관 장비 조회 실패: {e}")
        return []


def format_recommendations_for_llm(
    recommendations: List[RecommendationResult],
    item_type: str = "equipment"
) -> str:
    """추천 결과를 LLM 컨텍스트용으로 포맷팅

    Args:
        recommendations: 추천 결과 목록
        item_type: 아이템 유형

    Returns:
        포맷팅된 문자열
    """
    if not recommendations:
        return f"관련 {item_type}을(를) 찾지 못했습니다."

    lines = []
    type_label = "장비" if item_type == "equipment" else "과제"
    lines.append(f"총 {len(recommendations)}개의 관련 {type_label} 발견\n")

    for i, rec in enumerate(recommendations[:10], 1):
        lines.append(f"[{i}] {rec.item_name}")
        if rec.org_name:
            lines.append(f"    기관: {rec.org_name}")
        lines.append(f"    관련도: {rec.score:.2%}")

        if rec.metadata:
            if item_type == "equipment":
                if rec.metadata.get("category_lv1"):
                    lines.append(f"    분류: {rec.metadata['category_lv1']}")
            else:  # project
                if rec.metadata.get("budget"):
                    lines.append(f"    예산: {rec.metadata['budget']:,}원")
        lines.append("")

    return "\n".join(lines)


# 테스트용
if __name__ == "__main__":
    print("=== 추천 시스템 테스트 ===\n")

    # 1. 키워드 기반 장비 추천
    print("1. 키워드 기반 장비 추천 (원심분리기)")
    results = recommend_equipment_for_keywords(["원심분리기"], limit=5)
    for r in results:
        print(f"   - {r.item_name} ({r.org_name}): {r.score:.2%}")

    # 2. 장비 기반 과제 추천
    print("\n2. 장비 기반 과제 추천")
    results = recommend_projects_for_equipment("원심분리기", limit=5)
    for r in results:
        print(f"   - {r.item_name}: {r.score:.2%}")

    # 3. 기관별 장비 조회
    print("\n3. 기관별 장비 조회 (한국과학기술원)")
    results = get_equipment_by_organization("한국과학기술원", limit=5)
    for r in results:
        print(f"   - {r['equipment_name']} ({r['category_lv1']})")
