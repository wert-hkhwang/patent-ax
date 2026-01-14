-- EP-Agent: f_patents NaN 처리
-- 'NaN' 문자열을 NULL로 변환

-- 1. org_busir_no, org_corp_no NaN → NULL
UPDATE f_patents
SET org_busir_no = NULL
WHERE org_busir_no = 'NaN';

UPDATE f_patents
SET org_corp_no = NULL
WHERE org_corp_no = 'NaN';

-- 2. patent_rgstn_ymd NaN → NULL
UPDATE f_patents
SET patent_rgstn_ymd = NULL
WHERE patent_rgstn_ymd = 'NaN';

-- 3. 빈 문자열 처리
UPDATE f_patents
SET
    patent_abstc_ko = NULLIF(TRIM(patent_abstc_ko), ''),
    patent_abstc_ko_1 = NULLIF(TRIM(patent_abstc_ko_1), ''),
    objectko = NULLIF(TRIM(objectko), ''),
    solutionko = NULLIF(TRIM(solutionko), '');

-- 확인
SELECT
    'org_busir_no NaN' as check_item,
    COUNT(*) as count
FROM f_patents WHERE org_busir_no = 'NaN'
UNION ALL
SELECT 'patent_rgstn_ymd NaN', COUNT(*) FROM f_patents WHERE patent_rgstn_ymd = 'NaN';
