-- EP-Agent: f_patents 중복 제거
-- documentid 기준 중복 레코드 정리 (최신 id 유지)

-- 중복 확인
SELECT 'Before dedup - duplicates:' as status, COUNT(*) as count
FROM (
    SELECT documentid
    FROM f_patents
    GROUP BY documentid
    HAVING COUNT(*) > 1
) dup;

-- 중복 제거 (id가 큰 레코드 유지)
DELETE FROM f_patents a
USING f_patents b
WHERE a.documentid = b.documentid
  AND a.id < b.id;

-- 결과 확인
SELECT 'After dedup - total records:' as status, COUNT(*) as count FROM f_patents
UNION ALL
SELECT 'Unique documentid:', COUNT(DISTINCT documentid) FROM f_patents;
