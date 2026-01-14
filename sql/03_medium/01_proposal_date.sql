-- EP-Agent: f_proposal_profile 날짜 컬럼 변환

-- 날짜 컬럼 추가
ALTER TABLE f_proposal_profile ADD COLUMN IF NOT EXISTS start_date DATE;
ALTER TABLE f_proposal_profile ADD COLUMN IF NOT EXISTS end_date DATE;
ALTER TABLE f_proposal_profile ADD COLUMN IF NOT EXISTS dev_period_months INTEGER;

-- 날짜 변환
UPDATE f_proposal_profile
SET start_date = TO_DATE(tot_dvlp_srt_ymd, 'YYYYMMDD')
WHERE tot_dvlp_srt_ymd ~ '^\d{8}$';

UPDATE f_proposal_profile
SET end_date = TO_DATE(tot_dvlp_end_ymd, 'YYYYMMDD')
WHERE tot_dvlp_end_ymd ~ '^\d{8}$';

-- 개발기간(월) 계산
UPDATE f_proposal_profile
SET dev_period_months =
    EXTRACT(YEAR FROM AGE(end_date, start_date)) * 12 +
    EXTRACT(MONTH FROM AGE(end_date, start_date))
WHERE start_date IS NOT NULL AND end_date IS NOT NULL;

-- 확인
SELECT 'Proposal dates converted' as status, COUNT(*) as count
FROM f_proposal_profile WHERE start_date IS NOT NULL;
