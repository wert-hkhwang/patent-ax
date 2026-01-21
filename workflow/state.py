"""
LangGraph 에이전트 상태 정의
- AgentState: 워크플로우 전체 공유 상태
- 데이터 타입: SearchResult, SQLQueryResult, ChatMessage
- SearchConfig: Phase 89 - 의도별 검색 전략 설정
- history_reducer: 대화 기록 최대 길이 제한
"""

from typing import TypedDict, List, Dict, Any, Optional, Literal, Annotated, Callable
from dataclasses import dataclass, field
from enum import Enum


# === 상수 ===
MAX_HISTORY_LENGTH = 20  # 최대 대화 기록 수 (user+assistant 쌍 기준 10턴)


# === Phase 89: 검색 전략 관련 Enum 및 데이터클래스 ===

class SearchSource(Enum):
    """검색 소스 유형"""
    SQL = "sql"           # PostgreSQL 직접 쿼리
    ES = "es"             # Elasticsearch (BM25 키워드 검색)
    VECTOR = "vector"     # Qdrant (벡터 유사도 검색)
    GRAPH = "graph"       # cuGraph (그래프 탐색)


class GraphRAGStrategy(Enum):
    """GraphRAG 검색 전략"""
    VECTOR_ONLY = "vector_only"       # Qdrant 벡터 검색만
    GRAPH_ONLY = "graph_only"         # cuGraph 그래프 탐색만
    HYBRID = "hybrid"                 # 벡터 + 그래프 RRF 결합
    GRAPH_ENHANCED = "graph_enhanced" # 벡터 검색 후 그래프 확장
    NONE = "none"                     # GraphRAG 사용 안함


class ESMode(Enum):
    """Elasticsearch 사용 모드"""
    OFF = "off"                       # ES 사용 안함
    KEYWORD_BOOST = "keyword_boost"   # 키워드 매칭 보강 (RAG 결과에 추가)
    PRIMARY = "primary"               # ES를 주 검색 소스로 사용
    AGGREGATION = "aggregation"       # 집계/동향 분석용


@dataclass
class SearchConfig:
    """검색 설정 (query_subtype별 동적 결정)

    Phase 89: 의도 기반 검색 전략 최적화
    """
    # 검색 소스 우선순위
    primary_sources: List[SearchSource] = field(default_factory=lambda: [SearchSource.SQL])
    fallback_sources: List[SearchSource] = field(default_factory=list)

    # GraphRAG 전략
    graph_rag_strategy: GraphRAGStrategy = GraphRAGStrategy.NONE

    # ES 사용 모드
    es_mode: ESMode = ESMode.OFF

    # 결과 병합 우선순위 (숫자가 작을수록 높음)
    merge_priority: Dict[str, int] = field(default_factory=lambda: {
        "sql": 0,
        "es": 1,
        "vector": 2,
        "graph": 3
    })

    # 검색 제한
    sql_limit: int = 100
    es_limit: int = 20
    rag_limit: int = 15

    # Loader 사용 여부
    use_loader: bool = False
    loader_name: Optional[str] = None

    # 벡터 키워드 확장 필요 여부
    need_vector_enhancement: bool = True

    def should_use_sql(self) -> bool:
        """SQL 검색 필요 여부"""
        return SearchSource.SQL in self.primary_sources or SearchSource.SQL in self.fallback_sources

    def should_use_es(self) -> bool:
        """ES 검색 필요 여부"""
        return self.es_mode != ESMode.OFF

    def should_use_rag(self) -> bool:
        """RAG 검색 필요 여부"""
        return self.graph_rag_strategy != GraphRAGStrategy.NONE


def history_reducer(existing: List, new: List) -> List:
    """대화 기록 리듀서 - 최대 길이 제한

    Args:
        existing: 기존 대화 기록
        new: 새로운 대화 기록

    Returns:
        최대 MAX_HISTORY_LENGTH개로 제한된 대화 기록
    """
    combined = (existing or []) + (new or [])
    if len(combined) > MAX_HISTORY_LENGTH:
        return combined[-MAX_HISTORY_LENGTH:]
    return combined


@dataclass
class SearchResult:
    """Graph RAG 검색 결과"""
    node_id: str
    name: str
    entity_type: str
    score: float
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SQLQueryResult:
    """SQL 쿼리 결과"""
    success: bool
    columns: List[str] = field(default_factory=list)
    rows: List[List[Any]] = field(default_factory=list)
    row_count: int = 0
    error: Optional[str] = None
    execution_time_ms: float = 0


