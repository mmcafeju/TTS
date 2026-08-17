"""Manual integration check: _save_generate / _save_retry with output_format export.

Run from backend/:  python tests/manual_save_export_check.py
Uses a throwaway temp data dir + real SQLite DB.
"""
import sys, tempfile, subprocess, re
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import config  # noqa: E402

tmp = tempfile.TemporaryDirectory()
config.set_data_dir(tmp.name)

from backend.database.session import get_db, init_db  # noqa: E402
from backend.services.generation import _save_generate, _save_retry  # noqa: E402
from backend.utils import audio as audio_mod  # noqa: E402
from backend.utils.audio_export import resolve_ffmpeg  # noqa: E402
from backend.services import versions as versions_mod  # noqa: E402
from backend.database.models import Generation, VoiceProfile  # noqa: E402
import subprocess  # noqa: E402
import uuid  # noqa: E402

SR = 24000
t = np.linspace(0, 2.0, SR * 2, endpoint=False)
audio = (0.5 * np.sin(2 * np.pi * 220 * t) * (t < 1.0) + 0.5 * np.sin(2 * np.pi * 440 * t) * (t >= 1.0)).astype(np.float32)
audio = np.stack([audio, audio], axis=-1)  # stereo input

def ebur128_integrated(path):
    ff = str(resolve_ffmpeg())
    r = subprocess.run(
        [ff, "-nostdin", "-i", str(path), "-filter_complex", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    summary = r.stderr.split("Summary:")[-1]
    return float(re.search(r"I:\s+(-?[\d.]+) LUFS", summary).group(1))


passed = 0


def check(name, cond, detail=""):
    global passed
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {detail}")
    if not cond:
        sys.exit(1)
    passed += 1


def info(path):
    import soundfile as sf
    return sf.info(path)


def make_generation(db, gid):
    pid = str(uuid.uuid4())
    db.add(VoiceProfile(id=pid, name=f"p-{gid}"))
    db.add(Generation(id=gid, profile_id=pid, text="hello", language="en"))
    db.commit()


init_db()
db = next(get_db())

# --- A: _save_retry + mp3 (no DB) ---
p = _save_retry(generation_id="retry1", audio=audio, sample_rate=SR, save_audio=audio_mod.save_audio, output_format="mp3")
r = Path(config.resolve_storage_path(p))
check("retry mp3 returned .mp3 path", p.endswith(".mp3") and r.is_file(), f"-> {p}")
i = info(r)
check("retry mp3 44.1k stereo", i.samplerate == 44100 and i.channels == 2, str(i))

# --- B: effects + broadcast (in-place export of processed wav) ---
make_generation(db, "gen2")
p2 = _save_generate(
    generation_id="gen2", audio=audio, sample_rate=SR,
    effects_chain=[{"type": "gain", "enabled": True, "params": {"gain_db": 6.0}}],
    save_audio=audio_mod.save_audio, db=db, output_format="broadcast",
)
r2 = Path(config.resolve_storage_path(p2))
check("broadcast in-place keeps .wav path", r2.name == "gen2_processed.wav" and r2.is_file(), f"-> {p2}")
i2 = info(r2)
check("broadcast 48k/24-bit stereo", i2.samplerate == 48000 and i2.subtype == "PCM_24" and i2.channels == 2, str(i2))
vs = versions_mod.list_versions("gen2", db)
check("gen2 has original + version-2", len(vs) == 2)
dv = versions_mod.get_default_version("gen2", db)
check("gen2 default is version-2", dv.label == "version-2")
lufs = ebur128_integrated(r2)
check("broadcast loudness ~ -24 LUFS", abs(lufs - (-24.0)) < 1.0, f"measured {lufs:.1f} LUFS")

# --- C: no effects + cd (in-place re-encode on clean wav) ---
make_generation(db, "gen3")
p3 = _save_generate(
    generation_id="gen3", audio=audio, sample_rate=SR, effects_chain=None,
    save_audio=audio_mod.save_audio, db=db, output_format="cd",
)
r3 = Path(config.resolve_storage_path(p3))
check("cd in-place keeps gen3.wav", r3.name == "gen3.wav" and r3.is_file(), f"-> {p3}")
i3 = info(r3)
check("cd 44.1k/16-bit stereo", i3.samplerate == 44100 and i3.subtype == "PCM_16" and i3.channels == 2, str(i3))

# --- D: no effects + mp3 (rename + generation row sync) ---
make_generation(db, "gen4")
p4 = _save_generate(
    generation_id="gen4", audio=audio, sample_rate=SR, effects_chain=None,
    save_audio=audio_mod.save_audio, db=db, output_format="mp3",
)
r4 = Path(config.resolve_storage_path(p4))
check("mp3 rename to gen4.mp3", r4.name == "gen4.mp3" and r4.is_file(), f"-> {p4}")
check("source gen4.wav removed", not (r4.parent / "gen4.wav").exists())
gen_row = db.query(Generation).filter(Generation.id == "gen4").first()
check("generation row repointed to mp3", gen_row and gen_row.audio_path == p4, f"row={gen_row.audio_path if gen_row else None}")
i4 = info(r4)
check("mp3 44.1k stereo", i4.samplerate == 44100 and i4.channels == 2, str(i4))

# --- E: no output_format -> unchanged original WAV behavior ---
make_generation(db, "gen5")
p5 = _save_generate(
    generation_id="gen5", audio=audio, sample_rate=SR, effects_chain=None,
    save_audio=audio_mod.save_audio, db=db, output_format=None,
)
r5 = Path(config.resolve_storage_path(p5))
check("default keeps 24k wav", r5.name == "gen5.wav" and r5.is_file(), f"-> {p5}")
i5 = info(r5)
check("default stays 24k original", i5.samplerate == SR and i5.channels == 2, str(i5))

db.close()

import backend.database.session as sess  # noqa: E402
sess.engine.dispose()
print(f"\nALL {passed} CHECKS PASSED")
tmp.cleanup()