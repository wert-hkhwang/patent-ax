"""
Graph RAG 검색 로직 (cuGraph + Qdrant 하이브리드)
- cuGraph API 기반 그래프 탐색
- Qdrant 벡터 검색 결합
- GPU 서버 리소스 활용
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Dict, List, Optional, Any
import logging
from dataclasses import dataclass
from enum import Enum
import requests

from graph.graph_builder import (
    KnowledgeGraphBuilder,
    get_knowledge_graph,
    initialize_knowledge_graph,
    NODE_TYPES
)
from graph.node_resolver import get_node_resolver, NodeResolver

logger = logging.getLogger(__name__)


class SearchStrategy(Enum):
    """검색 전략"""
    GRAPH_ONLY = "graph_only"           # 그래프 탐색만 (cuGraph)
    VECTOR_ONLY = "vector_only"         # 벡터 검색만 (Qdrant)
    HYBRID = "hybrid"                   # 그래프 + 벡터 결합
    GRAPH_ENHANCED = "graph_enhanced"   # 그래프로 확장된 벡터 검색


@dataclass
class GraphSearchResult:
    """그래프 검색 결과"""
    node_id: str
    name: str
    entity_type: str
    description: str
    score: float
    path: Optional[List[Dict]] = None
    related_entities: Optional[List[Dict]] = None


class QdrantSearcher:
    """Qdrant 벡터 검색 클라이언트"""

    def __init__(
        self,
        qdrant_url: str = os.getenv("QDRANT_URL", "http://210.109.80.106:6333"),
        kure_api: str = os.getenv("KURE_API_URL", "http://210.109.80.106:7000/api/embedding")
    ):
        self.qdrant_url = qdrant_url.rstrip("/")
        self.kure_api = kure_api
        self.timeout = 30

        # 컬렉션 매핑 (노드 타입 -> Qdrant 컬렉션) - 12종 노드 타입 지원
        self.collection_map = {
            # 주요 엔티티
            "patent": "patents_v3_collection",              # 특허 (100만)
            "project": "projects_v3_collection",            # 연구과제 (5.3만)
            "equip": "equipments_v3_collection",            # 장비 (5.6만)
            "org": "equipments_v3_collection",              # 기관 (장비 컬렉션에 포함)
            "applicant": "patents_v3_collection",           # 출원인 (특허 컬렉션)
            "ipc": "patents_v3_collection",                 # IPC분류 (특허 컬렉션)
            "gis": "equipments_v3_collection",              # 지역 (장비 컬렉션)
            "tech": "tech_classifications_v3_collection",   # 기술분류
            # 기획지원 관련
            "ancm": "proposals_v3_collection",              # 공고 (제안서 컬렉션)
            "evalp": "proposals_v3_collection",             # 평가표 (제안서 컬렉션)
            # 분류 체계
            "k12": "tech_classifications_v3_collection",    # K12분류
            "6t": "tech_classifications_v3_collection",     # 6T분류
        }

    def get_embedding(self, text: str) -> Optional[List[float]]:
        """KURE API로 임베딩 생성"""
        try:
            response = requests.post(
                self.kure_api,
                json={"text": text},
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
            return result.get("embedding")
        except Exception as e:
            logger.error(f"임베딩 생성 실패: {e}")
            return None

    def search(
        self,
        query: str,
        collection: str = "projects_v3_collection",
        limit: int = 20,
        filters: Optional[Dict] = None
    ) -> List[Dict]:
        """Qdrant 벡터 검색"""
        # 임베딩 생성
        embedding = self.get_embedding(query)
        if not embedding:
            return []

        # 검색 요청
        search_body = {
            "vector": embedding,
            "limit": limit,
            "with_payload": True
        }

        if filters:
            search_body["filter"] = {"must": [
                {"key": k, "match": {"value": v}}
                for k, v in filters.items()
            ]}

        try:
            response = requests.post(
                f"{self.qdrant_url}/collections/{collection}/points/search",
                json=search_body,
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()

            return [
                {
                    "id": hit.get("id"),
                    "score": hit.get("score", 0.0),
                    "payload": hit.get("payload", {})
                }
                for hit in result.get("result", [])
            ]
        except Exception as e:
            logger.error(f"Qdrant 검색 실패: {e}")
            return []

    def multi_search(
        self,
        query: str,
        collections: List[str],
        limit_per_collection: int = 10
    ) -> Dict[str, List[Dict]]:
        """다중 컬렉션 검색"""
        results = {}
        for collection in collections:
            results[collection] = self.search(query, collection, limit_per_collection)
        return results


class GraphRAG:
    """Graph RAG 검색 엔진 (cuGraph + Qdrant 하이브리드)"""

    def __init__(
        self,
        graph_builder: Optional[KnowledgeGraphBuilder] = None,
        qdrant_url: str = os.getenv("QDRANT_URL", "http://210.109.80.106:6333"),
        kure_api: str = os.getenv("KURE_API_URL", "http://210.109.80.106:7000/api/embedding")
    ):
        self.graph_builder = graph_builder
        self.qdrant = QdrantSearcher(qdrant_url=qdrant_url, kure_api=kure_api)
        self.node_resolver = get_node_resolver()  # Phase 75.1: NodeResolver 통합
        self.initialized = False

    def initialize(self, graph_id: str = "713365bb", project_limit: int = 500) -> "GraphRAG":
        """Graph RAG 초기화"""
        if not self.initialized:
            self.graph_builder = initialize_knowledge_graph(
                graph_id=graph_id,
                project_limit=project_limit
            )
            self.initialized = True
        return self

    # =========================================================================
    # Phase 90: 그래프 기반 Fact-Check 메서드
    # =========================================================================

    def validate_relationship(self, node1_id: str, node2_id: str) -> bool:
        """Phase 90: 두 노드가 같은 커뮤니티에 속하는지 확인

        그래프 구조를 기반으로 두 엔티티 간의 관련성을 검증합니다.
        같은 커뮤니티에 속하면 관련성 있음으로 판단.

        Args:
            node1_id: 첫 번째 노드 ID
            node2_id: 두 번째 노드 ID

        Returns:
            True if 같은 커뮤니티, False otherwise
        """
        if not self.graph_builder:
            return True  # 그래프 미초기화 시 통과

        try:
            # 커뮤니티 정보 조회
            comm1 = self.graph_builder.get_node_community(node1_id)
            comm2 = self.graph_builder.get_node_community(node2_id)

            if comm1 is None or comm2 is None:
                return True  # 커뮤니티 정보 없으면 통과

            return comm1 == comm2
        except Exception as e:
            logger.debug(f"커뮤니티 검증 실패 (통과 처리): {e}")
            return True

    def filter_unrelated_results(
        self,
        results: List[GraphSearchResult],
        anchor_node_id: str
    ) -> List[GraphSearchResult]:
        """Phase 90: 앵커 노드와 관련 없는 결과 필터링

        Args:
            results: 검색 결과 목록
            anchor_node_id: 기준이 되는 앵커 노드 ID

        Returns:
            앵커 노드와 같은 커뮤니티에 속하는 결과만 반환
        """
        if not anchor_node_id or not results:
            return results

        filtered = []
        for r in results:
            if self.validate_relationship(anchor_node_id, r.node_id):
                filtered.append(r)

        if len(filtered) < len(results):
            logger.info(f"Phase 90: 그래프 관계 필터 {len(results)} → {len(filtered)}건")

        return filtered if filtered else results  # 모두 필터되면 원본 반환

    # =========================================================================
    # Phase 96: 그래프 교차 검증
    # =========================================================================

    def cross_validate_results(self, search_results: List[Any]) -> List[Any]:
        """Phase 96: 그래프 기반 결과 교차 검증

        검색 결과의 노드들이 그래프에서 서로 연결되어 있는지 확인.
        같은 커뮤니티에 속한 결과가 많으면 신뢰도 점수 부스트.
        고립된 결과는 신뢰도 감소.

        Args:
            search_results: SearchResult 또는 유사 객체 목록
                (node_id, score, metadata 속성 필요)

        Returns:
            교차 검증 후 점수가 조정된 결과 목록
        """
        if not self.graph_builder or not search_results:
            return search_results

        try:
            from collections import defaultdict

            # 1. 노드 ID 추출 및 커뮤니티 매핑
            node_communities = {}
            for r in search_results:
                node_id = self._extract_node_id(r)
                if node_id:
                    community = self.graph_builder.get_node_community(node_id)
                    node_communities[id(r)] = community  # 결과 객체 ID로 매핑

            # 2. 커뮤니티별 그룹화
            community_groups = defaultdict(list)
            for r in search_results:
                community = node_communities.get(id(r))
                if community is not None:
                    community_groups[community].append(r)

            # 3. 교차 검증 수행
            validated_count = 0
            for r in search_results:
                community = node_communities.get(id(r))

                # metadata 딕셔너리 확보
                if hasattr(r, 'metadata'):
                    metadata = r.metadata if r.metadata else {}
                else:
                    metadata = {}

                if community is None:
                    # 커뮤니티 정보 없음 - 검증 불가
                    metadata["graph_validated"] = False
                    metadata["validation_reason"] = "no_community"
                else:
                    group_size = len(community_groups.get(community, []))

                    if group_size >= 3:
                        # 강한 클러스터링: 20% 점수 부스트
                        metadata["graph_validated"] = True
                        metadata["validation_reason"] = f"strong_cluster_{group_size}"
                        metadata["cluster_boost"] = 1.2
                        if hasattr(r, 'score'):
                            r.score = r.score * 1.2
                        validated_count += 1
                    elif group_size == 2:
                        # 중간 클러스터링: 10% 점수 부스트
                        metadata["graph_validated"] = True
                        metadata["validation_reason"] = f"medium_cluster_{group_size}"
                        metadata["cluster_boost"] = 1.1
                        if hasattr(r, 'score'):
                            r.score = r.score * 1.1
                        validated_count += 1
                    else:
                        # 고립: 10% 점수 감소
                        metadata["graph_validated"] = False
                        metadata["validation_reason"] = "isolated"
                        metadata["cluster_boost"] = 0.9
                        if hasattr(r, 'score'):
                            r.score = r.score * 0.9

                # metadata 업데이트
                if hasattr(r, 'metadata'):
                    r.metadata = metadata

            logger.info(f"Phase 96: 그래프 교차 검증 완료 - {validated_count}/{len(search_results)}건 검증됨")

            # 점수순 재정렬
            search_results.sort(key=lambda x: getattr(x, 'score', 0), reverse=True)

            return search_results

        except Exception as e:
            logger.warning(f"Phase 96: 그래프 교차 검증 실패 (원본 반환): {e}")
            return search_results

    def _extract_node_id(self, result: Any) -> Optional[str]:
        """검색 결과에서 node_id 추출

        SearchResult, dict, 기타 객체에서 node_id 추출 시도.
        """
        if hasattr(result, 'node_id'):
            return result.node_id
        if isinstance(result, dict):
            return result.get('node_id')

        # entity_type + id 조합 시도
        if hasattr(result, 'entity_type') and hasattr(result, 'id'):
            return f"{result.entity_type}_{result.id}"

        return None

    def search(
        self,
        query: str,
        strategy: SearchStrategy = SearchStrategy.HYBRID,
        entity_types: Optional[List[str]] = None,
        max_depth: int = 2,
        limit: int = 20,
        include_context: bool = True,
        collections: Optional[List[str]] = None
    ) -> List[GraphSearchResult]:
        """통합 검색

        Args:
            query: 검색 쿼리
            strategy: 검색 전략
            entity_types: 필터링할 엔티티 타입 (project, tech, ipc, org, kpi)
            max_depth: 그래프 탐색 깊이
            limit: 최대 결과 수
            include_context: 관련 엔티티 포함 여부
            collections: 검색할 Qdrant 컬렉션 목록 (명시적 지정)
        """
        if not self.graph_builder:
            self.initialize()

        if strategy == SearchStrategy.GRAPH_ONLY:
            return self._graph_search(query, entity_types, max_depth, limit, include_context)
        elif strategy == SearchStrategy.VECTOR_ONLY:
            return self._vector_search(query, entity_types, limit, collections)
        elif strategy == SearchStrategy.HYBRID:
            return self._hybrid_search(query, entity_types, max_depth, limit, include_context, collections)
        elif strategy == SearchStrategy.GRAPH_ENHANCED:
            return self._graph_enhanced_search(query, entity_types, max_depth, limit, collections)
        else:
            return self._hybrid_search(query, entity_types, max_depth, limit, include_context, collections)

    def _graph_search(
        self,
        query: str,
        entity_types: Optional[List[str]],
        max_depth: int,
        limit: int,
        include_context: bool
    ) -> List[GraphSearchResult]:
        """cuGraph 기반 그래프 검색"""
        # PageRank 기반 노드 검색
        search_results = self.graph_builder.search_nodes(query, entity_types, limit * 2)

        results = []
        for r in search_results[:limit]:
            # Phase 75.1: NodeResolver로 노드 속성 해석
            node_attrs = self.node_resolver.resolve(r["node_id"])
            resolved_name = node_attrs.get("name", r["name"]) if node_attrs else r["name"]

            related = None
            if include_context:
                related_raw = self.graph_builder.find_related_entities(
                    r["node_id"],
                    relation_types=entity_types,
                    max_depth=max_depth
                )[:10]
                # 관련 엔티티 이름도 해석
                related = []
                for rel in related_raw:
                    rel_attrs = self.node_resolver.resolve(rel.get("node_id", ""))
                    rel_name = rel_attrs.get("name") if rel_attrs else rel.get("name")
                    related.append({
                        **rel,
                        "name": rel_name or rel.get("node_id", "")
                    })

            results.append(GraphSearchResult(
                node_id=r["node_id"],
                name=resolved_name,
                entity_type=r["entity_type"],
                description=r.get("description", ""),
                score=r.get("score", 0.0),
                related_entities=related
            ))

        return results

    def _vector_search(
        self,
        query: str,
        entity_types: Optional[List[str]],
        limit: int,
        collections: Optional[List[str]] = None
    ) -> List[GraphSearchResult]:
        """Qdrant 벡터 검색

        Args:
            query: 검색 쿼리
            entity_types: 필터링할 엔티티 타입
            limit: 최대 결과 수
            collections: 명시적으로 지정된 컬렉션 목록 (우선 사용)
        """
        # 컬렉션 결정 우선순위:
        # 1. 명시적으로 전달된 collections
        # 2. entity_types 기반 매핑
        # 3. 기본 컬렉션

        if collections:
            # 명시적 컬렉션 지정 (domain_mapping에서 전달)
            target_collections = collections
            logger.info(f"명시적 컬렉션 사용: {target_collections}")
        elif entity_types:
            target_collections = [
                self.qdrant.collection_map.get(t, "projects_v3_collection")
                for t in entity_types
                if t in self.qdrant.collection_map
            ]
            if not target_collections:
                target_collections = ["projects_v3_collection"]
        else:
            # 기본: 주요 컬렉션 검색
            target_collections = ["projects_v3_collection", "patents_v3_collection"]

        # 다중 컬렉션 검색
        all_results = []
        for collection in target_collections:
            results = self.qdrant.search(query, collection, limit)
            for r in results:
                # 컬렉션에서 엔티티 타입 추론
                entity_type = self._collection_to_type(collection)

                # payload에서 정보 추출
                payload = r.get("payload", {})
                name = (
                    payload.get("title") or
                    payload.get("name") or
                    payload.get("sbjt_nm") or
                    payload.get("apply_fndn_nm") or
                    str(r.get("id", ""))
                )
                description = (
                    payload.get("description") or
                    payload.get("abstract") or
                    payload.get("summary") or
                    payload.get("text", "")[:500]
                )

                # Phase 102: documentid 추출 (그래프 노드 매핑용)
                doc_id = (
                    payload.get("documentid") or
                    payload.get("conts_id") or
                    payload.get("sbjt_id") or
                    ""
                )

                all_results.append(GraphSearchResult(
                    node_id=f"{entity_type}_{r.get('id', '')}",
                    name=name,
                    entity_type=entity_type,
                    description=description,
                    score=r.get("score", 0.0),
                    related_entities=[{"document_id": doc_id}] if doc_id else None  # Phase 102: doc_id 저장
                ))

        # 점수순 정렬
        all_results.sort(key=lambda x: x.score, reverse=True)
        return all_results[:limit]

    def _collection_to_type(self, collection: str) -> str:
        """컬렉션 이름에서 엔티티 타입 추론 - 12종 노드 타입 지원"""
        type_map = {
            "projects": "project",
            "patents": "patent",          # 특허
            "proposals": "ancm",          # 공고/제안서
            "equipments": "equip",        # 장비
            "tech_classifications": "tech",
            "evaluation": "evalp"         # 평가표
        }
        for key, value in type_map.items():
            if key in collection:
                return value
        return "unknown"

    def _hybrid_search(
        self,
        query: str,
        entity_types: Optional[List[str]],
        max_depth: int,
        limit: int,
        include_context: bool,
        collections: Optional[List[str]] = None
    ) -> List[GraphSearchResult]:
        """하이브리드 검색 (cuGraph + Qdrant)"""
        # 그래프 검색 (PageRank 기반)
        graph_results = self._graph_search(query, entity_types, max_depth, limit, False)

        # 벡터 검색 (Qdrant) - collections 파라미터 전달
        vector_results = self._vector_search(query, entity_types, limit, collections)

        # RRF (Reciprocal Rank Fusion)로 결합
        combined_scores: Dict[str, Dict] = {}
        k = 60  # RRF 상수

        # 그래프 검색 결과
        for rank, r in enumerate(graph_results):
            node_id = r.node_id
            rrf_score = 1.0 / (k + rank + 1)
            combined_scores[node_id] = {
                "result": r,
                "graph_score": r.score,
                "vector_score": 0.0,
                "rrf_score": rrf_score,
                "source": "graph"
            }

        # 벡터 검색 결과 추가
        for rank, r in enumerate(vector_results):
            node_id = r.node_id
            rrf_score = 1.0 / (k + rank + 1)

            if node_id in combined_scores:
                combined_scores[node_id]["vector_score"] = r.score
                combined_scores[node_id]["rrf_score"] += rrf_score
                combined_scores[node_id]["source"] = "both"
            else:
                combined_scores[node_id] = {
                    "result": r,
                    "graph_score": 0.0,
                    "vector_score": r.score,
                    "rrf_score": rrf_score,
                    "source": "vector"
                }

        # RRF 점수순 정렬
        sorted_results = sorted(
            combined_scores.values(),
            key=lambda x: x["rrf_score"],
            reverse=True
        )

        # 최종 결과
        results = []
        for item in sorted_results[:limit]:
            r = item["result"]

            # 컨텍스트 추가 (그래프 노드인 경우)
            related = None
            if include_context and item["source"] in ["graph", "both"]:
                related = self.graph_builder.find_related_entities(
                    r.node_id,
                    max_depth=max_depth
                )[:10]

            results.append(GraphSearchResult(
                node_id=r.node_id,
                name=r.name,
                entity_type=r.entity_type,
                description=r.description,
                score=item["rrf_score"],
                related_entities=related
            ))

        return results

    def _graph_enhanced_search(
        self,
        query: str,
        entity_types: Optional[List[str]],
        max_depth: int,
        limit: int,
        collections: Optional[List[str]] = None
    ) -> List[GraphSearchResult]:
        """그래프 확장 검색 - 벡터 검색 후 그래프로 확장"""
        # 벡터 검색 - collections 파라미터 전달
        vector_results = self._vector_search(query, entity_types, limit // 2, collections)

        # 결과 노드의 관련 엔티티까지 확장
        expanded_results = list(vector_results)
        seen_ids = {r.node_id for r in vector_results}

        for r in vector_results:
            # 커뮤니티 기반 관련 엔티티 조회
            related = self.graph_builder.find_related_entities(
                r.node_id,
                relation_types=entity_types,
                max_depth=max_depth
            )

            for rel in related:
                rel_id = rel.get("node_id")
                if rel_id not in seen_ids:
                    seen_ids.add(rel_id)
                    expanded_results.append(GraphSearchResult(
                        node_id=rel_id,
                        name=rel.get("name", rel_id),
                        entity_type=rel.get("entity_type", "unknown"),
                        description="",
                        score=r.score * 0.5,  # 관련 노드는 가중치 감소
                        path=rel.get("path")
                    ))

        # 점수순 정렬
        expanded_results.sort(key=lambda x: x.score, reverse=True)
        return expanded_results[:limit]

    def get_entity_context(self, node_id: str, max_depth: int = 2) -> Dict:
        """엔티티의 전체 컨텍스트 조회"""
        if not self.graph_builder:
            self.initialize()

        node_data = self.graph_builder.get_node(node_id)
        neighbors = self.graph_builder.get_neighbors(node_id, depth=max_depth)
        related = self.graph_builder.find_related_entities(node_id, max_depth=max_depth)

        # Phase 75.1: NodeResolver로 이름 해석
        node_attrs = self.node_resolver.resolve(node_id)
        if node_data and node_attrs:
            node_data["name"] = node_attrs.get("name", node_data.get("name"))

        # 이웃 노드 이름 해석
        for neighbor in neighbors:
            n_id = neighbor.get("node_id")
            if n_id:
                n_attrs = self.node_resolver.resolve(n_id)
                if n_attrs:
                    neighbor["name"] = n_attrs.get("name", n_id)

        # 관련 엔티티 이름 해석
        for rel in related:
            r_id = rel.get("node_id")
            if r_id:
                r_attrs = self.node_resolver.resolve(r_id)
                if r_attrs:
                    rel["name"] = r_attrs.get("name", r_id)

        return {
            "entity": node_data,
            "neighbors": neighbors,
            "related_entities": related,
            "statistics": {
                "neighbor_count": len(neighbors),
                "related_count": len(related)
            }
        }

    def find_connections(self, source_id: str, target_id: str, max_length: int = 4) -> List[Dict]:
        """두 엔티티 간 연결 경로 찾기"""
        if not self.graph_builder:
            self.initialize()

        paths = self.graph_builder.find_path(source_id, target_id, max_length)

        result_paths = []
        for path in paths:
            path_info = []
            for i, node_id in enumerate(path):
                node_data = self.graph_builder.get_node(node_id)
                # Phase 75.1: NodeResolver로 이름 해석
                node_attrs = self.node_resolver.resolve(node_id)
                name = node_attrs.get("name") if node_attrs else (node_data.get("name") if node_data else node_id)
                path_info.append({
                    "step": i,
                    "node_id": node_id,
                    "name": name,
                    "entity_type": node_data.get("entity_type") if node_data else "unknown"
                })
            result_paths.append(path_info)

        return result_paths

    def get_recommendations(self, node_id: str, limit: int = 10) -> List[Dict]:
        """관련 엔티티 추천 (커뮤니티 + PageRank 기반)"""
        if not self.graph_builder:
            self.initialize()

        # 커뮤니티 기반 관련 엔티티
        related = self.graph_builder.find_related_entities(node_id, max_depth=2)

        # PageRank 점수 기반 정렬
        scored = []
        for r in related:
            rel_node = self.graph_builder.get_node(r["node_id"])
            pagerank = rel_node.get("pagerank", 0.0) if rel_node else 0.0
            depth_score = 1.0 / r.get("depth", 1)

            # Phase 75.1: NodeResolver로 이름 해석
            node_attrs = self.node_resolver.resolve(r["node_id"])
            name = node_attrs.get("name") if node_attrs else r.get("name", r["node_id"])

            scored.append({
                **r,
                "name": name,
                "score": depth_score * 0.3 + pagerank * 0.7,
                "pagerank": pagerank
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    def get_central_nodes(
        self,
        entity_type: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict]:
        """중심성 높은 노드 조회"""
        if not self.graph_builder:
            self.initialize()

        central_nodes = self.graph_builder.get_central_nodes(entity_type=entity_type, limit=limit)

        # Phase 75.1: NodeResolver로 이름 해석
        for node in central_nodes:
            node_id = node.get("node_id")
            if node_id:
                node_attrs = self.node_resolver.resolve(node_id)
                if node_attrs:
                    node["name"] = node_attrs.get("name", node_id)

        return central_nodes

    def generate_context_for_llm(self, query: str, limit: int = 10) -> str:
        """LLM을 위한 컨텍스트 생성"""
        results = self.search(
            query,
            strategy=SearchStrategy.HYBRID,
            limit=limit,
            include_context=True
        )

        context_parts = []
        context_parts.append(f"## 검색 쿼리: {query}\n")
        context_parts.append(f"## 관련 정보 ({len(results)}건 발견)\n")

        for i, r in enumerate(results, 1):
            context_parts.append(f"\n### {i}. {r.name} ({r.entity_type})")
            if r.description:
                context_parts.append(f"설명: {r.description[:300]}")

            if r.related_entities:
                related_names = [e.get("name", e.get("node_id", "")) for e in r.related_entities[:5]]
                context_parts.append(f"관련 엔티티: {', '.join(related_names)}")

        return "\n".join(context_parts)

    def get_statistics(self) -> Dict:
        """그래프 통계 조회"""
        if not self.graph_builder:
            self.initialize()

        return self.graph_builder.get_statistics()


# 싱글톤 인스턴스
_graph_rag_instance: Optional[GraphRAG] = None


def get_graph_rag() -> GraphRAG:
    """Graph RAG 싱글톤 인스턴스 반환 (Phase 98: 자동 초기화)

    첫 호출 시 GraphRAG를 생성하고 자동으로 초기화합니다.
    이전에는 get_graph_rag() 호출 후 별도로 initialize()를 호출해야 했으나,
    이로 인해 graph_builder가 None인 상태로 남아 그래프 검색이 스킵되는 문제가 있었습니다.

    Returns:
        초기화된 GraphRAG 인스턴스
    """
    global _graph_rag_instance
    if _graph_rag_instance is None:
        _graph_rag_instance = GraphRAG()
        # Phase 98: 첫 호출 시 기본 초기화 수행
        try:
            _graph_rag_instance.initialize(graph_id="713365bb", project_limit=500)
            logger.info("Phase 98: GraphRAG 자동 초기화 완료")
        except Exception as e:
            logger.warning(f"Phase 98: GraphRAG 자동 초기화 실패 (나중에 재시도): {e}")
    return _graph_rag_instance


def initialize_graph_rag(
    graph_id: str = "713365bb",
    project_limit: int = 500
) -> GraphRAG:
    """Graph RAG 초기화"""
    global _graph_rag_instance
    _graph_rag_instance = GraphRAG()
    _graph_rag_instance.initialize(graph_id=graph_id, project_limit=project_limit)
    return _graph_rag_instance


if __name__ == "__main__":
    print("Graph RAG 테스트 (cuGraph + Qdrant 하이브리드)")

    try:
        # 초기화
        print("\n1. 초기화 중...")
        rag = initialize_graph_rag(graph_id="713365bb", project_limit=100)
        print("   초기화 완료")

        # 그래프 통계
        print("\n2. 그래프 통계:")
        stats = rag.get_statistics()
        for key, value in stats.items():
            print(f"   - {key}: {value}")

        # 중심 노드
        print("\n3. 중심 노드 (PageRank 상위):")
        central = rag.get_central_nodes(limit=5)
        for node in central:
            print(f"   - {node['node_id']} ({node['entity_type']}): {node.get('pagerank', 0):.6f}")

        # 검색 테스트
        query = "인공지능"
        print(f"\n4. 검색: '{query}'")

        # 그래프 전용 검색
        print("\n   [그래프 전용]")
        graph_results = rag.search(query, strategy=SearchStrategy.GRAPH_ONLY, limit=3)
        for r in graph_results:
            print(f"   - {r.name} ({r.entity_type}): {r.score:.4f}")

        # 벡터 전용 검색
        print("\n   [벡터 전용]")
        vector_results = rag.search(query, strategy=SearchStrategy.VECTOR_ONLY, limit=3)
        for r in vector_results:
            print(f"   - {r.name} ({r.entity_type}): {r.score:.4f}")

        # 하이브리드 검색
        print("\n   [하이브리드]")
        hybrid_results = rag.search(query, strategy=SearchStrategy.HYBRID, limit=3)
        for r in hybrid_results:
            print(f"   - {r.name} ({r.entity_type}): {r.score:.4f}")
            if r.related_entities:
                print(f"     관련: {', '.join([e.get('name', e.get('node_id', ''))[:30] for e in r.related_entities[:3]])}")

        # LLM 컨텍스트 생성
        print("\n5. LLM 컨텍스트:")
        context = rag.generate_context_for_llm(query, limit=3)
        print(context[:500] + "...")

    except Exception as e:
        print(f"오류: {e}")
        import traceback
        traceback.print_exc()
