"""
cuGraph 기반 지식 그래프 빌더
- GPU 서버의 cuGraph API를 활용한 그래프 분석
- Qdrant 벡터 검색과 통합
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Dict, List, Optional, Any, Set
from collections import defaultdict
import logging

from graph.cugraph_client import (
    CuGraphClient,
    CuGraphRAGHelper,
    get_cugraph_client,
    get_cugraph_helper
)

logger = logging.getLogger(__name__)

# 노드 타입 정의 (cuGraph 713365bb 그래프 기준 - 12종)
NODE_TYPES = {
    # 주요 엔티티 (대용량)
    "patent": {"label": "특허", "color": "#E91E63", "prefix": "patent_"},           # 100만
    "org": {"label": "기관", "color": "#FF9800", "prefix": "org_"},                 # 8.1만
    "equip": {"label": "장비", "color": "#00BCD4", "prefix": "equip_"},             # 5.6만
    "project": {"label": "연구과제", "color": "#4CAF50", "prefix": "project_"},     # 5.3만
    "applicant": {"label": "출원인", "color": "#9C27B0", "prefix": "applicant_"},   # 5.2만
    "ipc": {"label": "IPC분류", "color": "#2196F3", "prefix": "ipc_"},              # 3.2만
    "gis": {"label": "지역", "color": "#795548", "prefix": "gis_"},                 # 1.8만
    "tech": {"label": "기술", "color": "#673AB7", "prefix": "tech_"},               # 9.2천
    # 기획지원 관련 (공고/평가)
    "ancm": {"label": "공고", "color": "#FF5722", "prefix": "ancm_"},               # 1.6천
    "evalp": {"label": "평가표", "color": "#607D8B", "prefix": "evalp_"},           # 658
    # 분류 체계
    "k12": {"label": "K12분류", "color": "#3F51B5", "prefix": "k12_"},              # 12
    "6t": {"label": "6T분류", "color": "#009688", "prefix": "6t_"},                 # 5
}


class KnowledgeGraphBuilder:
    """지식 그래프 빌더 - cuGraph API 기반"""

    def __init__(
        self,
        graph_id: str = "713365bb",
        cugraph_url: str = os.getenv("CUGRAPH_API_URL", "http://210.109.80.106:8000")
    ):
        self.graph_id = graph_id
        self.client = CuGraphClient(base_url=cugraph_url)
        self.helper = CuGraphRAGHelper(client=self.client, default_graph_id=graph_id)

        # 캐시
        self._graph_info: Optional[Dict] = None
        self._pagerank_cache: Dict[str, float] = {}
        self._community_cache: Dict[str, int] = {}
        self._type_index: Dict[str, Set[str]] = defaultdict(set)

    def initialize(self) -> bool:
        """그래프 초기화 (정보 로드)"""
        try:
            info = self.client.get_graph_info(self.graph_id)
            if info:
                self._graph_info = {
                    "graph_id": info.graph_id,
                    "name": info.name,
                    "num_nodes": info.num_nodes,
                    "num_edges": info.num_edges,
                    "directed": info.directed
                }
                logger.info(f"그래프 초기화 완료: {info.name} ({info.num_nodes:,} nodes)")
                return True
            return False
        except Exception as e:
            logger.error(f"그래프 초기화 실패: {e}")
            return False

    def get_node(self, node_id: str) -> Optional[Dict]:
        """노드 정보 조회"""
        # 노드 타입 추출
        node_type = self._get_node_type(node_id)

        return {
            "node_id": node_id,
            "name": node_id,  # 실제 이름은 Qdrant에서 조회
            "entity_type": node_type,
            "description": "",
            "pagerank": self._pagerank_cache.get(node_id, 0.0),
            "community": self._community_cache.get(node_id)
        }

    def _get_node_type(self, node_id: str) -> str:
        """노드 ID에서 타입 추출"""
        for type_name, info in NODE_TYPES.items():
            if node_id.startswith(info["prefix"]):
                return type_name
        return "unknown"

    def get_neighbors(
        self,
        node_id: str,
        direction: str = "both",
        depth: int = 1
    ) -> List[Dict]:
        """이웃 노드 조회"""
        try:
            result = self.client.get_neighbors(
                self.graph_id,
                node_ids=[node_id],
                direction=direction,
                max_depth=depth
            )

            neighbors = []
            node_neighbors = result.get("neighbors", {}).get(node_id, [])

            for n in node_neighbors:
                neighbor_id = n.get("node_id")
                neighbors.append({
                    "node_id": neighbor_id,
                    "node": self.get_node(neighbor_id),
                    "relation": None,  # cuGraph에서는 관계 타입 미지원
                    "direction": direction,
                    "depth": 1,
                    "weight": n.get("weight", 1.0)
                })

            return neighbors
        except Exception as e:
            logger.warning(f"이웃 조회 실패 ({node_id}): {e}")
            return []

    def find_path(self, source_id: str, target_id: str, max_length: int = 5) -> List[List[str]]:
        """두 노드 간 경로 찾기 (cuGraph에서 미지원, 빈 결과 반환)"""
        # cuGraph API에서 경로 찾기는 직접 지원하지 않음
        # 대안: 같은 커뮤니티인지 확인
        src_comm = self._community_cache.get(source_id)
        tgt_comm = self._community_cache.get(target_id)

        if src_comm is not None and tgt_comm is not None and src_comm == tgt_comm:
            return [[source_id, f"community_{src_comm}", target_id]]

        return []

    def search_nodes(
        self,
        query: str,
        entity_types: Optional[List[str]] = None,
        limit: int = 20
    ) -> List[Dict]:
        """노드 검색 (PageRank 결과에서 필터링)"""
        # 접두사로 검색
        results = self.helper.search_nodes_by_prefix(query, limit=limit * 5)

        # 타입 필터링
        if entity_types:
            type_prefixes = [NODE_TYPES.get(t, {}).get("prefix", "") for t in entity_types]
            results = [
                r for r in results
                if any(r["node_id"].startswith(p) for p in type_prefixes if p)
            ]

        # 결과 변환
        search_results = []
        for r in results[:limit]:
            node_id = r["node_id"]
            search_results.append({
                "node_id": node_id,
                "name": node_id,
                "entity_type": self._get_node_type(node_id),
                "description": "",
                "score": r.get("pagerank", 0.0)
            })

        return search_results

    def get_statistics(self) -> Dict:
        """그래프 통계"""
        if not self._graph_info:
            self.initialize()

        stats = self.helper.get_graph_statistics(self.graph_id)
        return {
            "nodes": stats.get("nodes", 0),
            "edges": stats.get("edges", 0),
            "node_types": stats.get("node_types", {}),
            "density": stats.get("density", 0.0),
            "is_connected": stats.get("is_connected", False),
            "components": stats.get("components", 0)
        }

    def get_central_nodes(
        self,
        entity_type: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict]:
        """중심성이 높은 노드 조회 (PageRank 기반)"""
        # 타입 접두사 변환
        node_type_prefix = None
        if entity_type:
            node_type_prefix = NODE_TYPES.get(entity_type, {}).get("prefix")

        central = self.helper.get_central_nodes(
            graph_id=self.graph_id,
            top_k=limit,
            node_type=node_type_prefix
        )

        results = []
        for node in central:
            node_id = node.get("vertex")
            # 커뮤니티 정보 조회
            community = self.helper.get_node_community(node_id, self.graph_id)
            results.append({
                "node_id": node_id,
                "name": node_id,
                "entity_type": self._get_node_type(node_id),
                "pagerank": node.get("pagerank", 0.0),
                "community": community,
                "degree": 0  # cuGraph에서 degree는 별도 API 필요
            })

        return results

    def find_related_entities(
        self,
        node_id: str,
        relation_types: Optional[List[str]] = None,
        max_depth: int = 2
    ) -> List[Dict]:
        """관련 엔티티 탐색 (커뮤니티 기반)"""
        # 같은 커뮤니티의 노드들 조회
        related = self.helper.get_related_by_community(
            node_id,
            graph_id=self.graph_id,
            limit=50
        )

        results = []
        for r in related:
            rel_node_id = r.get("node_id")
            node_type = self._get_node_type(rel_node_id)

            # 타입 필터링
            if relation_types and node_type not in relation_types:
                continue

            results.append({
                "node_id": rel_node_id,
                "name": rel_node_id,
                "entity_type": node_type,
                "depth": 1,
                "path": [{"from": node_id, "to": rel_node_id, "relation": "same_community"}]
            })

        return results[:max_depth * 10]

    def load_pagerank(self, top_k: int = 10000):
        """PageRank 캐시 로드"""
        try:
            result = self.client.pagerank(self.graph_id, top_k=top_k)
            for node in result.get("results", []):
                self._pagerank_cache[node["vertex"]] = node["pagerank"]
                # 타입 인덱스 업데이트
                node_type = self._get_node_type(node["vertex"])
                self._type_index[node_type].add(node["vertex"])
            logger.info(f"PageRank 캐시 로드: {len(self._pagerank_cache)}개 노드")
        except Exception as e:
            logger.error(f"PageRank 로드 실패: {e}")

    def load_communities(self, top_k: int = 10000):
        """커뮤니티 캐시 로드"""
        try:
            result = self.client.community_detection(self.graph_id, top_k=top_k)
            for node in result.get("results", []):
                self._community_cache[node["vertex"]] = node["partition"]
            logger.info(f"커뮤니티 캐시 로드: {len(self._community_cache)}개 노드")
        except Exception as e:
            logger.error(f"커뮤니티 로드 실패: {e}")

    def export_to_json(self) -> Dict:
        """JSON 형식으로 내보내기"""
        return {
            "graph_id": self.graph_id,
            "statistics": self.get_statistics(),
            "top_nodes": self.get_central_nodes(limit=100),
            "node_types": dict(self._type_index)
        }

    # ========== Phase 95.1: doc_id 기반 노드 검색 ==========

    def search_nodes_by_doc_ids(
        self,
        doc_ids: List[str],
        entity_types: Optional[List[str]] = None
    ) -> List[Dict]:
        """doc_id 목록으로 그래프 노드 검색

        Qdrant 검색 결과(doc_id)를 그래프 노드 ID로 변환합니다.

        Args:
            doc_ids: 문서 ID 목록 (documentid, conts_id 등)
            entity_types: 필터링할 엔티티 타입

        Returns:
            매칭된 그래프 노드 목록
        """
        matched_nodes = []

        for doc_id in doc_ids:
            if not doc_id:
                continue

            # doc_id → 노드 ID 매핑
            node_id = self._doc_id_to_node_id(doc_id, entity_types)
            if not node_id:
                continue

            # 노드 존재 여부 확인 (캐시에서)
            if not self._node_exists(node_id):
                continue

            node_type = self._get_node_type(node_id)

            # 엔티티 타입 필터
            if entity_types and node_type not in entity_types:
                continue

            matched_nodes.append({
                "node_id": node_id,
                "doc_id": doc_id,
                "entity_type": node_type,
                "pagerank": self._pagerank_cache.get(node_id, 0.0),
                "community": self._community_cache.get(node_id)
            })

        logger.debug(f"doc_id → 노드 매핑: {len(doc_ids)} → {len(matched_nodes)}개")
        return matched_nodes

    def _doc_id_to_node_id(
        self,
        doc_id: str,
        entity_types: Optional[List[str]] = None
    ) -> Optional[str]:
        """doc_id를 그래프 노드 ID로 변환

        변환 규칙:
        - 특허: "KR20240001234" → "patent_kr20240001234"
        - 과제: "CONTS_ID_12345" → "project_CONTS_ID_12345"
        - 장비: "EQP_12345" → "equip_EQP_12345"
        - 기관: "ORG_12345" → "org_ORG_12345"

        Args:
            doc_id: 문서 ID
            entity_types: 힌트로 사용할 엔티티 타입 목록

        Returns:
            그래프 노드 ID 또는 None
        """
        if not doc_id:
            return None

        doc_id_lower = doc_id.lower()
        doc_id_upper = doc_id.upper()

        # 특허 패턴 (국가코드로 시작)
        # Phase 102: cuGraph 노드 ID 형식은 "patent_2021-0125840" (년도-출원번호)
        # Qdrant documentid는 "kr20210125840b1" (국가코드+연도+번호+문서타입)
        patent_prefixes = ["kr", "us", "ep", "jp", "cn", "wo", "au", "ca", "de", "gb", "fr"]
        for prefix in patent_prefixes:
            if doc_id_lower.startswith(prefix):
                # 예: kr20210125840b1 → 2021-0125840
                # 국가코드 제거 후 연도-번호 추출
                import re
                # 국가코드 제거
                id_without_prefix = doc_id_lower[len(prefix):]
                # 숫자 부분 추출 (연도4자리 + 번호7자리)
                match = re.match(r'(\d{4})(\d{7})', id_without_prefix)
                if match:
                    year = match.group(1)
                    number = match.group(2)
                    return f"patent_{year}-{number}"
                # 다른 형식 시도 (예: kr10-2021-0125840)
                match2 = re.match(r'(\d+)-(\d{4})-(\d+)', doc_id_lower[len(prefix):])
                if match2:
                    return f"patent_{match2.group(2)}-{match2.group(3)}"
                # 기본 형식 (기존 방식)
                return f"patent_{doc_id_lower}"

        # entity_types 힌트가 있는 경우 우선 적용
        if entity_types:
            if "patent" in entity_types:
                return f"patent_{doc_id_lower}"
            elif "project" in entity_types:
                return f"project_{doc_id}"
            elif "equip" in entity_types:
                return f"equip_{doc_id}"
            elif "org" in entity_types:
                return f"org_{doc_id}"
            elif "proposal" in entity_types:
                return f"proposal_{doc_id}"

        # 기타 패턴
        if doc_id_upper.startswith("PRJ") or "CONTS" in doc_id_upper:
            return f"project_{doc_id}"
        elif doc_id_upper.startswith("EQP"):
            return f"equip_{doc_id}"
        elif doc_id_upper.startswith("ORG"):
            return f"org_{doc_id}"

        # 매핑 실패
        logger.debug(f"doc_id 매핑 실패: {doc_id}")
        return None

    def _node_exists(self, node_id: str) -> bool:
        """노드가 그래프에 존재하는지 확인 (캐시 기반)

        Args:
            node_id: 그래프 노드 ID

        Returns:
            노드 존재 여부
        """
        # PageRank 캐시에 있으면 존재
        if node_id in self._pagerank_cache:
            return True

        # 커뮤니티 캐시에 있으면 존재
        if node_id in self._community_cache:
            return True

        # 타입 인덱스에 있으면 존재
        node_type = self._get_node_type(node_id)
        if node_id in self._type_index.get(node_type, set()):
            return True

        return False

    def get_node_community(self, node_id: str) -> Optional[int]:
        """노드의 커뮤니티 ID 조회

        Args:
            node_id: 그래프 노드 ID

        Returns:
            커뮤니티 ID 또는 None
        """
        # 캐시에서 먼저 조회
        if node_id in self._community_cache:
            return self._community_cache[node_id]

        # API 조회
        try:
            community = self.helper.get_node_community(node_id, self.graph_id)
            if community is not None:
                self._community_cache[node_id] = community
            return community
        except Exception as e:
            logger.debug(f"커뮤니티 조회 실패: {node_id}, {e}")
            return None

    def get_community_members(
        self,
        community_id: int,
        limit: int = 50
    ) -> List[Dict]:
        """커뮤니티 멤버 조회

        Args:
            community_id: 커뮤니티 ID
            limit: 최대 결과 수

        Returns:
            커뮤니티 멤버 목록
        """
        members = []

        # 캐시에서 같은 커뮤니티 멤버 찾기
        for node_id, comm_id in self._community_cache.items():
            if comm_id == community_id:
                members.append({
                    "node_id": node_id,
                    "entity_type": self._get_node_type(node_id),
                    "pagerank": self._pagerank_cache.get(node_id, 0.0),
                    "community_id": community_id
                })

                if len(members) >= limit:
                    break

        # PageRank 순으로 정렬
        members.sort(key=lambda x: x["pagerank"], reverse=True)

        return members[:limit]


# 싱글톤 인스턴스
_graph_builder_instance: Optional[KnowledgeGraphBuilder] = None


def get_knowledge_graph() -> KnowledgeGraphBuilder:
    """지식 그래프 빌더 싱글톤 인스턴스"""
    global _graph_builder_instance
    if _graph_builder_instance is None:
        _graph_builder_instance = KnowledgeGraphBuilder()
    return _graph_builder_instance


def initialize_knowledge_graph(
    graph_id: str = "713365bb",
    project_limit: int = 500  # 호환성을 위해 유지 (미사용)
) -> KnowledgeGraphBuilder:
    """지식 그래프 초기화 및 구축"""
    global _graph_builder_instance

    _graph_builder_instance = KnowledgeGraphBuilder(graph_id=graph_id)
    _graph_builder_instance.initialize()

    # 캐시 로드
    _graph_builder_instance.load_pagerank(top_k=min(project_limit * 10, 50000))
    _graph_builder_instance.load_communities(top_k=min(project_limit * 10, 50000))

    return _graph_builder_instance


if __name__ == "__main__":
    # 테스트
    print("cuGraph 기반 지식 그래프 테스트")

    try:
        builder = initialize_knowledge_graph(graph_id="713365bb", project_limit=100)

        # 통계 출력
        stats = builder.get_statistics()
        print(f"\n그래프 통계:")
        for key, value in stats.items():
            print(f"  - {key}: {value}")

        # 중심 노드 조회
        print("\n중심 노드 (PageRank):")
        central = builder.get_central_nodes(limit=5)
        for node in central:
            print(f"  - {node['node_id']} ({node['entity_type']}): {node['pagerank']:.6f}")

        # 프로젝트 타입 노드
        print("\n중심 프로젝트:")
        central_projects = builder.get_central_nodes(entity_type="project", limit=5)
        for node in central_projects:
            print(f"  - {node['node_id']}: {node['pagerank']:.6f}")

        # 노드 검색
        print("\n'project_S' 검색:")
        results = builder.search_nodes("project_S", limit=5)
        for r in results:
            print(f"  - {r['node_id']} ({r['entity_type']})")

    except Exception as e:
        print(f"오류: {e}")
        import traceback
        traceback.print_exc()
