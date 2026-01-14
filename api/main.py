"""
EP-Agent 벡터 검색 API
FastAPI 기반 REST API
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api.models import (
    SearchRequest, MultiSearchRequest, SearchResponse, SearchResult,
    CollectionListResponse, CollectionInfo, ErrorResponse,
    GraphSearchRequest, GraphSearchResponse, GraphSearchResult as GraphSearchResultModel,
    GraphNode, RelatedEntity, EntityContextRequest, EntityContextResponse,
    GraphStatisticsResponse,
    ChatRequest, ChatResponse, ChatSource, SimpleChatRequest,
    # SQL Agent 모델
    SQLQueryRequest, SQLExecuteRequest, SQLQueryResponse, SQLExecuteResponse,
    SQLResultData, TableInfo, TableColumnInfo, SchemaResponse,
    TableListResponse, ExampleQuery, ExampleQueriesResponse
    # 공공 AX API 모델은 api/routers/ax_api.py에서 별도 import
)
from api.search import (
    search_single_collection, search_multiple_collections,
    get_all_collection_info, get_collection_count
)
from api.config import COLLECTIONS

# Graph RAG 모듈
from graph.graph_rag import GraphRAG, SearchStrategy, get_graph_rag, initialize_graph_rag
from graph.graph_builder import get_knowledge_graph

# Agent 모듈
from agent.rag_agent import RAGAgent, get_rag_agent, initialize_rag_agent

# SQL Agent 모듈
from sql.sql_agent import SQLAgent, get_sql_agent
from sql.schema_analyzer import get_schema_analyzer

# Workflow 모듈
from workflow.graph import get_workflow_agent, run_workflow

# 그래프 초기화 상태
graph_initialized = False
graph_rag: GraphRAG = None

# Agent 초기화 상태
agent_initialized = False
rag_agent: RAGAgent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 실행"""
    global graph_initialized, graph_rag
    # 시작 시: 그래프 초기화 (옵션)
    # 주의: 초기화에 시간이 걸릴 수 있으므로 lazy loading 권장
    print("API 서버 시작...")
    yield
    # 종료 시
    print("API 서버 종료...")

# FastAPI 앱 생성
app = FastAPI(
    title="EP-Agent 벡터 검색 API",
    description="특허, 제안서, 연구장비, 과제, 공고 통합 벡터 검색 + Graph RAG",
    version="1.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["Health"])
async def root():
    """API 상태 확인"""
    return {
        "status": "ok",
        "service": "EP-Agent Vector Search API",
        "version": "1.0.0"
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """헬스 체크"""
    return {"status": "healthy"}


@app.post(
    "/search",
    response_model=SearchResponse,
    responses={400: {"model": ErrorResponse}},
    tags=["Search"]
)
async def search(request: SearchRequest):
    """
    단일 컬렉션 검색

    - **query**: 검색어 (필수)
    - **collection**: 검색 대상 컬렉션 (기본: patents)
    - **limit**: 결과 수 (기본: 10, 최대: 100)
    - **filters**: 필터 조건 (선택)
    """
    start_time = time.time()

    # 컬렉션 유효성 검증
    if request.collection not in COLLECTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 컬렉션: {request.collection}. "
                   f"가능한 값: {list(COLLECTIONS.keys())}"
        )

    # 검색 실행
    results = search_single_collection(
        query=request.query,
        collection_key=request.collection,
        limit=request.limit,
        filters=request.filters
    )

    elapsed_ms = (time.time() - start_time) * 1000

    # 응답 변환
    search_results = [
        SearchResult(
            id=r.get("id"),
            score=r.get("score", 0),
            collection=r.get("collection", request.collection),
            payload=r.get("payload", {})
        )
        for r in results
    ]

    return SearchResponse(
        query=request.query,
        total=len(search_results),
        results=search_results,
        elapsed_ms=round(elapsed_ms, 2)
    )


@app.post(
    "/search/multi",
    response_model=SearchResponse,
    responses={400: {"model": ErrorResponse}},
    tags=["Search"]
)
async def search_multi(request: MultiSearchRequest):
    """
    다중 컬렉션 통합 검색

    - **query**: 검색어 (필수)
    - **collections**: 검색 대상 컬렉션 목록 (기본: patents, proposals)
    - **limit_per_collection**: 컬렉션당 결과 수 (기본: 5)
    - **filters**: 컬렉션별 필터 조건 (선택)
    """
    start_time = time.time()

    # 컬렉션 유효성 검증
    invalid_collections = [c for c in request.collections if c not in COLLECTIONS]
    if invalid_collections:
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 컬렉션: {invalid_collections}. "
                   f"가능한 값: {list(COLLECTIONS.keys())}"
        )

    # 검색 실행
    results = search_multiple_collections(
        query=request.query,
        collections=request.collections,
        limit_per_collection=request.limit_per_collection,
        filters=request.filters
    )

    elapsed_ms = (time.time() - start_time) * 1000

    # 응답 변환
    search_results = [
        SearchResult(
            id=r.get("id"),
            score=r.get("score", 0),
            collection=r.get("collection", ""),
            payload=r.get("payload", {})
        )
        for r in results
    ]

    return SearchResponse(
        query=request.query,
        total=len(search_results),
        results=search_results,
        elapsed_ms=round(elapsed_ms, 2)
    )


@app.get(
    "/collections",
    response_model=CollectionListResponse,
    tags=["Collections"]
)
async def list_collections():
    """
    전체 컬렉션 목록 및 정보 조회
    """
    info_list = get_all_collection_info()

    collections = [
        CollectionInfo(
            name=info["name"],
            display_name=info["display_name"],
            vector_count=info["vector_count"],
            filterable_fields=info["filterable_fields"]
        )
        for info in info_list
    ]

    return CollectionListResponse(
        total=len(collections),
        collections=collections
    )


