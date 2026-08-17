"""
Segment-level audio regeneration ("repaint a sentence chunk").

Splices a freshly generated chunk back into the stored audio at the chunk's
original time window, using short equal-power fades at the cut points to
avoid clicks.  The regenerated full track is saved as a new version so the
previous take is preserved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from typing import List, Optional

import numpy as np
from sqlalchemy.orm import Session

from .. import config
from ..database import Generation as DBGeneration
from ..database.session import get_db
from ..services import history, profiles, versions as versions_mod
from ..utils.audio import load_audio, save_audio

logger = logging.getLogger(__name__)

_DEFAULT_CROSSFADE_MS = 50


def parse_chunk_meta(gen) -> List[dict]:
    """Return the generation's stored chunk metadata as a list of dicts."""
    if not gen or not getattr(gen, "chunk_meta", None):
        return []
    try:
        parsed = json.loads(gen.chunk_meta)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [
        {
            "index": int(c.get("index", i)),
            "text": str(c.get("text", "")),
            "start_ms": int(c.get("start_ms", 0)),
            "end_ms": int(c.get("end_ms", 0)),
            "duration_ms": int(c.get("duration_ms", 0)),
        }
        for i, c in enumerate(parsed)
        if isinstance(c, dict)
    ]


def save_chunk_meta(db: Session, generation_id: str, chunk_meta: List[dict]) -> None:
    """Persist chunk metadata on the generation row (single JSON blob)."""
    gen = db.query(DBGeneration).filter_by(id=generation_id).first()
    if not gen:
        return
    gen.chunk_meta = json.dumps(
        [
            {
                "index": int(m.get("index", 0)),
                "text": m.get("text", ""),
                "start_ms": int(m.get("start_ms", 0)),
                "end_ms": int(m.get("end_ms", 0)),
                "duration_ms": int(m.get("duration_ms", 0)),
            }
            for m in chunk_meta
        ],
        ensure_ascii=False,
    )
    db.commit()
    db.refresh(gen)


def splice_chunk_into_audio(
    full_audio: np.ndarray,
    sample_rate: int,
    chunk_meta: List[dict],
    chunk_index: int,
    new_chunk_audio: np.ndarray,
    crossfade_ms: int = _DEFAULT_CROSSFADE_MS,
) -> tuple[np.ndarray, List[dict]]:
    """Replace chunk *chunk_index* with ``new_chunk_audio`` and reflow metadata.

    The original chunk occupies ``[start_ms, end_ms]``.  We cut there, splice
    the new chunk in with short equal-power fades at both junctions, and
    shift all downstream chunk windows by the length delta so the returned
    metadata stays accurate.

    Returns
    -------
    (audio, chunk_meta) : the spliced mono audio and the reflowed metadata.
    """
    full_audio = np.asarray(full_audio, dtype=np.float32)
    new_chunk = np.asarray(new_chunk_audio, dtype=np.float32)

    start = int(round(chunk_meta[chunk_index]["start_ms"] * sample_rate / 1000))
    end = int(round(chunk_meta[chunk_index]["end_ms"] * sample_rate / 1000))
    start = min(max(start, 0), len(full_audio))
    end = min(max(end, start), len(full_audio))
    original_len = end - start

    fade = min(
        int(sample_rate * crossfade_ms / 1000),
        start,
        len(full_audio) - end,
        len(new_chunk),
    )

    if fade <= 0 or original_len == 0:
        out = np.concatenate([full_audio[:start], new_chunk, full_audio[end:]])
    else:
        head = full_audio[:start]
        tail = full_audio[end:]
        fade_out = np.linspace(1.0, 0.0, fade, dtype=np.float32)
        fade_in = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        body = new_chunk[fade:-fade] if len(new_chunk) > 2 * fade else np.array([], dtype=np.float32)
        parts = [head[:-fade]] if len(head) > fade else []
        parts.append(head[-fade:] * fade_out + new_chunk[:fade] * fade_in)
        if len(body):
            parts.append(body)
        parts.append(new_chunk[-fade:] * fade_out + tail[:fade] * fade_in)
        if len(tail) > fade:
            parts.append(tail[fade:])
        out = np.concatenate(parts)

    # Reflow metadata with a continuous timeline model: the replaced chunk's
    # window becomes the new chunk's placement, and every later chunk starts
    # where the previous one ended (durations unchanged, so downstream shift
    # equals the length delta).  The tiny fade overlap at the junctions is
    # absorbed into the boundaries, which keeps the editor overlay stable.
    new_meta = [dict(m) for m in chunk_meta]
    delta = len(new_chunk) - original_len
    eff_start = max(0, start - fade)
    new_meta[chunk_index]["start_ms"] = int(round(eff_start * 1000 / sample_rate))
    new_meta[chunk_index]["end_ms"] = int(round((eff_start + len(new_chunk)) * 1000 / sample_rate))
    new_meta[chunk_index]["duration_ms"] = int(round(len(new_chunk) * 1000 / sample_rate))
    shift = int(round(delta * 1000 / sample_rate))
    for m in new_meta[chunk_index + 1 :]:
        m["start_ms"] += shift
        m["end_ms"] += shift
    return out, new_meta


