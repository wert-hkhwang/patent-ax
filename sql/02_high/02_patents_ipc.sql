-- EP-Agent: f_patents IPC 코드 분리 정규화
-- ipc_main, ipc_all에서 IPC 코드 추출하여 별도 테이블 생성

-- IPC 정규화 테이블 생성
DROP TABLE IF EXISTS patent_ipc_normalized;
CREATE TABLE patent_ipc_normalized (
    id SERIAL PRIMARY KEY,
    patent_documentid TEXT NOT NULL,
    ipc_code TEXT NOT NULL,
    ipc_section CHAR(1),
    ipc_class VARCHAR(10),
    ipc_order INTEGER,
    is_main BOOLEAN DEFAULT FALSE
);

-- ipc_main 삽입
INSERT INTO patent_ipc_normalized (patent_documentid, ipc_code, ipc_section, ipc_class, ipc_order, is_main)
SELECT
    documentid,
    ipc_main,
    LEFT(ipc_main, 1),
    SPLIT_PART(ipc_main, '-', 1),
    1,
    TRUE
FROM f_patents
WHERE ipc_main IS NOT NULL AND ipc_main != '';

-- ipc_all에서 추가 IPC 분리 삽입
INSERT INTO patent_ipc_normalized (patent_documentid, ipc_code, ipc_section, ipc_class, ipc_order, is_main)
SELECT
    documentid,
    TRIM(ipc),
    LEFT(TRIM(ipc), 1),
    SPLIT_PART(TRIM(ipc), '-', 1),
    ROW_NUMBER() OVER (PARTITION BY documentid ORDER BY ipc),
    FALSE
FROM f_patents,
     LATERAL UNNEST(STRING_TO_ARRAY(ipc_all, '|')) AS ipc
WHERE ipc_all IS NOT NULL AND ipc_all LIKE '%|%';

-- 인덱스 생성
CREATE INDEX idx_patent_ipc_documentid ON patent_ipc_normalized(patent_documentid);
CREATE INDEX idx_patent_ipc_section ON patent_ipc_normalized(ipc_section);
CREATE INDEX idx_patent_ipc_class ON patent_ipc_normalized(ipc_class);

-- 확인
SELECT 'patent_ipc_normalized created' as status, COUNT(*) as count FROM patent_ipc_normalized;
