"""
벡터 검색 기반 키워드 확장기 (Phase 31, Phase 96)
- Komoran 형태소 분석기를 사용한 명사 추출
- 빈도 기반 키워드 필터링
- LLM 키워드와 벡터 확장 키워드 병합
- LLM 기반 키워드 검토 (3단계 파이프라인)
- Phase 96: 환각 방지 강화 (빈도 60%, 최대 3개, payload 검증)
"""

import logging
import time
import json
import re
from collections import Counter
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional

from .stopwords import DOMAIN_STOPWORDS, is_stopword

logger = logging.getLogger(__name__)

# Phase 31/99.8: LLM 키워드 검토 프롬프트 (동의어 강화)
KEYWORD_REVIEW_PROMPT = """사용자 질문: {query}
LLM 추출 키워드: {llm_keywords}
벡터 확장 후보: {vector_keywords}

위 벡터 확장 후보 중 검색에 유용한 관련 키워드를 선택하세요.

## 반드시 포함 (Phase 99.8: 동의어/유사어 강화)
- 동의어/유사어: "수소연료" → "연료전지", "수소연료전지"
- 상위/하위 개념: "AI" → "인공지능", "머신러닝"
- 영문/한글 변환: "fuel cell" ↔ "연료전지", "PEMFC" ↔ "고분자전해질연료전지"
- 관련 기술 용어: "PEMFC", "스택", "전극", "MEA", "막전극접합체"

## 제외 기준
- 원본 키워드의 단순 분해 (예: "수소연료전지" → "수소", "전지", "연료")
- 무관한 일반어 (예: "발생", "발전", "인용", "문헌")
- 너무 범용적인 단어 (예: "전기", "화학", "물질")

## 출력 형식
JSON 배열로 출력 (동의어가 있으면 반드시 포함):
["키워드1", "키워드2", ...]
"""

# Komoran 싱글톤 (lazy loading)
_komoran = None


def get_komoran():
    """Komoran 인스턴스 반환 (싱글톤)"""
    global _komoran
    if _komoran is None:
        try:
            from konlpy.tag import Komoran
            _komoran = Komoran()
            logger.info("Komoran 형태소 분석기 초기화 완료")
        except Exception as e:
            logger.error(f"Komoran 초기화 실패: {e}")
            _komoran = None
    return _komoran


