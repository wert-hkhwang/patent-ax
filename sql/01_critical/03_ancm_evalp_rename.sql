-- EP-Agent: f_ancm_evalp 컬럼명 정규화
-- col27 → eval_score, col28 → ancm_id_ref, col29 → ancm_nm, col30 → eval_note

-- 컬럼명 변경
ALTER TABLE f_ancm_evalp RENAME COLUMN col27 TO eval_score;
ALTER TABLE f_ancm_evalp RENAME COLUMN col28 TO ancm_id_ref;
ALTER TABLE f_ancm_evalp RENAME COLUMN col29 TO ancm_nm;
ALTER TABLE f_ancm_evalp RENAME COLUMN col30 TO eval_note;

-- 배점 숫자 컬럼 추가
ALTER TABLE f_ancm_evalp ADD COLUMN IF NOT EXISTS eval_score_num INTEGER;

UPDATE f_ancm_evalp
SET eval_score_num = eval_score::INTEGER
WHERE eval_score ~ '^\d+$';

-- 확인
SELECT 'Column rename completed' as status;
\d f_ancm_evalp
