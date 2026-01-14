"""
R&D 도메인 온톨로지 정의
- OWL 기반 온톨로지 클래스 정의
- 연구과제, 연구자, 기술, 산출물 등의 관계 모델링
"""

from owlready2 import *
import os

# 온톨로지 저장 경로
ONTOLOGY_PATH = os.path.join(os.path.dirname(__file__), "rnd_ontology.owl")


def create_rnd_ontology():
    """R&D 도메인 온톨로지 생성"""

    # 새 온톨로지 생성
    onto = get_ontology("http://example.org/rnd_ontology#")

    with onto:
        # ========================================
        # 1. 핵심 클래스 정의
        # ========================================

        class Entity(Thing):
            """모든 엔티티의 기본 클래스"""
            pass

        # 연구 관련 클래스
        class ResearchProject(Entity):
            """연구과제"""
            comment = ["R&D 연구과제를 나타내는 클래스"]

        class Researcher(Entity):
            """연구자"""
            comment = ["연구를 수행하는 개인"]

        class Organization(Entity):
            """기관"""
            comment = ["연구기관, 대학, 기업 등"]

        class Technology(Entity):
            """기술"""
            comment = ["연구에서 개발되거나 사용되는 기술"]

        class ResearchOutput(Entity):
            """연구 산출물"""
            comment = ["논문, 특허, 보고서 등 연구 결과물"]

        class Keyword(Entity):
            """키워드"""
            comment = ["연구 분야나 주제를 나타내는 키워드"]

        class ResearchField(Entity):
            """연구 분야"""
            comment = ["연구 분야 분류"]

        # 산출물 하위 클래스
        class Paper(ResearchOutput):
            """논문"""
            pass

        class Patent(ResearchOutput):
            """특허"""
            pass

        class Report(ResearchOutput):
            """보고서"""
            pass

        class Software(ResearchOutput):
            """소프트웨어"""
            pass

        # 기관 하위 클래스
        class University(Organization):
            """대학"""
            pass

        class ResearchInstitute(Organization):
            """연구소"""
            pass

        class Company(Organization):
            """기업"""
            pass

        class GovernmentAgency(Organization):
            """정부기관"""
            pass

        # ========================================
        # 2. 데이터 프로퍼티 정의
        # ========================================

        class hasName(DataProperty):
            """이름"""
            domain = [Entity]
            range = [str]

        class hasDescription(DataProperty):
            """설명"""
            domain = [Entity]
            range = [str]

        class hasStartDate(DataProperty):
            """시작일"""
            domain = [ResearchProject]
            range = [str]

        class hasEndDate(DataProperty):
            """종료일"""
            domain = [ResearchProject]
            range = [str]

        class hasBudget(DataProperty):
            """예산"""
            domain = [ResearchProject]
            range = [float]

        class hasStatus(DataProperty):
            """상태"""
            domain = [ResearchProject]
            range = [str]

        class hasYear(DataProperty):
            """연도"""
            domain = [ResearchOutput]
            range = [int]

        class hasAbstract(DataProperty):
            """초록"""
            domain = [ResearchOutput]
            range = [str]

        class hasAffiliation(DataProperty):
            """소속"""
            domain = [Researcher]
            range = [str]

        class hasExpertise(DataProperty):
            """전문분야"""
            domain = [Researcher]
            range = [str]

        # ========================================
        # 3. 객체 프로퍼티 (관계) 정의
        # ========================================

        # 연구과제 관련 관계
        class hasLeadResearcher(ObjectProperty):
            """연구책임자"""
            domain = [ResearchProject]
            range = [Researcher]

        class hasParticipant(ObjectProperty):
            """참여연구원"""
            domain = [ResearchProject]
            range = [Researcher]

        class hasFundingAgency(ObjectProperty):
            """지원기관"""
            domain = [ResearchProject]
            range = [Organization]

        class hasExecutingOrg(ObjectProperty):
            """수행기관"""
            domain = [ResearchProject]
            range = [Organization]

        class producesOutput(ObjectProperty):
            """산출물 생성"""
            domain = [ResearchProject]
            range = [ResearchOutput]

        class usesTechnology(ObjectProperty):
            """기술 사용"""
            domain = [ResearchProject]
            range = [Technology]

        class developsTechnology(ObjectProperty):
            """기술 개발"""
            domain = [ResearchProject]
            range = [Technology]

        class hasKeyword(ObjectProperty):
            """키워드"""
            domain = [ResearchProject, ResearchOutput, Technology]
            range = [Keyword]

        class belongsToField(ObjectProperty):
            """연구분야"""
            domain = [ResearchProject, ResearchOutput, Technology]
            range = [ResearchField]

        # 연구자 관련 관계
        class worksAt(ObjectProperty):
            """소속기관"""
            domain = [Researcher]
            range = [Organization]

        class collaboratesWith(ObjectProperty):
            """협력관계"""
            domain = [Researcher]
            range = [Researcher]

        class authorsOutput(ObjectProperty):
            """저작"""
            domain = [Researcher]
            range = [ResearchOutput]

        # 기술 관련 관계
        class relatedTo(ObjectProperty):
            """관련기술"""
            domain = [Technology]
            range = [Technology]

        class basedOn(ObjectProperty):
            """기반기술"""
            domain = [Technology]
            range = [Technology]

        # 역관계 정의
        class isLeadResearcherOf(ObjectProperty):
            """연구책임자의 역관계"""
            inverse_property = hasLeadResearcher

        class participatesIn(ObjectProperty):
            """참여의 역관계"""
            inverse_property = hasParticipant

        class funds(ObjectProperty):
            """지원의 역관계"""
            inverse_property = hasFundingAgency

        class executes(ObjectProperty):
            """수행의 역관계"""
            inverse_property = hasExecutingOrg

        class isProducedBy(ObjectProperty):
            """산출물의 역관계"""
            inverse_property = producesOutput

        class isAuthoredBy(ObjectProperty):
            """저작의 역관계"""
            inverse_property = authorsOutput

        # ========================================
        # 4. 추가 제약조건 (SWRL 규칙 대신 Python으로 처리)
        # ========================================

        # 대칭 관계 설정
        collaboratesWith.is_a.append(SymmetricProperty)
        relatedTo.is_a.append(SymmetricProperty)

        # 전이 관계 설정
        basedOn.is_a.append(TransitiveProperty)

    return onto


