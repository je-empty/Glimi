"""Glimi profile image generator — Animagine XL 4.0 + Glimi Style LoRA.

Public API:
    generate_profile(prompt, full_path, crop_path, version="v3", seed=42, ...)

The pipeline is held as a singleton (lazy-loaded). On a fresh M3 base / 24GB,
first call: ~30-60s warm-up + ~6 min/image. Subsequent calls: ~6 min/image.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional, Literal
import gc

import torch
from diffusers import StableDiffusionXLPipeline, EulerAncestralDiscreteScheduler

from .crop import crop_1x1

PKG = Path(__file__).parent
LORA_PATHS = {
    "v2": PKG / "loras" / "glimi_style_v2.safetensors",
    "v3": PKG / "loras" / "glimi_style_v3.safetensors",
}

BASE_MODEL = "cagliostrolab/animagine-xl-4.0"
TRIGGER = "glimistyle"

# Wrapper template — caller supplies CHARACTER_BLOCK
QUALITY_PREFIX = "masterpiece, high score, great score, absurdres, best quality"
STYLE_SUFFIX = (
    "clean delicate thin lineart, soft cel shading, "
    "bust-up portrait, wholesome slice-of-life anime, "
    "centered composition, face at center, symmetric framing"
)
DEFAULT_NEGATIVE = (
    "lowres, bad anatomy, blurry, realistic, photo, 3d, full body, "
    "multiple people, watermark, signature, cropped, "
    "cleavage, voluptuous, sexy, mature female, glamorous, thick lipstick, "
    "heavy makeup, big sparkly eyes, chunky hair highlights, dramatic shading, "
    "side angle, hair covering eye, worst quality, low quality"
)

# Native SDXL portrait bucket — 832×1216 fits M3 24GB with QA running
DEFAULT_W, DEFAULT_H = 832, 1216
DEFAULT_STEPS = 30
DEFAULT_CFG = 5.0
DEFAULT_LORA_SCALE = 1.0
DEFAULT_CROP_SIZE = 1024


class GlimiImageGen:
    """Lazy-loaded singleton wrapper. Reuse across multiple generations."""

    _instances: dict = {}

    def __init__(self, version: Literal["v2", "v3"] = "v3"):
        if version not in LORA_PATHS:
            raise ValueError(f"version must be 'v2' or 'v3', got {version!r}")
        lora = LORA_PATHS[version]
        if not lora.exists():
            raise FileNotFoundError(
                f"LoRA weights missing at {lora}. "
                f"Re-install glimi_imagegen package or copy from training output."
            )
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        dtype = torch.float16 if device == "mps" else torch.float32
        pipe = StableDiffusionXLPipeline.from_pretrained(
            BASE_MODEL, torch_dtype=dtype, use_safetensors=True
        )
        pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)
        pipe.load_lora_weights(str(lora))
        pipe.fuse_lora(lora_scale=DEFAULT_LORA_SCALE)
        pipe = pipe.to(device)
        pipe.set_progress_bar_config(disable=True)
        self.pipe = pipe
        self.version = version
        self.device = device

    @classmethod
    def get(cls, version: Literal["v2", "v3"] = "v3") -> "GlimiImageGen":
        if version not in cls._instances:
            cls._instances[version] = cls(version)
        return cls._instances[version]

    @classmethod
    def unload(cls, version: Optional[str] = None):
        if version is None:
            cls._instances.clear()
        else:
            cls._instances.pop(version, None)
        gc.collect()
        if torch.backends.mps.is_available() and hasattr(torch.mps, "empty_cache"):
            torch.mps.empty_cache()

    def build_prompt(self, character_block: str) -> str:
        """Wrap caller's character description with quality + trigger + style suffix."""
        return f"{QUALITY_PREFIX}, {TRIGGER}, {character_block}, {STYLE_SUFFIX}"

    def generate(
        self,
        prompt: str,
        full_path: str | Path,
        crop_path: str | Path,
        seed: int = 42,
        width: int = DEFAULT_W,
        height: int = DEFAULT_H,
        steps: int = DEFAULT_STEPS,
        guidance_scale: float = DEFAULT_CFG,
        negative_prompt: Optional[str] = None,
        crop_target_size: int = DEFAULT_CROP_SIZE,
        wrap_prompt: bool = True,
    ) -> dict:
        """Generate full + crop and write both to disk.

        Args:
            prompt: character description. If wrap_prompt=True (default), this is
                the CHARACTER BLOCK only — quality / trigger / style suffix are
                added automatically. If False, used verbatim.
            full_path: where to save the 832×1216 (or width×height) full portrait.
            crop_path: where to save the 1024² (or crop_target_size) face crop.
            seed: integer seed for reproducible output.
            wrap_prompt: True → wrap with QUALITY + TRIGGER + STYLE_SUFFIX.
                False → caller fully controls prompt.

        Returns:
            dict with keys: full_path, crop_path, crop_method, prompt, seed, version.
        """
        full_path = Path(full_path)
        crop_path = Path(crop_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        crop_path.parent.mkdir(parents=True, exist_ok=True)

        final_prompt = self.build_prompt(prompt) if wrap_prompt else prompt
        neg = negative_prompt if negative_prompt is not None else DEFAULT_NEGATIVE
        g = torch.Generator(device=self.device).manual_seed(int(seed))
        img = self.pipe(
            prompt=final_prompt,
            negative_prompt=neg,
            width=width, height=height,
            num_inference_steps=steps,
            guidance_scale=guidance_scale,
            generator=g,
        ).images[0]
        img.save(full_path)
        crop, method = crop_1x1(img, target_size=crop_target_size)
        crop.save(crop_path)
        return {
            "full_path": str(full_path),
            "crop_path": str(crop_path),
            "crop_method": method,
            "prompt": final_prompt,
            "seed": int(seed),
            "version": self.version,
        }


def generate_profile(
    prompt: str,
    full_path: str | Path,
    crop_path: str | Path,
    version: Literal["v2", "v3"] = "v3",
    seed: int = 42,
    **kwargs,
) -> dict:
    """One-shot profile image generator. See GlimiImageGen.generate for kwargs.

    Reuses a cached pipeline across calls with the same `version`.
    """
    gen = GlimiImageGen.get(version)
    return gen.generate(prompt, full_path, crop_path, seed=seed, **kwargs)
