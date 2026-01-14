"""
공공 AX API 라우터
AX_API.yaml 명세 기반 구현

엔드포인트:
- POST /chat/ask - AI 질의응답
- POST /chat/detail - 특허 상세 정보
- GET /map/search - 지도 기반 검색
- POST /analyze/compare - 문서 비교 분석
- POST /analyze/detail - 상세 비교 분석
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import time
import json
import logging
from datetime import datetime
from typing import Literal, Dict, Any, List
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from api.models import (
    # Chat API
    ChatAskRequest, ChatAskResponse, WorkflowStatus, RelatedPatentItem, PatentImageItem,
    ChatDetailRequest, ChatDetailResponse, PatentInfo, TimelineEvent, ApplicantInfo, PatentImages,
    # Phase 102: 그래프 시각화 모델
    GraphNode, GraphEdge, GraphData,
    # Map API
    MapSearchResponse, MapLocation,
    # Analyze API
    AnalyzeCompareRequest, AnalyzeCompareResponse, DocumentSummary, ComparisonResult,
    AnalyzeDetailRequest, AnalyzeDetailResponse, DocumentAnalysis, ComparisonItem, AnalysisConclusion,
    APIError
)
from api.search import search_single_collection
from sql.db_connector import get_db_connection
from workflow.graph import run_workflow
from graph.graph_builder import NODE_TYPES  # Phase 102: 노드 타입 색상

logger = logging.getLogger(__name__)

# APIRouter 생성
router = APIRouter(prefix="", tags=["공공 AX API"])

# 로그 디렉토리 설정
LOG_DIR = Path(__file__).parent.parent.parent / "logs" / "workflow"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ========================================
# 유틸리티 함수
# ========================================

def save_workflow_log(
    query: str,
    level: str,
    result: Dict[str, Any],
    related_patents: List[Dict],
    elapsed_ms: float
) -> str:
    """워크플로우 처리 결과를 JSON 로그로 저장

    Args:
        query: 사용자 질문
        level: 리터러시 레벨
        result: run_workflow() 결과
        related_patents: 추출된 관련 특허 목록
        elapsed_ms: 총 처리 시간 (ms)

    Returns:
        저장된 로그 파일 경로
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    log_filename = f"workflow_{timestamp}.json"
    log_path = LOG_DIR / log_filename

    # SQL 결과 직렬화
    sql_result_data = None
    if result.get("sql_result"):
        sql_result = result["sql_result"]
        sql_result_data = {
            "success": getattr(sql_result, 'success', False),
            "columns": getattr(sql_result, 'columns', []),
            "rows": [list(row) for row in getattr(sql_result, 'rows', [])][:20],  # 최대 20행
            "row_count": getattr(sql_result, 'row_count', 0),
            "error": getattr(sql_result, 'error', None),
            "execution_time_ms": getattr(sql_result, 'execution_time_ms', 0)
        }

    # RAG 결과 직렬화
    rag_results_data = []
    for rag_item in result.get("rag_results", [])[:20]:  # 최대 20개
        rag_results_data.append({
            "node_id": getattr(rag_item, 'node_id', ''),
            "name": getattr(rag_item, 'name', ''),
            "entity_type": getattr(rag_item, 'entity_type', ''),
            "score": float(getattr(rag_item, 'score', 0)),
            "content": getattr(rag_item, 'content', '')[:500]  # 내용 요약
        })

    # Sources 직렬화
    sources_data = []
    for source in result.get("sources", [])[:20]:
        sources_data.append({
            "id": source.get("id", source.get("node_id", "")),
            "title": source.get("title", source.get("name", "")),
            "entity_type": source.get("entity_type", ""),
            "score": float(source.get("score", 0))
        })

    # 로그 데이터 구성
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "request": {
            "query": query,
            "level": level
        },
        "analysis": {
            "query_type": result.get("query_type", ""),
            "query_subtype": result.get("query_subtype", ""),
            "query_intent": result.get("query_intent", ""),
            "entity_types": result.get("entity_types", []),
            "related_tables": result.get("related_tables", []),
            "keywords": result.get("keywords", []),
            "structured_keywords": result.get("structured_keywords"),
            "expanded_keywords": result.get("expanded_keywords", []),
            "is_compound": result.get("is_compound", False),
            "is_aggregation": result.get("is_aggregation", False)
        },
        "search_results": {
            "es_scout": {
                "synonym_keywords": result.get("synonym_keywords", []),
                "es_doc_ids": result.get("es_doc_ids", {}),
                "domain_hits": result.get("domain_hits", {})
            },
            "vector_search": {
                "vector_doc_ids": result.get("vector_doc_ids", [])[:20],
                "vector_result_count": result.get("vector_result_count", 0),
                "cached_vector_results": bool(result.get("cached_vector_results"))
            },
            "sql_result": sql_result_data,
            "rag_results": rag_results_data,
            "sources": sources_data
        },
        "generated_sql": result.get("generated_sql"),
        "response": {
            "answer": result.get("response", result.get("answer", "")),
            "related_patents": [
                {"id": p.id, "title": p.title, "score": p.score}
                for p in related_patents
            ],
            "reasoning_trace": result.get("reasoning_trace", "")[:2000]  # 추론 과정 요약
        },
        "metadata": {
            "search_strategy": result.get("search_strategy", ""),
            "elapsed_ms": elapsed_ms,
            "stage_timing": result.get("stage_timing", {}),
            "error": result.get("error")
        }
    }

    # JSON 파일 저장
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"워크플로우 로그 저장: {log_path}")
        return str(log_path)
    except Exception as e:
        logger.error(f"로그 저장 실패: {e}")
        return ""


