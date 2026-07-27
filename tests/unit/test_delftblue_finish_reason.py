from __future__ import annotations

from types import SimpleNamespace

import torch

from src.llm_backends.base import LLMConfig
from src.llm_backends.delftblue_local_backend import DelftBlueLocalBackend


class _Inputs(dict):
    def __init__(self):
        self.input_ids = torch.tensor([[10, 11, 12]])
        super().__init__(input_ids=self.input_ids)

    def to(self, _device):
        return self


class _Tokenizer:
    eos_token_id = 2

    def __init__(self):
        self.decoded_ids = None

    def decode(self, ids, skip_special_tokens=True):
        self.decoded_ids = ids.tolist()
        return "generated only"


class _Model:
    device = "cpu"

    def __init__(self, generated):
        self.generated = generated
        self.generation_config = SimpleNamespace(
            eos_token_id=2,
            max_new_tokens=None,
            pad_token_id=None,
            do_sample=False,
            temperature=1.0,
            top_p=1.0,
            top_k=50,
        )

    def generate(self, **_kwargs):
        return torch.tensor([[10, 11, 12, *self.generated]])


def _run(generated: list[int], max_tokens: int):
    backend = DelftBlueLocalBackend(LLMConfig(model="fake", max_tokens=max_tokens))
    tokenizer = _Tokenizer()
    model = _Model(generated)
    backend._load_model = lambda: model
    backend._load_tokenizer = lambda: tokenizer
    backend._build_inputs = lambda **_kwargs: _Inputs()
    response = backend.generate(system="s", messages=[])
    return response, tokenizer


def test_decodes_only_new_tokens_and_reports_length_limit() -> None:
    response, tokenizer = _run([7, 8], max_tokens=2)
    assert tokenizer.decoded_ids == [7, 8]
    assert response.content == "generated only"
    assert response.output_tokens == 2
    assert response.finish_reason == "length"


def test_eos_completion_reports_stop_even_at_limit() -> None:
    response, _ = _run([7, 2], max_tokens=2)
    assert response.finish_reason == "stop"