@dataclass
class ChatMessage:
    """채팅 메시지"""
    role: Literal["user", "assistant", "system"]
    content: str


@dataclass
class SubQueryInfo:
    """하위 질의 정보 (복합 질의 분해 결과)"""
    query: str                          # 하위 질의 텍스트
    query_type: str = "rag"             # sql/rag
    entity_types: List[str] = field(default_factory=list)
    depends_on: Optional[int] = None    # 의존하는 하위 질의 인덱스
    priority: int = 0                   # 실행 우선순위
    result: Optional[Any] = None        # 실행 결과 (동적으로 채워짐)


# Phase 34.5: 구조화된 키워드 타입
@dataclass
class StructuredKeywords:
    """구조화된 키워드 (유형별 분류)"""
    tech: List[str] = field(default_factory=list)      # 기술/주제 키워드 (수소연료전지, 반도체)
    country: List[str] = field(default_factory=list)   # 국가 키워드 (KR, US, NOT_KR)
    filter: List[str] = field(default_factory=list)    # 필터 조건 (TOP 10, 최근 2년)
    metric: List[str] = field(default_factory=list)    # 분석 유형 (추이, 급증, 현황)


class AgentState(TypedDict, total=False):
    """
    LangGraph 에이전트 공유 상태

    모든 노드가 읽고 쓸 수 있는 상태 딕셔너리.
    Annotated 타입은 값을 덮어쓰지 않고 누적함.
    """
    # === 입력 ===
    query: str                          # 사용자 질문
    session_id: str                     # 세션 ID

    # === 분석 결과 ===
    query_type: Literal["sql", "rag", "hybrid", "simple"]  # 쿼리 유형
    query_subtype: Literal["list", "aggregation", "ranking", "concept", "compound", "recommendation", "comparison"]  # Phase 28/33: 쿼리 서브타입
    query_intent: str                   # 의도 설명
    entity_types: List[str]             # 관련 엔티티 타입 (project, patent 등)
    related_tables: List[str]           # SQL에서 사용할 테이블
    keywords: List[str]                 # 추출된 키워드 (flat 리스트 - 하위 호환성)
    structured_keywords: Optional[Dict[str, List[str]]]  # Phase 34.5: 구조화된 키워드 {tech, country, filter, metric}
    semantic_keywords: List[str]        # Phase 28: 벡터 검색에서 확장된 의미론적 키워드
    is_aggregation: bool                # Phase 27: 통계/집계 쿼리 여부 (전체 데이터 대상)

    # === 복합 질의 분해 (Phase 20) ===
    is_compound: bool                   # 복합 질의 여부
    sub_queries: List[Dict[str, Any]]   # 하위 질의 목록 (SubQueryInfo 직렬화)
    merge_strategy: Literal["parallel", "sequential"]  # 병합 전략
    complexity_reason: str              # 복합 질의로 판단된 이유
    sub_query_results: List[Dict[str, Any]]  # 하위 질의별 실행 결과

    # === Phase 100: ES Scout ===
    synonym_keywords: List[str]         # Phase 100: 동의어 사전에서 확장된 키워드
    es_doc_ids: Dict[str, List[str]]    # Phase 100: ES Scout에서 수집한 도메인별 문서 ID
    domain_hits: Dict[str, int]         # Phase 100: 도메인별 히트 수

    # === Vector Enhancement (Phase 4, 29, 35, 53) ===
    vector_doc_ids: List[str]           # 벡터 검색으로 찾은 문서 ID (Phase 29: 사용 안함)
    expanded_keywords: List[str]        # 확장된 키워드 (LLM 원본 + 벡터 확장)
    vector_scores: Dict[str, float]     # 문서별 벡터 유사도 점수 (Phase 29: 사용 안함)
    vector_result_count: int            # 벡터 검색 결과 수
    keyword_extraction_result: Optional[Dict[str, Any]]  # Phase 29: 키워드 추출 상세 결과 (디버깅용)
    cached_vector_results: Optional[Dict[str, List[Dict]]]  # Phase 35: 벡터 검색 결과 캐시 (rag_retriever 재사용)
    entity_keywords: Optional[Dict[str, List[str]]]  # Phase 53: 엔티티별 독립 키워드 {"patent": [...], "project": [...]}

    # === 실행 결과 ===
    rag_results: List[SearchResult]     # RAG 검색 결과
    sql_result: Optional[SQLQueryResult]  # SQL 실행 결과 (단일 엔티티)
    multi_sql_results: Optional[Dict[str, SQLQueryResult]]  # 다중 엔티티별 SQL 결과 (Phase 19)
    generated_sql: Optional[str]        # 생성된 SQL

    # === Phase 88: Loader 관련 ===
    loader_used: Optional[str]          # 사용된 Loader 이름 (예: "AnnouncementScoringLoader")
    loader_metadata: Optional[Dict[str, Any]]  # Loader 메타데이터 (announcement_name, total_score 등)

    # === Phase 99.5: ES 통계/동향 분석 ===
    es_statistics: Optional[Dict[str, Any]]  # ES aggregations 결과 (연도별/국가별 통계)
    statistics_type: Optional[str]      # 통계 유형 (trend_analysis, country_stats 등)

    # === 최종 출력 ===
    response: str                       # LLM 생성 응답
    sources: List[Dict[str, Any]]       # 참조 소스

    # === 메타데이터 ===
    conversation_history: Annotated[List[ChatMessage], history_reducer]  # 대화 기록 (최대 20개)
    search_strategy: str                # 사용된 검색 전략
    reasoning_trace: str                # LLM 추론 과정 (<think> 블록)
    elapsed_ms: float                   # 총 처리 시간
    stage_timing: Dict[str, float]      # 단계별 처리 시간 (ms)
    error: Optional[str]                # 에러 메시지

    # === Phase 89: 검색 전략 설정 ===
    search_config: Optional[SearchConfig]  # 의도 기반 검색 설정
    es_enabled: bool                    # ES 사용 여부 (런타임)

    # === 리터러시 레벨 (공공 AX API) ===
    level: Literal["초등", "일반인", "전문가"]  # 사용자 리터러시 수준

    # === Phase 102: 신뢰도 점수 ===
    context_quality: float              # 컨텍스트 품질 점수 (0.0~1.0)

    # === Phase 104: 관점별 요약 ===
    perspective_summary: Optional[Dict[str, Dict[str, str]]]  # 관점별 요약 {purpose: {original, explanation}, ...}


