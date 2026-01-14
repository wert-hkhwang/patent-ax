"""
Elasticsearch 클라이언트

AX 시스템용 Elasticsearch 검색 클라이언트.
한글 형태소 분석(Nori), BM25 랭킹, 동의어 검색을 지원합니다.
"""

import os
import logging
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from elasticsearch import Elasticsearch, AsyncElasticsearch
from elasticsearch.exceptions import ConnectionError, NotFoundError, TransportError

logger = logging.getLogger(__name__)

# 환경 변수 설정
ES_HOST = os.getenv("ES_HOST", "localhost")
ES_PORT = int(os.getenv("ES_PORT", "9200"))
ES_SCHEME = os.getenv("ES_SCHEME", "http")
ES_TIMEOUT = int(os.getenv("ES_TIMEOUT", "30"))
ES_ENABLED = os.getenv("ES_ENABLED", "false").lower() == "true"


@dataclass
class SearchResult:
    """검색 결과 데이터 클래스"""
    id: str
    score: float
    source: Dict[str, Any]
    highlight: Dict[str, List[str]] = field(default_factory=dict)
    index: str = ""


@dataclass
class AggregationResult:
    """집계 결과 데이터 클래스"""
    key: str
    doc_count: int
    sub_aggregations: Dict[str, Any] = field(default_factory=dict)