# 리터러시 레벨별 시스템 프롬프트
LEVEL_PROMPTS = {
    "초등": "초등학생이 이해할 수 있도록 쉽고 친근하게 설명해주세요. 어려운 용어는 쉬운 말로 바꿔주세요.",
    "일반인": "일반인이 이해할 수 있는 수준으로 설명해주세요. 전문 용어가 나오면 간단히 설명을 덧붙여주세요.",
    "전문가": "전문 용어를 사용하여 기술적으로 상세히 설명해주세요. 관련 기술 동향이나 특허 정보를 포함해주세요."
}


def calculate_expiration_date(application_date: str) -> str:
    """출원일로부터 만료일 계산 (출원일 + 20년)"""
    if not application_date:
        return None
    try:
        for fmt in ["%Y.%m.%d", "%Y-%m-%d", "%Y%m%d"]:
            try:
                dt = datetime.strptime(application_date.replace("-", ".").replace("/", "."), fmt)
                expiry = dt.replace(year=dt.year + 20)
                return expiry.strftime("%Y.%m.%d")
            except ValueError:
                continue
        return None
    except Exception:
        return None


def determine_patent_status(patent_row: dict) -> str:
    """특허 상태 판정"""
    if patent_row.get('patent_rgstn_ymd') or patent_row.get('registration_date'):
        return "등록"
    elif patent_row.get('ptnaplc_othbc_ymd') or patent_row.get('publication_date'):
        return "공개"
    elif patent_row.get('ptnaplc_ymd') or patent_row.get('application_date'):
        return "출원"
    return "출원"


def format_country(country_code: str) -> str:
    """국가 코드 포맷팅"""
    country_names = {
        "KR": "한국(KR)",
        "US": "미국(US)",
        "JP": "일본(JP)",
        "CN": "중국(CN)",
        "EP": "유럽(EP)",
        "WO": "PCT(WO)"
    }
    return country_names.get(country_code, country_code) if country_code else "한국(KR)"


# ========================================
# Chat API 엔드포인트
# ========================================

