"""
Phase 17: Instruction Tuning 평가 모듈 테스트
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from evaluation.table_evaluator import (
    MarkdownTableParser,
    TableStructureEvaluator,
    TableContentEvaluator,
    TableEvaluator,
    ParsedTable,
    EvaluationResult
)


class TestMarkdownTableParser:
    """마크다운 표 파서 테스트"""

    def test_parse_simple_table(self):
        """간단한 표 파싱"""
        table_text = """
| 순위 | 이름 | 점수 |
|------|------|------|
| 1    | 홍길동 | 100  |
| 2    | 김철수 | 90   |
"""
        parser = MarkdownTableParser()
        result = parser.parse(table_text)

        assert result.col_count == 3
        assert result.row_count == 2
        assert result.headers == ["순위", "이름", "점수"]
        assert len(result.rows) == 2
        assert result.rows[0] == ["1", "홍길동", "100"]

    def test_parse_complex_headers(self):
        """복잡한 헤더 파싱"""
        table_text = """
| 순위 | 출원기관(현재 권리자) | 국적 | 2016 | 2017 | 총 공개 특허수 |
|------|----------------------|------|------|------|----------------|
| 1    | 현대자동차           | KR   | 168  | 191  | 2,807          |
"""
        parser = MarkdownTableParser()
        result = parser.parse(table_text)

        assert result.col_count == 6
        assert "출원기관(현재 권리자)" in result.headers
        assert "총 공개 특허수" in result.headers

    def test_parse_empty_text(self):
        """빈 텍스트 파싱"""
        parser = MarkdownTableParser()
        result = parser.parse("")

        assert result.is_empty()

    def test_parse_no_table(self):
        """표가 없는 텍스트 파싱"""
        parser = MarkdownTableParser()
        result = parser.parse("이것은 표가 아닙니다.")

        assert result.is_empty()

    def test_extract_all_tables(self):
        """여러 표 추출"""
        text = """
설명 텍스트

| A | B |
|---|---|
| 1 | 2 |

중간 텍스트