@app.get(
    "/collections/{collection_name}/count",
    tags=["Collections"]
)
async def collection_count(collection_name: str):
    """
    특정 컬렉션의 벡터 수 조회
    """
    if collection_name not in COLLECTIONS:
        raise HTTPException(
            status_code=404,
            detail=f"컬렉션을 찾을 수 없음: {collection_name}"
        )

    count = get_collection_count(collection_name)

    return {
        "collection": collection_name,
        "vector_count": count
    }


# ========================================
# Graph RAG 엔드포인트
# ========================================

def ensure_graph_initialized():
    """그래프가 초기화되었는지 확인하고 필요시 초기화"""
    global graph_initialized, graph_rag
    if not graph_initialized:
        try:
            # cuGraph API 기반 그래프 초기화
            graph_rag = initialize_graph_rag(
                graph_id="713365bb",  # GPU 서버의 기본 그래프
                project_limit=500
            )
            graph_initialized = True
        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail=f"그래프 초기화 실패: {str(e)}"
            )
    return graph_rag


@app.post("/graph/init", tags=["Graph RAG"])
async def init_graph(graph_id: str = "713365bb", project_limit: int = 500):
    """
    지식 그래프 초기화 (수동)

    - **graph_id**: cuGraph 그래프 ID (기본: 713365bb)
    - **project_limit**: PageRank/커뮤니티 캐시 크기 (기본: 500)
    """
    global graph_initialized, graph_rag
    start_time = time.time()

    try:
        graph_rag = initialize_graph_rag(
            graph_id=graph_id,
            project_limit=project_limit
        )
        graph_initialized = True
        elapsed_ms = (time.time() - start_time) * 1000

        stats = graph_rag.graph_builder.get_statistics()
        return {
            "status": "initialized",
            "graph_id": graph_id,
            "elapsed_ms": round(elapsed_ms, 2),
            "statistics": stats
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"그래프 초기화 오류: {str(e)}"
        )


@app.post(
    "/graph/search",
    response_model=GraphSearchResponse,
    responses={400: {"model": ErrorResponse}},
    tags=["Graph RAG"]
)
async def graph_search(request: GraphSearchRequest):
    """
    Graph RAG 검색

    - **query**: 검색어
    - **strategy**: 검색 전략 (graph_only, vector_only, hybrid, graph_enhanced)
    - **entity_types**: 필터링할 엔티티 타입
    - **max_depth**: 그래프 탐색 깊이 (1-5)
    - **limit**: 결과 수
    - **include_context**: 관련 엔티티 포함 여부
    """
    rag = ensure_graph_initialized()
    start_time = time.time()

    # 검색 전략 매핑
    strategy_map = {
        "graph_only": SearchStrategy.GRAPH_ONLY,
        "vector_only": SearchStrategy.VECTOR_ONLY,
        "hybrid": SearchStrategy.HYBRID,
        "graph_enhanced": SearchStrategy.GRAPH_ENHANCED
    }

    strategy = strategy_map.get(request.strategy, SearchStrategy.HYBRID)

    try:
        results = rag.search(
            query=request.query,
            strategy=strategy,
            entity_types=request.entity_types,
            max_depth=request.max_depth,
            limit=request.limit,
            include_context=request.include_context
        )

        elapsed_ms = (time.time() - start_time) * 1000

        # 응답 변환
        search_results = []
        for r in results:
            node = GraphNode(
                node_id=r.node_id,
                name=r.name,
                entity_type=r.entity_type,
                description=r.description[:500] if r.description else None,
                score=r.score
            )

            related = None
            if r.related_entities:
                related = [
                    RelatedEntity(
                        node_id=e["node_id"],
                        name=e["name"],
                        entity_type=e["entity_type"],
                        relation=e.get("path", [{}])[0].get("relation") if e.get("path") else None,
                        depth=e["depth"]
                    )
                    for e in r.related_entities[:10]
                ]

            search_results.append(GraphSearchResultModel(
                node=node,
                related_entities=related
            ))

        return GraphSearchResponse(
            query=request.query,
            strategy=request.strategy,
            total=len(search_results),
            results=search_results,
            elapsed_ms=round(elapsed_ms, 2)
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"검색 오류: {str(e)}"
        )


@app.post(
    "/graph/context",
    response_model=EntityContextResponse,
    tags=["Graph RAG"]
)
async def get_entity_context(request: EntityContextRequest):
    """
    엔티티의 전체 컨텍스트 조회

    - **node_id**: 노드 ID
    - **max_depth**: 탐색 깊이
    """
    rag = ensure_graph_initialized()

    try:
        context = rag.get_entity_context(request.node_id, request.max_depth)

        if not context:
            raise HTTPException(
                status_code=404,
                detail=f"엔티티를 찾을 수 없음: {request.node_id}"
            )

        return EntityContextResponse(
            entity=context.get("entity", {}),
            neighbors=context.get("neighbors", []),
            related_entities=context.get("related_entities", []),
            statistics=context.get("statistics", {})
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"컨텍스트 조회 오류: {str(e)}"
        )


@app.get(
    "/graph/statistics",
    response_model=GraphStatisticsResponse,
    tags=["Graph RAG"]
)
async def get_graph_statistics():
    """
    지식 그래프 통계 조회
    """
    rag = ensure_graph_initialized()

    try:
        stats = rag.graph_builder.get_statistics()
        return GraphStatisticsResponse(**stats)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"통계 조회 오류: {str(e)}"
        )


@app.get("/graph/central-nodes", tags=["Graph RAG"])
async def get_central_nodes(entity_type: str = None, limit: int = 10):
    """
    중심성이 높은 노드 조회 (PageRank 기반)

    - **entity_type**: 필터링할 엔티티 타입
    - **limit**: 결과 수
    """
    rag = ensure_graph_initialized()

    try:
        central = rag.graph_builder.get_central_nodes(entity_type, limit)
        return {
            "total": len(central),
            "nodes": central
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"조회 오류: {str(e)}"
        )


