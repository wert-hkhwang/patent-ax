"""
EP-Agent 벡터 검색 API Pydantic 모델
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """검색 요청"""
    query: str = Field(..., min_length=1, description="검색어")
    collection: str = Field(default="patents", description="검색 대상 컬렉션")
    limit: int = Field(default=10, ge=1, le=100, description="결과 수")
    filters: Optional[Dict[str, str]] = Field(default=None, description="필터 조건")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "배터리 충전 기술",
                "collection": "patents",
                "limit": 10,
                "filters": {"ipc_main": "H01M"}
            }
        }


class MultiSearchRequest(BaseModel):
    """다중 컬렉션 검색 요청"""
    query: str = Field(..., min_length=1, description="검색어")
    collections: List[str] = Field(
        default=["patents", "proposals"],
        description="검색 대상 컬렉션 목록"
    )
    limit_per_collection: int = Field(default=5, ge=1, le=50, description="컬렉션별 결과 수")
    filters: Optional[Dict[str, Dict[str, str]]] = Field(
        default=None,
        description="컬렉션별 필터 조건"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "query": "인공지능 의료",
                "collections": ["patents", "proposals"],
                "limit_per_collection": 5,
                "filters": {
                    "patents": {"ipc_main": "G06"},
                    "proposals": {"ancm_year": "2024"}
                }
            }
        }


class SearchResult(BaseModel):
    """단일 검색 결과"""
    id: Any = Field(..., description="문서 ID")
    score: float = Field(..., description="유사도 점수")
    collection: str = Field(..., description="소속 컬렉션")
    payload: Dict[str, Any] = Field(..., description="문서 메타데이터")


class SearchResponse(BaseModel):
    """검색 응답"""
    query: str = Field(..., description="검색어")
    total: int = Field(..., description="결과 수")
    results: List[SearchResult] = Field(..., description="검색 결과 목록")
    elapsed_ms: float = Field(..., description="처리 시간 (밀리초)")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "배터리 충전 기술",
                "total": 10,
                "results": [
                    {
                        "id": 12345,
                        "score": 0.67,
                        "collection": "patents",
                        "payload": {
                            "title": "배터리 충전 장치",
                            "ipc_main": "H01M-010/44"
                        }
                    }
                ],
                "elapsed_ms": 125.5
            }
        }


class CollectionInfo(BaseModel):
    """컬렉션 정보"""
    name: str = Field(..., description="컬렉션 이름")
    display_name: str = Field(..., description="표시 이름")
    vector_count: int = Field(..., description="벡터 수")
    filterable_fields: List[str] = Field(..., description="필터 가능 필드")


class CollectionListResponse(BaseModel):
    """컬렉션 목록 응답"""
    total: int = Field(..., description="총 컬렉션 수")
    collections: List[CollectionInfo] = Field(..., description="컬렉션 목록")


class ErrorResponse(BaseModel):
    """오류 응답"""
    error: str = Field(..., description="오류 메시지")
    detail: Optional[str] = Field(default=None, description="상세 정보")


# ========================================
# Graph RAG 관련 모델
# ========================================

class GraphSearchRequest(BaseModel):
    """Graph RAG 검색 요청"""
    query: str = Field(..., min_length=1, description="검색어")
    strategy: str = Field(
        default="hybrid",
        description="검색 전략: graph_only, vector_only, hybrid, graph_enhanced"
    )
    entity_types: Optional[List[str]] = Field(
        default=None,
        description="필터링할 엔티티 타입 (ResearchProject, Researcher, Technology 등)"
    )
    max_depth: int = Field(default=2, ge=1, le=5, description="그래프 탐색 깊이")
    limit: int = Field(default=20, ge=1, le=100, description="결과 수")
    include_context: bool = Field(default=True, description="관련 엔티티 포함 여부")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "인공지능 딥러닝",
                "strategy": "hybrid",
                "entity_types": ["ResearchProject", "Technology"],
                "max_depth": 2,
                "limit": 20,
                "include_context": True
            }
        }


class GraphNode(BaseModel):
    """그래프 노드"""
    node_id: str = Field(..., description="노드 ID")
    name: str = Field(..., description="노드 이름")
    entity_type: str = Field(..., description="엔티티 타입")
    description: Optional[str] = Field(default=None, description="설명")
    score: float = Field(..., description="관련도 점수")


class RelatedEntity(BaseModel):
    """관련 엔티티"""
    node_id: str = Field(..., description="노드 ID")
    name: str = Field(..., description="이름")
    entity_type: str = Field(..., description="엔티티 타입")
    relation: Optional[str] = Field(default=None, description="관계 타입")
    depth: int = Field(..., description="탐색 깊이")


class GraphSearchResult(BaseModel):
    """Graph RAG 검색 결과"""
    node: GraphNode = Field(..., description="검색된 노드")
    related_entities: Optional[List[RelatedEntity]] = Field(
        default=None,
        description="관련 엔티티 목록"
    )


class GraphSearchResponse(BaseModel):
    """Graph RAG 검색 응답"""
    query: str = Field(..., description="검색어")
    strategy: str = Field(..., description="사용된 검색 전략")
    total: int = Field(..., description="결과 수")
    results: List[GraphSearchResult] = Field(..., description="검색 결과")
    elapsed_ms: float = Field(..., description="처리 시간 (밀리초)")


class EntityContextRequest(BaseModel):
    """엔티티 컨텍스트 요청"""
    node_id: str = Field(..., description="노드 ID")
    max_depth: int = Field(default=2, ge=1, le=5, description="탐색 깊이")


class EntityContextResponse(BaseModel):
    """엔티티 컨텍스트 응답"""
    entity: Dict[str, Any] = Field(..., description="엔티티 정보")
    neighbors: List[Dict[str, Any]] = Field(..., description="이웃 노드")
    related_entities: List[Dict[str, Any]] = Field(..., description="관련 엔티티")
    statistics: Dict[str, int] = Field(..., description="통계")


class GraphStatisticsResponse(BaseModel):
    """그래프 통계 응답"""
    nodes: int = Field(..., description="총 노드 수")
    edges: int = Field(..., description="총 엣지 수")
    node_types: Dict[str, int] = Field(..., description="타입별 노드 수")
    density: float = Field(..., description="그래프 밀도")
    is_connected: bool = Field(..., description="연결 여부")
    components: int = Field(..., description="컴포넌트 수")


# ========================================
# Agent 채팅 관련 모델
# ========================================

class ChatRequest(BaseModel):
    """채팅 요청"""
    query: str = Field(..., min_length=1, description="사용자 질문")
    search_strategy: str = Field(
        default="hybrid",
        description="검색 전략: hybrid, graph_only, vector_only, graph_enhanced"
    )
    max_tokens: int = Field(default=2048, ge=100, le=8192, description="최대 응답 토큰")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="생성 온도")
    use_history: bool = Field(default=True, description="대화 기록 사용 여부")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "인공지능 관련 연구과제에 대해 알려주세요",
                "search_strategy": "hybrid",
                "max_tokens": 2048,
                "temperature": 0.7,
                "use_history": True
            }
        }


class ChatSource(BaseModel):
    """채팅 소스"""
    node_id: str = Field(..., description="노드 ID")
    name: str = Field(..., description="이름")
    entity_type: str = Field(..., description="엔티티 타입")
    score: float = Field(..., description="관련도 점수")


class ChatResponse(BaseModel):
    """채팅 응답"""
    answer: str = Field(..., description="AI 응답")
    sources: List[ChatSource] = Field(..., description="참조 소스")
    search_strategy: str = Field(..., description="사용된 검색 전략")
    elapsed_ms: float = Field(..., description="처리 시간 (밀리초)")

    class Config:
        json_schema_extra = {
            "example": {
                "answer": "인공지능 관련 연구과제로는...",
                "sources": [
                    {
                        "node_id": "project_S2279867",
                        "name": "인공지능 기반 연구",
                        "entity_type": "project",
                        "score": 0.85
                    }
                ],
                "search_strategy": "hybrid",
                "elapsed_ms": 1250.5
            }
        }


class SimpleChatRequest(BaseModel):
    """단순 채팅 요청 (RAG 없이)"""
    query: str = Field(..., min_length=1, description="사용자 질문")
    system_prompt: Optional[str] = Field(default=None, description="시스템 프롬프트")
    max_tokens: int = Field(default=2048, ge=100, le=8192, description="최대 응답 토큰")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="생성 온도")


# ========================================
# SQL Agent 관련 모델
# ========================================

class SQLQueryRequest(BaseModel):
    """SQL 에이전트 쿼리 요청"""
    question: str = Field(..., min_length=1, description="자연어 질문")
    interpret_result: bool = Field(default=True, description="결과 해석 여부")
    max_tokens: int = Field(default=1024, ge=100, le=4096, description="LLM 최대 토큰")
    temperature: float = Field(default=0.3, ge=0.0, le=1.0, description="LLM 온도")

    class Config:
        json_schema_extra = {
            "example": {
                "question": "인공지능 관련 특허를 10개 검색해줘",
                "interpret_result": True,
                "max_tokens": 1024,
                "temperature": 0.3
            }
        }


class SQLExecuteRequest(BaseModel):
    """직접 SQL 실행 요청"""
    sql: str = Field(..., min_length=1, description="SQL 쿼리 (SELECT만 허용)")

    class Config:
        json_schema_extra = {
            "example": {
                "sql": "SELECT TOP 10 conts_id, conts_klang_nm FROM [f_projects]"
            }
        }


class SQLResultData(BaseModel):
    """SQL 실행 결과 데이터"""
    success: bool = Field(..., description="성공 여부")
    columns: List[str] = Field(default=[], description="컬럼명 목록")
    rows: List[List[Any]] = Field(default=[], description="결과 행")
    row_count: int = Field(default=0, description="결과 행 수")
    error: Optional[str] = Field(default=None, description="오류 메시지")
    execution_time_ms: float = Field(default=0, description="SQL 실행 시간 (밀리초)")


class SQLQueryResponse(BaseModel):
    """SQL 에이전트 쿼리 응답"""
    question: str = Field(..., description="원본 질문")
    generated_sql: str = Field(..., description="생성된 SQL")
    result: SQLResultData = Field(..., description="실행 결과")
    interpretation: Optional[str] = Field(default=None, description="결과 해석")
    related_tables: List[str] = Field(default=[], description="관련 테이블")
    elapsed_ms: float = Field(..., description="전체 처리 시간 (밀리초)")

    class Config:
        json_schema_extra = {
            "example": {
                "question": "인공지능 관련 특허를 10개 검색해줘",
                "generated_sql": "SELECT TOP 10 documentid, conts_klang_nm FROM [f_patents] WHERE conts_klang_nm LIKE '%인공지능%'",
                "result": {
                    "success": True,
                    "columns": ["documentid", "conts_klang_nm"],
                    "rows": [["DOC001", "인공지능 기반 영상 분석"]],
                    "row_count": 10,
                    "execution_time_ms": 125.5
                },
                "interpretation": "인공지능 관련 특허 10건을 찾았습니다...",
                "related_tables": ["f_patents"],
                "elapsed_ms": 2500.0
            }
        }


class SQLExecuteResponse(BaseModel):
    """직접 SQL 실행 응답"""
    sql: str = Field(..., description="실행된 SQL")
    result: SQLResultData = Field(..., description="실행 결과")
    elapsed_ms: float = Field(..., description="처리 시간 (밀리초)")


class TableColumnInfo(BaseModel):
    """테이블 컬럼 정보"""
    name: str = Field(..., description="컬럼명")
    data_type: str = Field(..., description="데이터 타입")
    max_length: Optional[int] = Field(default=None, description="최대 길이")
    is_nullable: bool = Field(default=True, description="NULL 허용 여부")
    description: str = Field(default="", description="컬럼 설명")


class TableInfo(BaseModel):
    """테이블 정보"""
    name: str = Field(..., description="테이블명")
    description: str = Field(default="", description="테이블 설명")
    row_count: int = Field(default=0, description="행 수")
    columns: List[TableColumnInfo] = Field(default=[], description="컬럼 목록")


class SchemaResponse(BaseModel):
    """스키마 정보 응답"""
    tables: List[TableInfo] = Field(..., description="테이블 목록")
    total_tables: int = Field(..., description="총 테이블 수")


class TableListResponse(BaseModel):
    """테이블 목록 응답"""
    tables: List[str] = Field(..., description="테이블명 목록")
    total: int = Field(..., description="총 테이블 수")


class ExampleQuery(BaseModel):
    """예제 쿼리"""
    name: str = Field(..., description="예제 이름")
    question: str = Field(..., description="자연어 질문")
    sql: str = Field(..., description="SQL 쿼리")


class ExampleQueriesResponse(BaseModel):
    """예제 쿼리 목록 응답"""
    examples: List[ExampleQuery] = Field(..., description="예제 목록")


# ========================================
# 공공 AX API 모델 (AX_API.yaml 명세)
# ========================================

from typing import Literal, Union

# ---------- Chat API ----------

class ChatAskRequest(BaseModel):
    """AI 질의응답 요청 (/chat/ask)"""
    level: Literal["초등", "일반인", "전문가"] = Field(
        ...,
        description="사용자 리터러시 수준"
    )
    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="사용자 질문 내용"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "level": "일반인",
                "question": "전기 자동차 배터리 급속충전 기술에 대해 알려주세요"
            }
        }


class WorkflowStatus(BaseModel):
    """AI 처리 워크플로우 상태"""
    analysis: Optional[Union[float, str]] = Field(
        default=None,
        description="질문 분석 단계 (숫자: 완료 시간(초), 'ing': 진행중)"
    )
    sql: Optional[Union[float, str]] = Field(
        default=None,
        description="데이터베이스 쿼리 단계"
    )
    rag: Optional[Union[float, str]] = Field(
        default=None,
        description="RAG 검색 단계"
    )
    merge: Optional[Union[float, str]] = Field(
        default=None,
        description="결과 병합 단계"
    )


class RelatedPatentItem(BaseModel):
    """관련 특허 항목"""
    id: str = Field(..., description="특허 ID")
    title: str = Field(..., description="특허 제목")
    score: str = Field(..., description="관련도 점수 (예: '95%')")


class PatentImageItem(BaseModel):
    """특허 이미지 항목"""
    id: str = Field(..., description="이미지 ID")
    source: str = Field(..., description="이미지 URL")


# Phase 102: 그래프 시각화 데이터 모델
class GraphNode(BaseModel):
    """그래프 노드 (시각화용)"""
    id: str = Field(..., description="노드 ID")
    name: str = Field(..., description="노드 이름")
    type: str = Field(..., description="노드 타입 (patent, org, tech 등)")
    score: float = Field(..., description="관련도 점수 (0.0~1.0)")
    color: Optional[str] = Field(default=None, description="노드 색상 (예: #E91E63)")


class GraphEdge(BaseModel):
    """그래프 엣지 (시각화용)"""
    from_id: str = Field(..., description="출발 노드 ID")
    to_id: str = Field(..., description="도착 노드 ID")
    relation: str = Field(..., description="관계 타입 (applicant, same_community 등)")


class GraphData(BaseModel):
    """시각화용 그래프 데이터"""
    nodes: List[GraphNode] = Field(default=[], description="노드 목록")
    edges: List[GraphEdge] = Field(default=[], description="엣지 목록")


class PerspectiveSummary(BaseModel):
    """관점별 요약 (특허 문서 구조 기반)"""
    purpose: str = Field(..., description="목적: 특허가 해결하려는 과제/문제 (objectko 기반)")
    material: str = Field(..., description="소재: 사용되는 주요 소재/기술 요소 (IPC 분류 기반)")
    method: str = Field(..., description="공법: 구체적인 기술 구현 방법 (solutionko 기반)")
    effect: str = Field(..., description="효과: 기술 적용으로 인한 성과/개선점 (초록 기반)")


class ChatAskResponse(BaseModel):
    """AI 질의응답 응답 (/chat/ask)"""
    workflow: WorkflowStatus = Field(..., description="워크플로우 상태")
    answer: str = Field(..., description="AI가 생성한 답변 텍스트")
    confidence_score: float = Field(
        default=0.0,
        ge=0.0, le=1.0,
        description="답변 신뢰도 점수 (0.0~1.0)"
    )
    related_patents: List[RelatedPatentItem] = Field(
        default=[],
        description="관련 특허 목록"
    )
    graph_data: Optional[GraphData] = Field(
        default=None,
        description="시각화용 그래프 데이터 (특허 + 1-hop 관련 엔티티)"
    )
    perspective_summary: Optional[PerspectiveSummary] = Field(
        default=None,
        description="관점별 요약 (목적/소재/공법/효과)"
    )
    application_no: Optional[str] = Field(default=None, description="출원번호")
    application_date: Optional[str] = Field(default=None, description="출원일")
    img: List[PatentImageItem] = Field(default=[], description="관련 이미지 목록")


class ChatDetailRequest(BaseModel):
    """특허 상세 정보 요청 (/chat/detail)"""
    doc_id: str = Field(..., description="특허 문서 번호 (출원번호 또는 등록번호)")

    class Config:
        json_schema_extra = {
            "example": {
                "doc_id": "KR-2022-7030829"
            }
        }


class PatentInfo(BaseModel):
    """특허 기본 정보"""
    title: str = Field(..., description="특허 제목 (영문 병기)")
    status: str = Field(..., description="특허 상태 (출원/공개/등록/거절/취하/소멸)")
    country: str = Field(..., description="국가 코드")
    app_num: Optional[str] = Field(default=None, description="출원번호")
    reg_num: Optional[str] = Field(default=None, description="등록번호")
    expiration_date: Optional[str] = Field(default=None, description="만료일")


class TimelineEvent(BaseModel):
    """특허 타임라인 이벤트"""
    date: str = Field(..., description="이벤트 발생일")
    event: str = Field(..., description="이벤트 내용")


class ApplicantInfo(BaseModel):
    """출원인 정보"""
    current: Optional[str] = Field(default=None, description="현재 권리자")
    original: Optional[str] = Field(default=None, description="원출원인")


class PatentImages(BaseModel):
    """특허 이미지"""
    main_representative: Optional[str] = Field(default=None, description="대표 이미지 URL")
    thumbnails: List[str] = Field(default=[], description="썸네일 이미지 URL 목록")


class ChatDetailResponse(BaseModel):
    """특허 상세 정보 응답 (/chat/detail)"""
    patent_info: PatentInfo = Field(..., description="특허 기본 정보")
    timeline: List[TimelineEvent] = Field(default=[], description="특허 진행 타임라인")
    applicants: ApplicantInfo = Field(..., description="출원인 정보")
    images: PatentImages = Field(..., description="특허 이미지")


# ---------- Map API ----------

class MapLocation(BaseModel):
    """지도 위치 정보"""
    lat: float = Field(..., description="위도")
    lng: float = Field(..., description="경도")
    title: str = Field(..., description="특허 제목")
    type: Literal["cluster", "point"] = Field(
        ...,
        description="마커 타입 (cluster: 밀집, point: 개별)"
    )


class MapSearchResponse(BaseModel):
    """지도 검색 응답 (/map/search)"""
    locations: List[MapLocation] = Field(default=[], description="지도상 표시 위치 목록")


# ---------- Analyze API ----------

class AnalyzeCompareRequest(BaseModel):
    """문서 비교 분석 요청 (/analyze/compare)"""
    keyword: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="검색된 특허 키워드"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "keyword": "배터리 예열 충전"
            }
        }


class DocumentSummary(BaseModel):
    """문서 요약"""
    title: str = Field(..., description="문서 제목")
    goal: str = Field(..., description="연구/발명 목표")
    method: str = Field(..., description="해결 방법")


class ComparisonResult(BaseModel):
    """비교 결과"""
    common_tech: str = Field(..., description="공통 기술 요소")
    conclusion: str = Field(..., description="비교 결론")


class AnalyzeCompareResponse(BaseModel):
    """문서 비교 분석 응답 (/analyze/compare)"""
    my_doc_summary: DocumentSummary = Field(..., description="내 문서 요약")
    comparison: ComparisonResult = Field(..., description="비교 분석 결과")


class AnalyzeDetailRequest(BaseModel):
    """상세 비교 분석 요청 (/analyze/detail)"""
    doc_id: str = Field(..., description="분석 대상 문서 번호")

    class Config:
        json_schema_extra = {
            "example": {
                "doc_id": "KR-2022-7030829"
            }
        }


class ComparisonItem(BaseModel):
    """비교 항목"""
    item: str = Field(..., description="비교 항목명")
    desc: str = Field(..., description="항목 설명")


class DocumentAnalysis(BaseModel):
    """문서 분석 결과"""
    title: str = Field(..., description="분석 섹션 제목")
    content: List[ComparisonItem] = Field(default=[], description="비교 항목 목록")


class AnalysisConclusion(BaseModel):
    """분석 결론"""
    title: str = Field(..., description="결론 섹션 제목")
    main_text: str = Field(..., description="주요 결론")
    detail_text: str = Field(..., description="상세 설명")


class AnalyzeDetailResponse(BaseModel):
    """상세 비교 분석 응답 (/analyze/detail)"""
    category_mode: Literal["EASY_SUMMARY", "DETAILED"] = Field(
        default="EASY_SUMMARY",
        description="분석 카테고리 모드"
    )
    my_doc: DocumentAnalysis = Field(..., description="내 문서 분석")
    target_patent: DocumentAnalysis = Field(..., description="대상 특허 분석")
    conclusion: AnalysisConclusion = Field(..., description="결론 및 시사점")


# ---------- Error Response ----------

class APIError(BaseModel):
    """API 오류 응답"""
    code: str = Field(..., description="에러 코드")
    message: str = Field(..., description="에러 메시지")
    details: Optional[Dict[str, Any]] = Field(default=None, description="추가 에러 상세 정보")
