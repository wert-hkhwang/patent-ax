"""
Patent Applicant Ranking Loader
===============================

기술분야별 특허 출원기관 TOP N 조회 로더
- f_patents 테이블에서 기술분야별 출원기관 순위 조회
- 특허 출원 건수 기준 정렬
- 한국 특허 우선 필터링 지원
- GIS 데이터 추출 지원

RISE-GPT에서 이식
작성일: 2025-12-12
"""

from typing import Dict, List, Any, Optional
import logging
import re

from workflow.loaders.base_loader import BaseLoader, create_markdown_table

logger = logging.getLogger(__name__)


# 지역명 → PNU 코드 매핑
REGION_TO_PNU = {
    "서울": "11", "서울특별시": "11",
    "부산": "26", "부산광역시": "26",
    "대구": "27", "대구광역시": "27",
    "인천": "28", "인천광역시": "28",
    "광주": "29", "광주광역시": "29",
    "대전": "30", "대전광역시": "30",
    "울산": "31", "울산광역시": "31",
    "세종": "36", "세종특별자치시": "36",
    "경기": "41", "경기도": "41",
    "강원": "42", "강원도": "42", "강원특별자치도": "42",
    "충북": "43", "충청북도": "43",
    "충남": "44", "충청남도": "44",
    "전북": "45", "전라북도": "45", "전북특별자치도": "45",
    "전남": "46", "전라남도": "46",
    "경북": "47", "경상북도": "47",
    "경남": "48", "경상남도": "48",
    "제주": "50", "제주특별자치도": "50",
}