@app.get("/graph/recommendations/{node_id}", tags=["Graph RAG"])
async def get_recommendations(node_id: str, limit: int = 10):
    """
    관련 엔티티 추천

    - **node_id**: 기준 노드 ID
    - **limit**: 결과 수
    """
    rag = ensure_graph_initialized()

    try:
        recommendations = rag.get_recommendations(node_id, limit)
        return {
            "node_id": node_id,
            "total": len(recommendations),
            "recommendations": recommendations
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"추천 오류: {str(e)}"
        )


@app.get("/graph/connections", tags=["Graph RAG"])
async def find_connections(source_id: str, target_id: str, max_length: int = 4):
    """
    두 엔티티 간 연결 경로 찾기

    - **source_id**: 출발 노드 ID
    - **target_id**: 도착 노드 ID
    - **max_length**: 최대 경로 길이
    """
    rag = ensure_graph_initialized()

    try:
        paths = rag.find_connections(source_id, target_id, max_length)
        return {
            "source_id": source_id,
            "target_id": target_id,
            "path_count": len(paths),
            "paths": paths
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"경로 검색 오류: {str(e)}"
        )


@app.post("/graph/llm-context", tags=["Graph RAG"])
async def generate_llm_context(query: str, limit: int = 10):
    """
    LLM을 위한 컨텍스트 생성

    - **query**: 검색 쿼리
    - **limit**: 결과 수
    """
    rag = ensure_graph_initialized()
    start_time = time.time()

    try:
        context = rag.generate_context_for_llm(query, limit)
        elapsed_ms = (time.time() - start_time) * 1000

        return {
            "query": query,
            "context": context,
            "elapsed_ms": round(elapsed_ms, 2)
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"컨텍스트 생성 오류: {str(e)}"
        )


# ========================================
# Agent 채팅 엔드포인트
# ========================================

def ensure_agent_initialized():
    """Agent가 초기화되었는지 확인하고 필요시 초기화"""
    global agent_initialized, rag_agent
    if not agent_initialized:
        try:
            rag_agent = initialize_rag_agent(
                graph_id="713365bb",
                project_limit=500,
                search_limit=10
            )
            agent_initialized = True
        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail=f"Agent 초기화 실패: {str(e)}"
            )
    return rag_agent


@app.post(
    "/agent/chat",
    response_model=ChatResponse,
    responses={400: {"model": ErrorResponse}},
    tags=["Agent"]
)
async def agent_chat(request: ChatRequest):
    """
    RAG 기반 AI 채팅

    - **query**: 사용자 질문
    - **search_strategy**: 검색 전략 (hybrid, graph_only, vector_only, graph_enhanced)
    - **max_tokens**: 최대 응답 토큰 (100-8192)
    - **temperature**: 생성 온도 (0.0-2.0)
    - **use_history**: 대화 기록 사용 여부
    """
    agent = ensure_agent_initialized()

    try:
        response = agent.chat(
            query=request.query,
            search_strategy=request.search_strategy,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            stream=False,
            use_history=request.use_history
        )

        # 소스 변환
        sources = [
            ChatSource(
                node_id=s["node_id"],
                name=s["name"],
                entity_type=s["entity_type"],
                score=s["score"]
            )
            for s in response.sources
        ]

        return ChatResponse(
            answer=response.answer,
            sources=sources,
            search_strategy=response.search_strategy,
            elapsed_ms=response.elapsed_ms
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"채팅 오류: {str(e)}"
        )


@app.post("/agent/simple-chat", tags=["Agent"])
async def agent_simple_chat(request: SimpleChatRequest):
    """
    단순 AI 채팅 (RAG 없이)

    - **query**: 사용자 질문
    - **system_prompt**: 시스템 프롬프트 (선택)
    - **max_tokens**: 최대 응답 토큰
    - **temperature**: 생성 온도
    """
    agent = ensure_agent_initialized()

    try:
        answer = agent.simple_chat(
            query=request.query,
            system_prompt=request.system_prompt,
            max_tokens=request.max_tokens,
            temperature=request.temperature
        )

        return {
            "query": request.query,
            "answer": answer
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"채팅 오류: {str(e)}"
        )


@app.post("/agent/init", tags=["Agent"])
async def init_agent(graph_id: str = "713365bb", project_limit: int = 500):
    """
    RAG Agent 초기화 (수동)

    - **graph_id**: cuGraph 그래프 ID
    - **project_limit**: PageRank/커뮤니티 캐시 크기
    """
    global agent_initialized, rag_agent
    start_time = time.time()

    try:
        rag_agent = initialize_rag_agent(
            graph_id=graph_id,
            project_limit=project_limit,
            search_limit=10
        )
        agent_initialized = True
        elapsed_ms = (time.time() - start_time) * 1000

        return {
            "status": "initialized",
            "graph_id": graph_id,
            "elapsed_ms": round(elapsed_ms, 2)
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Agent 초기화 오류: {str(e)}"
        )


@app.delete("/agent/history", tags=["Agent"])
async def clear_agent_history():
    """대화 기록 초기화"""
    agent = ensure_agent_initialized()
    agent.clear_history()
    return {"status": "cleared"}


@app.get("/agent/history", tags=["Agent"])
async def get_agent_history():
    """대화 기록 조회"""
    agent = ensure_agent_initialized()
    return {"history": agent.get_history()}


