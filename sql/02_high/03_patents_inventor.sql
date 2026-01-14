-- EP-Agent: f_patents 발명자 분리 정규화
-- patent_invno_group에서 발명자 추출하여 별도 테이블 생성

-- 발명자 정규화 테이블 생성
DROP TABLE IF EXISTS patent_inventor_normalized;
CREATE TABLE patent_inventor_normalized (
    id SERIAL PRIMARY KEY,
    patent_documentid TEXT NOT NULL,
    inventor_name TEXT NOT NULL,
    inventor_order INTEGER
);

-- 발명자 분리 삽입
INSERT INTO patent_inventor_normalized (patent_documentid, inventor_name, inventor_order)
SELECT
    documentid,
    TRIM(inventor),
    ROW_NUMBER() OVER (PARTITION BY documentid ORDER BY inventor)
FROM f_patents,
     LATERAL UNNEST(STRING_TO_ARRAY(patent_invno_group, '|')) AS inventor
WHERE patent_invno_group IS NOT NULL AND patent_invno_group != '';

-- 인덱스 생성
CREATE INDEX idx_patent_inventor_documentid ON patent_inventor_normalized(patent_documentid);
CREATE INDEX idx_patent_inventor_name ON patent_inventor_normalized(inventor_name);

-- 확인
SELECT 'patent_inventor_normalized created' as status, COUNT(*) as count FROM patent_inventor_normalized;
