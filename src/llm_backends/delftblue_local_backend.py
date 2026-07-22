"""
DelftBlue local HuggingFace backend.

This backend is designed for local inference on DelftBlue GPU nodes where models
are pre-cached in /scratch and internet access is disabled during jobs.

Supports:
- FP16 inference (default, best quality)
- Optional 4-bit quantization via bitsandbytes (NF4)

Environment (recommended in SLURM jobs):
    HF_HOME=/scratch/$USER/models
    TRANSFORMERS_CACHE=/scratch/$USER/models/hub
    HF_HUB_OFFLINE=1
"""

from __future__ import annotations

from copy import deepcopy
import os
import time
from typing import Any

import torch

from .base import LLMBackend, LLMConfig, LLMError, LLMResponse


class DelftBlueLocalBackend(LLMBackend):
    """Local HuggingFace backend for DelftBlue GPU inference.

    Configuration uses `LLMConfig.extra` for local-specific options:
      - `quantization`: "fp16" (default) or "4bit"
      - `local_files_only`: bool (default: True)
      - `trust_remote_code`: bool (default: True)
      - `device_map`: str | dict (default: "auto")
      - `top_p`: float (default: 0.9)
      - `do_sample`: bool (default: False when temperature=0, else True)
      - `bnb_4bit_quant_type`: str (default: "nf4")
      - `bnb_4bit_use_double_quant`: bool (default: True)
      - `bnb_4bit_compute_dtype`: "float16" | "bfloat16" (default: "float16")
    """

    def __init__(self, config: LLMConfig):
        super().__init__(config)

        self._model = None
        self._tokenizer = None

        self._quantization = str(config.extra.get("quantization", "fp16")).lower()
        self._local_files_only = bool(config.extra.get("local_files_only", True))
        self._trust_remote_code = bool(config.extra.get("trust_remote_code", True))
        self._device_map = config.extra.get("device_map", "auto")

        if self._quantization not in {"fp16", "4bit"}:
            raise LLMError(
                f"Unsupported quantization '{self._quantization}'. "
                "Use 'fp16' or '4bit'."
            )

    @property
    def provider_name(self) -> str:
        return "DelftBlueLocalHF"

    def is_available(self) -> bool:
        """Check if model is accessible from local cache and CUDA is available."""
        if not torch.cuda.is_available():
            return False

        try:
            from transformers import AutoConfig  # type: ignore

            AutoConfig.from_pretrained(
                self.config.model,
                local_files_only=self._local_files_only,
                trust_remote_code=self._trust_remote_code,
            )
            return True
        except Exception:
            return False

    def _load_tokenizer(self):
        if self._tokenizer is not None:
            return self._tokenizer

        try:
            from transformers import AutoTokenizer  # type: ignore

            self._tokenizer = AutoTokenizer.from_pretrained(
                self.config.model,
                local_files_only=self._local_files_only,
                trust_remote_code=self._trust_remote_code,
            )
            return self._tokenizer
        except Exception as e:
            raise LLMError(f"Failed to load tokenizer for {self.config.model}: {e}")

    def _load_model(self):
        if self._model is not None:
            return self._model

        try:
            from transformers import AutoModelForCausalLM  # type: ignore
            from transformers.utils import logging as transformers_logging  # type: ignore

            kwargs: dict[str, Any] = {
                "device_map": self._device_map,
                "local_files_only": self._local_files_only,
                "trust_remote_code": self._trust_remote_code,
            }

            if self._quantization == "fp16":
                kwargs["dtype"] = torch.float16
            else:
                from transformers import BitsAndBytesConfig  # type: ignore

                compute_dtype_str = str(
                    self.config.extra.get("bnb_4bit_compute_dtype", "float16")
                ).lower()
                compute_dtype = (
                    torch.bfloat16 if compute_dtype_str == "bfloat16" else torch.float16
                )

                kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type=self.config.extra.get("bnb_4bit_quant_type", "nf4"),
                    bnb_4bit_use_double_quant=bool(
                        self.config.extra.get("bnb_4bit_use_double_quant", True)
                    ),
                    bnb_4bit_compute_dtype=compute_dtype,
                )

            # Suppress the very verbose Transformers tqdm progress bar in SLURM logs.
            try:
                transformers_logging.disable_progress_bar()
            except Exception:
                pass

            print(f"   Loading model weights ({self._quantization})...", flush=True)
            _load_start = time.perf_counter()
            self._model = AutoModelForCausalLM.from_pretrained(self.config.model, **kwargs)
            _load_elapsed = time.perf_counter() - _load_start
            print(f"   ✅ Model loaded in {_load_elapsed:.1f}s", flush=True)
            return self._model

        except Exception as e:
            raise LLMError(
                f"Failed to load model '{self.config.model}' "
                f"(quantization={self._quantization}): {e}"
            )

    @staticmethod
    def _flatten_system(system: str | list[dict]) -> str:
        if isinstance(system, list):
            return "\n".join(
                block.get("text", "")
                for block in system
                if isinstance(block, dict) and "text" in block
            )
        return system

    def _build_inputs(self, system: str | list[dict], messages: list[dict]):
        tokenizer = self._load_tokenizer()
        model = self._load_model()

        all_messages = []
        system_text = self._flatten_system(system)
        if system_text:
            all_messages.append({"role": "system", "content": system_text})
        all_messages.extend(messages)

        try:
            text = tokenizer.apply_chat_template(
                all_messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception:
            # Fallback if chat template is unavailable
            text = ""
            for msg in all_messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                text += f"[{role}]\n{content}\n\n"
            text += "[assistant]\n"

        inputs = tokenizer(text, return_tensors="pt")
        return inputs.to(model.device)

    def generate(
        self,
        system: str | list[dict],
        messages: list[dict],
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a response from a locally loaded HuggingFace model."""
        start_time = time.perf_counter()

        # Enforce offline mode by default on HPC compute nodes
        os.environ.setdefault("HF_HUB_OFFLINE", "1")

        model = self._load_model()
        tokenizer = self._load_tokenizer()
        inputs = self._build_inputs(system=system, messages=messages)

        input_tokens = int(inputs.input_ids.shape[1])

        temperature = float(kwargs.get("temperature", self.config.temperature))
        max_new_tokens = int(kwargs.get("max_tokens", self.config.max_tokens))
        top_p = float(kwargs.get("top_p", self.config.extra.get("top_p", 0.9)))
        do_sample = bool(
            kwargs.get(
                "do_sample",
                self.config.extra.get("do_sample", temperature > 0.0),
            )
        )

        if temperature <= 0.0:
            temperature = 1.0
            do_sample = False

        try:
            generation_config = deepcopy(model.generation_config)
            generation_config.max_new_tokens = max_new_tokens
            generation_config.pad_token_id = tokenizer.eos_token_id
            generation_config.do_sample = do_sample

            if do_sample:
                generation_config.temperature = temperature
                generation_config.top_p = top_p
            else:
                # Reset sampling-only fields to greedy defaults so Transformers
                # does not warn that they are invalid / ignored.
                generation_config.temperature = 1.0
                generation_config.top_p = 1.0
                generation_config.top_k = 50

            generation_kwargs: dict[str, Any] = {
                **inputs,
                "generation_config": generation_config,
            }

            with torch.no_grad():
                outputs = model.generate(**generation_kwargs)

            generated_ids = outputs[0, input_tokens:]
            output_tokens = int(generated_ids.shape[0])
            content = tokenizer.decode(generated_ids, skip_special_tokens=True)

            eos_value = generation_config.eos_token_id
            if eos_value is None:
                eos_value = tokenizer.eos_token_id
            eos_ids = (
                {int(token_id) for token_id in eos_value}
                if isinstance(eos_value, (list, tuple, set))
                else ({int(eos_value)} if eos_value is not None else set())
            )
            generated_token_ids = [int(token_id) for token_id in generated_ids.tolist()]
            hit_eos = bool(eos_ids.intersection(generated_token_ids))
            finish_reason = (
                "length" if output_tokens >= max_new_tokens and not hit_eos else "stop"
            )

            latency_ms = (time.perf_counter() - start_time) * 1000

            return LLMResponse(
                content=content.strip(),
                model=self.config.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                finish_reason=finish_reason,
                raw_response={
                    "quantization": self._quantization,
                    "device": str(getattr(model, "device", "unknown")),
                    "do_sample": do_sample,
                    "top_p": top_p,
                    "max_new_tokens": max_new_tokens,
                    "hit_eos": hit_eos,
                },
            )
        except Exception as e:
            raise LLMError(f"Local generation failed for model {self.config.model}: {e}")


def create_delftblue_local_backend(
    model: str = "Qwen/Qwen2.5-Coder-32B-Instruct",
    quantization: str = "fp16",
    **kwargs: Any,
) -> DelftBlueLocalBackend:
    """Convenience factory for DelftBlue local backend.

    Args:
        model: HuggingFace model id.
        quantization: "fp16" or "4bit".
        **kwargs: Other LLMConfig fields. `extra` can be provided/extended.
    """
    extra = dict(kwargs.pop("extra", {}))
    extra.setdefault("quantization", quantization)

    config = LLMConfig(model=model, extra=extra, **kwargs)
    return DelftBlueLocalBackend(config)