class PatentRankingLoader(BaseLoader):
    """
    기술분야별 특허 출원기관 순위 로더

    query_subtype: ranking (특허 출원기관 TOP N)
    """

    def __init__(self):
        super().__init__()
        self.table_name = "f_patents"

    def _get_pnu_code(self, region: str) -> Optional[str]:
        """
        지역명을 PNU 코드(시도코드 2자리)로 변환

        Args:
            region: 지역명 (예: "경기", "서울특별시")

        Returns:
            PNU 시도코드 2자리 또는 None
        """
        if not region:
            return None

        # 정확한 매핑 먼저 시도
        if region in REGION_TO_PNU:
            return REGION_TO_PNU[region]

        # 부분 매칭 시도
        for name, code in REGION_TO_PNU.items():
            if region in name or name in region:
                return code

        return None

    async def load_data(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        DB에서 기술분야별 특허 출원기관 데이터 로드

        Args:
            context: {
                'technology_field': 기술 키워드 (예: "수소 저장·운송"),
                'nationality': 국적 필터 (옵션, 예: "KR"),
                'region': 지역 필터 (옵션, 예: "경기", "서울"),
                'top_n': 상위 N개 (default: 10)
            }

        Returns:
            [{"company_name": "현대자동차주식회사", "patent_count": 1668, ...}, ...]
        """
        technology_keyword = context.get('technology_field') or context.get('technology_keyword')
        nationality = context.get('nationality', 'KR')  # 기본값: KR
        region = context.get('region')
        top_n = context.get('top_n', 10)

        if not technology_keyword:
            logger.warning("기술분야명이 없습니다.")
            return []

        logger.info(f"기술분야 검색: {technology_keyword} (TOP {top_n}, 국적: {nationality})")

        try:
            # 데이터 쿼리 (출원기관별 특허 집계)
            data_query = """
                SELECT
                    TRIM(SPLIT_PART(p.patent_appn_group, '|', 1)) AS company_name,
                    COALESCE(
                        NULLIF(TRIM(SPLIT_PART(p.org_corp_no, '|', 1)), ''),
                        NULLIF(TRIM(SPLIT_PART(p.org_busir_no, '|', 1)), ''),
                        '-'
                    ) AS applicant_code,
                    COUNT(*) AS patent_count,
                    COUNT(CASE WHEN p.patent_rgno IS NOT NULL AND p.patent_rgno != '' THEN 1 END) AS registration_count,
                    MAX(CASE
                        WHEN p.patent_rgstn_ymd IS NOT NULL
                             AND LENGTH(p.patent_rgstn_ymd) = 8
                             AND p.patent_rgstn_ymd ~ '^[0-9]{8}$'
                        THEN TO_DATE(p.patent_rgstn_ymd, 'YYYYMMDD')
                        ELSE NULL
                    END) AS latest_registration_date
                FROM f_patents p
            """
            params = [technology_keyword]
            param_counter = 2

            # 지역 필터가 있는 경우 GIS JOIN 추가
            pnu_code = self._get_pnu_code(region) if region else None
            if pnu_code:
                data_query += """
                LEFT JOIN f_gis g
                    ON p.conts_id = g.conts_id
                    AND g.conts_lclas_nm = '특허'
                """

            data_query += """
                WHERE p.conts_sclas_nm ILIKE '%' || $1 || '%'
                  AND p.patent_appn_group IS NOT NULL
                  AND p.patent_appn_group != ''
            """

            # 국적 필터
            if nationality:
                data_query += f" AND p.ntcd = ${param_counter}"
                params.append(nationality)
                param_counter += 1

            # 지역 필터
            if pnu_code:
                data_query += f" AND g.pnu LIKE ${param_counter}"
                params.append(f"{pnu_code}%")
                param_counter += 1
                logger.info(f"지역 필터: {region} → PNU 코드: {pnu_code}")

            data_query += f"""
                GROUP BY
                    TRIM(SPLIT_PART(p.patent_appn_group, '|', 1)),
                    TRIM(SPLIT_PART(p.org_corp_no, '|', 1)),
                    TRIM(SPLIT_PART(p.org_busir_no, '|', 1))
                ORDER BY patent_count DESC
                LIMIT ${param_counter}
            """
            params.append(top_n)

            rows = await self.execute_query(data_query, params)

            results = []
            for idx, row in enumerate(rows, 1):
                patent_count = row.get('patent_count', 0)
                registration_count = row.get('registration_count', 0)
                registration_rate = (registration_count / patent_count * 100) if patent_count > 0 else 0.0

                results.append({
                    'rank': idx,
                    'company_name': row.get('company_name') or '미상',
                    'applicant_code': row.get('applicant_code') or '',
                    'patent_count': patent_count,
                    'registration_count': registration_count,
                    'registration_rate': round(registration_rate, 1),
                    'latest_registration_date': str(row.get('latest_registration_date') or '-')
                })

            logger.info(f"PatentRankingLoader: {len(results)}개 출원기관 데이터 로드 성공")
            return results

        except Exception as e:
            logger.error(f"PatentRankingLoader load_data 오류: {e}")
            return []

    def format_markdown(
        self,
        data: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        마크다운 테이블 포맷팅

        Args:
            data: DB에서 로드한 데이터
            context: 포맷팅 컨텍스트

        Returns:
            마크다운 형식 테이블
        """
        if not data:
            return "검색 결과가 없습니다."

        context = context or {}
        technology_field = context.get('technology_field', '기술분야')
        nationality = context.get('nationality', 'KR')
        region = context.get('region', '')
        top_n = len(data)

        # 헤더 생성
        lines = []
        title_parts = [f"{technology_field} 분야"]
        if region:
            title_parts.append(f"{region} 지역")
        if nationality:
            title_parts.append(f"{nationality} 특허")
        title_parts.append(f"출원기관 TOP {top_n}")

        lines.append(f"### {' '.join(title_parts)}")
        lines.append("")

        # 테이블 생성
        headers = ["순위", "출원기관명", "출원건수", "등록건수", "등록률", "최근등록일"]
        rows = []
        for item in data:
            rows.append([
                item['rank'],
                item['company_name'],
                self._format_number(item['patent_count']),
                self._format_number(item['registration_count']),
                f"{item['registration_rate']}%",
                item['latest_registration_date']
            ])

        table = create_markdown_table(headers, rows, alignments=["center", "left", "right", "right", "right", "center"])
        lines.append(table)

        return "\n".join(lines)


class PatentCitationLoader(BaseLoader):
    """
    특허 피인용 순위 로더

    query_subtype: citation_ranking (평균 피인용수 기준)
    """

    def __init__(self):
        super().__init__()
        self.table_name = "f_patents"

    async def load_data(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        DB에서 특허 피인용 순위 데이터 로드

        Args:
            context: {
                'technology_field': 기술 키워드,
                'nationality': 국적 필터 (기본: KR),
                'top_n': 상위 N개 (default: 10)
            }
        """
        technology_keyword = context.get('technology_field') or context.get('technology_keyword')
        nationality = context.get('nationality', 'KR')
        top_n = context.get('top_n', 10)

        if not technology_keyword:
            logger.warning("기술분야명이 없습니다.")
            return []

        logger.info(f"피인용 순위 검색: {technology_keyword} (TOP {top_n})")

        try:
            # 피인용 순위 쿼리 (평균 피인용수 기준)
            query = """
                SELECT
                    TRIM(SPLIT_PART(p.patent_appn_group, '|', 1)) AS company_name,
                    COUNT(*) AS patent_count,
                    SUM(COALESCE(CAST(p.citation_cnt AS INTEGER), 0)) AS total_citations,
                    AVG(COALESCE(CAST(p.citation_cnt AS INTEGER), 0)) AS avg_citations,
                    MAX(COALESCE(CAST(p.citation_cnt AS INTEGER), 0)) AS max_citations
                FROM f_patents p
                WHERE p.conts_sclas_nm ILIKE '%' || $1 || '%'
                  AND p.patent_appn_group IS NOT NULL
                  AND p.patent_appn_group != ''
            """
            params = [technology_keyword]
            param_counter = 2

            if nationality:
                query += f" AND p.ntcd = ${param_counter}"
                params.append(nationality)
                param_counter += 1

            query += f"""
                GROUP BY TRIM(SPLIT_PART(p.patent_appn_group, '|', 1))
                HAVING SUM(COALESCE(CAST(p.citation_cnt AS INTEGER), 0)) > 0
                ORDER BY avg_citations DESC
                LIMIT ${param_counter}
            """
            params.append(top_n)

            rows = await self.execute_query(query, params)

            results = []
            for idx, row in enumerate(rows, 1):
                results.append({
                    'rank': idx,
                    'company_name': row.get('company_name') or '미상',
                    'patent_count': row.get('patent_count', 0),
                    'total_citations': row.get('total_citations', 0),
                    'avg_citations': round(float(row.get('avg_citations', 0)), 2),
                    'max_citations': row.get('max_citations', 0)
                })

            logger.info(f"PatentCitationLoader: {len(results)}개 피인용 순위 데이터 로드")
            return results

        except Exception as e:
            logger.error(f"PatentCitationLoader load_data 오류: {e}")
            return []

    def format_markdown(
        self,
        data: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """마크다운 테이블 포맷팅"""
        if not data:
            return "검색 결과가 없습니다."

        context = context or {}
        technology_field = context.get('technology_field', '기술분야')
        top_n = len(data)

        lines = []
        lines.append(f"### {technology_field} 분야 평균 피인용 순위 TOP {top_n}")
        lines.append("")

        headers = ["순위", "출원기관명", "특허수", "총피인용수", "평균피인용수", "최대피인용수"]
        rows = []
        for item in data:
            rows.append([
                item['rank'],
                item['company_name'],
                self._format_number(item['patent_count']),
                self._format_number(item['total_citations']),
                f"{item['avg_citations']:.2f}",
                self._format_number(item['max_citations'])
            ])

        table = create_markdown_table(headers, rows, alignments=["center", "left", "right", "right", "right", "right"])
        lines.append(table)

        return "\n".join(lines)


class PatentInfluenceLoader(BaseLoader):
    """
    특허 영향력 순위 로더

    query_subtype: impact_ranking (인용특허비율 기준)
    """

    def __init__(self):
        super().__init__()
        self.table_name = "f_patents"

    async def load_data(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        DB에서 특허 영향력 순위 데이터 로드

        Args:
            context: {
                'technology_field': 기술 키워드,
                'nationality': 국적 필터 (기본: KR),
                'top_n': 상위 N개 (default: 10)
            }
        """
        technology_keyword = context.get('technology_field') or context.get('technology_keyword')
        nationality = context.get('nationality', 'KR')
        top_n = context.get('top_n', 10)

        if not technology_keyword:
            logger.warning("기술분야명이 없습니다.")
            return []

        logger.info(f"영향력 순위 검색: {technology_keyword} (TOP {top_n})")

        try:
            # 영향력 순위 쿼리 (인용특허비율 = 피인용 특허 수 / 전체 특허 수)
            query = """
                SELECT
                    TRIM(SPLIT_PART(p.patent_appn_group, '|', 1)) AS company_name,
                    COUNT(*) AS patent_count,
                    COUNT(CASE WHEN COALESCE(CAST(p.citation_cnt AS INTEGER), 0) > 0 THEN 1 END) AS cited_patent_count,
                    SUM(COALESCE(CAST(p.citation_cnt AS INTEGER), 0)) AS total_citations,
                    ROUND(100.0 * COUNT(CASE WHEN COALESCE(CAST(p.citation_cnt AS INTEGER), 0) > 0 THEN 1 END) / COUNT(*), 1) AS citation_ratio
                FROM f_patents p
                WHERE p.conts_sclas_nm ILIKE '%' || $1 || '%'
                  AND p.patent_appn_group IS NOT NULL
                  AND p.patent_appn_group != ''
            """
            params = [technology_keyword]
            param_counter = 2

            if nationality:
                query += f" AND p.ntcd = ${param_counter}"
                params.append(nationality)
                param_counter += 1

            query += f"""
                GROUP BY TRIM(SPLIT_PART(p.patent_appn_group, '|', 1))
                HAVING COUNT(*) >= 5
                ORDER BY citation_ratio DESC, total_citations DESC
                LIMIT ${param_counter}
            """
            params.append(top_n)

            rows = await self.execute_query(query, params)

            results = []
            for idx, row in enumerate(rows, 1):
                results.append({
                    'rank': idx,
                    'company_name': row.get('company_name') or '미상',
                    'patent_count': row.get('patent_count', 0),
                    'cited_patent_count': row.get('cited_patent_count', 0),
                    'total_citations': row.get('total_citations', 0),
                    'citation_ratio': float(row.get('citation_ratio', 0))
                })

            logger.info(f"PatentInfluenceLoader: {len(results)}개 영향력 순위 데이터 로드")
            return results

        except Exception as e:
            logger.error(f"PatentInfluenceLoader load_data 오류: {e}")
            return []

    def format_markdown(
        self,
        data: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """마크다운 테이블 포맷팅"""
        if not data:
            return "검색 결과가 없습니다."

        context = context or {}
        technology_field = context.get('technology_field', '기술분야')
        top_n = len(data)

        lines = []
        lines.append(f"### {technology_field} 분야 특허 영향력 순위 TOP {top_n}")
        lines.append("")

        headers = ["순위", "출원기관명", "특허수", "피인용특허수", "총피인용수", "인용특허비율"]
        rows = []
        for item in data:
            rows.append([
                item['rank'],
                item['company_name'],
                self._format_number(item['patent_count']),
                self._format_number(item['cited_patent_count']),
                self._format_number(item['total_citations']),
                f"{item['citation_ratio']}%"
            ])

        table = create_markdown_table(headers, rows, alignments=["center", "left", "right", "right", "right", "right"])
        lines.append(table)

        return "\n".join(lines)


class PatentNationalityLoader(BaseLoader):
    """
    국적별 특허 순위 로더

    query_subtype: nationality_ranking (자국/타국 분리 특허 순위)
    - 자국(KR) 특허와 타국(non-KR) 특허를 분리하여 순위 표시
    """

    def __init__(self):
        super().__init__()
        self.table_name = "f_patents"

    async def load_data(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        DB에서 국적별 특허 출원기관 데이터 로드

        Args:
            context: {
                'technology_field': 기술 키워드,
                'top_n': 상위 N개 (default: 10)
            }

        Returns:
            [{"category": "자국", "company_name": "삼성전자", ...}, ...]
        """
        technology_keyword = context.get('technology_field') or context.get('technology_keyword')
        top_n = context.get('top_n', 10)

        if not technology_keyword:
            logger.warning("기술분야명이 없습니다.")
            return []

        logger.info(f"국적별 특허 순위 검색: {technology_keyword} (TOP {top_n})")

        try:
            results = []

            # 자국(KR) 특허 조회
            kr_query = """
                SELECT
                    TRIM(SPLIT_PART(p.patent_appn_group, '|', 1)) AS company_name,
                    COUNT(*) AS patent_count,
                    COUNT(CASE WHEN p.patent_rgno IS NOT NULL AND p.patent_rgno != '' THEN 1 END) AS registration_count
                FROM f_patents p
                WHERE p.conts_sclas_nm ILIKE '%' || $1 || '%'
                  AND p.patent_appn_group IS NOT NULL
                  AND p.patent_appn_group != ''
                  AND p.ntcd = 'KR'
                GROUP BY TRIM(SPLIT_PART(p.patent_appn_group, '|', 1))
                ORDER BY patent_count DESC
                LIMIT $2
            """
            kr_rows = await self.execute_query(kr_query, [technology_keyword, top_n])

            for idx, row in enumerate(kr_rows, 1):
                patent_count = row.get('patent_count', 0)
                registration_count = row.get('registration_count', 0)
                registration_rate = (registration_count / patent_count * 100) if patent_count > 0 else 0.0

                results.append({
                    'category': '자국',
                    'rank': idx,
                    'company_name': row.get('company_name') or '미상',
                    'patent_count': patent_count,
                    'registration_count': registration_count,
                    'registration_rate': round(registration_rate, 1)
                })

            # 타국(non-KR) 특허 조회
            foreign_query = """
                SELECT
                    TRIM(SPLIT_PART(p.patent_appn_group, '|', 1)) AS company_name,
                    p.ntcd AS nationality,
                    COUNT(*) AS patent_count,
                    COUNT(CASE WHEN p.patent_rgno IS NOT NULL AND p.patent_rgno != '' THEN 1 END) AS registration_count
                FROM f_patents p
                WHERE p.conts_sclas_nm ILIKE '%' || $1 || '%'
                  AND p.patent_appn_group IS NOT NULL
                  AND p.patent_appn_group != ''
                  AND p.ntcd != 'KR'
                  AND p.ntcd IS NOT NULL
                GROUP BY TRIM(SPLIT_PART(p.patent_appn_group, '|', 1)), p.ntcd
                ORDER BY patent_count DESC
                LIMIT $2
            """
            foreign_rows = await self.execute_query(foreign_query, [technology_keyword, top_n])

            for idx, row in enumerate(foreign_rows, 1):
                patent_count = row.get('patent_count', 0)
                registration_count = row.get('registration_count', 0)
                registration_rate = (registration_count / patent_count * 100) if patent_count > 0 else 0.0

                results.append({
                    'category': '타국',
                    'rank': idx,
                    'company_name': row.get('company_name') or '미상',
                    'nationality': row.get('nationality', '-'),
                    'patent_count': patent_count,
                    'registration_count': registration_count,
                    'registration_rate': round(registration_rate, 1)
                })

            logger.info(f"PatentNationalityLoader: 자국 {len(kr_rows)}개, 타국 {len(foreign_rows)}개 데이터 로드")
            return results

        except Exception as e:
            logger.error(f"PatentNationalityLoader load_data 오류: {e}")
            return []

    def format_markdown(
        self,
        data: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """마크다운 테이블 포맷팅 (자국/타국 분리 출력)"""
        if not data:
            return "검색 결과가 없습니다."

        context = context or {}
        technology_field = context.get('technology_field', '기술분야')

        lines = []

        # 자국 특허 테이블
        kr_data = [d for d in data if d.get('category') == '자국']
        if kr_data:
            lines.append(f"### {technology_field} 분야 자국(KR) 특허 출원기관 TOP {len(kr_data)}")
            lines.append("")

            headers = ["순위", "출원기관명", "출원건수", "등록건수", "등록률"]
            rows = []
            for item in kr_data:
                rows.append([
                    item['rank'],
                    item['company_name'],
                    self._format_number(item['patent_count']),
                    self._format_number(item['registration_count']),
                    f"{item['registration_rate']}%"
                ])

            table = create_markdown_table(headers, rows, alignments=["center", "left", "right", "right", "right"])
            lines.append(table)
            lines.append("")

        # 타국 특허 테이블
        foreign_data = [d for d in data if d.get('category') == '타국']
        if foreign_data:
            lines.append(f"### {technology_field} 분야 타국 특허 출원기관 TOP {len(foreign_data)}")
            lines.append("")

            headers = ["순위", "출원기관명", "국적", "출원건수", "등록건수", "등록률"]
            rows = []
            for item in foreign_data:
                rows.append([
                    item['rank'],
                    item['company_name'],
                    item.get('nationality', '-'),
                    self._format_number(item['patent_count']),
                    self._format_number(item['registration_count']),
                    f"{item['registration_rate']}%"
                ])

            table = create_markdown_table(headers, rows, alignments=["center", "left", "center", "right", "right", "right"])
            lines.append(table)

        return "\n".join(lines)
