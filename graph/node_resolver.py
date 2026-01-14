"""
노드 ID → 실제 속성 매핑 (Qdrant 기반)
Phase 75.1: cuGraph 노드 ID를 실제 엔티티 정보로 변환
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Dict, Optional, List
import logging
import requests

logger = logging.getLogger(__name__)

# 노드 타입 → Qdrant 컬렉션 매핑
NODE_TO_COLLECTION = {
    "project": "projects_v3_collection",
    "patent": "patents_v3_collection",
    "equip": "equipments_v3_collection",
    "org": "projects_v3_collection",       # org_nm 필드로 검색
    "applicant": "patents_v3_collection",  # applicant 필드로 검색
    "tech": "tech_classifications_v3_collection",
    "ancm": "proposals_v3_collection",
    "evalp": "proposals_v3_collection",
    "ipc": None,   # IPC는 코드 자체가 의미있음
    "gis": None,   # 지역코드는 별도 매핑 테이블 필요
    "k12": None,   # K12 분류 코드
    "6t": None,    # 6T 분류 코드
}

# 노드 타입별 ID 추출 필드 (Qdrant payload → 그래프 노드 ID 매핑)
NODE_ID_FIELD_MAP = {
    "project": "conts_id",        # S3269017 형식
    "patent": "application_no",   # 2022-0108400 형식 또는 documentid
    "equip": "equip_id",          # 장비 ID
    "tech": "tech_code",          # 기술분류 코드
    "ancm": "ancm_id",            # 공고 ID
}

# 지역 코드 → 이름 매핑 (간략화)
GIS_CODE_MAP = {
    "11": "서울", "26": "부산", "27": "대구", "28": "인천", "29": "광주",
    "30": "대전", "31": "울산", "36": "세종", "41": "경기", "42": "강원",
    "43": "충북", "44": "충남", "45": "전북", "46": "전남", "47": "경북",
    "48": "경남", "50": "제주", "11680": "강남구", "11650": "서초구",
    "30200": "대전시청", "41135": "수원시", "41590": "화성시"
}

# 6T 분류 코드 → 이름 매핑
TECH_6T_MAP = {
    "IT": "정보기술(IT)",
    "BT": "바이오기술(BT)",
    "NT": "나노기술(NT)",
    "ST": "우주기술(ST)",
    "ET": "환경기술(ET)",
    "CT": "문화기술(CT)"
}

# K12 분류 코드 → 이름 매핑
K12_MAP = {
    "K12-001": "인공지능", "K12-002": "빅데이터", "K12-003": "클라우드",
    "K12-004": "사물인터넷", "K12-005": "블록체인", "K12-006": "가상현실",
    "K12-007": "로봇", "K12-008": "자율주행", "K12-009": "드론",
    "K12-010": "3D프린팅", "K12-011": "바이오", "K12-012": "신에너지"
}


class NodeResolver:
    """그래프 노드 ID를 실제 엔티티 속성으로 변환"""

    def __init__(
        self,
        qdrant_url: str = os.getenv("QDRANT_URL", "http://210.109.80.106:6333"),
        max_cache_size: int = 10000
    ):
        self.qdrant_url = qdrant_url.rstrip("/")
        self._cache: Dict[str, Dict] = {}
        self._max_cache_size = max_cache_size
        self.timeout = 10

    def resolve(self, node_id: str) -> Optional[Dict]:
        """노드 ID → 속성 변환

        Args:
            node_id: 그래프 노드 ID (예: project_S3269017, org_0509db834128)

        Returns:
            속성 딕셔너리 또는 None
        """
        if not node_id:
            return None

        # 캐시 확인
        if node_id in self._cache:
            return self._cache[node_id]

        # 노드 타입과 값 추출
        parts = node_id.split('_', 1)
        if len(parts) != 2:
            return {"name": node_id, "type": "unknown"}

        node_type, node_value = parts

        # 정적 매핑 먼저 시도 (IPC, GIS, 6T, K12)
        result = self._resolve_static(node_type, node_value)
        if result:
            self._add_to_cache(node_id, result)
            return result

        # Qdrant 검색
        collection = NODE_TO_COLLECTION.get(node_type)
        if not collection:
            return {"name": node_id, "type": node_type}

        result = self._search_qdrant(collection, node_type, node_value)
        if result:
            self._add_to_cache(node_id, result)
            return result

        # 폴백: 노드 ID 자체 반환
        return {"name": node_value, "type": node_type}

    def resolve_batch(self, node_ids: List[str]) -> Dict[str, Dict]:
        """배치 변환

        Args:
            node_ids: 노드 ID 목록

        Returns:
            노드 ID → 속성 딕셔너리
        """
        results = {}
        for node_id in node_ids:
            results[node_id] = self.resolve(node_id)
        return results

    def _resolve_static(self, node_type: str, node_value: str) -> Optional[Dict]:
        """정적 매핑으로 해결 (IPC, GIS, 6T, K12)"""
        if node_type == "ipc":
            # IPC 코드는 그 자체로 의미있음
            return {
                "name": f"IPC {node_value}",
                "code": node_value,
                "type": "ipc",
                "description": self._get_ipc_description(node_value)
            }

        elif node_type == "gis":
            name = GIS_CODE_MAP.get(node_value, f"지역 {node_value}")
            # 앞 2자리로 시도
            if name == f"지역 {node_value}" and len(node_value) >= 2:
                name = GIS_CODE_MAP.get(node_value[:2], f"지역 {node_value}")
            return {
                "name": name,
                "code": node_value,
                "type": "gis"
            }

        elif node_type == "6t":
            name = TECH_6T_MAP.get(node_value, f"6T분류 {node_value}")
            return {
                "name": name,
                "code": node_value,
                "type": "6t"
            }

        elif node_type == "k12":
            name = K12_MAP.get(node_value, f"K12분류 {node_value}")
            return {
                "name": name,
                "code": node_value,
                "type": "k12"
            }

        elif node_type == "evalp":
            # 평가표는 노드 ID에 이름이 포함됨
            return {
                "name": node_value,
                "type": "evalp"
            }

        return None

    def _get_ipc_description(self, ipc_code: str) -> str:
        """IPC 코드 설명 (간략)"""
        # 상위 분류만 설명
        ipc_desc = {
            "A": "생활필수품", "B": "처리조작/운수", "C": "화학/야금",
            "D": "섬유/제지", "E": "고정구조물", "F": "기계공학/조명/가열/무기",
            "G": "물리학", "H": "전기"
        }
        if len(ipc_code) >= 1:
            return ipc_desc.get(ipc_code[0], "")
        return ""

    def _search_qdrant(
        self,
        collection: str,
        node_type: str,
        node_value: str
    ) -> Optional[Dict]:
        """Qdrant에서 노드 속성 검색"""
        try:
            # 노드 타입별 검색 전략
            if node_type == "project":
                return self._search_project(collection, node_value)
            elif node_type == "patent":
                return self._search_patent(collection, node_value)
            elif node_type == "org":
                return self._search_org(collection, node_value)
            elif node_type == "applicant":
                return self._search_applicant(collection, node_value)
            elif node_type == "equip":
                return self._search_equip(collection, node_value)
            elif node_type == "tech":
                return self._search_tech(collection, node_value)
            elif node_type == "ancm":
                return self._search_ancm(collection, node_value)
            else:
                return None
        except Exception as e:
            logger.warning(f"Qdrant 검색 실패 ({node_type}_{node_value}): {e}")
            return None

    def _search_project(self, collection: str, conts_id: str) -> Optional[Dict]:
        """과제 검색 (conts_id로)"""
        # scroll API로 필터 검색
        result = self._scroll_search(
            collection,
            filter_must=[{"key": "conts_id", "match": {"value": conts_id}}]
        )

        if result:
            payload = result.get("payload", {})
            return {
                "name": payload.get("title") or payload.get("sbjt_nm", conts_id),
                "org": payload.get("org_nm"),
                "conts_id": conts_id,
                "type": "project"
            }
        return None

    def _search_patent(self, collection: str, patent_id: str) -> Optional[Dict]:
        """특허 검색 (application_no 또는 documentid로)"""
        # application_no로 검색
        result = self._scroll_search(
            collection,
            filter_must=[{"key": "application_no", "match": {"value": patent_id}}]
        )

        if not result:
            # documentid로 재시도
            result = self._scroll_search(
                collection,
                filter_must=[{"key": "documentid", "match": {"value": patent_id}}]
            )

        if result:
            payload = result.get("payload", {})
            return {
                "name": payload.get("title", patent_id),
                "applicant": payload.get("applicant"),
                "application_no": payload.get("application_no"),
                "documentid": payload.get("documentid"),
                "ipc_main": payload.get("ipc_main"),
                "type": "patent"
            }
        return None

    def _search_org(self, collection: str, org_hash: str) -> Optional[Dict]:
        """기관 검색 (해시 ID는 역산 불가, 텍스트 검색 시도)"""
        # org_ 해시는 역산 불가
        # 대안: org_nm 필드에 해시 저장 여부 확인 또는 텍스트 검색
        # 현재는 해시 자체를 이름으로 반환
        return {
            "name": f"기관_{org_hash[:8]}",
            "hash": org_hash,
            "type": "org",
            "note": "해시 ID - 상세 정보 조회 불가"
        }

    def _search_applicant(self, collection: str, applicant_code: str) -> Optional[Dict]:
        """출원인 검색"""
        # applicant_code로 텍스트 검색은 어려움
        # 코드 자체를 반환
        return {
            "name": f"출원인_{applicant_code}",
            "code": applicant_code,
            "type": "applicant"
        }

    def _search_equip(self, collection: str, equip_id: str) -> Optional[Dict]:
        """장비 검색"""
        # 장비 컬렉션에서 ID로 검색
        result = self._scroll_search(
            collection,
            filter_must=[{"key": "equip_id", "match": {"value": equip_id}}]
        )

        if result:
            payload = result.get("payload", {})
            return {
                "name": payload.get("title") or payload.get("equip_nm", equip_id),
                "org": payload.get("org_nm"),
                "equip_id": equip_id,
                "type": "equip"
            }
        return {"name": equip_id, "type": "equip"}

    def _search_tech(self, collection: str, tech_code: str) -> Optional[Dict]:
        """기술분류 검색"""
        result = self._scroll_search(
            collection,
            filter_must=[{"key": "tech_code", "match": {"value": tech_code}}]
        )

        if result:
            payload = result.get("payload", {})
            return {
                "name": payload.get("title") or payload.get("tech_nm", tech_code),
                "code": tech_code,
                "type": "tech"
            }
        return {"name": f"기술분류_{tech_code}", "code": tech_code, "type": "tech"}

    def _search_ancm(self, collection: str, ancm_id: str) -> Optional[Dict]:
        """공고 검색"""
        result = self._scroll_search(
            collection,
            filter_must=[{"key": "ancm_id", "match": {"value": ancm_id}}]
        )

        if result:
            payload = result.get("payload", {})
            return {
                "name": payload.get("title") or payload.get("ancm_nm", ancm_id),
                "ancm_id": ancm_id,
                "type": "ancm"
            }
        return {"name": f"공고_{ancm_id}", "ancm_id": ancm_id, "type": "ancm"}

    def _scroll_search(
        self,
        collection: str,
        filter_must: List[Dict],
        limit: int = 1
    ) -> Optional[Dict]:
        """Qdrant scroll API로 필터 검색"""
        try:
            response = requests.post(
                f"{self.qdrant_url}/collections/{collection}/points/scroll",
                json={
                    "filter": {"must": filter_must},
                    "limit": limit,
                    "with_payload": True
                },
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                points = data.get("result", {}).get("points", [])
                if points:
                    return points[0]
        except Exception as e:
            logger.warning(f"Qdrant scroll 검색 실패: {e}")

        return None

    def _add_to_cache(self, node_id: str, result: Dict):
        """캐시에 추가 (크기 제한)"""
        if len(self._cache) >= self._max_cache_size:
            # 오래된 항목 제거 (간단히 절반 삭제)
            keys_to_remove = list(self._cache.keys())[:self._max_cache_size // 2]
            for key in keys_to_remove:
                del self._cache[key]

        self._cache[node_id] = result

    def clear_cache(self):
        """캐시 초기화"""
        self._cache.clear()

    def get_cache_stats(self) -> Dict:
        """캐시 통계"""
        return {
            "size": len(self._cache),
            "max_size": self._max_cache_size
        }


# 싱글톤 인스턴스
_resolver_instance: Optional[NodeResolver] = None


def get_node_resolver() -> NodeResolver:
    """NodeResolver 싱글톤 인스턴스"""
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = NodeResolver()
    return _resolver_instance


if __name__ == "__main__":
    # 테스트
    print("NodeResolver 테스트")
    resolver = get_node_resolver()

    test_nodes = [
        "project_S3269017",
        "project_C0403660",
        "patent_2022-0108400",
        "ipc_G06F",
        "ipc_H01M",
        "gis_11680",
        "6t_IT",
        "k12_K12-001",
        "org_0509db834128",
        "tech_T070111",
        "evalp_기업부설연구소 서면평가 평가표"
    ]

    print("\n노드 ID → 속성 변환 테스트:")
    for node_id in test_nodes:
        result = resolver.resolve(node_id)
        name = result.get("name", "N/A") if result else "None"
        print(f"  {node_id} → {name}")

    print(f"\n캐시 통계: {resolver.get_cache_stats()}")
