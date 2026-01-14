-- 특허 기술요소 추출 테이블 생성
-- 4대 관점 기반 특허 분석: 목적/소재/공법/효과

CREATE TABLE IF NOT EXISTS f_patent_tech_elements (
    id SERIAL PRIMARY KEY,
    conts_id VARCHAR(50) NOT NULL,  -- 특허 콘텐츠 ID (f_patents.conts_id)

    -- 4대 관점 기술요소 (JSON 형식)
    purpose JSONB,   -- 목적 관점: {"problem": "...", "limitation": "...", "goal": "..."}
    material JSONB,  -- 소재 관점: {"compounds": [...], "properties": [...]}
    process JSONB,   -- 공법 관점: {"steps": [...]}
    effect JSONB,    -- 효과 관점: {"improvements": [...], "advantages": [...]}

    -- 추출 메타데이터
    extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    extraction_version VARCHAR(20) DEFAULT 'v1.0',  -- 추출 알고리즘 버전
    confidence_score FLOAT,  -- 추출 신뢰도 (0.0~1.0)

    -- 메타데이터
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 제약조건
    UNIQUE(conts_id),  -- 특허당 하나의 기술요소 레코드
    CHECK (confidence_score IS NULL OR (confidence_score >= 0.0 AND confidence_score <= 1.0))
);

-- 인덱스 생성
CREATE INDEX idx_tech_elements_conts_id ON f_patent_tech_elements(conts_id);
CREATE INDEX idx_tech_elements_extracted_at ON f_patent_tech_elements(extracted_at);
CREATE INDEX idx_tech_elements_confidence ON f_patent_tech_elements(confidence_score);

-- GIN 인덱스 (JSONB 검색용)
CREATE INDEX idx_tech_elements_purpose_gin ON f_patent_tech_elements USING GIN (purpose);
CREATE INDEX idx_tech_elements_material_gin ON f_patent_tech_elements USING GIN (material);
CREATE INDEX idx_tech_elements_process_gin ON f_patent_tech_elements USING GIN (process);
CREATE INDEX idx_tech_elements_effect_gin ON f_patent_tech_elements USING GIN (effect);

-- updated_at 자동 업데이트 트리거
CREATE OR REPLACE FUNCTION update_tech_elements_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_tech_elements_updated_at
    BEFORE UPDATE ON f_patent_tech_elements
    FOR EACH ROW
    EXECUTE FUNCTION update_tech_elements_updated_at();

-- 코멘트
COMMENT ON TABLE f_patent_tech_elements IS '특허 기술요소 추출 결과 (4대 관점)';
COMMENT ON COLUMN f_patent_tech_elements.conts_id IS '특허 콘텐츠 ID (f_patents 외래키)';
COMMENT ON COLUMN f_patent_tech_elements.purpose IS '목적 관점: 해결하려는 문제, 선행기술 한계, 발명 목표';
COMMENT ON COLUMN f_patent_tech_elements.material IS '소재 관점: 화합물, 조성비, 물성';
COMMENT ON COLUMN f_patent_tech_elements.process IS '공법 관점: 제조/처리 공정 단계';
COMMENT ON COLUMN f_patent_tech_elements.effect IS '효과 관점: 개선 사항, 장점';
COMMENT ON COLUMN f_patent_tech_elements.extraction_version IS '추출 알고리즘 버전 (v1.0, v1.1 등)';
COMMENT ON COLUMN f_patent_tech_elements.confidence_score IS '추출 신뢰도 (0.0~1.0)';
