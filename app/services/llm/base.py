"""
Base classes for LLM providers.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from an LLM."""
    text: str
    tokens_used: int
    finish_reason: str  # "stop", "length", "error"
    model_name: str


class BaseLLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    Implement this class to add support for different Persian LLMs:
    - HuggingFace Transformers (GPT-2 Persian, Dorna, etc.)
    - GGUF models via llama-cpp-python
    - API-based models (if needed)
    """

    def __init__(self, model_path: str, device: str = "auto", **kwargs):
        self.model_path = model_path
        self.device = device
        self.model = None
        self.tokenizer = None
        self._is_loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    @abstractmethod
    def load_model(self) -> None:
        """Load the model into memory."""
        pass

    @abstractmethod
    def unload_model(self) -> None:
        """Unload the model from memory."""
        pass

    @abstractmethod
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
        """
        Generate a response from the model.

        Args:
            prompt: The input prompt
            max_new_tokens: Maximum tokens to generate
            temperature: Sampling temperature (higher = more creative)
            top_p: Nucleus sampling parameter
            top_k: Top-k sampling parameter
            repetition_penalty: Penalty for repeating tokens
            stop_sequences: Sequences that stop generation

        Returns:
            LLMResponse with generated text
        """
        pass

    def format_chat_prompt(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None
    ) -> str:
        """
        Format chat messages into a prompt string.
        Override this for model-specific chat formats.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."}
            system_prompt: Optional system prompt

        Returns:
            Formatted prompt string
        """
        prompt_parts = []

        if system_prompt:
            prompt_parts.append(f"سیستم: {system_prompt}\n\n")

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            if role == "user":
                prompt_parts.append(f"کاربر: {content}\n")
            elif role == "assistant":
                prompt_parts.append(f"دستیار: {content}\n")

        # Add prompt for assistant response
        prompt_parts.append("دستیار: ")

        return "".join(prompt_parts)

    def __enter__(self):
        self.load_model()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unload_model()
