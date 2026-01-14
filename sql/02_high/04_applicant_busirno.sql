-- EP-Agent: f_applicant_address busir_no 정규화
-- 하이픈 포함 12자리 → 10자리 숫자

-- 정규화 컬럼 추가
ALTER TABLE f_applicant_address ADD COLUMN IF NOT EXISTS busir_no_normalized VARCHAR(10);

-- 하이픈 제거
UPDATE f_applicant_address
SET busir_no_normalized = REPLACE(busir_no, '-', '')
WHERE busir_no IS NOT NULL AND busir_no != '';

-- 10자리가 아닌 경우 NULL 처리
UPDATE f_applicant_address
SET busir_no_normalized = NULL
WHERE busir_no_normalized IS NOT NULL AND LENGTH(busir_no_normalized) != 10;

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_applicant_address_busir_normalized ON f_applicant_address(busir_no_normalized);

-- 확인
SELECT 'busir_no_normalized populated' as status, COUNT(*) as count
FROM f_applicant_address WHERE busir_no_normalized IS NOT NULL;
