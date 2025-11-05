"""Embedding backend selection for torch-based models."""

from __future__ import annotations

import io
import logging
import os
from functools import lru_cache
from typing import Dict, Iterable, List

from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True



def _backend_choice(
    explicit: str | None, env_var: str, fallback_env: str, default: str
) -> str:
    if explicit:
        return explicit.lower()
    value = os.getenv(env_var)
    if value:
        return value.lower()
    value = os.getenv(fallback_env)
    if value:
        return value.lower()
    return default


def _load_torch_modules():
    import torch  # type: ignore
    import torch.nn.functional as F  # type: ignore
    from transformers import (  # type: ignore
        AutoImageProcessor,
        AutoModel,
        AutoProcessor,
        Dinov2Model,
    )
    from transformers.utils import logging as hf_logging  # type: ignore

    hf_logging.set_verbosity_error()

    return torch, F, AutoModel, AutoProcessor, Dinov2Model, AutoImageProcessor


@lru_cache(maxsize=1)
def _load_metaclip_bundle(
    model_name: str, device: str, use_bfloat16: bool
) -> tuple:
    torch, F, AutoModel, AutoProcessor, _, _ = _load_torch_modules()
    kwargs = {"attn_implementation": "sdpa"}
    if use_bfloat16 and device.startswith("cuda"):
        kwargs["dtype"] = torch.bfloat16
    model = AutoModel.from_pretrained(model_name, **kwargs).to(device).eval()
    processor = AutoProcessor.from_pretrained(model_name)
    return model, processor, torch, F


@lru_cache(maxsize=1)
def _load_dinov2_bundle(
    model_name: str, device: str, use_float16: bool
) -> tuple:
    torch, F, _, _, Dinov2Model, AutoImageProcessor = _load_torch_modules()
    kwargs = {}
    if use_float16 and device.startswith("cuda"):
        kwargs["dtype"] = torch.float16
    model = Dinov2Model.from_pretrained(model_name, **kwargs).to(device).eval()
    processor = AutoImageProcessor.from_pretrained(model_name)
    return model, processor, torch, F


class _TorchImageBackend:
    def __init__(
        self,
        metaclip_name: str,
        dinov2_name: str,
        device: str,
        use_bfloat16: bool,
        use_float16: bool,
    ) -> None:
        self._metaclip, self._metaclip_processor, torch, F = _load_metaclip_bundle(
            metaclip_name, device, use_bfloat16
        )
        self._dinov2, self._dinov2_processor, _, _ = _load_dinov2_bundle(
            dinov2_name, device, use_float16
        )
        self._torch = torch
        self._F = F
        self._device = device

    def _prepare_images(self, images: Iterable[bytes]) -> List[Image.Image]:
        pil_images: List[Image.Image] = []
        for data in images:
            if not data:
                raise ValueError("Image bytes are empty")
            try:
                with Image.open(io.BytesIO(data)) as img:
                    pil_images.append(img.convert("RGB"))
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "Failed to load image in batch: %s", exc
                )
                pil_images.append(Image.new("RGB", (1, 1), color=(255, 255, 255)))
        return pil_images

    def encode(self, image_bytes: bytes) -> Dict[str, List[float]]:
        results = self.encode_batch([image_bytes])
        if not results:
            raise RuntimeError("Torch image backend failed to encode image bytes")
        return results[0]

    def encode_batch(self, images: Iterable[bytes]) -> List[Dict[str, List[float]]]:
        pil_images = self._prepare_images(images)
        if not pil_images:
            return []

        meta_inputs = self._metaclip_processor(images=pil_images, return_tensors="pt")
        meta_inputs = {k: v.to(self._device) for k, v in meta_inputs.items()}
        with self._torch.no_grad():
            meta_features = self._metaclip.get_image_features(**meta_inputs)
        meta_features = self._F.normalize(meta_features, dim=-1).cpu().to(self._torch.float32)

        dino_inputs = self._dinov2_processor(images=pil_images, return_tensors="pt")
        dino_inputs = {k: v.to(self._device) for k, v in dino_inputs.items()}
        with self._torch.no_grad():
            dino_outputs = self._dinov2(**dino_inputs)
        dino_features = self._F.normalize(
            dino_outputs.pooler_output, dim=-1
        ).cpu().to(self._torch.float32)

        results: List[Dict[str, List[float]]] = []
        for idx in range(meta_features.shape[0]):
            results.append(
                {
                    "metaclip": meta_features[idx].tolist(),
                    "dino": dino_features[idx].tolist(),
                }
            )
        return results


