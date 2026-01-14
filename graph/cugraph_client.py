"""
cuGraph API 클라이언트
- GPU 서버의 cuGraph REST API와 통신
- 그래프 분석 기능 제공 (PageRank, Community Detection 등)
"""

import os
import requests
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class GraphInfo:
    """그래프 정보"""
    graph_id: str
    name: str
    num_nodes: int
    num_edges: int
    directed: bool
    created_at: str
    source_col: str
    dest_col: str
    weight_col: Optional[str] = None


class CuGraphClient:
    """cuGraph REST API 클라이언트"""

    def __init__(self, base_url: str = os.getenv("CUGRAPH_API_URL", "http://210.109.80.106:8000")):
        self.base_url = base_url.rstrip("/")
        self.timeout = 120  # 대규모 그래프 연산을 위한 타임아웃

    def _normalize_graph_id(self, graph_id) -> str:
        """Phase 95: graph_id를 문자열로 정규화

        GraphInfo 객체가 전달될 경우 graph_id 속성 추출.

        Args:
            graph_id: 문자열 또는 GraphInfo 객체

        Returns:
            문자열 graph_id
        """
        if hasattr(graph_id, 'graph_id'):
            return graph_id.graph_id
        return str(graph_id) if graph_id else ""

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """API 요청 수행"""
        url = f"{self.base_url}{endpoint}"
        kwargs.setdefault("timeout", self.timeout)

        try:
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"cuGraph API 오류: {e}")
            raise

    def list_graphs(self) -> List[GraphInfo]:
        """저장된 그래프 목록 조회"""
        result = self._request("GET", "/graph/list")

        graphs = []
        for g in result.get("graphs", []):
            graphs.append(GraphInfo(
                graph_id=g["graph_id"],
                name=g["name"],
                num_nodes=g["num_nodes"],
                num_edges=g["num_edges"],
                directed=g["directed"],
                created_at=g["created_at"],
                source_col=g["source_col"],
                dest_col=g["dest_col"],
                weight_col=g.get("weight_col")
            ))
        return graphs

    def get_graph_info(self, graph_id: str) -> Optional[GraphInfo]:
        """특정 그래프 정보 조회

        Args:
            graph_id: 그래프 ID (문자열 또는 GraphInfo 객체)
        """
        graph_id = self._normalize_graph_id(graph_id)

        try:
            result = self._request("GET", f"/graph/{graph_id}")
            if result.get("status") == "success":
                return GraphInfo(
                    graph_id=result["graph_id"],
                    name=result["name"],
                    num_nodes=result["num_nodes"],
                    num_edges=result["num_edges"],
                    directed=result["directed"],
                    created_at=result["created_at"],
                    source_col=result["source_col"],
                    dest_col=result["dest_col"],
                    weight_col=result.get("weight_col")
                )
        except Exception as e:
            logger.error(f"그래프 정보 조회 실패: {e}")
        return None

    def get_graph_stats(self, graph_id: str) -> Dict:
        """그래프 통계 조회"""
        graph_id = self._normalize_graph_id(graph_id)
        return self._request("GET", f"/graph/{graph_id}/stats")

    def pagerank(
        self,
        graph_id: str,
        top_k: int = 100,
        alpha: float = 0.85,
        max_iter: int = 100
    ) -> Dict:
        """PageRank 계산

        Args:
            graph_id: 그래프 ID
            top_k: 상위 K개 노드 반환
            alpha: 감쇠 계수 (기본 0.85)
            max_iter: 최대 반복 횟수
        """
        graph_id = self._normalize_graph_id(graph_id)
        return self._request(
            "POST",
            f"/graph/{graph_id}/pagerank",
            json={"top_k": top_k, "alpha": alpha, "max_iter": max_iter}
        )

    def community_detection(
        self,
        graph_id: str,
        top_k: int = 1000,
        resolution: float = 1.0
    ) -> Dict:
        """커뮤니티 탐지 (Louvain)

        Args:
            graph_id: 그래프 ID
            top_k: 상위 K개 결과 반환
            resolution: 해상도 파라미터
        """
        graph_id = self._normalize_graph_id(graph_id)
        return self._request(
            "POST",
            f"/graph/{graph_id}/community",
            json={"top_k": top_k, "resolution": resolution}
        )

    def get_neighbors(
        self,
        graph_id: str,
        node_ids: List[str],
        direction: str = "both",
        max_depth: int = 1
    ) -> Dict:
        """이웃 노드 탐색

        Args:
            graph_id: 그래프 ID
            node_ids: 쿼리 노드 ID 목록
            direction: "in", "out", "both"
            max_depth: 탐색 깊이
        """
        graph_id = self._normalize_graph_id(graph_id)
        return self._request(
            "POST",
            f"/graph/{graph_id}/neighbors",
            json={
                "node_ids": node_ids,
                "direction": direction,
                "max_depth": max_depth
            }
        )

    def get_node_attributes(self, node_id: int) -> Dict:
        """노드 속성 조회 (정수 ID만 지원)"""
        return self._request("GET", f"/graph/node/{node_id}/attributes")

    def get_nodes_attributes(self, node_ids: List[int]) -> Dict:
        """여러 노드 속성 일괄 조회"""
        return self._request(
            "POST",
            "/graph/nodes/attributes",
            json={"node_ids": node_ids}
        )


