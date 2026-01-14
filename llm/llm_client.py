"""
vLLM OpenAI 호환 클라이언트
- EXAONE-4.0.1-32B 모델 연동
- 스트리밍 지원
- Reasoning Mode 지원 (<think> 태그 기반 Chain-of-Thought)
- 에러 핸들링 및 재시도
"""

import os
import re
import json
import logging
from typing import Dict, List, Optional, Generator, Any, Tuple
from dataclasses import dataclass, field
import requests

logger = logging.getLogger(__name__)


@dataclass
class ReasoningResult:
    """Reasoning Mode 결과"""
    thinking: str = ""          # <think> 블록 내용
    answer: str = ""            # 최종 답변
    raw_response: str = ""      # 원본 응답


@dataclass
class LLMConfig:
    """LLM 설정"""
    base_url: str = os.getenv("VLLM_BASE_URL", "http://210.109.80.106:12288")
    api_key: str = os.getenv("VLLM_API_KEY", "sk-exaone-276f9a048c26141a8f8f339537c20d97")
    model: str = os.getenv("VLLM_MODEL", "LGAI-EXAONE/EXAONE-4.0.1-32B")
    max_tokens: int = 4096
    temperature: float = 0.3  # 응답 일관성을 위해 낮춤
    top_p: float = 0.9
    timeout: int = 120


class LLMClient:
    """vLLM OpenAI 호환 클라이언트"""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}"
        }

    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """채팅 완성 요청

        Args:
            messages: 메시지 목록 [{"role": "user", "content": "..."}]
            max_tokens: 최대 토큰 수
            temperature: 온도
            stream: 스트리밍 여부
            **kwargs: 추가 파라미터

        Returns:
            응답 딕셔너리
        """
        payload = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": max_tokens or self.config.max_tokens,
            "temperature": temperature if temperature is not None else self.config.temperature,
            "top_p": self.config.top_p,
            "stream": stream,
            **kwargs
        }

        try:
            response = requests.post(
                f"{self.config.base_url}/v1/chat/completions",
                headers=self.headers,
                json=payload,
                timeout=self.config.timeout,
                stream=stream
            )
            response.raise_for_status()

            if stream:
                return self._handle_stream(response)
            else:
                return response.json()

        except requests.exceptions.Timeout:
            logger.error("LLM 요청 타임아웃")
            raise TimeoutError("LLM 요청이 시간 초과되었습니다.")
        except requests.exceptions.RequestException as e:
            logger.error(f"LLM 요청 오류: {e}")
            raise

    def _handle_stream(self, response) -> Generator[str, None, None]:
        """스트리밍 응답 처리"""
        for line in response.iter_lines():
            if line:
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> Generator[str, None, None]:
        """스트리밍 채팅"""
        return self.chat(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            **kwargs
        )

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False
    ) -> str:
        """텍스트 생성

        Args:
            prompt: 사용자 프롬프트
            system_prompt: 시스템 프롬프트
            max_tokens: 최대 토큰 수
            temperature: 온도
            stream: 스트리밍 여부

        Returns:
            생성된 텍스트
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        if stream:
            return self.chat_stream(messages, max_tokens, temperature)
        else:
            response = self.chat(messages, max_tokens, temperature)
            return response.get("choices", [{}])[0].get("message", {}).get("content", "")

    def get_models(self) -> List[Dict]:
        """사용 가능한 모델 목록"""
        try:
            response = requests.get(
                f"{self.config.base_url}/v1/models",
                headers=self.headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json().get("data", [])
        except Exception as e:
            logger.error(f"모델 목록 조회 실패: {e}")
            return []

    def health_check(self) -> bool:
        """서버 상태 확인"""
        try:
            models = self.get_models()
            return len(models) > 0
        except Exception:
            return False

    def generate_with_reasoning(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None
    ) -> ReasoningResult:
        """Reasoning Mode로 생성 (EXAONE <think> 태그 활용)

        Args:
            prompt: 사용자 프롬프트 (<think> 블록 포함 권장)
            system_prompt: 시스템 프롬프트
            max_tokens: 최대 토큰 수

        Returns:
            ReasoningResult: thinking, answer, raw_response 포함

        Note:
            - EXAONE 4.0.1 Reasoning Mode 권장 설정 적용
            - temperature=0.6, top_p=0.95
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Reasoning Mode 권장 파라미터
        # Phase 105: vLLM chat_template_kwargs로 enable_thinking 전달
        # Note: requests 직접 사용 시 chat_template_kwargs를 최상위에 포함
        payload = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": max_tokens or self.config.max_tokens,
            "temperature": 0.6,  # Reasoning Mode 권장
            "top_p": 0.95,       # Reasoning Mode 권장
            "chat_template_kwargs": {
                "enable_thinking": True  # EXAONE 4.0.1 추론 모드 활성화
            }
        }

        try:
            response = requests.post(
                f"{self.config.base_url}/v1/chat/completions",
                headers=self.headers,
                json=payload,
                timeout=self.config.timeout
            )
            response.raise_for_status()

            result = response.json()
            raw_content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

            # <think>...</think> 블록 파싱
            return self._parse_reasoning_response(raw_content)

        except requests.exceptions.Timeout:
            logger.error("Reasoning 요청 타임아웃")
            raise TimeoutError("Reasoning 요청이 시간 초과되었습니다.")
        except requests.exceptions.RequestException as e:
            logger.error(f"Reasoning 요청 오류: {e}")
            raise

    def _parse_reasoning_response(self, content: str) -> ReasoningResult:
        """<think> 태그에서 추론 과정과 답변 분리

        Args:
            content: LLM 응답 전체 텍스트

        Returns:
            ReasoningResult: 파싱된 결과
        """
        result = ReasoningResult(raw_response=content)

        # <think>...</think> 패턴 매칭
        think_pattern = r'<think>(.*?)</think>'
        think_match = re.search(think_pattern, content, re.DOTALL)

        if think_match:
            result.thinking = think_match.group(1).strip()
            # <think> 블록 이후의 텍스트가 답변
            result.answer = content[think_match.end():].strip()
        else:
            # <think> 없으면 전체가 답변
            result.answer = content.strip()

        return result


# 싱글톤 인스턴스
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """LLM 클라이언트 싱글톤"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


def create_llm_client(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None
) -> LLMClient:
    """커스텀 설정으로 LLM 클라이언트 생성"""
    config = LLMConfig()
    if base_url:
        config.base_url = base_url
    if api_key:
        config.api_key = api_key
    if model:
        config.model = model
    return LLMClient(config)


if __name__ == "__main__":
    # 테스트
    print("vLLM 클라이언트 테스트")

    client = get_llm_client()

    # 헬스 체크
    print(f"\n1. 서버 상태: {'정상' if client.health_check() else '오류'}")

    # 모델 목록
    print("\n2. 모델 목록:")
    models = client.get_models()
    for m in models:
        print(f"   - {m.get('id')}")

    # 간단한 생성 테스트
    print("\n3. 생성 테스트:")
    response = client.generate(
        prompt="안녕하세요, 간단히 자기소개 해주세요.",
        system_prompt="당신은 친절한 AI 어시스턴트입니다.",
        max_tokens=100,
        temperature=0.7
    )
    print(f"   응답: {response[:200]}...")