@router.post("/chat/ask", response_model=ChatAskResponse, tags=["Chat"])
async def chat_ask(request: ChatAskRequest):
    """
    AI 질의응답

    사용자의 질문에 대해 AI가 답변을 생성합니다.
    기존 LangGraph 워크플로우(ES + Vector RAG + Graph RAG + SQL)를 활용합니다.

    - **level**: 사용자 리터러시 수준 (초등/일반인/전문가)
    - **question**: 사용자 질문 내용
    """
    start_time = time.time()
    workflow_status = WorkflowStatus()

    try:
        # 1. 분석 단계
        workflow_status.analysis = "ing"
        analysis_start = time.time()

        # 워크플로우 실행 (공공 AX API: 특허 데이터만 검색)
        result = run_workflow(
            query=request.question,
            session_id="chat_ask_session",
            level=request.level,
            entity_types=["patent"]  # 공공 AX API는 특허 데이터만 참조
        )

        workflow_status.analysis = round(time.time() - analysis_start, 1)

        # 2. SQL 단계 (워크플로우에서 처리)
        workflow_status.sql = round(result.get("sql_time", 0), 1) if result.get("sql_time") else None

        # 3. RAG 단계
        workflow_status.rag = round(result.get("rag_time", 0), 1) if result.get("rag_time") else None

        # 4. 병합 단계
        workflow_status.merge = round(time.time() - start_time, 1)

        # 관련 특허 추출 (sources, sql_result, rag_results에서 수집)
        related_patents = []
        seen_ids = set()

        # 1. sources에서 추출
        sources = result.get("sources", [])
        for i, source in enumerate(sources[:10]):
            entity_type = source.get("entity_type", "")
            if entity_type in ["patent", "patents", "Patent"]:
                doc_id = str(source.get("id", source.get("node_id", "")))
                title = source.get("title", source.get("name", ""))
                # 유효한 특허 ID와 제목이 있는 경우만 추가 (placeholder 제외)
                if doc_id and doc_id not in seen_ids and not doc_id.startswith("p00") and title and title != "제목 없음":
                    seen_ids.add(doc_id)
                    related_patents.append(RelatedPatentItem(
                        id=doc_id,
                        title=title[:100],
                        score=f"{int(source.get('score', 0.5) * 100)}%"
                    ))

        # 2. SQL 결과에서 특허 추출
        sql_result = result.get("sql_result")
        if sql_result and hasattr(sql_result, 'rows') and sql_result.rows:
            columns = sql_result.columns if hasattr(sql_result, 'columns') else []
            col_map = {col.lower(): idx for idx, col in enumerate(columns)}

            for row in sql_result.rows[:10]:
                # 특허번호 컬럼 탐색
                doc_id = None
                title = "제목 없음"

                for col_name in ['documentid', 'ptnaplc_no', '특허번호', 'patent_id']:
                    if col_name.lower() in col_map:
                        doc_id = str(row[col_map[col_name.lower()]])
                        break

                for col_name in ['conts_klang_nm', 'title', '특허명', 'patent_name']:
                    if col_name.lower() in col_map:
                        title = str(row[col_map[col_name.lower()]])[:100]
                        break

                if doc_id and doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    related_patents.append(RelatedPatentItem(
                        id=doc_id,
                        title=title,
                        score="SQL"
                    ))

        # 3. RAG 결과에서 특허 추출
        rag_results = result.get("rag_results", [])
        for rag_item in rag_results[:10]:
            if hasattr(rag_item, 'entity_type') and rag_item.entity_type in ["patent", "patents"]:
                doc_id = str(getattr(rag_item, 'node_id', ''))
                if doc_id and doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    related_patents.append(RelatedPatentItem(
                        id=doc_id,
                        title=getattr(rag_item, 'name', '제목 없음')[:100],
                        score=f"{int(getattr(rag_item, 'score', 0.5) * 100)}%"
                    ))

        # 최대 5개로 제한
        related_patents = related_patents[:5]

        # 총 처리 시간 계산
        total_elapsed_ms = (time.time() - start_time) * 1000

        # JSON 로그 저장
        log_path = save_workflow_log(
            query=request.question,
            level=request.level,
            result=result,
            related_patents=related_patents,
            elapsed_ms=total_elapsed_ms
        )
        if log_path:
            logger.info(f"처리 로그 저장 완료: {log_path}")

        # Phase 102: 신뢰도 점수
        confidence_score = result.get("context_quality", 0.0)

        # Phase 102: 그래프 데이터 추출 (특허 + 1-hop 관련 엔티티)
        graph_nodes = []
        graph_edges = []
        seen_graph_nodes = set()

        rag_results = result.get("rag_results", [])
        # Phase 102: 벡터 검색 결과(related_entities 있음)와 ES 결과를 모두 포함하도록 상위 15개 처리
        for rag_item in rag_results[:15]:
            node_id = getattr(rag_item, 'node_id', '') if hasattr(rag_item, 'node_id') else ''
            entity_type = getattr(rag_item, 'entity_type', 'patent') if hasattr(rag_item, 'entity_type') else 'patent'
            node_name = getattr(rag_item, 'name', '') if hasattr(rag_item, 'name') else ''
            node_score = float(getattr(rag_item, 'score', 0.5)) if hasattr(rag_item, 'score') else 0.5

            # 특허 노드 추가
            if node_id and node_id not in seen_graph_nodes:
                seen_graph_nodes.add(node_id)
                node_color = NODE_TYPES.get(entity_type, {}).get("color", "#9E9E9E")
                graph_nodes.append(GraphNode(
                    id=node_id,
                    name=node_name[:100] if node_name else node_id,
                    type=entity_type,
                    score=node_score,
                    color=node_color
                ))

            # 1-hop 관련 엔티티 + 엣지 추출
            metadata = getattr(rag_item, 'metadata', {}) if hasattr(rag_item, 'metadata') else {}
            if metadata:
                related_entities = metadata.get("related_entities", [])
                for rel in related_entities[:5]:  # 특허당 최대 5개
                    rel_id = rel.get("node_id", "")
                    rel_type = rel.get("entity_type", "org")
                    rel_name = rel.get("name", "")

                    # 관련 엔티티 노드 추가
                    if rel_id and rel_id not in seen_graph_nodes:
                        seen_graph_nodes.add(rel_id)
                        rel_color = NODE_TYPES.get(rel_type, {}).get("color", "#9E9E9E")
                        graph_nodes.append(GraphNode(
                            id=rel_id,
                            name=rel_name[:100] if rel_name else rel_id,
                            type=rel_type,
                            score=rel.get("score", 0.3),
                            color=rel_color
                        ))

                    # 엣지 추가
                    if node_id and rel_id:
                        graph_edges.append(GraphEdge(
                            from_id=node_id,
                            to_id=rel_id,
                            relation=rel.get("relation", "related")
                        ))

        # 그래프 데이터 생성 (노드가 있을 때만)
        graph_data = GraphData(nodes=graph_nodes, edges=graph_edges) if graph_nodes else None

        # 응답 생성
        return ChatAskResponse(
            workflow=workflow_status,
            answer=result.get("response", result.get("answer", "답변을 생성하지 못했습니다.")),
            confidence_score=confidence_score,
            related_patents=related_patents,
            graph_data=graph_data,
            application_no=related_patents[0].id if related_patents else None,
            application_date=None,
            img=[]  # Mock 데이터
        )

    except Exception as e:
        logger.error(f"/chat/ask 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/detail", response_model=ChatDetailResponse, tags=["Chat"])
