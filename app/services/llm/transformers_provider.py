"""
HuggingFace Transformers provider for Persian LLMs.

Supports models like:
- HooshvareLab/gpt2-fa
- m3hrdadfi/gpt2-persian
- Dorna models
- PersianLLaMA
- Any HF-compatible Persian model
"""
import logging
from typing import Optional

from .base import BaseLLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class TransformersProvider(BaseLLMProvider):
    """
    LLM provider using HuggingFace Transformers.

    Usage:
        provider = TransformersProvider(
            model_path="HooshvareLab/gpt2-fa",  # or local path
            device="cuda"  # or "cpu", "auto"
        )
        provider.load_model()
        response = provider.generate("سلام، چطور می‌توانم کمکتان کنم؟")
    """

    def __init__(
        self,
        model_path: str,
        device: str = "auto",
        torch_dtype: str = "auto",
        load_in_8bit: bool = False,
        load_in_4bit: bool = False,
        **kwargs
    ):
        super().__init__(model_path, device, **kwargs)
        self.torch_dtype = torch_dtype
        self.load_in_8bit = load_in_8bit
        self.load_in_4bit = load_in_4bit
        self._model_name = model_path.split("/")[-1]

    def load_model(self) -> None:
        """Load the model and tokenizer."""
        if self._is_loaded:
            logger.info(f"Model {self._model_name} already loaded")
            return

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            logger.info(f"Loading model: {self.model_path}")

            # Determine device
            if self.device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            else:
                device = self.device

            # Determine dtype
            if self.torch_dtype == "auto":
                dtype = torch.float16 if device == "cuda" else torch.float32
            elif self.torch_dtype == "float16":
                dtype = torch.float16
            elif self.torch_dtype == "bfloat16":
                dtype = torch.bfloat16
            else:
                dtype = torch.float32

            # Load tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_path,
                trust_remote_code=True
            )

            # Ensure pad token exists
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token

            # Load model with quantization options
            load_kwargs = {
                "trust_remote_code": True,
                "device_map": "auto" if device == "cuda" else None,
            }

            if self.load_in_8bit:
                load_kwargs["load_in_8bit"] = True
            elif self.load_in_4bit:
                load_kwargs["load_in_4bit"] = True
            else:
                load_kwargs["torch_dtype"] = dtype

            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                **load_kwargs
            )

            # Move to device if not using device_map
            if device != "cuda" or (not self.load_in_8bit and not self.load_in_4bit):
                if hasattr(self.model, "to"):
                    self.model = self.model.to(device)

            self.model.eval()
            self._device = device
            self._is_loaded = True

            logger.info(f"Model loaded successfully on {device}")

        except ImportError as e:
            logger.error(f"Missing dependency: {e}")
            raise ImportError(
                "Please install transformers: pip install transformers torch"
            ) from e
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise

    def unload_model(self) -> None:
        """Unload the model from memory."""
        if not self._is_loaded:
            return

        try:
            import torch
            import gc

            del self.model
            del self.tokenizer
            self.model = None
            self.tokenizer = None

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

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
        """Generate text from the model."""
        if not self._is_loaded:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        import torch

        try:
            # Tokenize input
            inputs = self.tokenizer(
                prompt,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=2048
            )

            # Move to device
            inputs = {k: v.to(self._device) for k, v in inputs.items()}
            input_length = inputs["input_ids"].shape[1]

            # Prepare generation config
            gen_kwargs = {
                "max_new_tokens": max_new_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "repetition_penalty": repetition_penalty,
                "do_sample": temperature > 0,
                "pad_token_id": self.tokenizer.pad_token_id,
                "eos_token_id": self.tokenizer.eos_token_id,
            }

            # Handle stop sequences
            if stop_sequences:
                stop_ids = []
                for seq in stop_sequences:
                    ids = self.tokenizer.encode(seq, add_special_tokens=False)
                    if ids:
                        stop_ids.extend(ids)
                if stop_ids:
                    gen_kwargs["eos_token_id"] = [
                        self.tokenizer.eos_token_id,
                        *stop_ids
                    ]

            # Generate
            with torch.no_grad():
                outputs = self.model.generate(**inputs, **gen_kwargs)

            # Decode only new tokens
            generated_ids = outputs[0][input_length:]
            generated_text = self.tokenizer.decode(
                generated_ids,
                skip_special_tokens=True
            )

            # Clean up stop sequences from output
            if stop_sequences:
                for seq in stop_sequences:
                    if seq in generated_text:
                        generated_text = generated_text.split(seq)[0]

            # Determine finish reason
            total_tokens = len(outputs[0])
            finish_reason = "stop"
            if len(generated_ids) >= max_new_tokens:
                finish_reason = "length"

            return LLMResponse(
                text=generated_text.strip(),
                tokens_used=total_tokens,
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
        Uses ChatML-style format if the model supports it,
        otherwise falls back to simple format.
        """
        # Check if tokenizer has chat template
        if hasattr(self.tokenizer, "apply_chat_template"):
            try:
                full_messages = []
                if system_prompt:
                    full_messages.append({
                        "role": "system",
                        "content": system_prompt
                    })
                full_messages.extend(messages)

                return self.tokenizer.apply_chat_template(
                    full_messages,
                    tokenize=False,
                    add_generation_prompt=True
                )
            except Exception:
                pass  # Fall back to simple format

        # Simple Persian format
        return super().format_chat_prompt(messages, system_prompt)