class _TorchTextBackend:
    def __init__(
        self,
        metaclip_name: str,
        device: str,
        use_bfloat16: bool,
    ) -> None:
        (
            self._metaclip,
            self._metaclip_processor,
            self._torch,
            self._F,
        ) = _load_metaclip_bundle(metaclip_name, device, use_bfloat16)
        self._device = device
        config = getattr(self._metaclip, "config", None)
        text_config = getattr(config, "text_config", None)
        self._max_length = getattr(text_config, "max_position_embeddings", 77)

    def _encode(self, text: str) -> List[float]:
        prompt = text if text.strip() else " "
        inputs = self._metaclip_processor(
            text=[prompt],
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=self._max_length,
        )
        inputs = {k: v.to(self._device) for k, v in inputs.items()}
        with self._torch.no_grad():
            feats = self._metaclip.get_text_features(**inputs)
        feats = self._F.normalize(feats, dim=-1).cpu().to(self._torch.float32)
        return feats.squeeze(0).tolist()

    def encode_text(self, text: str) -> List[float]:
        return self._encode(text)

    def encode_prompt(self, text: str) -> List[float]:
        return self._encode(text)

    def encode_batch(self, texts: Iterable[str]) -> List[List[float]]:
        cleaned = [text if text.strip() else " " for text in texts]
        if not cleaned:
            return []
        inputs = self._metaclip_processor(
            text=cleaned,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=self._max_length,
        )
        inputs = {k: v.to(self._device) for k, v in inputs.items()}
        with self._torch.no_grad():
            feats = self._metaclip.get_text_features(**inputs)
        feats = self._F.normalize(feats, dim=-1).cpu().to(self._torch.float32)
        return [row.tolist() for row in feats]

    def encode_prompt_batch(self, texts: Iterable[str]) -> List[List[float]]:
        return self.encode_batch(texts)


def get_image_backend(kind: str | None = None) -> object:
    choice = _backend_choice(kind, "IMAGE_EMBED_BACKEND", "EMBED_BACKEND", "torch")
    if choice != "torch":
        raise RuntimeError(
            "Unsupported IMAGE_EMBED_BACKEND value. Only 'torch' is allowed; "
            "remove legacy hashed settings and ensure torch models are available."
        )

    device = os.getenv("EMBED_DEVICE")
    if not device:
        try:
            import torch  # type: ignore
        except ImportError as exc:  # pragma: no cover - configuration issue
            raise RuntimeError(
                "Torch image backend requires PyTorch. Install torch or set EMBED_DEVICE explicitly."
            ) from exc
        device = "cuda" if torch.cuda.is_available() else "cpu"

    metaclip_name = os.getenv("METACLIP_MODEL_NAME", "facebook/metaclip-2-worldwide-giant")
    dinov2_name = os.getenv("DINOV2_MODEL_NAME", "facebook/dinov2-giant")
    use_bfloat16 = os.getenv("METACLIP_DTYPE", "bfloat16").lower() in {"bf16", "bfloat16"}
    use_float16 = os.getenv("DINOV2_DTYPE", "float16").lower() in {"float16", "fp16", "half"}
    return _TorchImageBackend(metaclip_name, dinov2_name, device, use_bfloat16, use_float16)


def get_text_backend(kind: str | None = None) -> object:
    choice = _backend_choice(kind, "TEXT_EMBED_BACKEND", "EMBED_BACKEND", "torch")
    if choice != "torch":
        raise RuntimeError(
            "Unsupported TEXT_EMBED_BACKEND value. Only 'torch' is allowed; "
            "remove legacy hashed settings and ensure torch models are available."
        )

    device = os.getenv("EMBED_DEVICE")
    if not device:
        try:
            import torch  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Torch text backend requires PyTorch. Install torch or set EMBED_DEVICE explicitly."
            ) from exc
        device = "cuda" if torch.cuda.is_available() else "cpu"

    metaclip_name = os.getenv("METACLIP_MODEL_NAME", "facebook/metaclip-2-worldwide-giant")
    use_bfloat16 = os.getenv("METACLIP_DTYPE", "bfloat16").lower() in {"bf16", "bfloat16"}
    return _TorchTextBackend(metaclip_name, device, use_bfloat16)