async def chat_detail(request: ChatDetailRequest):
    """
    특허 문서 상세 정보 조회

    특정 특허 문서의 상세 정보를 조회합니다.

    - **doc_id**: 특허 문서 번호 (출원번호 또는 등록번호)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # doc_id 정규화 (KR- 접두사 제거)
        doc_id = request.doc_id.replace("KR-", "").replace("kr-", "").strip()

        # 특허 기본 정보 조회
        cursor.execute("""
            SELECT
                documentid,
                conts_klang_nm as title,
                conts_engl_nm as title_en,
                ntcd as country,
                ptnaplc_no as app_num,
                patent_rgno as reg_num,
                ptnaplc_ymd as application_date,
                ptnaplc_othbc_ymd as publication_date,
                patent_rgstn_ymd as registration_date,
                patent_frst_appn as original_applicant
            FROM f_patents
            WHERE documentid = %s
               OR ptnaplc_no = %s
               OR patent_rgno = %s
            LIMIT 1
        """, (doc_id, doc_id, doc_id))

        patent_row = cursor.fetchone()

        if not patent_row:
            conn.close()
            raise HTTPException(
                status_code=404,
                detail={"code": "NOT_FOUND", "message": "해당 문서를 찾을 수 없습니다.", "details": {"doc_id": request.doc_id}}
            )

        # 딕셔너리로 변환
        columns = [desc[0] for desc in cursor.description]
        patent = dict(zip(columns, patent_row))

        # 출원인 정보 조회
        cursor.execute("""
            SELECT applicant_name, applicant_country
            FROM f_patent_applicants
            WHERE document_id = %s
            ORDER BY applicant_order
        """, (patent['documentid'],))

        applicant_rows = cursor.fetchall()
        conn.close()

        # 타임라인 생성
        timeline = []
        if patent.get('application_date'):
            timeline.append(TimelineEvent(date=patent['application_date'], event="출원"))
        if patent.get('publication_date'):
            timeline.append(TimelineEvent(date=patent['publication_date'], event="공개"))
        if patent.get('registration_date'):
            timeline.append(TimelineEvent(date=patent['registration_date'], event="등록"))

        # 제목 포맷팅 (한영 병기)
        title = patent.get('title', '')
        title_en = patent.get('title_en', '')
        formatted_title = f"{title}({title_en})" if title_en else title

        # 응답 생성
        return ChatDetailResponse(
            patent_info=PatentInfo(
                title=formatted_title,
                status=determine_patent_status(patent),
                country=format_country(patent.get('country')),
                app_num=patent.get('app_num'),
                reg_num=patent.get('reg_num'),
                expiration_date=calculate_expiration_date(patent.get('application_date'))
            ),
            timeline=timeline,
            applicants=ApplicantInfo(
                current=applicant_rows[0][0] if applicant_rows else None,
                original=patent.get('original_applicant')
            ),
            images=PatentImages(
                main_representative=None,  # Mock
                thumbnails=[]  # Mock
            )
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/chat/detail 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# Map API 엔드포인트
# ========================================

@router.get("/map/search", response_model=MapSearchResponse, tags=["Map"])
async def map_search(
    keyword: str = Query(..., min_length=1, max_length=200, description="검색할 특허 키워드")
):
    """
    지도 기반 특허 검색

    특허 키워드로 검색하여 지도상에 표시할 위치 데이터를 반환합니다.

    - **keyword**: 검색 키워드
    """
    try:
        # 1. 벡터 검색으로 관련 특허 찾기
        search_results = search_single_collection(
            query=keyword,
            collection_key="patents",
            limit=50
        )

        if not search_results:
            return MapSearchResponse(locations=[])

        # 특허 ID 추출 (문자열로 변환)
        patent_ids = [str(r.get("id")) for r in search_results if r.get("id")]

        if not patent_ids:
            return MapSearchResponse(locations=[])

        # 2. 출원인 주소 기반 위치 정보 조회
        conn = get_db_connection()
        cursor = conn.cursor()

        # f_gis에서 좌표 조회 (기관명 기반 매칭)
        cursor.execute("""
            SELECT DISTINCT
                p.documentid,
                p.conts_klang_nm as title,
                g.y_coord as lat,
                g.x_coord as lng,
                g.admin_dong_name as region
            FROM f_patents p
            LEFT JOIN f_patent_applicants pa ON p.documentid = pa.document_id
            LEFT JOIN f_gis g ON g.coord_valid = true
            WHERE p.documentid = ANY(%s)
              AND g.y_coord IS NOT NULL
              AND g.x_coord IS NOT NULL
            LIMIT 100
        """, (patent_ids[:20],))

        rows = cursor.fetchall()
        conn.close()

        # 위치 데이터 생성
        location_groups = defaultdict(list)

        for row in rows:
            doc_id, title, lat, lng, region = row
            if lat and lng:
                # 약 1km 정밀도로 그룹핑
                key = (round(float(lat), 2), round(float(lng), 2))
                location_groups[key].append({
                    "id": doc_id,
                    "title": title or "제목 없음",
                    "lat": float(lat),
                    "lng": float(lng)
                })

        # 클러스터링
        locations = []
        for (lat, lng), items in location_groups.items():
            if len(items) > 3:
                locations.append(MapLocation(
                    lat=lat,
                    lng=lng,
                    title=f"{len(items)}건 밀집",
                    type="cluster"
                ))
            else:
                for item in items:
                    locations.append(MapLocation(
                        lat=item["lat"],
                        lng=item["lng"],
                        title=item["title"],
                        type="point"
                    ))

        # 위치 데이터가 없으면 기본 좌표 제공 (서울)
        if not locations:
            for i, r in enumerate(search_results[:5]):
                locations.append(MapLocation(
                    lat=37.5665 + (i * 0.01),
                    lng=126.9780 + (i * 0.01),
                    title=r.get("payload", {}).get("title", f"특허 {i+1}"),
                    type="point"
                ))

        return MapSearchResponse(locations=locations)

    except Exception as e:
        logger.error(f"/map/search 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# Analyze API 엔드포인트
# ========================================

@router.post("/analyze/compare", response_model=AnalyzeCompareResponse, tags=["Analyze"])
async def analyze_compare(request: AnalyzeCompareRequest):
    """
    문서 비교 분석

    키워드 기반으로 내 문서와 관련 특허를 비교 분석합니다.

    - **keyword**: 검색된 특허 키워드
    """
    try:
        # 1. 키워드로 관련 특허 검색
        search_results = search_single_collection(
            query=request.keyword,
            collection_key="patents",
            limit=3
        )

        if not search_results:
            return AnalyzeCompareResponse(
                my_doc_summary=DocumentSummary(
                    title=f"{request.keyword} 관련 연구",
                    goal=f"{request.keyword} 기술 개발 및 적용",
                    method="기존 기술 분석 및 개선"
                ),
                comparison=ComparisonResult(
                    common_tech="관련 특허를 찾을 수 없습니다.",
                    conclusion="키워드를 변경하여 다시 검색해주세요."
                )
            )

        # 2. 상위 특허 정보 추출
        top_patent = search_results[0]
        payload = top_patent.get("payload", {})
        patent_title = payload.get("title", payload.get("conts_klang_nm", ""))

        # 3. 비교 분석 생성
        common_techs = []
        keyword_lower = request.keyword.lower()
        if "배터리" in request.keyword or "battery" in keyword_lower:
            common_techs.append("배터리 관리 시스템(BMS)")
        if "충전" in request.keyword:
            common_techs.append("충전 제어 기술")
        if "AI" in request.keyword or "인공지능" in request.keyword:
            common_techs.append("기계학습 알고리즘")
        if not common_techs:
            common_techs.append(request.keyword.split()[0] if request.keyword.split() else request.keyword)

        return AnalyzeCompareResponse(
            my_doc_summary=DocumentSummary(
                title=f"{request.keyword} 관련 기술 문서",
                goal=f"{request.keyword} 분야의 기술적 문제 해결",
                method=f"기존 {request.keyword} 기술 분석 및 개선 방안 도출"
            ),
            comparison=ComparisonResult(
                common_tech=", ".join(common_techs),
                conclusion=f"검색된 특허 '{patent_title[:30]}...'와 비교 시, "
                           f"공통적으로 {common_techs[0]} 기술을 활용하고 있습니다. "
                           f"세부 기술 구현 방식에서 차별점이 있을 수 있습니다."
            )
        )

    except Exception as e:
        logger.error(f"/analyze/compare 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze/detail", response_model=AnalyzeDetailResponse, tags=["Analyze"])
async def analyze_detail(request: AnalyzeDetailRequest):
    """
    상세 비교 분석

    특정 문서에 대한 상세 비교 분석 결과를 제공합니다.

    - **doc_id**: 분석 대상 문서 번호
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # doc_id 정규화
        doc_id = request.doc_id.replace("KR-", "").replace("kr-", "").strip()

        # 특허 정보 조회
        cursor.execute("""
            SELECT
                documentid,
                conts_klang_nm as title,
                objectko,
                solutionko,
                ipc_main
            FROM f_patents
            WHERE documentid = %s
               OR ptnaplc_no = %s
               OR patent_rgno = %s
            LIMIT 1
        """, (doc_id, doc_id, doc_id))

        patent_row = cursor.fetchone()
        conn.close()

        if not patent_row:
            raise HTTPException(
                status_code=404,
                detail={"code": "NOT_FOUND", "message": "해당 문서를 찾을 수 없습니다.", "details": {"doc_id": request.doc_id}}
            )

        columns = [desc[0] for desc in cursor.description]
        patent = dict(zip(columns, patent_row))

        # 분석 결과 생성
        title = patent.get('title', '제목 없음')
        objectko = patent.get('objectko', '')
        solutionko = patent.get('solutionko', '')

        return AnalyzeDetailResponse(
            category_mode="EASY_SUMMARY",
            my_doc=DocumentAnalysis(
                title="내 문서 요약",
                content=[
                    ComparisonItem(item="문서 유형", desc="연구 문서 (비교 대상)"),
                    ComparisonItem(item="주요 대상", desc="기술 개발 및 연구 목적"),
                    ComparisonItem(item="핵심 기술", desc="상세 분석을 위해 문서 업로드 필요")
                ]
            ),
            target_patent=DocumentAnalysis(
                title="비교대상 특허요약",
                content=[
                    ComparisonItem(item="문서 유형", desc="특허 (발명 기술)"),
                    ComparisonItem(item="특허명", desc=title[:50] + "..." if len(title) > 50 else title),
                    ComparisonItem(item="해결 과제", desc=objectko[:100] + "..." if len(objectko) > 100 else objectko if objectko else "정보 없음"),
                    ComparisonItem(item="해결 수단", desc=solutionko[:100] + "..." if len(solutionko) > 100 else solutionko if solutionko else "정보 없음")
                ]
            ),
            conclusion=AnalysisConclusion(
                title="결론 및 시사점",
                main_text=f"대상 특허 '{title[:30]}...'에 대한 분석 결과입니다.",
                detail_text=f"이 특허는 {objectko[:50] if objectko else '특정 기술적 과제'}를 해결하기 위한 발명입니다. "
                           f"상세 비교를 위해서는 비교 대상 문서의 업로드가 필요합니다."
            )
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/analyze/detail 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))