async def regenerate_chunk(
    *,
    generation_id: str,
    chunk_index: int,
    text_override: Optional[str] = None,
    seed: Optional[int] = None,
    crossfade_ms: int = _DEFAULT_CROSSFADE_MS,
) -> None:
    """Regenerate one sentence chunk and splice it back in as a new version.

    Mirrors ``run_generation``: loads the engine/model, rebuilds the voice
    prompt from the profile, generates the single chunk, splices it into the
    current default version's audio, saves a new version, and reflows the
    chunk metadata.
    """
    from ..backends import get_tts_backend_for_engine, load_engine_model
    from ..utils.chunked_tts import generate_chunked

    bg_db = next(get_db())
    try:
        gen = bg_db.query(DBGeneration).filter_by(id=generation_id).first()
        if not gen:
            logger.error("chunk regenerate: generation %s not found", generation_id)
            return
        chunk_meta = parse_chunk_meta(gen)
        if not chunk_meta or not (0 <= chunk_index < len(chunk_meta)):
            await history.update_generation_status(
                generation_id, "failed", db=bg_db, error=f"Invalid chunk index {chunk_index}"
            )
            return

        await history.update_generation_status(generation_id, "loading_model", db=bg_db)
        await load_engine_model(gen.engine or "qwen", gen.model_size or "1.7B")

        voice_prompt = await profiles.create_voice_prompt_for_profile(
            gen.profile_id, bg_db, use_cache=True, engine=gen.engine or "qwen"
        )

        chunk_text = (text_override or chunk_meta[chunk_index]["text"]).strip()
        if not chunk_text:
            await history.update_generation_status(
                generation_id, "failed", db=bg_db, error="Chunk text is empty"
            )
            return

        await history.update_generation_status(generation_id, "generating", db=bg_db)
        tts_model = get_tts_backend_for_engine(gen.engine or "qwen")
        new_chunk, new_sr = await generate_chunked(
            tts_model,
            chunk_text,
            voice_prompt,
            language=gen.language or "en",
            seed=seed,
            instruct=gen.instruct,
            crossfade_ms=0,
        )
        new_chunk = np.asarray(new_chunk, dtype=np.float32)

        base_path = config.resolve_storage_path(gen.audio_path)
        if base_path is None or not base_path.is_file():
            await history.update_generation_status(
                generation_id, "failed", db=bg_db, error="Source audio file missing"
            )
            return

        import soundfile as sf

        with sf.SoundFile(str(base_path)) as f:
            base_sr = f.samplerate
        full_audio, _ = load_audio(str(base_path), sample_rate=base_sr, mono=True)

        if new_sr != base_sr:
            import librosa

            new_chunk = librosa.resample(new_chunk, orig_sr=new_sr, target_sr=base_sr)

        spliced, new_meta = splice_chunk_into_audio(
            full_audio,
            base_sr,
            chunk_meta,
            chunk_index,
            new_chunk,
            crossfade_ms=crossfade_ms,
        )

        out_path = config.get_generations_dir() / f"{generation_id}_chunk{chunk_index}.wav"
        save_audio(spliced, str(out_path), base_sr)
        out_storage = config.to_storage_path(out_path)

        versions_mod.create_version(
            generation_id=generation_id,
            label=f"chunk-{chunk_index} regenerated",
            audio_path=out_storage,
            db=bg_db,
            effects_chain=None,
            is_default=True,
        )
        save_chunk_meta(bg_db, generation_id, new_meta)

        await history.update_generation_status(
            generation_id,
            "completed",
            db=bg_db,
            audio_path=out_storage,
            duration=len(spliced) / base_sr,
        )
        logger.info("chunk %d of %s regenerated -> %s", chunk_index, generation_id, out_storage)
    except asyncio.CancelledError:
        await history.update_generation_status(
            generation_id, "failed", db=bg_db, error="Chunk regeneration cancelled"
        )
    except Exception as e:
        traceback.print_exc()
        await history.update_generation_status(
            generation_id, "failed", db=bg_db, error=str(e)
        )
    finally:
        bg_db.close()