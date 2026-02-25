"""
Ollama LLM provider — calls a local Ollama server via its HTTP API.
"""
import logging
from typing import Optional

import httpx

from .base import BaseLLMProvider, LLMResponse

logger = logging.getLogger(__name__)

# Generous timeout: CPU inference on large models can be slow.
_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)


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
    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 50,
        repetition_penalty: float = 1.1,
        stop_sequences: Optional[list[str]] = None,
    ) -> LLMResponse:
        if not self._client:
            raise RuntimeError("OllamaProvider not loaded. Call load_model() first.")

        payload: dict = {
            "model": self.model_path,
            "prompt": prompt,
            "stream": False,
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

        try:
            resp = self._client.post("/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()

            text = data.get("response", "").strip()
            tokens = data.get("eval_count", 0)
            done_reason = data.get("done_reason", "stop")

            return LLMResponse(
                text=text,
                tokens_used=tokens,
                finish_reason=done_reason,
                model_name=self.model_path,
            )

        except httpx.HTTPError as exc:
            logger.error("Ollama generation failed: %s", exc)
            return LLMResponse(
                text="",
                tokens_used=0,
                finish_reason="error",
                model_name=self.model_path,
            )