class ESSearchClient:
    """
    Elasticsearch 검색 클라이언트

    AX 시스템의 5개 인덱스에 대한 검색, 집계, 하이라이트 기능을 제공합니다.

    사용 예:
        client = ESSearchClient()
        results = await client.search("인공지능", "patent", limit=20)
    """

    # 인덱스 매핑
    INDEX_MAP = {
        "patent": "ax_patents",
        "project": "ax_projects",
        "equipment": "ax_equipments",
        "proposal": "ax_proposals",
        "evaluation": "ax_evaluations",
    }

    # 엔티티별 검색 필드 (실제 ES 매핑 기반)
    SEARCH_FIELDS = {
        "patent": ["conts_klang_nm^3", "patent_abstc_ko^2", "objectko", "solutionko", "patent_frst_appn", "keyvalue"],
        "project": ["conts_klang_nm^3", "bucl_nm^2", "ancm_tl_nm", "conts_rspns_nm"],
        "equipment": ["conts_klang_nm^3", "equip_desc^2", "org_nm", "equip_spec", "kpi_nm_list"],
        "proposal": ["sbjt_nm^3", "dvlp_gole^2", "rhdp_whol_cn", "prd_sv_nm", "orgn_nm"],
        "evaluation": ["ancm_nm^3", "eval_idx_nm^2", "eval_note", "bucl_nm"],
    }

    # 엔티티별 ID 필드
    ID_FIELD = {
        "patent": "documentid",
        "project": "conts_id",
        "equipment": "conts_id",
        "proposal": "sbjt_id",
        "evaluation": "evalp_id",
    }

    def __init__(
        self,
        hosts: Optional[List[str]] = None,
        timeout: int = ES_TIMEOUT,
    ):
        """
        ES 클라이언트 초기화

        Args:
            hosts: ES 호스트 목록 (기본값: [localhost:9200])
            timeout: 요청 타임아웃 (초)
        """
        self.hosts = hosts or [f"{ES_SCHEME}://{ES_HOST}:{ES_PORT}"]
        self.timeout = timeout
        self._client: Optional[Elasticsearch] = None
        self._async_client: Optional[AsyncElasticsearch] = None

    @property
    def client(self) -> Elasticsearch:
        """동기 클라이언트 (lazy initialization)"""
        if self._client is None:
            self._client = Elasticsearch(
                hosts=self.hosts,
                request_timeout=self.timeout,
                retry_on_timeout=True,
                max_retries=3,
            )
        return self._client

    @property
    def async_client(self) -> AsyncElasticsearch:
        """비동기 클라이언트 (lazy initialization)"""
        if self._async_client is None:
            self._async_client = AsyncElasticsearch(
                hosts=self.hosts,
                request_timeout=self.timeout,
                retry_on_timeout=True,
                max_retries=3,
            )
        return self._async_client

    def is_available(self) -> bool:
        """ES 연결 상태 확인"""
        try:
            return self.client.ping()
        except ConnectionError:
            logger.warning("Elasticsearch connection failed")
            return False

    async def is_available_async(self) -> bool:
        """ES 연결 상태 확인 (비동기)"""
        try:
            return await self.async_client.ping()
        except ConnectionError:
            logger.warning("Elasticsearch connection failed")
            return False

    def _get_index(self, entity_type: str) -> str:
        """엔티티 타입에서 인덱스명 반환"""
        if entity_type not in self.INDEX_MAP:
            raise ValueError(f"Unknown entity type: {entity_type}. Valid types: {list(self.INDEX_MAP.keys())}")
        return self.INDEX_MAP[entity_type]

    def _build_search_query(
        self,
        query: str,
        entity_type: str,
        filters: Optional[Dict[str, Any]] = None,
        date_range: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        검색 쿼리 빌드

        Args:
            query: 검색어
            entity_type: 엔티티 타입 (patent, project, equipment, proposal, evaluation)
            filters: 필터 조건 (예: {"ntcd": "KR"})
            date_range: 날짜 범위 (예: {"gte": "2020-01-01", "lte": "2024-12-31"})

        Returns:
            Elasticsearch 쿼리 딕셔너리
        """
        search_fields = self.SEARCH_FIELDS.get(entity_type, ["*"])

        # Phase 94.2: 복합 키워드 감지 (공백 없는 한글 2어절 이상)
        # 예: "특허맵", "인공지능", "자율주행" 등
        is_compound_keyword = len(query.strip()) >= 2 and " " not in query.strip()

        # Phase 94.2: 복합 키워드는 phrase_prefix + must로 정확 검색
        # 일반 키워드는 best_fields + or로 폭넓은 검색
        if is_compound_keyword:
            # 복합 키워드: phrase 검색 우선, fallback으로 일반 검색
            must_clauses = [
                {
                    "bool": {
                        "should": [
                            # 1순위: phrase_prefix로 정확한 구문 검색 (boost 3.0)
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": search_fields,
                                    "type": "phrase_prefix",
                                    "boost": 3.0,
                                }
                            },
                            # 2순위: AND 조건으로 모든 토큰 포함 (boost 1.5)
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": search_fields,
                                    "type": "best_fields",
                                    "operator": "and",
                                    "boost": 1.5,
                                }
                            },
                            # 3순위: OR 조건 폴백 (boost 0.5)
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": search_fields,
                                    "type": "best_fields",
                                    "operator": "or",
                                    "boost": 0.5,
                                }
                            },
                        ],
                        "minimum_should_match": 1,
                    }
                }
            ]
        else:
            # 기본 multi_match 쿼리 (공백 있는 다중 키워드)
            must_clauses = [
                {
                    "multi_match": {
                        "query": query,
                        "fields": search_fields,
                        "type": "best_fields",
                        "operator": "or",
                        "fuzziness": "AUTO",
                        "prefix_length": 2,
                    }
                }
            ]

        filter_clauses = []

        # 필터 조건 추가
        if filters:
            for field, value in filters.items():
                if isinstance(value, list):
                    filter_clauses.append({"terms": {field: value}})
                else:
                    filter_clauses.append({"term": {field: value}})

        # 날짜 범위 필터
        if date_range:
            date_field = self._get_date_field(entity_type)
            if date_field:
                filter_clauses.append({
                    "range": {
                        date_field: date_range
                    }
                })

        query_body = {
            "bool": {
                "must": must_clauses,
            }
        }

        if filter_clauses:
            query_body["bool"]["filter"] = filter_clauses

        return query_body

    def _get_date_field(self, entity_type: str) -> Optional[str]:
        """엔티티별 날짜 필드 반환"""
        date_fields = {
            "patent": "ptnaplc_ymd",
            "project": "rsrh_bgnv_ymd",
            "equipment": "conts_ymd",
            "proposal": "start_date",
            "evaluation": "vlid_srt_ymd",
        }
        return date_fields.get(entity_type)

    def _build_highlight(self, entity_type: str) -> Dict[str, Any]:
        """하이라이트 설정 빌드"""
        search_fields = self.SEARCH_FIELDS.get(entity_type, [])
        highlight_fields = {}

        for field in search_fields:
            # ^2 같은 부스트 제거
            field_name = field.split("^")[0]
            highlight_fields[field_name] = {
                "number_of_fragments": 3,
                "fragment_size": 150,
            }

        return {
            "pre_tags": ["<mark>"],
            "post_tags": ["</mark>"],
            "fields": highlight_fields,
        }

    async def search(
        self,
        query: str,
        entity_type: str,
        limit: int = 20,
        offset: int = 0,
        filters: Optional[Dict[str, Any]] = None,
        date_range: Optional[Dict[str, str]] = None,
        include_highlight: bool = True,
        sort: Optional[List[Dict[str, str]]] = None,
    ) -> List[SearchResult]:
        """
        텍스트 검색 실행 (비동기)

        Args:
            query: 검색어
            entity_type: 엔티티 타입
            limit: 반환할 결과 수
            offset: 시작 위치
            filters: 필터 조건
            date_range: 날짜 범위
            include_highlight: 하이라이트 포함 여부
            sort: 정렬 기준 (예: [{"ptnaplc_ymd": "desc"}])

        Returns:
            SearchResult 리스트
        """
        index = self._get_index(entity_type)
        query_body = self._build_search_query(query, entity_type, filters, date_range)

        body = {
            "query": query_body,
            "size": limit,
            "from": offset,
            "_source": True,
        }

        if include_highlight:
            body["highlight"] = self._build_highlight(entity_type)

        if sort:
            body["sort"] = sort
        else:
            # 기본: 관련성 점수 순
            body["sort"] = ["_score", {"_id": "asc"}]

        try:
            response = await self.async_client.search(
                index=index,
                body=body,
            )

            results = []
            for hit in response["hits"]["hits"]:
                result = SearchResult(
                    id=hit["_id"],
                    score=hit["_score"] or 0.0,
                    source=hit["_source"],
                    highlight=hit.get("highlight", {}),
                    index=hit["_index"],
                )
                results.append(result)

            logger.info(f"ES search: query='{query}', entity={entity_type}, hits={len(results)}")
            return results

        except NotFoundError:
            logger.error(f"Index not found: {index}")
            return []
        except TransportError as e:
            logger.error(f"ES transport error: {e}")
            return []

    def search_sync(
        self,
        query: str,
        entity_type: str,
        limit: int = 20,
        offset: int = 0,
        filters: Optional[Dict[str, Any]] = None,
        date_range: Optional[Dict[str, str]] = None,
        include_highlight: bool = True,
    ) -> List[SearchResult]:
        """텍스트 검색 실행 (동기)"""
        index = self._get_index(entity_type)
        query_body = self._build_search_query(query, entity_type, filters, date_range)

        body = {
            "query": query_body,
            "size": limit,
            "from": offset,
            "_source": True,
        }

        if include_highlight:
            body["highlight"] = self._build_highlight(entity_type)

        try:
            response = self.client.search(index=index, body=body)

            results = []
            for hit in response["hits"]["hits"]:
                result = SearchResult(
                    id=hit["_id"],
                    score=hit["_score"] or 0.0,
                    source=hit["_source"],
                    highlight=hit.get("highlight", {}),
                    index=hit["_index"],
                )
                results.append(result)

            return results

        except (NotFoundError, TransportError) as e:
            logger.error(f"ES search error: {e}")
            return []

    async def aggregate(
        self,
        query: str,
        entity_type: str,
        aggregations: Dict[str, Any],
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        집계 쿼리 실행

        Args:
            query: 검색어 (컨텍스트)
            entity_type: 엔티티 타입
            aggregations: 집계 정의
            filters: 필터 조건

        Returns:
            집계 결과 딕셔너리
        """
        index = self._get_index(entity_type)
        query_body = self._build_search_query(query, entity_type, filters)

        body = {
            "query": query_body,
            "size": 0,  # 집계만 필요, 문서는 불필요
            "aggs": aggregations,
        }

        try:
            response = await self.async_client.search(index=index, body=body)
            return response.get("aggregations", {})
        except (NotFoundError, TransportError) as e:
            logger.error(f"ES aggregation error: {e}")
            return {}

    async def trend_analysis(
        self,
        query: str,
        entity_type: str,
        years: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        동향 분석용 집계

        연도별 문서 수, 상위 출원인/기관, IPC 분류 등을 집계합니다.

        Args:
            query: 검색어
            entity_type: 엔티티 타입
            years: 분석 기간 (년)
            filters: 추가 필터

        Returns:
            동향 분석 결과
        """
        date_field = self._get_date_field(entity_type)

        aggregations = {
            "yearly_trend": {
                "date_histogram": {
                    "field": date_field,
                    "calendar_interval": "year",
                    "format": "yyyy",
                    "min_doc_count": 1,
                }
            },
        }

        # 엔티티별 추가 집계
        if entity_type == "patent":
            aggregations["top_applicants"] = {
                "terms": {
                    "field": "patent_frst_appn.keyword",
                    "size": 10,
                }
            }
            aggregations["by_ipc"] = {
                "terms": {
                    "field": "ipc_main",
                    "size": 10,
                }
            }
            aggregations["by_country"] = {
                "terms": {
                    "field": "ntcd",
                    "size": 10,
                }
            }
        elif entity_type == "project":
            aggregations["top_organizations"] = {
                "terms": {
                    "field": "conts_rsrh_org_nm.keyword",
                    "size": 10,
                }
            }
            aggregations["total_budget"] = {
                "sum": {
                    "field": "tot_rsrh_blgn_amt",
                }
            }

        return await self.aggregate(query, entity_type, aggregations, filters)

    async def ranking(
        self,
        query: str,
        entity_type: str,
        group_field: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[AggregationResult]:
        """
        랭킹 집계

        특정 필드 기준으로 상위 N개를 반환합니다.

        Args:
            query: 검색어
            entity_type: 엔티티 타입
            group_field: 그룹화할 필드
            limit: 상위 N개
            filters: 필터 조건

        Returns:
            AggregationResult 리스트
        """
        aggregations = {
            "ranking": {
                "terms": {
                    "field": group_field,
                    "size": limit,
                }
            }
        }

        result = await self.aggregate(query, entity_type, aggregations, filters)

        rankings = []
        for bucket in result.get("ranking", {}).get("buckets", []):
            rankings.append(AggregationResult(
                key=bucket["key"],
                doc_count=bucket["doc_count"],
            ))

        return rankings

    async def multi_search(
        self,
        query: str,
        entity_types: List[str],
        limit_per_type: int = 10,
    ) -> Dict[str, List[SearchResult]]:
        """
        다중 인덱스 검색

        여러 엔티티 타입에 대해 동시에 검색합니다.

        Args:
            query: 검색어
            entity_types: 검색할 엔티티 타입 리스트
            limit_per_type: 타입별 결과 수

        Returns:
            엔티티 타입별 검색 결과 딕셔너리
        """
        body = []

        for entity_type in entity_types:
            index = self._get_index(entity_type)
            query_body = self._build_search_query(query, entity_type)

            body.append({"index": index})
            body.append({
                "query": query_body,
                "size": limit_per_type,
                "_source": True,
            })

        try:
            response = await self.async_client.msearch(body=body)

            results = {}
            for i, entity_type in enumerate(entity_types):
                hits = response["responses"][i].get("hits", {}).get("hits", [])
                results[entity_type] = [
                    SearchResult(
                        id=hit["_id"],
                        score=hit["_score"] or 0.0,
                        source=hit["_source"],
                        index=hit["_index"],
                    )
                    for hit in hits
                ]

            return results

        except (NotFoundError, TransportError) as e:
            logger.error(f"ES multi-search error: {e}")
            return {et: [] for et in entity_types}

    async def autocomplete(
        self,
        prefix: str,
        entity_type: str,
        field: str = "conts_klang_nm",
        limit: int = 10,
    ) -> List[str]:
        """
        자동완성 제안

        Args:
            prefix: 입력 접두어
            entity_type: 엔티티 타입
            field: 자동완성 필드
            limit: 제안 수

        Returns:
            자동완성 제안 리스트
        """
        index = self._get_index(entity_type)

        body = {
            "query": {
                "match": {
                    f"{field}.autocomplete": {
                        "query": prefix,
                        "operator": "and",
                    }
                }
            },
            "size": limit,
            "_source": [field],
        }

        try:
            response = await self.async_client.search(index=index, body=body)

            suggestions = []
            for hit in response["hits"]["hits"]:
                value = hit["_source"].get(field)
                if value and value not in suggestions:
                    suggestions.append(value)

            return suggestions

        except (NotFoundError, TransportError) as e:
            logger.error(f"ES autocomplete error: {e}")
            return []

    def entity_statistics(
        self,
        entity_type: str,
        keywords: Optional[str] = None,
        countries: Optional[List[str]] = None,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
        group_by: str = "year",
    ) -> Dict[str, Any]:
        """
        Phase 99.5: 엔티티 통계 조회 (특허/과제 연도별/국가별/IPC별)

        실시간 ES aggregations를 사용하여 통계를 계산합니다.
        기본적으로 최근 10년 데이터를 대상으로 합니다.
        동기 메서드로 구현 (이벤트 루프 문제 회피).

        Args:
            entity_type: 엔티티 타입 (patent, project)
            keywords: 검색 키워드 (선택)
            countries: 국가 코드 리스트 (예: ["KR", "US"])
            start_year: 시작 연도 (기본: 10년 전)
            end_year: 종료 연도 (기본: 현재)
            group_by: 집계 기준 (year, country, ipc, applicant)

        Returns:
            {
                "total": 1234,
                "buckets": [{"key": "2024", "count": 100}, ...],
                "elapsed_ms": 80
            }
        """
        import time
        from datetime import datetime

        start_time = time.time()

        # 기본값: 최근 10년
        current_year = datetime.now().year
        if start_year is None:
            start_year = current_year - 10
        if end_year is None:
            end_year = current_year

        index = self._get_index(entity_type)
        date_field = self._get_date_field(entity_type)

        # 날짜 범위 필터 구성 (ES date 형식에 맞춤)
        # ES 필드가 다양한 형식을 지원하므로 yyyy-MM-dd 형식 사용
        date_filter = {
            "range": {
                date_field: {
                    "gte": f"{start_year}0101",  # yyyyMMdd 형식
                    "lte": f"{end_year}1231",
                    "format": "yyyyMMdd"
                }
            }
        }

        # 필터 조건 구성
        filter_clauses = [date_filter]

        # 국가 필터 (특허만)
        if countries and entity_type == "patent":
            filter_clauses.append({"terms": {"ntcd": countries}})

        # 키워드 검색 쿼리
        if keywords:
            search_fields = self.SEARCH_FIELDS.get(entity_type, ["*"])
            must_clause = {
                "multi_match": {
                    "query": keywords,
                    "fields": search_fields,
                    "type": "best_fields",
                    "operator": "or",
                }
            }
        else:
            must_clause = {"match_all": {}}

        # Aggregation 정의
        if group_by == "year":
            aggregations = {
                "by_group": {
                    "date_histogram": {
                        "field": date_field,
                        "calendar_interval": "year",
                        "format": "yyyy",
                        "min_doc_count": 1,  # 데이터가 있는 연도만 반환
                    }
                }
            }
        elif group_by == "country":
            aggregations = {
                "by_group": {
                    "terms": {
                        "field": "ntcd",
                        "size": 20,
                    }
                }
            }
        elif group_by == "ipc":
            aggregations = {
                "by_group": {
                    "terms": {
                        "field": "ipc_main",
                        "size": 20,
                    }
                }
            }
        elif group_by == "applicant":
            aggregations = {
                "by_group": {
                    "terms": {
                        "field": "patent_frst_appn.keyword",
                        "size": 20,
                    }
                }
            }
        elif group_by == "program":  # 과제용
            aggregations = {
                "by_group": {
                    "terms": {
                        "field": "bucl_nm.keyword",
                        "size": 20,
                    }
                }
            }
        else:
            # 기본: 연도별
            aggregations = {
                "by_group": {
                    "date_histogram": {
                        "field": date_field,
                        "calendar_interval": "year",
                        "format": "yyyy",
                        "min_doc_count": 0,
                    }
                }
            }

        body = {
            "query": {
                "bool": {
                    "must": [must_clause],
                    "filter": filter_clauses,
                }
            },
            "size": 0,
            "aggs": aggregations,
        }

        try:
            # Phase 99.5 fix: 동기 클라이언트 사용 (이벤트 루프 문제 회피)
            response = self.client.search(index=index, body=body)

            elapsed_ms = int((time.time() - start_time) * 1000)
            total = response["hits"]["total"]["value"]

            # 버킷 파싱
            buckets = []
            agg_result = response.get("aggregations", {}).get("by_group", {})

            for bucket in agg_result.get("buckets", []):
                key = bucket.get("key_as_string") or str(bucket.get("key"))
                buckets.append({
                    "key": key,
                    "count": bucket["doc_count"],
                })

            logger.info(f"ES statistics: entity={entity_type}, keywords={keywords}, group_by={group_by}, total={total}, elapsed={elapsed_ms}ms")

            return {
                "entity_type": entity_type,
                "keywords": keywords,
                "group_by": group_by,
                "period": f"{start_year}-{end_year}",
                "total": total,
                "buckets": buckets,
                "elapsed_ms": elapsed_ms,
            }

        except (NotFoundError, TransportError) as e:
            logger.error(f"ES statistics error: {e}")
            return {
                "entity_type": entity_type,
                "error": str(e),
                "total": 0,
                "buckets": [],
            }

    async def close(self):
        """비동기 클라이언트 연결 종료"""
        if self._async_client:
            await self._async_client.close()
            self._async_client = None

    def close_sync(self):
        """동기 클라이언트 연결 종료"""
        if self._client:
            self._client.close()
            self._client = None


# 싱글톤 인스턴스
_es_client: Optional[ESSearchClient] = None


def get_es_client(force_new: bool = False) -> ESSearchClient:
    """ES 클라이언트 싱글톤 반환

    Args:
        force_new: True면 새 인스턴스 생성 (이벤트 루프 문제 해결용)
    """
    global _es_client
    if _es_client is None or force_new:
        _es_client = ESSearchClient()
    return _es_client
