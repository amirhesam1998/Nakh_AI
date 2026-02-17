"""
LLM Manager - Singleton manager for LLM providers.
"""
import logging
from pathlib import Path
from typing import Optional

from app.config import settings
from .base import BaseLLMProvider, LLMResponse
from .transformers_provider import TransformersProvider
from .gguf_provider import GGUFProvider

logger = logging.getLogger(__name__)


class LLMManager:
    """
    Singleton manager for LLM providers.

    Handles model loading, caching, and provider selection.

    Usage:
        manager = LLMManager()
        manager.initialize()  # Call once at startup

        response = manager.generate("سلام")
        # or
        response = manager.chat([
            {"role": "user", "content": "سلام"}
        ])
    """

    _instance: Optional["LLMManager"] = None
    _provider: Optional[BaseLLMProvider] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Only initialize once
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._system_prompt: Optional[str] = None

    @property
    def is_ready(self) -> bool:
        """Check if the LLM is loaded and ready."""
        return self._provider is not None and self._provider.is_loaded

    def initialize(
        self,
        model_path: Optional[str] = None,
        model_type: Optional[str] = None,
        device: Optional[str] = None,
        **kwargs
    ) -> None:
        """
        Initialize the LLM provider.

        Args:
            model_path: Path to model (local or HF hub)
            model_type: "transformers" or "gguf"
            device: "auto", "cpu", "cuda"
            **kwargs: Additional provider-specific arguments
        """
        # Use settings if not provided
        model_path = model_path or getattr(settings, "LLM_MODEL_PATH", None)
        model_type = model_type or getattr(settings, "LLM_MODEL_TYPE", "transformers")
        device = device or getattr(settings, "LLM_DEVICE", "auto")

        if not model_path:
            logger.warning(
                "No LLM_MODEL_PATH configured. Chat functionality will be disabled."
            )
            return

        logger.info(f"Initializing LLM: {model_path} (type: {model_type})")

        # Select provider based on model type
        if model_type == "gguf" or model_path.endswith(".gguf"):
            self._provider = GGUFProvider(
                model_path=model_path,
                device=device,
                **kwargs
            )
        else:
            self._provider = TransformersProvider(
                model_path=model_path,
                device=device,
                **kwargs
            )

        # Load the model
        self._provider.load_model()
        logger.info("LLM initialized successfully")

    def shutdown(self) -> None:
        """Unload the model and free resources."""
        if self._provider:
            self._provider.unload_model()
            self._provider = None
        logger.info("LLM manager shut down")

    def set_system_prompt(self, prompt: str) -> None:
        """Set the default system prompt for chat."""
        self._system_prompt = prompt

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        **kwargs
    ) -> LLMResponse:
        """
        Generate text from a raw prompt.

        Args:
            prompt: The input prompt
            max_new_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional generation parameters

        Returns:
            LLMResponse with generated text
        """
        if not self.is_ready:
            raise RuntimeError(
                "LLM not initialized. Call initialize() first or check LLM_MODEL_PATH."
            )

        return self._provider.generate(
            prompt=prompt,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            **kwargs
        )

    def chat(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        **kwargs
    ) -> LLMResponse:
        """
        Generate a chat response.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."}
            system_prompt: System prompt (uses default if not provided)
            max_new_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional generation parameters

        Returns:
            LLMResponse with generated text
        """
        if not self.is_ready:
            raise RuntimeError(
                "LLM not initialized. Call initialize() first or check LLM_MODEL_PATH."
            )

        # Use provided or default system prompt
        sys_prompt = system_prompt or self._system_prompt

        # Format messages into prompt
        prompt = self._provider.format_chat_prompt(messages, sys_prompt)

        # Generate response
        return self._provider.generate(
            prompt=prompt,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            stop_sequences=["کاربر:", "User:", "\n\n\n"],
            **kwargs
        )


# Global instance
llm_manager = LLMManager()