def create_initial_state(
    query: str,
    session_id: str = "default",
    level: str = "일반인"
) -> AgentState:
    """초기 상태 생성 (Patent-AX: 특허 전용)

    Args:
        query: 사용자 질문
        session_id: 세션 ID
        level: 리터러시 수준 (초등/일반인/전문가)
    """
    return AgentState(
        query=query,
        session_id=session_id,
        query_type="simple",
        query_subtype="list",
        query_intent="",
        entity_types=["patent"],  # Patent-AX: 특허만 고정
        related_tables=[],
        keywords=[],
        structured_keywords=None,  # Phase 34.5
        semantic_keywords=[],
        # 복합 질의 관련 필드 (Phase 20)
        is_compound=False,
        sub_queries=[],
        merge_strategy="parallel",
        complexity_reason="",
        sub_query_results=[],
        # Phase 100: ES Scout
        synonym_keywords=[],
        es_doc_ids={},
        domain_hits={},
        # Vector Enhancement (Phase 4, 29)
        vector_doc_ids=[],
        expanded_keywords=[],
        vector_scores={},
        vector_result_count=0,
        keyword_extraction_result=None,
        cached_vector_results=None,  # Phase 35
        entity_keywords=None,  # Phase 53: 엔티티별 독립 키워드
        # 실행 결과
        rag_results=[],
        sql_result=None,
        multi_sql_results=None,
        generated_sql=None,
        loader_used=None,  # Phase 88: Loader 이름
        loader_metadata=None,  # Phase 88: Loader 메타데이터
        es_statistics=None,  # Phase 99.5: ES 통계 결과
        statistics_type=None,  # Phase 99.5: 통계 유형
        response="",
        sources=[],
        # 메타데이터
        conversation_history=[],
        search_strategy="",
        reasoning_trace="",
        elapsed_ms=0.0,
        stage_timing={},
        error=None,
        # Phase 89: 검색 전략 설정
        search_config=None,
        es_enabled=False,
        # 리터러시 레벨 (공공 AX API)
        level=level,
        # Phase 102: 신뢰도 점수
        context_quality=0.0
    )
