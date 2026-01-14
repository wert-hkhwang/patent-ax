-- EP-Agent: f_equipments KPI 분리 테이블

-- 장비 KPI 정규화 테이블 생성
DROP TABLE IF EXISTS equipment_kpi_normalized;
CREATE TABLE equipment_kpi_normalized (
    id SERIAL PRIMARY KEY,
    equipment_conts_id TEXT NOT NULL,
    kpi_name TEXT NOT NULL,
    kpi_order INTEGER
);

-- KPI 분리 삽입
INSERT INTO equipment_kpi_normalized (equipment_conts_id, kpi_name, kpi_order)
SELECT
    conts_id,
    TRIM(kpi),
    ROW_NUMBER() OVER (PARTITION BY conts_id ORDER BY kpi)
FROM f_equipments,
     LATERAL UNNEST(STRING_TO_ARRAY(kpi_nm_list, '|')) AS kpi
WHERE kpi_nm_list IS NOT NULL AND kpi_nm_list != '';

-- 지역 코드 정규화
ALTER TABLE f_equipments ADD COLUMN IF NOT EXISTS region_code VARCHAR(2);

UPDATE f_equipments
SET region_code = CASE address_dosi
    WHEN '서울' THEN '11' WHEN '부산' THEN '21' WHEN '대구' THEN '22'
    WHEN '인천' THEN '23' WHEN '광주' THEN '24' WHEN '대전' THEN '25'
    WHEN '울산' THEN '26' WHEN '세종' THEN '29' WHEN '경기' THEN '31'
    WHEN '강원' THEN '32' WHEN '충북' THEN '33' WHEN '충남' THEN '34'
    WHEN '전북' THEN '35' WHEN '전남' THEN '36' WHEN '경북' THEN '37'
    WHEN '경남' THEN '38' WHEN '제주' THEN '39' ELSE NULL
END;

-- 인덱스 생성
CREATE INDEX idx_equipment_kpi_conts_id ON equipment_kpi_normalized(equipment_conts_id);
CREATE INDEX idx_equipment_kpi_name ON equipment_kpi_normalized(kpi_name);

-- 확인
SELECT 'equipment_kpi_normalized created' as status, COUNT(*) as count FROM equipment_kpi_normalized;
