"""
GGUF model provider using llama-cpp-python.

Supports quantized models for efficient inference:
- Persian LLaMA GGUF
- Dorna GGUF
- Any GGUF-format Persian model
"""
import logging
from typing import Optional

from .base import BaseLLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class GGUFProvider(BaseLLMProvider):
    """
    LLM provider using llama-cpp-python for GGUF models.

    Usage:
        provider = GGUFProvider(
            model_path="/path/to/model.gguf",
            n_ctx=4096,
            n_gpu_layers=35  # GPU acceleration
        )
        provider.load_model()
        response = provider.generate("سلام")
    """

    def __init__(
        self,
        model_path: str,
        device: str = "auto",
        n_ctx: int = 4096,
        n_gpu_layers: int = -1,  # -1 = all layers on GPU
        n_threads: Optional[int] = None,
        verbose: bool = False,
        **kwargs
    ):
        super().__init__(model_path, device, **kwargs)
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.n_threads = n_threads
        self.verbose = verbose
        self._model_name = model_path.split("/")[-1].split("\\")[-1]

    def load_model(self) -> None:
        """Load the GGUF model."""
        if self._is_loaded:
            logger.info(f"Model {self._model_name} already loaded")
            return

        try:
            from llama_cpp import Llama

            logger.info(f"Loading GGUF model: {self.model_path}")

            # Determine GPU layers
            n_gpu = self.n_gpu_layers
            if self.device == "cpu":
                n_gpu = 0
            elif self.device == "auto":
                # Try to use GPU if available
                try:
                    import torch
                    if not torch.cuda.is_available():
                        n_gpu = 0
                except ImportError:
                    n_gpu = 0

            load_kwargs = {
                "model_path": self.model_path,
                "n_ctx": self.n_ctx,
                "n_gpu_layers": n_gpu,
                "verbose": self.verbose,
            }

            if self.n_threads:
                load_kwargs["n_threads"] = self.n_threads

            self.model = Llama(**load_kwargs)
            self._is_loaded = True

            logger.info(f"GGUF model loaded (GPU layers: {n_gpu})")

        except ImportError as e:
            logger.error(f"Missing dependency: {e}")
            raise ImportError(
                "Please install llama-cpp-python: "
                "pip install llama-cpp-python\n"
                "For GPU support: CMAKE_ARGS=\"-DLLAMA_CUDA=on\" pip install llama-cpp-python"
            ) from e
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise

    def unload_model(self) -> None:
        """Unload the model from memory."""
        if not self._is_loaded:
            return

        try:
            import gc

            del self.model
            self.model = None
            gc.collect()

            self._is_loaded = False
            logger.info(f"Model {self._model_name} unloaded")

        except Exception as e:
            logger.error(f"Error unloading model: {e}")

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 50,
        repetition_penalty: float = 1.1,
        stop_sequences: Optional[list[str]] = None,
        system_prompt: Optional[str] = None,  # accepted for API parity; unused
    ) -> LLMResponse:
        """Generate text from the GGUF model."""
        if not self._is_loaded:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        try:
            # Prepare stop sequences
            stop = stop_sequences or []
            # Add common Persian stop patterns
            stop.extend(["کاربر:", "\nکاربر:", "User:", "\nUser:"])

            output = self.model(
                prompt,
                max_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                repeat_penalty=repetition_penalty,
                stop=stop,
                echo=False
            )

            generated_text = output["choices"][0]["text"]
            finish_reason = output["choices"][0].get("finish_reason", "stop")
            tokens_used = output.get("usage", {}).get("total_tokens", 0)

            return LLMResponse(
                text=generated_text.strip(),
                tokens_used=tokens_used,
                finish_reason=finish_reason,
                model_name=self._model_name
            )

        except Exception as e:
            logger.error(f"Generation error: {e}")
            return LLMResponse(
                text="",
                tokens_used=0,
                finish_reason="error",
                model_name=self._model_name
            )

    def format_chat_prompt(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None
    ) -> str:
        """
        Format messages for chat.
        Uses Llama-2 style format for compatibility.
        """
        prompt_parts = []

        # System prompt in Llama format
        if system_prompt:
            prompt_parts.append(f"<<SYS>>\n{system_prompt}\n<</SYS>>\n\n")

        # Build conversation
        for i, msg in enumerate(messages):
            role = msg["role"]
            content = msg["content"]

            if role == "user":
                if i == 0 and system_prompt:
                    prompt_parts.append(f"[INST] {content} [/INST]")
                else:
                    prompt_parts.append(f"[INST] {content} [/INST]")
            elif role == "assistant":
                prompt_parts.append(f" {content} ")

        return "".join(prompt_parts)
