"""
온톨로지 모듈
"""
from .rnd_ontology import (
    create_rnd_ontology,
    load_ontology,
    save_ontology,
    ENTITY_TYPES,
    RELATION_TYPES
)
from .ontology_loader import OntologyLoader, get_ontology_loader