class CuGraphRAGHelper:
    """Graph RAG를 위한 cuGraph 헬퍼 클래스"""

    def __init__(
        self,
        client: Optional[CuGraphClient] = None,
        default_graph_id: str = "713365bb"  # 기본 그래프
    ):
        self.client = client or CuGraphClient()
        self.default_graph_id = default_graph_id
        self._pagerank_cache: Dict[str, Dict] = {}
        self._community_cache: Dict[str, Dict] = {}

    def get_central_nodes(
        self,
        graph_id: Optional[str] = None,
        top_k: int = 100,
        node_type: Optional[str] = None
    ) -> List[Dict]:
        """중심성 높은 노드 조회

        Args:
            graph_id: 그래프 ID (없으면 기본값 사용)
            top_k: 상위 K개
            node_type: 노드 타입 필터 (예: "project_", "ipc_")
        """
        gid = graph_id or self.default_graph_id

        # 캐시 확인
        cache_key = f"{gid}_{top_k}"
        if cache_key not in self._pagerank_cache:
            result = self.client.pagerank(gid, top_k=top_k * 10)  # 필터링 고려해 더 많이 요청
            self._pagerank_cache[cache_key] = result

        result = self._pagerank_cache[cache_key]
        # results에 전체 PageRank 결과가 있음 (top_10_nodes는 항상 10개만)
        nodes = result.get("results", []) or result.get("top_10_nodes", [])

        # 노드 타입 필터링
        if node_type:
            nodes = [n for n in nodes if n.get("vertex", "").startswith(node_type)]

        return nodes[:top_k]

    def get_node_community(
        self,
        node_id: str,
        graph_id: Optional[str] = None
    ) -> Optional[int]:
        """노드의 커뮤니티 ID 조회"""
        gid = graph_id or self.default_graph_id

        if gid not in self._community_cache:
            result = self.client.community_detection(gid, top_k=10000)
            # 결과를 노드 ID -> 커뮤니티 매핑으로 변환
            community_map = {}
            for item in result.get("results", []):
                community_map[item["vertex"]] = item["partition"]
            self._community_cache[gid] = community_map

        return self._community_cache[gid].get(node_id)

    def get_related_by_community(
        self,
        node_id: str,
        graph_id: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict]:
        """같은 커뮤니티의 관련 노드 조회"""
        gid = graph_id or self.default_graph_id
        community_id = self.get_node_community(node_id, gid)

        if community_id is None:
            return []

        # 같은 커뮤니티 노드 필터링
        community_map = self._community_cache.get(gid, {})
        related = [
            {"node_id": nid, "community": cid}
            for nid, cid in community_map.items()
            if cid == community_id and nid != node_id
        ]

        return related[:limit]

    def get_graph_statistics(self, graph_id: Optional[str] = None) -> Dict:
        """그래프 통계"""
        gid = graph_id or self.default_graph_id
        stats = self.client.get_graph_stats(gid)

        # 커뮤니티 수 조회
        community_count = 0
        try:
            comm_result = self.client.community_detection(gid, top_k=1)
            community_count = comm_result.get("num_communities", 0)
        except:
            pass

        return {
            "graph_id": stats.get("graph_id"),
            "name": stats.get("name"),
            "nodes": stats.get("num_nodes", 0),
            "edges": stats.get("num_edges", 0),
            "directed": stats.get("directed", True),
            "node_types": self._count_node_types(gid),
            "density": self._calculate_density(stats),
            "is_connected": True,  # 근사값
            "components": community_count  # 실제 Louvain 커뮤니티 수
        }

    def _count_node_types(self, graph_id: str) -> Dict[str, int]:
        """노드 타입별 개수 (PageRank 결과 기반 추정)"""
        try:
            result = self.client.pagerank(graph_id, top_k=10000)
            nodes = result.get("results", [])

            type_counts = {}
            for node in nodes:
                vertex = node.get("vertex", "")
                # 타입 추출 (예: project_123 -> project)
                parts = vertex.split("_")
                if parts:
                    node_type = parts[0]
                    type_counts[node_type] = type_counts.get(node_type, 0) + 1

            return type_counts
        except Exception:
            return {}

    def _calculate_density(self, stats: Dict) -> float:
        """그래프 밀도 계산"""
        n = stats.get("num_nodes", 0)
        e = stats.get("num_edges", 0)
        if n <= 1:
            return 0.0
        max_edges = n * (n - 1)
        if not stats.get("directed", True):
            max_edges //= 2
        return e / max_edges if max_edges > 0 else 0.0

    def search_nodes_by_prefix(
        self,
        prefix: str,
        graph_id: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """노드 ID 접두사로 검색 (PageRank 결과에서)"""
        gid = graph_id or self.default_graph_id
        try:
            result = self.client.pagerank(gid, top_k=10000)
            nodes = result.get("results", [])

            matched = [
                {"node_id": n["vertex"], "pagerank": n["pagerank"]}
                for n in nodes
                if n.get("vertex", "").lower().startswith(prefix.lower())
            ]

            return sorted(matched, key=lambda x: x["pagerank"], reverse=True)[:limit]
        except Exception:
            return []


# 싱글톤 인스턴스
_client_instance: Optional[CuGraphClient] = None
_helper_instance: Optional[CuGraphRAGHelper] = None


def get_cugraph_client() -> CuGraphClient:
    """cuGraph 클라이언트 싱글톤"""
    global _client_instance
    if _client_instance is None:
        _client_instance = CuGraphClient()
    return _client_instance


def get_cugraph_helper(graph_id: str = "713365bb") -> CuGraphRAGHelper:
    """cuGraph RAG 헬퍼 싱글톤"""
    global _helper_instance
    if _helper_instance is None:
        _helper_instance = CuGraphRAGHelper(default_graph_id=graph_id)
    return _helper_instance


if __name__ == "__main__":
    # 테스트
    client = CuGraphClient()

    print("=== 그래프 목록 ===")
    graphs = client.list_graphs()
    for g in graphs[:5]:
        print(f"  - {g.name}: {g.num_nodes:,} nodes, {g.num_edges:,} edges")

    print("\n=== PageRank (713365bb) ===")
    pr = client.pagerank("713365bb", top_k=5)
    for node in pr.get("top_10_nodes", [])[:5]:
        print(f"  - {node['vertex']}: {node['pagerank']:.6f}")

    print("\n=== 커뮤니티 (713365bb) ===")
    comm = client.community_detection("713365bb", top_k=5)
    print(f"  총 커뮤니티 수: {comm.get('num_communities', 0)}")
    print(f"  모듈성: {comm.get('modularity', 0):.4f}")

    print("\n=== Graph RAG Helper ===")
    helper = CuGraphRAGHelper()
    central = helper.get_central_nodes(top_k=5, node_type="project_")
    print("  중심 프로젝트:")
    for n in central:
        print(f"    - {n['vertex']}: {n['pagerank']:.6f}")