| C | D |
|---|---|
| 3 | 4 |
"""
        parser = MarkdownTableParser()
        tables = parser.extract_all_tables(text)

        assert len(tables) == 2
        assert tables[0].headers == ["A", "B"]
        assert tables[1].headers == ["C", "D"]


class TestTableStructureEvaluator:
    """표 구조 평가기 테스트"""

    def test_evaluate_identical_structure(self):
        """동일한 구조 평가"""
        pred_table = ParsedTable(
            headers=["순위", "이름", "점수"],
            rows=[["1", "홍길동", "100"]],
            row_count=1,
            col_count=3
        )
        gold_table = ParsedTable(
            headers=["순위", "이름", "점수"],
            rows=[["1", "홍길동", "100"]],
            row_count=1,
            col_count=3
        )

        evaluator = TableStructureEvaluator()
        result = evaluator.evaluate(pred_table, gold_table)

        assert result["score"] == 1.0
        assert result["column_match_rate"] == 1.0
        assert result["row_count_score"] == 1.0

    def test_evaluate_missing_columns(self):
        """누락된 컬럼 평가"""
        pred_table = ParsedTable(
            headers=["순위", "이름"],
            rows=[["1", "홍길동"]],
            row_count=1,
            col_count=2
        )
        gold_table = ParsedTable(
            headers=["순위", "이름", "점수"],
            rows=[["1", "홍길동", "100"]],
            row_count=1,
            col_count=3
        )

        evaluator = TableStructureEvaluator()
        result = evaluator.evaluate(pred_table, gold_table)

        assert result["column_match_rate"] < 1.0
        assert "점수" in result["missing_columns"]

    def test_evaluate_extra_columns(self):
        """추가 컬럼 평가"""
        pred_table = ParsedTable(
            headers=["순위", "이름", "점수", "등급"],
            rows=[["1", "홍길동", "100", "A"]],
            row_count=1,
            col_count=4
        )
        gold_table = ParsedTable(
            headers=["순위", "이름", "점수"],
            rows=[["1", "홍길동", "100"]],
            row_count=1,
            col_count=3
        )

        evaluator = TableStructureEvaluator()
        result = evaluator.evaluate(pred_table, gold_table)

        assert "등급" in result["extra_columns"]

    def test_evaluate_row_count_diff(self):
        """행 수 차이 평가"""
        pred_table = ParsedTable(
            headers=["순위", "이름"],
            rows=[["1", "홍길동"], ["2", "김철수"]],
            row_count=2,
            col_count=2
        )
        gold_table = ParsedTable(
            headers=["순위", "이름"],
            rows=[["1", "홍길동"], ["2", "김철수"], ["3", "이영희"]],
            row_count=3,
            col_count=2
        )

        evaluator = TableStructureEvaluator()
        result = evaluator.evaluate(pred_table, gold_table)

        assert result["row_count_score"] < 1.0

    def test_evaluate_header_partial_match(self):
        """헤더 부분 일치 평가"""
        pred_table = ParsedTable(
            headers=["순위", "출원기관", "국적"],
            rows=[],
            row_count=0,
            col_count=3
        )
        gold_table = ParsedTable(
            headers=["순위", "출원기관(현재 권리자)", "국적"],
            rows=[],
            row_count=0,
            col_count=3
        )

        evaluator = TableStructureEvaluator()
        result = evaluator.evaluate(pred_table, gold_table)

        # 부분 일치 허용되어야 함
        assert result["column_match_rate"] >= 0.66


class TestTableContentEvaluator:
    """표 컨텐츠 평가기 테스트"""

    def test_evaluate_identical_content(self):
        """동일한 컨텐츠 평가"""
        pred_table = ParsedTable(
            headers=["순위", "이름", "점수"],
            rows=[["1", "홍길동", "100"], ["2", "김철수", "90"]],
            row_count=2,
            col_count=3
        )
        gold_table = ParsedTable(
            headers=["순위", "이름", "점수"],
            rows=[["1", "홍길동", "100"], ["2", "김철수", "90"]],
            row_count=2,
            col_count=3
        )

        evaluator = TableContentEvaluator()
        result = evaluator.evaluate(pred_table, gold_table)

        assert result["score"] >= 0.8

    def test_evaluate_sorting(self):
        """정렬 평가"""
        # 내림차순 정렬된 표
        pred_table = ParsedTable(
            headers=["순위", "점수"],
            rows=[["1", "100"], ["2", "90"], ["3", "80"]],
            row_count=3,
            col_count=2
        )
        gold_table = ParsedTable(
            headers=["순위", "점수"],
            rows=[["1", "100"], ["2", "90"], ["3", "80"]],
            row_count=3,
            col_count=2
        )

        evaluator = TableContentEvaluator()
        result = evaluator.evaluate(pred_table, gold_table)

        assert result["sort_accuracy"] == 1.0

    def test_evaluate_empty_tables(self):
        """빈 표 평가"""
        pred_table = ParsedTable()
        gold_table = ParsedTable()

        evaluator = TableContentEvaluator()
        result = evaluator.evaluate(pred_table, gold_table)

        assert result["score"] == 1.0


class TestTableEvaluator:
    """통합 표 평가기 테스트"""

    def test_evaluate_full_match(self):
        """완전 일치 평가"""
        gold_text = """
| 순위 | 이름 | 점수 |
|------|------|------|
| 1    | 홍길동 | 100  |
| 2    | 김철수 | 90   |
"""
        pred_text = """
| 순위 | 이름 | 점수 |
|------|------|------|
| 1    | 홍길동 | 100  |
| 2    | 김철수 | 90   |
"""
        evaluator = TableEvaluator()
        result = evaluator.evaluate(pred_text, gold_text)

        assert result.final_score >= 0.9
        assert result.structure_score >= 0.9
        assert result.content_score >= 0.9

    def test_evaluate_partial_match(self):
        """부분 일치 평가"""
        gold_text = """
| 순위 | 출원기관(현재 권리자) | 국적 | 2016 | 2017 | 총 공개 특허수 |
|------|----------------------|------|------|------|----------------|
| 1    | 현대자동차           | KR   | 168  | 191  | 2,807          |
| 2    | 기아                 | KR   | 42   | 32   | 1,424          |
"""
        pred_text = """
| 순위 | 출원기관 | 국적 | 특허수 |
|------|----------|------|--------|
| 1    | 현대자동차 | KR   | 2807   |
| 2    | 기아       | KR   | 1424   |
"""
        evaluator = TableEvaluator()
        result = evaluator.evaluate(pred_text, gold_text)

        # 부분 일치이므로 점수가 0~1 사이
        assert 0.3 <= result.final_score <= 0.9
        assert len(result.missing_columns) > 0

    def test_evaluate_result_to_dict(self):
        """결과 딕셔너리 변환"""
        gold_text = """
