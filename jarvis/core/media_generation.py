"""Provider interface for image/video generation — no vendor is hard-coded.

``generate_media`` (actions/generate_media.py) runs as a background job and
asks the first configured :class:`MediaProvider` that supports the requested
kind. A real image or video API plugs in by registering a provider from a
plugin file::

    from core.media_generation import MediaProvider, register_media_provider
    class MyVideoAPI(MediaProvider):
        name = "my_video_api"
        kinds = ("video",)
        def is_configured(self): return bool(os.environ.get("MY_VIDEO_KEY"))
        def generate(self, request): ...
    register_media_provider(MyVideoAPI())

Built in, with no API key, is :class:`PosterProvider`: it turns a reference
photo (for example a camera frame of a product) and a headline/tagline into
a still advert with Pillow. That keeps the "camera sees a product, JARVIS
makes an ad" flow working until a generation API is configured.
"""
from __future__ import annotations

import io
import textwrap
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class MediaRequest:
    kind: str                         # "image" | "video" | "ad"
    prompt: str
    reference_image: Optional[bytes] = None
    headline: str = ""
    tagline: str = ""
    out_dir: Path = field(default_factory=lambda: default_output_dir())
    cancel_event: Optional[threading.Event] = None


@dataclass
class MediaResult:
    files: list[str]
    provider: str
    note: str = ""


class MediaProvider(ABC):
    name = "media"
    kinds: tuple[str, ...] = ()

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def generate(self, request: MediaRequest) -> MediaResult: ...


def default_output_dir() -> Path:
    pictures = Path.home() / "Pictures"
    base = pictures if pictures.exists() else Path.home()
    out = base / "JARVIS"
    out.mkdir(parents=True, exist_ok=True)
    return out


_lock = threading.Lock()
_providers: list[MediaProvider] = []


def register_media_provider(provider: MediaProvider) -> None:
    with _lock:
        _providers[:] = [p for p in _providers if p.name != provider.name] + [provider]


def provider_for(kind: str) -> Optional[MediaProvider]:
    """Configured providers win over the built-in poster in registration order."""
    with _lock:
        candidates = list(_providers)
    for provider in reversed(candidates):        # newest registration first
        try:
            if kind in provider.kinds and provider.is_configured():
                return provider
        except Exception as exc:
            print(f"[Media] provider {provider.name} check failed: {exc}")
    return None


def reset_for_tests() -> None:
    with _lock:
        _providers.clear()
    register_media_provider(PosterProvider())


class PosterProvider(MediaProvider):
    """Built-in still advert: photo + headline + tagline. No network, no key."""

    name = "poster"
    kinds = ("ad", "image")

    def is_configured(self) -> bool:
        return True

    def generate(self, request: MediaRequest) -> MediaResult:
        from PIL import Image, ImageDraw, ImageFont, ImageOps

        width, height = 1080, 1350
        canvas = Image.new("RGB", (width, height), (12, 16, 28))
        if request.reference_image:
            photo = Image.open(io.BytesIO(request.reference_image)).convert("RGB")
            photo = ImageOps.fit(photo, (width, int(height * 0.68)))
            canvas.paste(photo, (0, 0))
        draw = ImageDraw.Draw(canvas)
        band_top = int(height * 0.68)
        draw.rectangle([0, band_top, width, height], fill=(12, 16, 28))
        try:
            big = ImageFont.truetype("arialbd.ttf", 72)
            small = ImageFont.truetype("arial.ttf", 40)
        except OSError:
            try:
                big = ImageFont.truetype("DejaVuSans-Bold.ttf", 72)
                small = ImageFont.truetype("DejaVuSans.ttf", 40)
            except OSError:
                big = small = ImageFont.load_default()
        headline = (request.headline or request.prompt or "New").strip()
        tagline = request.tagline.strip()
        y = band_top + 40
        for line in textwrap.wrap(headline, 24)[:2]:
            draw.text((60, y), line, font=big, fill=(255, 255, 255))
            y += 90
        for line in textwrap.wrap(tagline, 42)[:3]:
            draw.text((60, y + 10), line, font=small, fill=(120, 200, 255))
            y += 52
        out = Path(request.out_dir) / f"ad-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
        canvas.save(out, format="JPEG", quality=90)
        return MediaResult(files=[str(out)], provider=self.name,
                           note="Still advert made locally. Configure a video provider for motion ads.")


register_media_provider(PosterProvider())
