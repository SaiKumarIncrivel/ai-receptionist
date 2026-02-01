"""
Claude API Client

Manages Anthropic API connections with async support, retry logic,
and model fallback capabilities for the Intelligence Layer.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from anthropic import AsyncAnthropic, APIError, RateLimitError, APIConnectionError

from app.config import settings

logger = logging.getLogger(__name__)


class ClaudeClientError(Exception):
    """Raised when Claude API call fails."""
    pass


@dataclass
class ClaudeResponse:
    """Response from Claude API."""
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str
    latency_ms: float


class ClaudeClient:
    """
    Async Claude API client wrapper.

    Features:
    - Async API calls
    - Automatic retries with exponential backoff
    - Model fallback (Haiku -> Sonnet)
    - Token counting
    """

    _instance: Optional["ClaudeClient"] = None

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Claude client.

        Args:
            api_key: Anthropic API key (defaults to settings)
        """
        self.api_key = api_key or settings.anthropic_api_key
        if not self.api_key:
            raise ValueError("Anthropic API key is required")

        self._client = AsyncAnthropic(api_key=self.api_key)
        self._default_model = settings.claude_intent_model
        self._fallback_model = settings.claude_fallback_model

        logger.info(f"ClaudeClient initialized with model={self._default_model}")

    @classmethod
    def get_instance(cls) -> "ClaudeClient":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (useful for testing)."""
        cls._instance = None

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        use_fallback_on_error: bool = True,
    ) -> ClaudeResponse:
        """
        Generate a response from Claude.

        Args:
            prompt: User message
            system_prompt: System prompt (optional)
            model: Model to use (defaults to intent model)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (0.0 for deterministic)
            use_fallback_on_error: Try fallback model on failure

        Returns:
            ClaudeResponse with generated content

        Raises:
            ClaudeClientError: If API call fails after retries
        """
        model = model or self._default_model
        start_time = time.time()

        messages = [{"role": "user", "content": prompt}]

        try:
            response = await self._call_with_retry(
                messages=messages,
                system=system_prompt,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            latency_ms = (time.time() - start_time) * 1000

            return ClaudeResponse(
                content=response.content[0].text,
                model=model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                stop_reason=response.stop_reason,
                latency_ms=latency_ms,
            )

        except Exception as e:
            if use_fallback_on_error and model != self._fallback_model:
                logger.warning(f"Primary model failed, trying fallback: {e}")
                return await self.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    model=self._fallback_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    use_fallback_on_error=False,
                )
            raise ClaudeClientError(f"Claude API call failed: {e}") from e

    async def _call_with_retry(
        self,
        messages: list[dict],
        system: Optional[str],
        model: str,
        max_tokens: int,
        temperature: float,
        max_retries: int = 3,
    ) -> Any:
        """Call API with exponential backoff retry."""
        last_error = None

        for attempt in range(max_retries):
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "messages": messages,
                }
                if system:
                    kwargs["system"] = system

                return await self._client.messages.create(**kwargs)

            except RateLimitError as e:
                last_error = e
                wait_time = 2 ** attempt
                logger.warning(f"Rate limited, waiting {wait_time}s (attempt {attempt + 1})")
                await asyncio.sleep(wait_time)

            except APIConnectionError as e:
                last_error = e
                wait_time = 2 ** attempt
                logger.warning(f"Connection error, retrying in {wait_time}s (attempt {attempt + 1})")
                await asyncio.sleep(wait_time)

            except APIError as e:
                logger.error(f"API error: {e}")
                raise

        raise last_error or ClaudeClientError("Max retries exceeded")

    async def close(self) -> None:
        """Close the client."""
        await self._client.close()


# Singleton accessor
async def get_claude_client() -> ClaudeClient:
    """Get Claude client singleton instance."""
    return ClaudeClient.get_instance()