def save_ontology(onto, path=None):
    """온톨로지를 OWL 파일로 저장"""
    if path is None:
        path = ONTOLOGY_PATH
    onto.save(file=path, format="rdfxml")
    print(f"온톨로지 저장됨: {path}")


def load_ontology(path=None):
    """저장된 온톨로지 로드"""
    if path is None:
        path = ONTOLOGY_PATH

    if os.path.exists(path):
        onto = get_ontology(path).load()
        print(f"온톨로지 로드됨: {path}")
        return onto
    else:
        print("저장된 온톨로지 없음, 새로 생성")
        onto = create_rnd_ontology()
        save_ontology(onto, path)
        return onto


# 관계 타입 정의 (그래프 구축시 사용)
RELATION_TYPES = {
    "hasLeadResearcher": {"source": "ResearchProject", "target": "Researcher", "label": "책임연구원"},
    "hasParticipant": {"source": "ResearchProject", "target": "Researcher", "label": "참여연구원"},
    "hasFundingAgency": {"source": "ResearchProject", "target": "Organization", "label": "지원기관"},
    "hasExecutingOrg": {"source": "ResearchProject", "target": "Organization", "label": "수행기관"},
    "producesOutput": {"source": "ResearchProject", "target": "ResearchOutput", "label": "산출물"},
    "usesTechnology": {"source": "ResearchProject", "target": "Technology", "label": "사용기술"},
    "developsTechnology": {"source": "ResearchProject", "target": "Technology", "label": "개발기술"},
    "hasKeyword": {"source": "Entity", "target": "Keyword", "label": "키워드"},
    "belongsToField": {"source": "Entity", "target": "ResearchField", "label": "연구분야"},
    "worksAt": {"source": "Researcher", "target": "Organization", "label": "소속"},
    "collaboratesWith": {"source": "Researcher", "target": "Researcher", "label": "협력"},
    "authorsOutput": {"source": "Researcher", "target": "ResearchOutput", "label": "저작"},
    "relatedTo": {"source": "Technology", "target": "Technology", "label": "관련기술"},
    "basedOn": {"source": "Technology", "target": "Technology", "label": "기반기술"},
}

# 엔티티 타입 정의
ENTITY_TYPES = {
    "ResearchProject": {"label": "연구과제", "color": "#4CAF50"},
    "Researcher": {"label": "연구자", "color": "#2196F3"},
    "Organization": {"label": "기관", "color": "#FF9800"},
    "University": {"label": "대학", "color": "#FF9800"},
    "ResearchInstitute": {"label": "연구소", "color": "#FF9800"},
    "Company": {"label": "기업", "color": "#FF9800"},
    "GovernmentAgency": {"label": "정부기관", "color": "#FF9800"},
    "Technology": {"label": "기술", "color": "#9C27B0"},
    "ResearchOutput": {"label": "산출물", "color": "#F44336"},
    "Paper": {"label": "논문", "color": "#F44336"},
    "Patent": {"label": "특허", "color": "#F44336"},
    "Report": {"label": "보고서", "color": "#F44336"},
    "Software": {"label": "소프트웨어", "color": "#F44336"},
    "Keyword": {"label": "키워드", "color": "#607D8B"},
    "ResearchField": {"label": "연구분야", "color": "#795548"},
}


if __name__ == "__main__":
    # 온톨로지 생성 및 저장 테스트
    onto = create_rnd_ontology()
    save_ontology(onto)

    # 클래스 목록 출력
    print("\n정의된 클래스:")
    for cls in onto.classes():
        print(f"  - {cls.name}")

    print("\n정의된 객체 프로퍼티:")
    for prop in onto.object_properties():
        print(f"  - {prop.name}")

    print("\n정의된 데이터 프로퍼티:")
    for prop in onto.data_properties():
        print(f"  - {prop.name}")