| A | B |
|---|---|
| 1 | 2 |
"""
        pred_text = """
| A | B |
|---|---|
| 1 | 2 |
"""
        evaluator = TableEvaluator()
        result = evaluator.evaluate(pred_text, gold_text)

        result_dict = result.to_dict()

        assert "structure_score" in result_dict
        assert "content_score" in result_dict
        assert "final_score" in result_dict
        assert "matched_columns" in result_dict


class TestParsedTable:
    """ParsedTable 클래스 테스트"""

    def test_get_column_values(self):
        """컬럼 값 추출"""
        table = ParsedTable(
            headers=["A", "B", "C"],
            rows=[["1", "2", "3"], ["4", "5", "6"]],
            row_count=2,
            col_count=3
        )

        values = table.get_column_values(0)
        assert values == ["1", "4"]

        values = table.get_column_values(1)
        assert values == ["2", "5"]

    def test_get_column_by_name(self):
        """컬럼명으로 값 추출"""
        table = ParsedTable(
            headers=["순위", "이름", "점수"],
            rows=[["1", "홍길동", "100"], ["2", "김철수", "90"]],
            row_count=2,
            col_count=3
        )

        values = table.get_column_by_name("이름")
        assert values == ["홍길동", "김철수"]

    def test_is_empty(self):
        """빈 표 판단"""
        empty_table = ParsedTable()
        assert empty_table.is_empty()

        non_empty_table = ParsedTable(
            headers=["A"],
            rows=[["1"]],
            row_count=1,
            col_count=1
        )
        assert not non_empty_table.is_empty()


class TestRealWorldScenarios:
    """실제 사용 시나리오 테스트"""

    def test_patent_table_evaluation(self):
        """특허 표 평가"""
        gold_text = """
| 순위 | 출원기관(현재 권리자) | 국적 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 총 공개 특허수 |
|------|----------------------|------|------|------|------|------|------|------|------|------|----------------|
| 1    | 현대자동차           | KR   | 168  | 191  | 182  | 118  | 151  | 166  | 191  | 253  | 2,807 |
| 2    | 기아                 | KR   | 42   | 32   | 43   | 118  | 151  | 166  | 191  | 253  | 1,424 |
| 3    | 삼성SDI              | KR   | 7    | 4    | 2    | 0    | 1    | 0    | 0    | 0    | 1,386 |
"""
        pred_text = """
| 순위 | 출원기관 | 국적 | 특허수 |
|------|----------|------|--------|
| 1    | 현대자동차 | KR   | 2807   |
| 2    | 기아       | KR   | 1424   |
| 3    | 삼성SDI    | KR   | 1386   |
"""
        evaluator = TableEvaluator()
        result = evaluator.evaluate(pred_text, gold_text)

        # 핵심 데이터는 포함하지만 연도별 상세 누락
        assert result.final_score > 0.3
        assert "현대자동차" in str(result.pred_table.rows)
        print(f"특허 표 평가 점수: {result.final_score:.2%}")

    def test_equipment_table_evaluation(self):
        """장비 표 평가"""
        gold_text = """
| 장비ID | 장비코드 |
|--------|----------|
| 1212-C-0164 | Z-201901248603 |
"""
        pred_text = """
| 장비ID | 장비코드 |
|--------|----------|
| 1212-C-0164 | Z-201901248603 |
"""
        evaluator = TableEvaluator()
        result = evaluator.evaluate(pred_text, gold_text)

        assert result.final_score >= 0.9

    def test_top_n_evaluation(self):
        """TOP N 평가"""
        # TOP 5 요청에 3개만 반환한 경우
        gold_text = """
| 순위 | 기관 |
|------|------|
| 1    | A사  |
| 2    | B사  |
| 3    | C사  |
| 4    | D사  |
| 5    | E사  |
"""
        pred_text = """
| 순위 | 기관 |
|------|------|
| 1    | A사  |
| 2    | B사  |
| 3    | C사  |
"""
        evaluator = TableEvaluator()
        result = evaluator.evaluate(pred_text, gold_text)

        # 행 수 차이로 인해 점수 감점
        assert result.row_count_diff == 2
        assert result.row_count_score < 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
