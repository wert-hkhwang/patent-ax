-- EP-Agent: f_patents 날짜 정규화
-- TEXT 형식의 날짜를 DATE 타입으로 변환

-- 등록일 DATE 컬럼 추가
ALTER TABLE f_patents ADD COLUMN IF NOT EXISTS registration_date DATE;

UPDATE f_patents
SET registration_date = TO_DATE(
    REGEXP_REPLACE(patent_rgstn_ymd, '\.0$', ''),
    'YYYYMMDD'
)
WHERE patent_rgstn_ymd IS NOT NULL
  AND patent_rgstn_ymd ~ '^\d{8}';

-- 출원일 DATE 컬럼 추가
ALTER TABLE f_patents ADD COLUMN IF NOT EXISTS application_date DATE;

UPDATE f_patents
SET application_date = TO_DATE(ptnaplc_ymd, 'YYYYMMDD')
WHERE ptnaplc_ymd ~ '^\d{8}$';

-- 확인
SELECT
    'registration_date populated' as check_item,
    COUNT(*) as count
FROM f_patents WHERE registration_date IS NOT NULL
UNION ALL
SELECT 'application_date populated', COUNT(*) FROM f_patents WHERE application_date IS NOT NULL;