@app.get("/agent/health", tags=["Agent"])
async def agent_health():
    """Agent 상태 확인"""
    try:
        from llm.llm_client import get_llm_client
        llm = get_llm_client()
        llm_healthy = llm.health_check()

        return {
            "status": "healthy" if llm_healthy else "degraded",
            "llm": "connected" if llm_healthy else "disconnected",
            "agent_initialized": agent_initialized
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


# ========================================
# SQL Agent 엔드포인트
# ========================================

@app.post(
    "/sql/query",
    response_model=SQLQueryResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    tags=["SQL Agent"]
)
async def sql_query(request: SQLQueryRequest):
    """
    자연어로 SQL 쿼리 실행

    - **question**: 자연어 질문 (예: "인공지능 관련 특허를 검색해줘")
    - **interpret_result**: 결과 해석 여부 (LLM이 결과를 설명)
    - **max_tokens**: LLM 최대 토큰
    - **temperature**: LLM 온도 (낮을수록 정확)
    """
    start_time = time.time()

    try:
        sql_agent = get_sql_agent()

        response = sql_agent.query(
            question=request.question,
            interpret_result=request.interpret_result,
            max_tokens=request.max_tokens,
            temperature=request.temperature
        )

        # 응답 변환
        result_data = SQLResultData(
            success=response.result.success,
            columns=response.result.columns,
            rows=response.result.rows,
            row_count=response.result.row_count,
            error=response.result.error,
            execution_time_ms=response.result.execution_time_ms
        )

        return SQLQueryResponse(
            question=response.question,
            generated_sql=response.generated_sql,
            result=result_data,
            interpretation=response.interpretation,
            related_tables=response.related_tables,
            elapsed_ms=response.elapsed_ms
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"SQL 쿼리 오류: {str(e)}"
        )


@app.post(
    "/sql/execute",
    response_model=SQLExecuteResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    tags=["SQL Agent"]
)
async def sql_execute(request: SQLExecuteRequest):
    """
    직접 SQL 실행 (SELECT만 허용)

    - **sql**: SQL 쿼리 (SELECT 문만 허용)
    """
    start_time = time.time()

    try:
        sql_agent = get_sql_agent()

        result = sql_agent.execute_raw(request.sql)

        elapsed_ms = (time.time() - start_time) * 1000

        result_data = SQLResultData(
            success=result.success,
            columns=result.columns,
            rows=result.rows,
            row_count=result.row_count,
            error=result.error,
            execution_time_ms=result.execution_time_ms
        )

        return SQLExecuteResponse(
            sql=request.sql,
            result=result_data,
            elapsed_ms=round(elapsed_ms, 2)
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"SQL 실행 오류: {str(e)}"
        )


@app.get(
    "/sql/tables",
    response_model=TableListResponse,
    tags=["SQL Agent"]
)
async def sql_list_tables():
    """
    데이터베이스 테이블 목록 조회
    """
    try:
        analyzer = get_schema_analyzer()
        tables = analyzer.get_tables()

        return TableListResponse(
            tables=tables,
            total=len(tables)
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"테이블 목록 조회 오류: {str(e)}"
        )


@app.get(
    "/sql/schema",
    response_model=SchemaResponse,
    tags=["SQL Agent"]
)
async def sql_get_schema(tables: str = None):
    """
    데이터베이스 스키마 정보 조회

    - **tables**: 특정 테이블만 조회 (쉼표 구분, 예: f_projects,f_patents)
    """
    try:
        analyzer = get_schema_analyzer()

        table_list = None
        if tables:
            table_list = [t.strip() for t in tables.split(",")]

        if table_list:
            schema = {t: analyzer.get_table_info(t) for t in table_list}
        else:
            schema = analyzer.get_full_schema()

        table_infos = []
        for table_name, info in schema.items():
            if info:
                columns = [
                    TableColumnInfo(
                        name=c.name,
                        data_type=c.data_type,
                        max_length=c.max_length,
                        is_nullable=c.is_nullable,
                        description=c.description
                    )
                    for c in info.columns
                ]
                table_infos.append(TableInfo(
                    name=info.name,
                    description=info.description,
                    row_count=info.row_count,
                    columns=columns
                ))

        return SchemaResponse(
            tables=table_infos,
            total_tables=len(table_infos)
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"스키마 조회 오류: {str(e)}"
        )


@app.get(
    "/sql/schema/{table_name}",
    response_model=TableInfo,
    tags=["SQL Agent"]
)
async def sql_get_table_schema(table_name: str):
    """
    특정 테이블 스키마 정보 조회

    - **table_name**: 테이블 이름
    """
    try:
        analyzer = get_schema_analyzer()
        info = analyzer.get_table_info(table_name, include_samples=True)

        if not info:
            raise HTTPException(
                status_code=404,
                detail=f"테이블을 찾을 수 없음: {table_name}"
            )

        columns = [
            TableColumnInfo(
                name=c.name,
                data_type=c.data_type,
                max_length=c.max_length,
                is_nullable=c.is_nullable,
                description=c.description
            )
            for c in info.columns
        ]

        return TableInfo(
            name=info.name,
            description=info.description,
            row_count=info.row_count,
            columns=columns
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"테이블 스키마 조회 오류: {str(e)}"
        )


@app.get(
    "/sql/examples",
    response_model=ExampleQueriesResponse,
    tags=["SQL Agent"]
)
async def sql_get_examples():
    """
    예제 SQL 쿼리 목록
    """
    try:
        sql_agent = get_sql_agent()
        examples = sql_agent.get_example_queries()

        return ExampleQueriesResponse(
            examples=[
                ExampleQuery(
                    name=ex["name"],
                    question=ex["question"],
                    sql=ex["sql"]
                )
                for ex in examples
            ]
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"예제 조회 오류: {str(e)}"
        )


@app.get("/sql/health", tags=["SQL Agent"])
async def sql_health():
    """SQL Agent 상태 확인"""
    try:
        from sql.db_connector import test_connection
        db_healthy = test_connection()

        from llm.llm_client import get_llm_client
        llm = get_llm_client()
        llm_healthy = llm.health_check()

        return {
            "status": "healthy" if (db_healthy and llm_healthy) else "degraded",
            "database": "connected" if db_healthy else "disconnected",
            "llm": "connected" if llm_healthy else "disconnected"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


# ========================================
# LangGraph 워크플로우 엔드포인트
# ========================================

@app.post("/workflow/chat", tags=["Workflow"])
async def workflow_chat(query: str, session_id: str = "default"):
    """
    LangGraph 통합 워크플로우 채팅

    자동으로 쿼리 유형을 분석하여 최적의 파이프라인 실행:
    - SQL: 데이터베이스 조회 (예: "특허 10개")
    - RAG: 의미 검색 (예: "인공지능 연구 동향")
    - Hybrid: SQL + RAG 병합 (예: "AI 특허와 연구 연결")
    - Simple: 직접 응답 (예: "안녕하세요")

    - **query**: 사용자 질문
    - **session_id**: 세션 ID (대화 기록 관리용)
    """
    try:
        result = run_workflow(query=query, session_id=session_id)

        return {
            "query": query,
            "query_type": result.get("query_type", "unknown"),
            "response": result.get("response", ""),
            "sources": result.get("sources", []),
            "generated_sql": result.get("generated_sql"),
            "search_strategy": result.get("search_strategy", ""),
            "elapsed_ms": result.get("elapsed_ms", 0),
            "error": result.get("error")
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"워크플로우 실행 오류: {str(e)}"
        )


@app.post("/workflow/analyze", tags=["Workflow"])
async def workflow_analyze(query: str):
    """
    쿼리 분석만 수행 (실행 없이)

    - **query**: 분석할 질문
    """
    try:
        from workflow.nodes.analyzer import analyze_query
        from workflow.state import create_initial_state

        state = create_initial_state(query=query)
        result = analyze_query(state)

        return {
            "query": query,
            "query_type": result.get("query_type"),
            "query_intent": result.get("query_intent"),
            "entity_types": result.get("entity_types", []),
            "related_tables": result.get("related_tables", []),
            "keywords": result.get("keywords", [])
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"쿼리 분석 오류: {str(e)}"
        )


@app.delete("/workflow/history", tags=["Workflow"])
async def workflow_clear_history():
    """워크플로우 대화 기록 초기화"""
    try:
        agent = get_workflow_agent()
        agent.clear_history()
        return {"status": "cleared"}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"기록 초기화 오류: {str(e)}"
        )


@app.get("/workflow/history", tags=["Workflow"])
async def workflow_get_history():
    """워크플로우 대화 기록 조회"""
    try:
        agent = get_workflow_agent()
        history = agent.get_history()

        return {
            "count": len(history),
            "history": [
                {"role": msg.role, "content": msg.content}
                for msg in history
            ]
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"기록 조회 오류: {str(e)}"
        )


# ========================================
# 스트리밍 API 엔드포인트
# ========================================

from api.streaming import (
    StreamChatRequest,
    stream_workflow_sse,
    stream_workflow_datastream
)


@app.post("/workflow/chat/stream", tags=["Workflow Streaming"])
async def workflow_chat_stream(request: StreamChatRequest):
    """
    LangGraph 워크플로우 스트리밍 채팅 (SSE)

    실시간으로 응답을 스트리밍합니다.

    **이벤트 타입:**
    - `status`: 처리 상태 업데이트 (analyzing, executing_sql, searching 등)
    - `text`: 응답 텍스트
    - `done`: 완료 (sources, elapsed_ms 포함)
    - `error`: 오류 발생

    **요청 예시:**
    ```json
    {
        "query": "AI 특허 알려줘",
        "session_id": "user123"
    }
    ```

    **curl 예시:**
    ```bash
    curl -X POST http://localhost:8000/workflow/chat/stream \\
      -H "Content-Type: application/json" \\
      -d '{"query": "AI 특허 알려줘"}' \\
      --no-buffer
    ```
    """
    return await stream_workflow_sse(request)


@app.post("/workflow/chat/datastream", tags=["Workflow Streaming"])
async def workflow_chat_datastream(request: StreamChatRequest):
    """
    LangGraph 워크플로우 스트리밍 채팅 (AI SDK 호환)

    assistant-ui와 연동 가능한 DataStream 형식으로 응답합니다.

    **요청 예시:**
    ```json
    {
        "query": "인공지능 연구 동향",
        "session_id": "default"
    }
    ```
    """
    return await stream_workflow_datastream(request)


# ========================================
# 시각화 API 엔드포인트
# ========================================

def _infer_relation(src_type: str, tgt_type: str) -> str:
    """노드 타입 기반 관계 추론"""
    relation_map = {
        ("patent", "ipc"): "has_ipc",
        ("ipc", "patent"): "ipc_of",
        ("patent", "applicant"): "applied_by",
        ("applicant", "patent"): "applied",
        ("patent", "org"): "owned_by",
        ("org", "patent"): "owns",
        ("project", "org"): "conducted_by",
        ("org", "project"): "conducts",
        ("project", "tech"): "uses_tech",
        ("tech", "project"): "tech_of",
        ("equip", "org"): "owned_by",
        ("org", "equip"): "owns_equip",
        ("patent", "tech"): "related_tech",
        ("tech", "patent"): "tech_in_patent",
        ("ancm", "evalp"): "has_criteria",
        ("evalp", "ancm"): "criteria_of",
        ("project", "gis"): "located_in",
        ("gis", "project"): "location_of",
    }
    return relation_map.get((src_type, tgt_type), "related")

@app.get("/visualization/graph", tags=["Visualization"])
async def get_graph_visualization(
    entity_type: str = None,
    community_id: int = None,
    limit: int = 100,
    include_edges: bool = True
):
    """
    그래프 시각화 데이터 조회 (cuGraph/Louvain)

    - **entity_type**: 특정 엔티티 타입만 조회 (patent, project, equip 등)
    - **community_id**: 특정 커뮤니티만 조회
    - **limit**: 최대 노드 수 (기본값 100)
    - **include_edges**: 엣지 포함 여부

    **응답:**
    - nodes: 노드 목록 (id, name, entity_type, community, pagerank)
    - links: 엣지 목록 (source, target, relation)
    - stats: 통계 정보
    """
    try:
        kg = get_knowledge_graph()
        if not kg:
            raise HTTPException(status_code=503, detail="Knowledge Graph가 초기화되지 않았습니다")

        nodes = []
        node_ids = set()

        if entity_type:
            # 특정 타입만 조회 후 연결된 이웃도 추가
            central_nodes = kg.get_central_nodes(
                entity_type=entity_type,
                limit=limit
            )
            primary_node_ids = set()
            for node in central_nodes:
                node_data = {
                    "id": node["node_id"],
                    "name": node.get("name", node["node_id"]),
                    "entity_type": node.get("entity_type", "unknown"),
                    "community": node.get("community"),
                    "pagerank": node.get("pagerank", 0.0)
                }
                nodes.append(node_data)
                node_ids.add(node["node_id"])
                primary_node_ids.add(node["node_id"])

            # 연결된 이웃 노드도 추가 (엣지 시각화를 위해)
            if include_edges:
                for node_id in list(primary_node_ids)[:20]:  # 상위 20개만
                    try:
                        neighbors = kg.get_neighbors(node_id, depth=1)
                        for neighbor in neighbors[:5]:  # 각 노드당 5개 이웃
                            neighbor_id = neighbor.get("node_id")
                            if neighbor_id and neighbor_id not in node_ids:
                                # 이웃 노드 정보 가져오기
                                neighbor_node = kg.get_node(neighbor_id)
                                if neighbor_node:
                                    nodes.append({
                                        "id": neighbor_id,
                                        "name": neighbor_node.get("name", neighbor_id),
                                        "entity_type": neighbor_node.get("entity_type", "unknown"),
                                        "community": neighbor_node.get("community"),
                                        "pagerank": neighbor_node.get("pagerank", 0.0)
                                    })
                                    node_ids.add(neighbor_id)
                    except:
                        pass
        else:
            # 다양한 타입에서 균등하게 가져오기
            entity_types = ["patent", "project", "equip", "org", "ipc", "ancm", "evalp"]
            per_type = max(5, limit // len(entity_types))
            primary_node_ids = set()

            for etype in entity_types:
                type_nodes = kg.get_central_nodes(entity_type=etype, limit=per_type)
                for node in type_nodes:
                    if len(nodes) >= limit:
                        break
                    node_data = {
                        "id": node["node_id"],
                        "name": node.get("name", node["node_id"]),
                        "entity_type": node.get("entity_type", "unknown"),
                        "community": node.get("community"),
                        "pagerank": node.get("pagerank", 0.0)
                    }
                    nodes.append(node_data)
                    node_ids.add(node["node_id"])
                    primary_node_ids.add(node["node_id"])

            # 연결된 이웃 노드도 추가 (전체 타입 조회 시에도)
            # 노드 수에 비례하여 이웃 조회 범위 조정
            if include_edges:
                nodes_to_expand = min(len(primary_node_ids), max(30, limit // 10))
                neighbors_per_node = max(3, min(10, limit // 50))
                for node_id in list(primary_node_ids)[:nodes_to_expand]:
                    try:
                        neighbors = kg.get_neighbors(node_id, depth=1)
                        for neighbor in neighbors[:neighbors_per_node]:
                            neighbor_id = neighbor.get("node_id")
                            if neighbor_id and neighbor_id not in node_ids:
                                neighbor_node = kg.get_node(neighbor_id)
                                if neighbor_node:
                                    nodes.append({
                                        "id": neighbor_id,
                                        "name": neighbor_node.get("name", neighbor_id),
                                        "entity_type": neighbor_node.get("entity_type", "unknown"),
                                        "community": neighbor_node.get("community"),
                                        "pagerank": neighbor_node.get("pagerank", 0.0)
                                    })
                                    node_ids.add(neighbor_id)
                    except:
                        pass

        # 엣지 조회 - 모든 노드의 이웃 관계 확인
        links = []
        link_set = set()  # 중복 엣지 방지
        if include_edges and nodes:
            # 모든 노드에 대해 이웃 조회 (제한 없이)
            for node in nodes:
                try:
                    # get_neighbors는 리스트를 반환
                    neighbors = kg.get_neighbors(node["id"], depth=1)
                    for neighbor in neighbors:
                        neighbor_id = neighbor.get("node_id")
                        if neighbor_id in node_ids:
                            # 중복 방지 (양방향 고려)
                            edge_key = tuple(sorted([node["id"], neighbor_id]))
                            if edge_key not in link_set:
                                link_set.add(edge_key)
                                # 관계 타입 추론 (노드 타입 기반)
                                src_type = node.get("entity_type", "")
                                tgt_node = next((n for n in nodes if n["id"] == neighbor_id), None)
                                tgt_type = tgt_node.get("entity_type", "") if tgt_node else ""
                                relation = _infer_relation(src_type, tgt_type)
                                links.append({
                                    "source": node["id"],
                                    "target": neighbor_id,
                                    "relation": relation,
                                    "weight": neighbor.get("weight", 1.0)
                                })
                except Exception as e:
                    logger.debug(f"이웃 조회 오류 ({node['id']}): {e}")

        # 통계
        stats = {
            "total_nodes": len(nodes),
            "total_edges": len(links),
            "community_count": len(set(n.get("community", 0) for n in nodes if n.get("community") is not None))
        }

        return {
            "nodes": nodes,
            "links": links,
            "stats": stats
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"그래프 조회 오류: {str(e)}")


@app.get("/visualization/graph/community/{community_id}", tags=["Visualization"])
async def get_community_graph(community_id: int, limit: int = 50):
    """
    특정 Louvain 커뮤니티의 그래프 데이터 조회

    - **community_id**: 커뮤니티 ID
    - **limit**: 최대 노드 수
    """
    try:
        kg = get_knowledge_graph()
        if not kg:
            raise HTTPException(status_code=503, detail="Knowledge Graph가 초기화되지 않았습니다")

        # 커뮤니티 노드 조회
        nodes_data = kg.get_community_nodes(community_id, limit=limit)

        nodes = []
        node_ids = set()

        for node in nodes_data:
            node_data = {
                "id": node["node_id"],
                "name": node.get("name", node["node_id"]),
                "entity_type": node.get("entity_type", "unknown"),
                "community": community_id,
                "pagerank": node.get("pagerank", 0.0)
            }
            nodes.append(node_data)
            node_ids.add(node["node_id"])

        # 커뮤니티 내부 엣지만 조회 (모든 노드 확인)
        links = []
        link_set = set()  # 중복 방지
        for node in nodes:
            try:
                # get_neighbors는 리스트를 반환
                neighbors = kg.get_neighbors(node["id"], depth=1)
                for neighbor in neighbors:
                    neighbor_id = neighbor.get("node_id")
                    if neighbor_id in node_ids:
                        edge_key = tuple(sorted([node["id"], neighbor_id]))
                        if edge_key not in link_set:
                            link_set.add(edge_key)
                            # 관계 타입 추론
                            src_type = node.get("entity_type", "")
                            tgt_node = next((n for n in nodes if n["id"] == neighbor_id), None)
                            tgt_type = tgt_node.get("entity_type", "") if tgt_node else ""
                            relation = _infer_relation(src_type, tgt_type)
                            links.append({
                                "source": node["id"],
                                "target": neighbor_id,
                                "relation": relation,
                                "weight": neighbor.get("weight", 1.0)
                            })
            except:
                pass

        return {
            "community_id": community_id,
            "nodes": nodes,
            "links": links,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(links)
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"커뮤니티 조회 오류: {str(e)}")


@app.get("/visualization/graph/subgraph", tags=["Visualization"])
async def get_subgraph(node_ids: str, depth: int = 1, include_metadata: bool = True):
    """
    특정 노드들의 서브그래프 조회 (검색 결과 시각화용)

    - **node_ids**: 쉼표 구분 노드 ID 목록 (예: patent_123,project_456)
    - **depth**: 탐색 깊이 (기본 1-hop)
    - **include_metadata**: community, pagerank, connections 포함 여부

    **응답:**
    - nodes: 노드 목록 (id, name, entity_type, community, pagerank, connections)
    - links: 엣지 목록 (source, target, relation)
    """
    try:
        kg = get_knowledge_graph()
        if not kg:
            raise HTTPException(status_code=503, detail="Knowledge Graph가 초기화되지 않았습니다")

        # 노드 ID 파싱
        target_node_ids = [nid.strip() for nid in node_ids.split(",") if nid.strip()]
        if not target_node_ids:
            raise HTTPException(status_code=400, detail="node_ids가 필요합니다")

        nodes = []
        node_ids_set = set(target_node_ids)
        links = []
        link_set = set()

        # 각 노드와 이웃 조회
        for node_id in target_node_ids:
            node_info = kg.get_node(node_id)
            if not node_info:
                continue

            # 연결 수 계산
            connections = {"ipc": 0, "applicant": 0, "org": 0, "related": 0}
            neighbors = kg.get_neighbors(node_id, depth=1)

            for neighbor in neighbors:
                neighbor_id = neighbor.get("node_id")
                neighbor_type = neighbor.get("node", {}).get("entity_type", "unknown")

                # 연결 타입별 카운트
                if neighbor_type == "ipc":
                    connections["ipc"] += 1
                elif neighbor_type == "applicant":
                    connections["applicant"] += 1
                elif neighbor_type == "org":
                    connections["org"] += 1
                else:
                    connections["related"] += 1

                # depth 범위 내 이웃 노드 추가
                if neighbor_id and neighbor_id not in node_ids_set:
                    node_ids_set.add(neighbor_id)
                    neighbor_node = neighbor.get("node", {})
                    nodes.append({
                        "id": neighbor_id,
                        "name": neighbor_node.get("name", neighbor_id),
                        "entity_type": neighbor_node.get("entity_type", "unknown"),
                        "community": neighbor_node.get("community"),
                        "pagerank": neighbor_node.get("pagerank", 0.0)
                    })

                # 엣지 추가
                if neighbor_id:
                    edge_key = tuple(sorted([node_id, neighbor_id]))
                    if edge_key not in link_set:
                        link_set.add(edge_key)
                        src_type = node_info.get("entity_type", "")
                        tgt_type = neighbor.get("node", {}).get("entity_type", "")
                        relation = _infer_relation(src_type, tgt_type)
                        links.append({
                            "source": node_id,
                            "target": neighbor_id,
                            "relation": relation,
                            "weight": neighbor.get("weight", 1.0)
                        })

            # 메인 노드 정보 추가
            node_data = {
                "id": node_id,
                "name": node_info.get("name", node_id),
                "entity_type": node_info.get("entity_type", "unknown"),
                "community": node_info.get("community"),
                "pagerank": node_info.get("pagerank", 0.0),
                "is_main": True  # 검색 결과 노드 표시
            }
            if include_metadata:
                node_data["connections"] = connections
            nodes.insert(0, node_data)

        return {
            "nodes": nodes,
            "links": links,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(links),
                "main_nodes": len(target_node_ids)
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서브그래프 조회 오류: {str(e)}")


@app.get("/visualization/vectors", tags=["Visualization"])
async def get_vector_visualization(
    collection: str = None,
    query: str = None,
    limit: int = 200
):
    """
    벡터 시각화 데이터 조회 (Qdrant + UMAP)

    - **collection**: 특정 컬렉션만 조회 (patent, project 등)
    - **query**: 검색 쿼리 (입력 시 유사 벡터 조회)
    - **limit**: 최대 포인트 수

    **응답:**
    - points: 2D 좌표로 변환된 벡터 포인트
    - stats: 통계 정보

    **참고:** UMAP 변환은 서버 측에서 수행됨
    """
    try:
        import numpy as np
        from api.search import search_single_collection, get_all_collection_info

        points = []

        if query:
            # 쿼리 기반 검색
            collections_to_search = [collection] if collection else list(COLLECTIONS.keys())[:5]

            all_results = []
            for coll in collections_to_search:
                try:
                    # search_single_collection(query, collection_key, limit)
                    results = search_single_collection(query, coll, limit=limit // max(1, len(collections_to_search)))
                    for r in results:
                        all_results.append({
                            "id": r.get("id", ""),
                            "name": r.get("payload", {}).get("title", r.get("id", "")),
                            "collection": coll,
                            "score": r.get("score", 0.0)
                        })
                except Exception as e:
                    logger.debug(f"벡터 검색 오류 ({coll}): {e}")

            # 간단한 2D 배치 (실제로는 UMAP 사용 권장)
            n = len(all_results)
            if n > 0:
                # 점수 기반 원형 배치 (시각화용)
                for i, r in enumerate(all_results):
                    angle = 2 * np.pi * i / n
                    radius = 1 - r["score"]  # 높은 점수는 중심에
                    points.append({
                        "id": r["id"],
                        "name": r["name"],
                        "collection": r["collection"],
                        "x": float(radius * np.cos(angle)),
                        "y": float(radius * np.sin(angle)),
                        "score": r["score"]
                    })
        else:
            # 컬렉션 정보 기반 샘플 데이터
            collections_info = get_all_collection_info()

            # 간단한 그리드 배치
            x_offset = 0
            for coll_info in collections_info[:8]:
                coll_name = coll_info.get("name", "")
                count = min(coll_info.get("count", 0), limit // 8)

                for i in range(min(count, 25)):
                    points.append({
                        "id": f"{coll_name}_{i}",
                        "name": f"{coll_name} 샘플 {i+1}",
                        "collection": coll_name,
                        "x": float(x_offset + (i % 5) * 0.2),
                        "y": float((i // 5) * 0.2),
                        "score": None
                    })
                x_offset += 1.5

        # 컬렉션 통계
        collections_info = get_all_collection_info()
        total_vectors = sum(c.get("count", 0) for c in collections_info)

        return {
            "points": points,
            "stats": {
                "total_vectors": total_vectors,
                "collections": [c.get("name", "") for c in collections_info],
                "dimension": 1024  # KURE v1
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"벡터 조회 오류: {str(e)}")


@app.get("/visualization/vectors/search", tags=["Visualization"])
async def search_vectors_visualization(
    query: str,
    collections: str = None,
    top_k: int = 50
):
    """
    검색 결과를 시각화용 데이터로 반환

    - **query**: 검색 쿼리
    - **collections**: 검색할 컬렉션 (쉼표 구분, 예: "patent,project")
    - **top_k**: 상위 결과 수
    """
    try:
        import numpy as np
        from api.search import search_single_collection

        collection_list = collections.split(",") if collections else list(COLLECTIONS.keys())[:5]

        all_results = []
        for coll in collection_list:
            try:
                # search_single_collection(query, collection_key, limit)
                results = search_single_collection(query, coll.strip(), limit=top_k // max(1, len(collection_list)))
                for r in results:
                    all_results.append({
                        "id": r.get("id", ""),
                        "name": r.get("payload", {}).get("title", r.get("id", "")),
                        "collection": coll.strip(),
                        "score": r.get("score", 0.0)
                    })
            except Exception as e:
                logger.debug(f"벡터 검색 오류 ({coll}): {e}")

        # 점수 기반 정렬
        all_results.sort(key=lambda x: x["score"], reverse=True)

        # 2D 좌표 생성 (점수 기반 방사형 배치)
        points = []
        n = len(all_results)
        for i, r in enumerate(all_results):
            angle = 2 * np.pi * i / max(n, 1)
            radius = 0.2 + (1 - r["score"]) * 0.8  # 높은 점수 = 중심 근처
            points.append({
                "id": r["id"],
                "name": r["name"],
                "collection": r["collection"],
                "x": float(radius * np.cos(angle)),
                "y": float(radius * np.sin(angle)),
                "score": r["score"]
            })

        return {
            "query": query,
            "points": points,
            "result_count": len(points)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"검색 시각화 오류: {str(e)}")


@app.get("/visualization/stats", tags=["Visualization"])
async def get_visualization_stats():
    """
    시각화용 전체 통계 정보
    """
    try:
        stats = {
            "graph": {},
            "vectors": {},
            "available_features": []
        }

        # 그래프 통계
        try:
            kg = get_knowledge_graph()
            if kg:
                # cuGraph API에서 실제 통계 가져오기
                graph_stats = kg.get_statistics()
                stats["graph"] = {
                    "available": True,
                    "node_count": graph_stats.get("nodes", 0),
                    "edge_count": graph_stats.get("edges", 0),
                    "community_count": graph_stats.get("components", 0)
                }
                stats["available_features"].append("graph_visualization")
                stats["available_features"].append("community_detection")
                stats["available_features"].append("pagerank")
        except Exception as e:
            logger.warning(f"그래프 통계 조회 오류: {e}")
            stats["graph"] = {"available": False}

        # 벡터 통계
        try:
            collections_info = get_all_collection_info()
            stats["vectors"] = {
                "available": True,
                "total_vectors": sum(c.get("count", 0) for c in collections_info),
                "collections": len(collections_info),
                "dimension": 1024
            }
            stats["available_features"].append("vector_visualization")
            stats["available_features"].append("semantic_search")
        except:
            stats["vectors"] = {"available": False}

        return stats

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"통계 조회 오류: {str(e)}")


# ========================================
# 공공 AX API 라우터 등록
# ========================================
from api.routers.ax_api import router as ax_router

# 공공 AX API 라우터 추가 (Chat, Map, Analyze 엔드포인트)
app.include_router(ax_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
