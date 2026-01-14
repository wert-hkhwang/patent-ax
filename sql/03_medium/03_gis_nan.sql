-- EP-Agent: f_gis NaN 처리

UPDATE f_gis SET org_busir_no = NULL WHERE org_busir_no = 'NaN' OR org_busir_no = '';
UPDATE f_gis SET org_corp_no = NULL WHERE org_corp_no = 'NaN' OR org_corp_no = '';

-- 좌표 유효성 검증 컬럼 추가
ALTER TABLE f_gis ADD COLUMN IF NOT EXISTS coord_valid BOOLEAN;

UPDATE f_gis
SET coord_valid = (x_coord BETWEEN 124 AND 132 AND y_coord BETWEEN 33 AND 39)
WHERE x_coord IS NOT NULL AND y_coord IS NOT NULL;

-- 확인
SELECT 'GIS NaN cleaned' as status, COUNT(*) as count FROM f_gis WHERE org_busir_no IS NULL;
