"""Typed exceptions for inference backends.

Agents raise / propagate these instead of swallowing errors (see
`.cursor/rules/python-style.mdc`). Each backend owns a subclass of
``InferenceError`` so callers can branch on the source without introspecting
strings.
"""

from __future__ import annotations


class InferenceError(Exception):
    """Base class for any inference-backend failure."""


class StepfunError(InferenceError):
    """Stepfun (阶跃星辰) API call failed."""


class VlmJsonError(StepfunError):
    """The VLM returned a response that could not be parsed as JSON."""


class OllamaError(InferenceError):
    """Local Ollama API call failed."""


class ComfyUIError(InferenceError):
    """ComfyUI prompt submit / poll / fetch failed."""


class CudaDirtyError(ComfyUIError):
    """ComfyUI CUDA context is dirty (invalid argument / illegal memory access).

    Recoverable: restart ComfyUI and retry the render once.
    """


class NimError(InferenceError):
    """NVIDIA NIM (cloud) API call failed."""
