"""
Ollama LLM provider — calls a local Ollama server via its HTTP API.

Uses /api/chat (chat completion with roles) instead of /api/generate
because instruct-tuned models perform significantly better when given
system + user message roles rather than a raw prompt string.
"""
import json
import logging
from typing import Iterator, Optional

import httpx

from app.config import settings
from .base import BaseLLMProvider, LLMResponse

logger = logging.getLogger(__name__)

# Generous timeout: CPU inference on large models can be slow.
_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=10.0, pool=10.0)


def _split_prompt(prompt: str) -> tuple[str, str]:
    """Heuristically split a raw prompt into (system, user).

    Convention: everything before the first '\\n---' line is the system
    message. Kept for backward compatibility when no explicit system_prompt is
    passed.
    """
    system_msg = ""
    user_msg = prompt
    separator_idx = prompt.find("\n---")
    if separator_idx > 0:
        system_msg = prompt[:separator_idx].strip()
        user_msg = prompt[separator_idx:].strip()
    elif "\n\n" in prompt:
        first_break = prompt.index("\n\n")
        if first_break < 500:
            system_msg = prompt[:first_break].strip()
            user_msg = prompt[first_break:].strip()
    return system_msg, user_msg


class OllamaProvider(BaseLLMProvider):
    """
    LLM provider that delegates generation to a running Ollama instance.

    Requires `ollama serve` to be running (default http://localhost:11434).
    """

    def __init__(
        self,
        model_path: str,
        device: str = "auto",
        ollama_base_url: str = "http://localhost:11434",
        **kwargs,
    ):
        super().__init__(model_path=model_path, device=device, **kwargs)
        self.base_url = ollama_base_url.rstrip("/")
        self._client: Optional[httpx.Client] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def load_model(self) -> None:
        """Validate that Ollama is reachable and the requested model exists."""
        self._client = httpx.Client(base_url=self.base_url, timeout=_TIMEOUT)
        try:
            resp = self._client.get("/api/tags")
            resp.raise_for_status()
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            # Ollama may store as "model:tag" — accept a prefix match
            found = any(
                m == self.model_path or m.startswith(self.model_path + ":")
                for m in models
            )
            if not found:
                logger.warning(
                    "Model '%s' not found in Ollama. Available: %s. "
                    "Generation will fail until the model is pulled.",
                    self.model_path,
                    models,
                )
            else:
                logger.info("Ollama provider ready — model '%s'", self.model_path)
            self._is_loaded = True
        except httpx.HTTPError as exc:
            logger.error("Cannot reach Ollama at %s: %s", self.base_url, exc)
            raise RuntimeError(
                f"Ollama server unreachable at {self.base_url}. "
                "Is `ollama serve` running?"
            ) from exc

    def unload_model(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
        self._is_loaded = False
        logger.info("Ollama provider shut down")

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    @property
    def supports_streaming(self) -> bool:
        return True

    def _build_payload(
        self,
        prompt: str,
        max_new_tokens: int,
        temperature: float,
        top_p: float,
        top_k: int,
        repetition_penalty: float,
        stop_sequences: Optional[list[str]],
        system_prompt: Optional[str],
        stream: bool,
    ) -> dict:
        """Build the /api/chat payload.

        When an explicit ``system_prompt`` is supplied it is used verbatim and
        the entire ``prompt`` becomes the user message. A stable system message
        across calls lets Ollama reuse the cached prompt prefix (KV cache),
        cutting latency on the large, unchanging stylist/fabric knowledge block.
        """
        if system_prompt is not None:
            system_msg, user_msg = system_prompt, prompt
        else:
            system_msg, user_msg = _split_prompt(prompt)

        messages = []
        if system_msg:
            messages.append({"role": "system", "content": system_msg})
        messages.append({"role": "user", "content": user_msg})

        payload: dict = {
            "model": self.model_path,
            "messages": messages,
            "stream": stream,
            "keep_alive": getattr(settings, "llm_keep_alive", "30m"),
            "options": {
                "num_predict": max_new_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "repeat_penalty": repetition_penalty,
            },
        }
        if stop_sequences:
            payload["options"]["stop"] = stop_sequences
        return payload

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 50,
        repetition_penalty: float = 1.1,
        stop_sequences: Optional[list[str]] = None,
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        """Generate text using Ollama's /api/chat endpoint."""
        if not self._client:
            raise RuntimeError("OllamaProvider not loaded. Call load_model() first.")

        payload = self._build_payload(
            prompt, max_new_tokens, temperature, top_p, top_k,
            repetition_penalty, stop_sequences, system_prompt, stream=False,
        )

        try:
            resp = self._client.post("/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

            text = (data.get("message") or {}).get("content", "").strip()
            tokens = data.get("eval_count", 0)
            done_reason = data.get("done_reason", "stop")

            return LLMResponse(
                text=text,
                tokens_used=tokens,
                finish_reason=done_reason,
                model_name=self.model_path,
            )

        except httpx.HTTPError as exc:
            logger.error("Ollama chat generation failed: %s", exc)
            return LLMResponse(
                text="",
                tokens_used=0,
                finish_reason="error",
                model_name=self.model_path,
            )

    def generate_stream(
        self,
        prompt: str,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        stop_sequences: Optional[list[str]] = None,
        system_prompt: Optional[str] = None,
        top_p: float = 0.9,
        top_k: int = 50,
        repetition_penalty: float = 1.1,
        **kwargs,
    ) -> Iterator[str]:
        """Yield content deltas from Ollama's streaming /api/chat endpoint.

        This is a *synchronous* generator (Ollama client is sync httpx). The API
        layer adapts it to an async SSE stream via a threadpool iterator.
        """
        if not self._client:
            raise RuntimeError("OllamaProvider not loaded. Call load_model() first.")

        payload = self._build_payload(
            prompt, max_new_tokens, temperature, top_p, top_k,
            repetition_penalty, stop_sequences, system_prompt, stream=True,
        )

        try:
            with self._client.stream("POST", "/api/chat", json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    delta = (chunk.get("message") or {}).get("content", "")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        break
        except httpx.HTTPError as exc:
            logger.error("Ollama streaming generation failed: %s", exc)
            return
