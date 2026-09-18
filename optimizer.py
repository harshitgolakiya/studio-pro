"""Intelligent optimizer: compare codecs and qualities, score them objectively,
find the Pareto frontier and recommend a setting for a destination.

SSIM is computed with Pillow's float-image ops only (no numpy): 8x8
non-overlapping block statistics, the "uniform window" variant of SSIM.
It agrees with the Gaussian-window form to within a few thousandths on
photographic content and costs ~10 ms per comparison at 512 px.

Sweeps run on a working copy capped at ``max_edge`` pixels so AVIF/HEIC
(0.3-0.6 s per encode) stay interactive; sizes are then scaled to the full
image's pixel count and flagged as estimates. The exact size solver
(optimize_for_size) always encodes at full resolution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import io
import time
from typing import Any, Callable, Iterable, Sequence

from PIL import Image

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # pragma: no cover - optional at runtime
    pass

from converter import solve_target_size_quality
from metrics import block_ssim, psnr  # noqa: F401 -- re-exported for callers/tests


# -- image profile -------------------------------------------------------

@dataclass(frozen=True)
class ImageProfile:
    width: int
    height: int
    has_alpha: bool
    is_animated: bool
    kind: str  # "photo" | "graphic"
    unique_colors: int

    @property
    def pixels(self) -> int:
        return self.width * self.height


def profile_image(image: Image.Image) -> ImageProfile:
    has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
    if has_alpha and image.mode in ("RGBA", "LA"):
        extrema = image.getchannel("A").getextrema()
        has_alpha = extrema[0] < 255
    is_animated = bool(getattr(image, "is_animated", False)) and getattr(image, "n_frames", 1) > 1
    thumb = image.convert("RGB").copy()
    thumb.thumbnail((96, 96))
    colors = thumb.getcolors(96 * 96)
    unique = len(colors) if colors else 96 * 96
    # Flat-colour artwork / screenshots use a tiny palette relative to pixel
    # count; photographs use nearly every sampled pixel value.
    kind = "graphic" if unique < 0.15 * thumb.width * thumb.height else "photo"
    return ImageProfile(image.width, image.height, has_alpha, is_animated, kind, unique)


# -- candidates ----------------------------------------------------------

@dataclass
class Candidate:
    codec: str
    quality: int
    size_bytes: int
    ssim: float
    psnr: float
    encode_ms: float
    estimated_full_bytes: int
    pareto: bool = False

    @property
    def label(self) -> str:
        return f"{self.codec} q{self.quality}"


CODECS: dict[str, Callable[[int], dict[str, Any]]] = {
    "WEBP": lambda q: {"format": "WEBP", "quality": q, "method": 4},
    "AVIF": lambda q: {"format": "AVIF", "quality": q},
    "HEIC": lambda q: {"format": "HEIF", "quality": q},
    "JPEG": lambda q: {"format": "JPEG", "quality": q, "optimize": True, "progressive": True},
    "JPEG 2000": lambda q: {"format": "JPEG2000", "quality_mode": "dB", "quality_layers": [28 + q * 0.22]},
}

ALPHA_CODECS = {"WEBP", "AVIF", "HEIC", "JPEG 2000"}
DEFAULT_QUALITIES: tuple[int, ...] = (40, 55, 70, 80, 90)


def _working_copy(image: Image.Image, max_edge: int) -> Image.Image:
    work = image.convert("RGBA" if image.mode in ("RGBA", "LA", "PA") else "RGB")
    if max(work.size) > max_edge:
        work = work.copy()
        work.thumbnail((max_edge, max_edge), Image.LANCZOS)
    return work


def encode_candidate(work: Image.Image, codec: str, quality: int, full_pixels: int | None = None) -> Candidate | None:
    """Encode in memory, decode, score. Returns None if the codec can't
    encode this image (e.g. JPEG with alpha, missing plugin)."""
    factory = CODECS.get(codec)
    if factory is None:
        return None
    source = work
    kwargs = factory(quality)
    if codec == "JPEG" and source.mode != "RGB":
        source = source.convert("RGB")
    buf = io.BytesIO()
    start = time.perf_counter()
    try:
        source.save(buf, **kwargs)
        elapsed = (time.perf_counter() - start) * 1000
        buf.seek(0)
        decoded = Image.open(buf)
        decoded.load()
    except Exception:
        return None
    size = buf.getbuffer().nbytes
    ratio = (full_pixels / (work.width * work.height)) if full_pixels else 1.0
    return Candidate(
        codec=codec,
        quality=quality,
        size_bytes=size,
        ssim=block_ssim(work, decoded),
        psnr=psnr(work, decoded),
        encode_ms=elapsed,
        estimated_full_bytes=int(round(size * ratio)),
    )


def sweep(
    image: Image.Image,
    codecs: Sequence[str] = ("WEBP", "AVIF", "HEIC", "JPEG"),
    qualities: Sequence[int] = DEFAULT_QUALITIES,
    max_edge: int = 1024,
    progress: Callable[[int, int, str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[Candidate]:
    profile = profile_image(image)
    work = _working_copy(image, max_edge)
    usable = [c for c in codecs if c in CODECS and (not profile.has_alpha or c in ALPHA_CODECS)]
    total = len(usable) * len(qualities)
    done = 0
    results: list[Candidate] = []
    for codec in usable:
        for q in qualities:
            if should_stop and should_stop():
                return mark_pareto(results)
            cand = encode_candidate(work, codec, q, profile.pixels)
            done += 1
            if progress:
                progress(done, total, f"{codec} q{q}")
            if cand is not None:
                results.append(cand)
    return mark_pareto(results)


def pareto_frontier(cands: Iterable[Candidate]) -> list[Candidate]:
    """Candidates not dominated on (smaller size, higher SSIM), smallest first."""
    ordered = sorted(cands, key=lambda c: (c.size_bytes, -c.ssim))
    frontier: list[Candidate] = []
    best_ssim = -1.0
    for cand in ordered:
        if cand.ssim > best_ssim:
            frontier.append(cand)
            best_ssim = cand.ssim
    return frontier


def mark_pareto(cands: list[Candidate]) -> list[Candidate]:
    frontier = {id(c) for c in pareto_frontier(cands)}
    for c in cands:
        c.pareto = id(c) in frontier
    return cands


# -- recommendation ------------------------------------------------------

DESTINATIONS: dict[str, dict[str, Any]] = {
    "Web (modern browsers)": {"codecs": ("AVIF", "WEBP", "JPEG"), "min_ssim": 0.95},
    "Universal compatibility": {"codecs": ("JPEG", "WEBP"), "min_ssim": 0.96},
    "Photography / Apple devices": {"codecs": ("HEIC", "AVIF", "JPEG"), "min_ssim": 0.97},
    "Smallest possible": {"codecs": ("AVIF", "WEBP", "HEIC", "JPEG", "JPEG 2000"), "min_ssim": 0.92},
}


@dataclass
class Recommendation:
    candidate: Candidate | None
    reason: str
    alternatives: list[Candidate] = field(default_factory=list)


def recommend(
    cands: Sequence[Candidate],
    profile: ImageProfile,
    destination: str = "Web (modern browsers)",
    min_ssim: float | None = None,
) -> Recommendation:
    spec = DESTINATIONS.get(destination, DESTINATIONS["Web (modern browsers)"])
    floor = spec["min_ssim"] if min_ssim is None else min_ssim
    allowed = [c for c in spec["codecs"] if not profile.has_alpha or c in ALPHA_CODECS]
    pool = [c for c in cands if c.codec in allowed]
    if not pool:
        return Recommendation(None, "No candidate could be encoded for this destination.")

    frontier = [c for c in pareto_frontier(pool) if c.ssim >= floor]
    notes: list[str] = []
    if profile.has_alpha:
        notes.append("transparency rules out JPEG")
    if profile.kind == "graphic":
        notes.append("flat-colour artwork favours higher quality settings")
    if frontier:
        pick = frontier[0]
        why = f"smallest Pareto-optimal candidate keeping SSIM ≥ {floor:.2f} for {destination.lower()}"
    else:
        pick = max(pool, key=lambda c: (c.ssim, -c.size_bytes))
        why = f"no candidate reaches SSIM {floor:.2f}; picked the highest-quality one instead"
    if notes:
        why += " (" + "; ".join(notes) + ")"
    alternatives = [c for c in pareto_frontier(pool) if c is not pick][:3]
    return Recommendation(pick, why, alternatives)


# -- targeted solvers ----------------------------------------------------

@dataclass
class SizeOptimization:
    quality: int
    size_bytes: int
    ssim: float
    meets_target: bool
    meets_quality_floor: bool


def optimize_for_size(
    image: Image.Image,
    codec: str,
    max_bytes: int,
    min_ssim: float = 0.90,
) -> SizeOptimization | None:
    """Exact (full-resolution) search for the highest quality that fits
    under max_bytes, reporting whether the result also clears the SSIM floor."""
    factory = CODECS.get(codec)
    if factory is None:
        return None
    base = factory(50)
    fmt = base.pop("format")
    base.pop("quality", None)
    if "quality_layers" in base:
        return None  # dB-layer codecs don't take a 1-100 quality
    source = image.convert("RGB") if codec == "JPEG" and image.mode != "RGB" else image
    quality = solve_target_size_quality(source, max_bytes, fmt=fmt, save_kwargs=base)
    buf = io.BytesIO()
    try:
        source.save(buf, format=fmt, quality=quality, **base)
        buf.seek(0)
        decoded = Image.open(buf)
        decoded.load()
    except Exception:
        return None
    work = _working_copy(source, 1024)
    ssim = block_ssim(work, _working_copy(decoded, 1024))
    size = buf.getbuffer().nbytes
    return SizeOptimization(quality, size, ssim, size <= max_bytes, ssim >= min_ssim)


def optimize_for_quality(
    image: Image.Image,
    codec: str,
    target_ssim: float = 0.95,
    max_edge: int = 1024,
) -> Candidate | None:
    """Lowest quality whose SSIM meets the target (binary search, 7 steps)."""
    work = _working_copy(image, max_edge)
    full = image.width * image.height
    low, high = 5, 95
    best: Candidate | None = None
    highest_seen: Candidate | None = None
    for _ in range(7):
        mid = (low + high) // 2
        cand = encode_candidate(work, codec, mid, full)
        if cand is None:
            return None
        if highest_seen is None or cand.ssim > highest_seen.ssim:
            highest_seen = cand
        if cand.ssim >= target_ssim:
            best = cand
            high = mid - 1
        else:
            low = mid + 1
    return best or highest_seen
