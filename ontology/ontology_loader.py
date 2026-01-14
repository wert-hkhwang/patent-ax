"""
온톨로지 로더 및 데이터베이스 연동
- DB에서 데이터를 읽어 온톨로지 인스턴스 생성
- 온톨로지 기반 추론 지원
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owlready2 import *
from typing import Dict, List, Optional, Any
import re

from sql.db_connector import get_db_connection
from ontology.rnd_ontology import (
    create_rnd_ontology,
    load_ontology,
    ENTITY_TYPES,
    RELATION_TYPES
)


class OntologyLoader:
    """온톨로지 로더 - DB 데이터를 온톨로지 인스턴스로 변환"""

    def __init__(self):
        self.onto = create_rnd_ontology()
        self.entities: Dict[str, Any] = {}  # entity_id -> ontology instance
        self.connection = None

    def connect_db(self):
        """DB 연결"""
        if self.connection is None:
            self.connection = get_db_connection()
        return self.connection

    def close_db(self):
        """DB 연결 종료"""
        if self.connection:
            self.connection.close()
            self.connection = None

    def _sanitize_name(self, name: str) -> str:
        """온톨로지 인스턴스 이름으로 사용 가능하도록 정제"""
        if not name:
            return "unnamed"
        # 특수문자 제거, 공백을 _로 변환
        sanitized = re.sub(r'[^\w\s가-힣]', '', str(name))
        sanitized = re.sub(r'\s+', '_', sanitized)
        return sanitized[:100] if sanitized else "unnamed"

    def _get_or_create_entity(self, entity_type: str, entity_id: str, name: str) -> Any:
        """엔티티 조회 또는 생성"""
        key = f"{entity_type}_{entity_id}"

        if key in self.entities:
            return self.entities[key]

        with self.onto:
            # 클래스 가져오기
            cls = getattr(self.onto, entity_type, None)
            if cls is None:
                cls = self.onto.Entity

            # 인스턴스 생성
            instance_name = f"{entity_type}_{self._sanitize_name(entity_id)}"
            instance = cls(instance_name)

            # 이름 설정
            if hasattr(self.onto, 'hasName'):
                instance.hasName = [name]

            self.entities[key] = instance
            return instance

    def load_research_projects(self, limit: int = 1000) -> List[Any]:
        """연구과제 데이터 로드"""
        conn = self.connect_db()
        cursor = conn.cursor()

        query = """
        SELECT TOP (?)
            pjt_id,
            pjt_name,
            pjt_summary,
            tech_keyword,
            start_date,
            end_date,
            performing_org,
            funding_agency
        FROM rnd_projects
        """

        cursor.execute(query, (limit,))
        rows = cursor.fetchall()

        projects = []
        with self.onto:
            for row in rows:
                pjt_id, pjt_name, summary, keywords, start_date, end_date, org, agency = row

                # 연구과제 인스턴스 생성
                project = self._get_or_create_entity("ResearchProject", str(pjt_id), pjt_name or "")

                # 속성 설정
                if summary:
                    project.hasDescription = [summary]
                if start_date:
                    project.hasStartDate = [str(start_date)]
                if end_date:
                    project.hasEndDate = [str(end_date)]

                # 수행기관 연결
                if org:
                    org_instance = self._get_or_create_entity("Organization", self._sanitize_name(org), org)
                    project.hasExecutingOrg = [org_instance]

                # 지원기관 연결
                if agency:
                    agency_instance = self._get_or_create_entity("GovernmentAgency", self._sanitize_name(agency), agency)
                    project.hasFundingAgency = [agency_instance]

                # 키워드 연결
                if keywords:
                    keyword_list = [k.strip() for k in keywords.split(',') if k.strip()]
                    keyword_instances = []
                    for kw in keyword_list[:10]:  # 최대 10개 키워드
                        kw_instance = self._get_or_create_entity("Keyword", self._sanitize_name(kw), kw)
                        keyword_instances.append(kw_instance)
                    if keyword_instances:
                        project.hasKeyword = keyword_instances

                projects.append(project)

        return projects

    def load_researchers(self, limit: int = 1000) -> List[Any]:
        """연구자 데이터 로드 (연구과제 참여자 기반)"""
        conn = self.connect_db()
        cursor = conn.cursor()

        # 연구책임자 정보 로드
        query = """
        SELECT TOP (?)
            pjt_id,
            lead_researcher,
            performing_org
        FROM rnd_projects
        WHERE lead_researcher IS NOT NULL
        """

        cursor.execute(query, (limit,))
        rows = cursor.fetchall()

        researchers = []
        with self.onto:
            for row in rows:
                pjt_id, researcher_name, org = row

                if not researcher_name:
                    continue

                # 연구자 인스턴스 생성
                researcher = self._get_or_create_entity("Researcher", self._sanitize_name(researcher_name), researcher_name)

                # 소속 설정
                if org:
                    researcher.hasAffiliation = [org]
                    org_instance = self._get_or_create_entity("Organization", self._sanitize_name(org), org)
                    researcher.worksAt = [org_instance]

                # 연구과제와 연결
                project_key = f"ResearchProject_{pjt_id}"
                if project_key in self.entities:
                    project = self.entities[project_key]
                    project.hasLeadResearcher = [researcher]

                researchers.append(researcher)

        return researchers

    def load_technologies(self, limit: int = 500) -> List[Any]:
        """기술 키워드를 기술 엔티티로 변환"""
        conn = self.connect_db()
        cursor = conn.cursor()

        # 기술 키워드 추출
        query = """
        SELECT TOP (?)
            pjt_id,
            tech_keyword
        FROM rnd_projects
        WHERE tech_keyword IS NOT NULL
        """

        cursor.execute(query, (limit,))
        rows = cursor.fetchall()

        technologies = []
        tech_set = set()

        with self.onto:
            for row in rows:
                pjt_id, tech_keywords = row

                if not tech_keywords:
                    continue

                # 키워드 파싱
                keywords = [k.strip() for k in tech_keywords.split(',') if k.strip()]

                for kw in keywords[:5]:  # 과제당 최대 5개 기술
                    if kw not in tech_set:
                        tech = self._get_or_create_entity("Technology", self._sanitize_name(kw), kw)
                        tech.hasName = [kw]
                        technologies.append(tech)
                        tech_set.add(kw)

                    # 연구과제와 연결
                    project_key = f"ResearchProject_{pjt_id}"
                    if project_key in self.entities:
                        project = self.entities[project_key]
                        tech = self.entities.get(f"Technology_{self._sanitize_name(kw)}")
                        if tech:
                            current_techs = list(project.usesTechnology) if hasattr(project, 'usesTechnology') else []
                            if tech not in current_techs:
                                current_techs.append(tech)
                                project.usesTechnology = current_techs

        return technologies

    def load_all(self, project_limit: int = 500) -> Dict[str, int]:
        """모든 데이터 로드"""
        print("온톨로지 데이터 로딩 시작...")

        # 순서대로 로드 (의존성 고려)
        projects = self.load_research_projects(limit=project_limit)
        print(f"  - 연구과제 로드: {len(projects)}건")

        researchers = self.load_researchers(limit=project_limit)
        print(f"  - 연구자 로드: {len(researchers)}건")

        technologies = self.load_technologies(limit=project_limit)
        print(f"  - 기술 로드: {len(technologies)}건")

        # 통계
        stats = {
            "projects": len(projects),
            "researchers": len(researchers),
            "technologies": len(technologies),
            "total_entities": len(self.entities)
        }

        print(f"  - 총 엔티티: {stats['total_entities']}건")
        return stats

    def get_entity(self, entity_type: str, entity_id: str) -> Optional[Any]:
        """특정 엔티티 조회"""
        key = f"{entity_type}_{entity_id}"
        return self.entities.get(key)

    def get_all_entities(self) -> Dict[str, Any]:
        """모든 엔티티 조회"""
        return self.entities

    def get_entity_relations(self, entity: Any) -> List[Dict]:
        """엔티티의 모든 관계 조회"""
        relations = []

        for prop in self.onto.object_properties():
            prop_name = prop.name
            try:
                values = getattr(entity, prop_name, [])
                if values:
                    for value in values:
                        relations.append({
                            "property": prop_name,
                            "target": value.name if hasattr(value, 'name') else str(value),
                            "target_type": type(value).__name__
                        })
            except Exception:
                continue

        return relations

    def query_by_keyword(self, keyword: str) -> List[Dict]:
        """키워드로 관련 엔티티 검색"""
        results = []
        keyword_lower = keyword.lower()

        for key, entity in self.entities.items():
            # 이름에서 검색
            names = getattr(entity, 'hasName', [])
            for name in names:
                if keyword_lower in str(name).lower():
                    results.append({
                        "entity_id": key,
                        "entity_type": type(entity).__name__,
                        "name": name,
                        "match_type": "name"
                    })
                    break

            # 설명에서 검색
            descriptions = getattr(entity, 'hasDescription', [])
            for desc in descriptions:
                if keyword_lower in str(desc).lower():
                    if not any(r['entity_id'] == key for r in results):
                        results.append({
                            "entity_id": key,
                            "entity_type": type(entity).__name__,
                            "name": names[0] if names else key,
                            "match_type": "description"
                        })
                    break

        return results


# 싱글톤 인스턴스
_loader_instance: Optional[OntologyLoader] = None


def get_ontology_loader() -> OntologyLoader:
    """온톨로지 로더 싱글톤 인스턴스 반환"""
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = OntologyLoader()
    return _loader_instance


if __name__ == "__main__":
    # 테스트
    loader = OntologyLoader()

    try:
        stats = loader.load_all(project_limit=100)
        print(f"\n로드 완료: {stats}")

        # 키워드 검색 테스트
        results = loader.query_by_keyword("인공지능")
        print(f"\n'인공지능' 검색 결과: {len(results)}건")
        for r in results[:5]:
            print(f"  - [{r['entity_type']}] {r['name']}")

    except Exception as e:
        print(f"오류 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        loader.close_db()
