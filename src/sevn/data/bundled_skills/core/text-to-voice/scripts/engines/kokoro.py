"""Kokoro ONNX engine for the text-to-voice skill.

Models and voices are downloaded on first ``generate()`` call from HuggingFace / GitHub.
Set HF_TOKEN env var if using a gated model or private repo.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import sys

_ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(os.path.dirname(_ENGINE_DIR))

_MODEL_MIN_BYTES = 1_000_000
_VOICES_MIN_BYTES = 100_000
# kokoro-onnx model-files-v1.0 release (voices-v1.0.bin).
_VOICES_EXPECTED_SHA256 = "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"
_VOICES_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
)
DEFAULT_VOICE = "af_heart"

_kokoro_patched = False


def _find_model() -> str | None:
    """Find the ONNX model — prefer quantized, then standard."""
    snapshot_glob = os.path.join(
        SKILL_DIR, "models", ".cache", "models--*", "snapshots", "*", "onnx"
    )
    for onnx_dir in sorted(glob.glob(snapshot_glob)):
        for name in ("model_quantized.onnx", "model.onnx", "model_q4.onnx"):
            candidate = os.path.join(onnx_dir, name)
            if os.path.isfile(candidate) and os.path.getsize(candidate) > _MODEL_MIN_BYTES:
                return candidate
    return None


def _file_sha256(path: str) -> str:
    """Return the SHA-256 hex digest of ``path``."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _voices_valid(path: str) -> bool:
    """Return whether ``voices.bin`` meets size and checksum expectations."""
    if not os.path.isfile(path) or os.path.getsize(path) < _VOICES_MIN_BYTES:
        return False
    return _file_sha256(path) == _VOICES_EXPECTED_SHA256


def _find_voices() -> str | None:
    """Find voices.bin (Numpy format expected by kokoro-onnx)."""
    root_voices = os.path.join(SKILL_DIR, "voices.bin")
    if _voices_valid(root_voices):
        return root_voices
    return None


def _auto_download() -> None:
    """Download ONNX model and voices on first generate() call."""
    import urllib.request

    if not _find_model():
        from huggingface_hub import snapshot_download

        cache_dir = os.path.join(SKILL_DIR, "models", ".cache")
        token = os.environ.get("HF_TOKEN") or None
        print("Downloading Kokoro ONNX model (first run, ~200MB)...", file=sys.stderr)
        snapshot_download(
            "onnx-community/Kokoro-82M-v1.0-ONNX",
            cache_dir=cache_dir,
            token=token,
        )

    voices_path = os.path.join(SKILL_DIR, "voices.bin")
    if not _voices_valid(voices_path):
        print("Downloading voices.bin (~27MB)...", file=sys.stderr)
        tmp_path = voices_path + ".partial"
        urllib.request.urlretrieve(_VOICES_URL, tmp_path)
        if not _voices_valid(tmp_path):
            os.remove(tmp_path)
            print(
                f"ERROR: voices.bin failed integrity check (expected sha256 {_VOICES_EXPECTED_SHA256}).",
                file=sys.stderr,
            )
            sys.exit(1)
        os.replace(tmp_path, voices_path)

    print("Download complete.", file=sys.stderr)


def _ensure_assets() -> tuple[str, str]:
    """Ensure model and voices are present; download on first use."""
    model_path = _find_model()
    voices_path = _find_voices()
    if model_path and voices_path:
        return model_path, voices_path
    _auto_download()
    model_path = _find_model()
    voices_path = _find_voices()
    if not model_path:
        print("ERROR: No ONNX model found after download attempt.", file=sys.stderr)
        sys.exit(1)
    if not voices_path:
        print("ERROR: voices.bin not found or failed integrity check.", file=sys.stderr)
        sys.exit(1)
    return model_path, voices_path


def _ensure_kokoro_patched() -> None:
    """Apply the int32→float32 speed-input patch once before first inference."""
    global _kokoro_patched
    if _kokoro_patched:
        return
    import kokoro_onnx
    import numpy as np

    def _patched_create_audio(self, phonemes, voice, speed):
        tokens = np.array(
            self.tokenizer.tokenize(phonemes[: kokoro_onnx.MAX_PHONEME_LENGTH]), dtype=np.int64
        )
        voice = voice[len(tokens)]
        tokens = [[0, *tokens, 0]]
        if "input_ids" in [i.name for i in self.sess.get_inputs()]:
            inputs = {
                "input_ids": tokens,
                "style": np.array(voice, dtype=np.float32),
                "speed": np.array([speed], dtype=np.float32),
            }
        else:
            inputs = {
                "tokens": tokens,
                "style": voice,
                "speed": np.ones(1, dtype=np.float32) * speed,
            }
        audio = self.sess.run(None, inputs)[0]
        return audio, kokoro_onnx.SAMPLE_RATE

    kokoro_onnx.Kokoro._create_audio = _patched_create_audio
    _kokoro_patched = True


def generate(
    text: str,
    voice: str = DEFAULT_VOICE,
    speed: float = 1.0,
    output_path: str | None = None,
    lang: str | None = None,
) -> str:
    """Generate audio file from text via Kokoro ONNX."""
    import kokoro_onnx
    import numpy as np
    import soundfile as sf

    _ = lang  # Kokoro derives language from voice prefix.
    model_path, voices_path = _ensure_assets()
    _ensure_kokoro_patched()

    lang_code = "en-us"
    if voice.startswith("j"):
        lang_code = "ja"
    elif voice.startswith("z"):
        lang_code = "cmn"

    kokoro = kokoro_onnx.Kokoro(model_path, voices_path)

    available = kokoro.get_voices()
    if voice not in available:
        print(
            f"WARNING: Voice '{voice}' not found for kokoro, falling back to {DEFAULT_VOICE}. "
            f"Available: {available[:5]}...",
            file=sys.stderr,
        )
        voice = DEFAULT_VOICE

    speed = max(0.5, min(2.0, speed))

    audio, sample_rate = kokoro.create(text, voice, speed=speed, lang=lang_code)

    if audio is None:
        raise ValueError("No audio generated")

    if output_path is None:
        output_path = os.path.join(SKILL_DIR, "output.wav")

    sf.write(output_path, np.array(audio).squeeze(), sample_rate)
    print(output_path)
    return output_path


def list_voices() -> None:
    """Print available Kokoro voices as JSON (static catalog — no model download)."""
    voices = [
        {"code": "af_heart", "label": "American F, warm"},
        {"code": "af_bella", "label": "American F, bright"},
        {"code": "af_nicole", "label": "American F, elegant"},
        {"code": "af_sarah", "label": "American F, soft"},
        {"code": "af_sky", "label": "American F, clear"},
        {"code": "am_adam", "label": "American M, deep"},
        {"code": "am_michael", "label": "American M, warm"},
        {"code": "bf_emma", "label": "British F, refined"},
        {"code": "bf_isabella", "label": "British F, elegant"},
        {"code": "bm_george", "label": "British M, formal"},
        {"code": "bm_lewis", "label": "British M, calm"},
        {"code": "jf_ai", "label": "Japanese F"},
        {"code": "zf_xiaojiao", "label": "Mandarin F"},
    ]
    print(json.dumps(voices))