@dataclass
class KeywordExtractionResult:
    """키워드 추출 결과 (디버깅/로깅용)"""
    original_keywords: List[str]      # LLM 추출 원본
    expanded_keywords: List[str]      # 벡터 기반 확장
    final_keywords: List[str]         # 최종 병합
    source_doc_count: int             # 분석 문서 수
    extraction_time_ms: float         # 소요 시간

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환 (State 저장용)"""
        return asdict(self)


class KeywordExtractor:
    """벡터 검색 기반 키워드 확장기"""

    # 추출할 품사 태그 (Komoran 기준)
    # NNG: 일반명사, NNP: 고유명사, SL: 외국어
    TARGET_POS = {'NNG', 'NNP', 'SL'}

    # 최소 단어 길이
    MIN_WORD_LENGTH = 2

    def __init__(self):
        """초기화 (Komoran lazy loading)"""
        self._komoran = None

    @property
    def komoran(self):
        """Komoran 인스턴스 (lazy loading)"""
        if self._komoran is None:
            self._komoran = get_komoran()
        return self._komoran

    def extract_nouns(self, text: str) -> List[str]:
        """텍스트에서 명사 추출

        Args:
            text: 분석할 텍스트

        Returns:
            명사 목록
        """
        if not text or not self.komoran:
            return []

        try:
            # 텍스트 전처리 (Komoran 오류 방지)
            cleaned = text.replace('\x00', '').replace('\n', ' ')[:2000]

            # 형태소 분석
            pos_tags = self.komoran.pos(cleaned)

            # 명사만 추출 (불용어 제외)
            nouns = []
            for word, pos in pos_tags:
                if pos in self.TARGET_POS:
                    if len(word) >= self.MIN_WORD_LENGTH:
                        if not is_stopword(word):
                            nouns.append(word)

            return nouns

        except Exception as e:
            logger.debug(f"명사 추출 실패: {e}")
            return []

    def extract_from_vector_results(
        self,
        vector_results: Dict[str, List[Dict]],
        min_frequency: int = 500,
        max_keywords: int = 5
    ) -> List[str]:
        """벡터 검색 결과에서 기술 키워드 추출

        Args:
            vector_results: 컬렉션별 벡터 검색 결과
                {collection_name: [{payload: {...}, score: float}, ...]}
            min_frequency: 최소 등장 빈도
            max_keywords: 최대 추출 키워드 수

        Returns:
            확장 키워드 목록
        """
        start_time = time.time()

        # 모든 텍스트에서 명사 추출
        noun_counter = Counter()
        doc_count = 0

        for collection, results in vector_results.items():
            for r in results:
                payload = r.get("payload", {})

                # text 필드 우선 (통합 필드)
                text = payload.get("text", "")
                if not text:
                    # 폴백: 개별 필드 조합
                    text = " ".join([
                        payload.get("title", ""),
                        payload.get("name", ""),
                        payload.get("conts_klang_nm", ""),
                        payload.get("sbjt_nm", ""),
                        payload.get("abstract", "")[:500] if payload.get("abstract") else "",
                    ])

                if text:
                    nouns = self.extract_nouns(text)
                    noun_counter.update(nouns)
                    doc_count += 1

        # 빈도 기준 필터링
        expanded = []
        for word, count in noun_counter.most_common(50):
            if count >= min_frequency:
                expanded.append(word)
                if len(expanded) >= max_keywords:
                    break

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"벡터 키워드 추출: {doc_count}건 분석, {len(expanded)}개 추출, {elapsed_ms:.1f}ms")

        return expanded

    def merge_keywords(
        self,
        llm_keywords: List[str],
        vector_keywords: List[str]
    ) -> List[str]:
        """LLM 원본 + 벡터 확장 병합

        LLM 키워드: 원본 그대로 유지 (쪼개지 않음)
        벡터 확장: 중복 제거 후 추가

        Args:
            llm_keywords: LLM이 추출한 원본 키워드
            vector_keywords: 벡터 검색 기반 확장 키워드

        Returns:
            병합된 최종 키워드 목록
        """
        # LLM 원본 우선
        result = list(llm_keywords)

        # 벡터 확장 중 LLM에 없는 것만 추가
        llm_lower = {k.lower() for k in llm_keywords}

        for vk in vector_keywords:
            # 대소문자 무시 중복 체크
            if vk.lower() not in llm_lower:
                # Phase 42: 원본 키워드의 부분 문자열 제외 (복합어 분해 방지)
                # 예: "수질예측" → "수질", "예측" 제외 (원본의 구성 요소)
                # 예: "PEMFC" vs "연료전지" → 포함 (별개 기술 용어)
                is_component = False
                for lk in llm_keywords:
                    lk_lower = lk.lower()
                    vk_lower = vk.lower()

                    # 벡터 키워드가 LLM 키워드의 부분 문자열인 경우 제외
                    # (원본 복합어를 분해한 단순 키워드 차단)
                    if vk_lower in lk_lower and len(vk) < len(lk):
                        is_component = True
                        logger.debug(f"복합어 분해 제외: '{vk}' (원본: '{lk}')")
                        break

                    # 반대로 LLM 키워드가 벡터 키워드의 부분이면 포함
                    # (더 구체적인 기술 용어는 유지)
                    # 예: 원본 "AI" → 벡터 "인공지능" 포함

                if not is_component:
                    result.append(vk)

        return result

    def review_keywords_with_llm(
        self,
        query: str,
        llm_keywords: List[str],
        vector_keywords: List[str],
        llm_client = None
    ) -> List[str]:
        """LLM으로 키워드 후보 검토 및 선별 (Phase 31)

        Args:
            query: 사용자 질문
            llm_keywords: LLM이 추출한 원본 키워드
            vector_keywords: 벡터 검색 기반 확장 키워드 후보
            llm_client: LLM 클라이언트 (None이면 기본 클라이언트 사용)

        Returns:
            LLM이 선별한 최종 키워드 목록 (LLM 원본 + 선별된 벡터 확장)
        """
        if not vector_keywords:
            return list(llm_keywords)

        try:
            # LLM 클라이언트 가져오기 (프로젝트의 기존 LLM 클라이언트 사용)
            if llm_client is None:
                from llm.llm_client import get_llm_client
                llm_client = get_llm_client()

            # 프롬프트 생성
            prompt = KEYWORD_REVIEW_PROMPT.format(
                query=query,
                llm_keywords=llm_keywords,
                vector_keywords=vector_keywords
            )

            # LLM 호출 (temperature=0으로 일관성 확보)
            start_time = time.time()
            response = llm_client.generate(
                prompt=prompt,
                max_tokens=256,
                temperature=0
            )
            elapsed_ms = (time.time() - start_time) * 1000

            # JSON 파싱
            content = response.strip()
            # JSON 배열 추출 (마크다운 코드 블록 처리)
            json_match = re.search(r'\[.*?\]', content, re.DOTALL)
            if json_match:
                selected = json.loads(json_match.group())
            else:
                logger.warning(f"LLM 응답에서 JSON 배열을 찾을 수 없음: {content}")
                selected = []

            # LLM 원본은 항상 포함
            result = list(llm_keywords)
            llm_lower = {k.lower() for k in llm_keywords}
            for kw in selected:
                if kw.lower() not in llm_lower:
                    # Phase 42: 복합어 분해 방지 (merge_keywords와 동일 로직)
                    is_component = False
                    kw_lower = kw.lower()
                    for lk in llm_keywords:
                        lk_lower = lk.lower()
                        # 벡터 키워드가 LLM 키워드의 부분 문자열인 경우 제외
                        if kw_lower in lk_lower and len(kw) < len(lk):
                            is_component = True
                            logger.debug(f"LLM 검토에서 복합어 분해 제외: '{kw}' (원본: '{lk}')")
                            break
                    if not is_component:
                        result.append(kw)

            logger.info(f"LLM 키워드 검토 완료: {elapsed_ms:.1f}ms")
            logger.info(f"  - 입력 후보: {vector_keywords}")
            logger.info(f"  - LLM 선별: {selected}")
            logger.info(f"  - 최종: {result}")

            return result

        except Exception as e:
            logger.error(f"LLM 키워드 검토 실패: {e}", exc_info=True)
            # 실패 시 규칙 기반 병합으로 폴백
            return self.merge_keywords(llm_keywords, vector_keywords)

    def _appears_in_payloads(self, keyword: str, vector_results: Dict[str, List[Dict]]) -> bool:
        """Phase 96: 키워드가 벡터 결과 payload에 실제 등장하는지 확인

        환각 방지를 위해 추출된 키워드가 실제 문서에 존재하는지 검증.

        Args:
            keyword: 확인할 키워드
            vector_results: 벡터 검색 결과

        Returns:
            payload에 키워드가 존재하면 True
        """
        keyword_lower = keyword.lower()
        for collection, results in vector_results.items():
            for r in results:
                payload = r.get("payload", {})
                # text 필드 우선
                text = payload.get("text", "")
                if not text:
                    text = " ".join([
                        payload.get("title", ""),
                        payload.get("name", ""),
                        payload.get("conts_klang_nm", ""),
                        payload.get("sbjt_nm", ""),
                    ])
                if keyword_lower in text.lower():
                    return True
        return False

    def extract_and_merge(
        self,
        llm_keywords: List[str],
        vector_results: Dict[str, List[Dict]],
        min_frequency: int = 500,
        max_expanded: int = 5,
        query: str = None,
        use_llm_review: bool = False,
        llm_client = None
    ) -> KeywordExtractionResult:
        """키워드 추출 및 병합 (통합 메서드)

        Phase 96: 환각 방지 강화
        - 빈도 기준: 60% 이상
        - 최대 확장: 3개
        - payload 검증: 실제 문서에 등장 확인

        Args:
            llm_keywords: LLM 추출 원본 키워드
            vector_results: 벡터 검색 결과
            min_frequency: 벡터 키워드 최소 빈도 (Phase 96: 60% 권장)
            max_expanded: 벡터 키워드 최대 수 (Phase 96: 3개 권장)
            query: 사용자 질문 (LLM 검토 시 필요)
            use_llm_review: LLM 기반 키워드 검토 사용 여부 (Phase 31)
            llm_client: LLM 클라이언트 (None이면 기본 클라이언트 사용)

        Returns:
            KeywordExtractionResult
        """
        start_time = time.time()

        # Phase 96: 환각 방지 강화 - 최대 확장 수 제한
        # 기존 호출에서 max_expanded가 8로 설정되어도 3개로 제한
        phase96_max_expanded = min(max_expanded, 3)

        # 1. 벡터 기반 키워드 추출
        expanded_keywords = self.extract_from_vector_results(
            vector_results=vector_results,
            min_frequency=min_frequency,
            max_keywords=phase96_max_expanded
        )

        # Phase 96: payload 검증 - 실제 문서에 등장하는 키워드만 유지
        verified_expanded = []
        for kw in expanded_keywords:
            if self._appears_in_payloads(kw, vector_results):
                verified_expanded.append(kw)
            else:
                logger.debug(f"Phase 96: 키워드 '{kw}' payload 검증 실패 - 제외")

        if len(verified_expanded) < len(expanded_keywords):
            logger.info(f"Phase 96: payload 검증 후 확장 키워드 {len(expanded_keywords)} → {len(verified_expanded)}")

        expanded_keywords = verified_expanded

        # 2. 병합 (규칙 기반 또는 LLM 기반)
        if use_llm_review and query:
            # Phase 31: LLM 기반 키워드 검토
            final_keywords = self.review_keywords_with_llm(
                query=query,
                llm_keywords=llm_keywords,
                vector_keywords=expanded_keywords,
                llm_client=llm_client
            )
        else:
            # 기존 규칙 기반 병합
            final_keywords = self.merge_keywords(
                llm_keywords=llm_keywords,
                vector_keywords=expanded_keywords
            )

        # 3. 문서 수 계산
        doc_count = sum(len(results) for results in vector_results.values())

        elapsed_ms = (time.time() - start_time) * 1000

        result = KeywordExtractionResult(
            original_keywords=llm_keywords,
            expanded_keywords=expanded_keywords,
            final_keywords=final_keywords,
            source_doc_count=doc_count,
            extraction_time_ms=elapsed_ms
        )

        logger.info(f"키워드 추출 완료 (Phase 96, LLM 검토: {use_llm_review}):")
        logger.info(f"  - 원본(LLM): {llm_keywords}")
        logger.info(f"  - 확장(벡터): {expanded_keywords}")
        logger.info(f"  - 최종: {final_keywords}")
        logger.info(f"  - 분석 문서: {doc_count}건, 소요 시간: {elapsed_ms:.1f}ms")

        return result


# 싱글톤 인스턴스
_extractor = None


def get_keyword_extractor() -> KeywordExtractor:
    """KeywordExtractor 싱글톤 인스턴스 반환"""
    global _extractor
    if _extractor is None:
        _extractor = KeywordExtractor()
    return _extractor
