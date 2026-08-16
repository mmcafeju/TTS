"""Engine creation, initialization, and session management."""

import logging
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .. import config
from .models import (
    Base,
    AudioChannel,
    EffectPreset,
    Generation,
    GenerationVersion,
    ProfileChannelMapping,
    VoiceProfile,
)
from .migrations import run_migrations
from .seed import backfill_generation_versions, seed_builtin_presets

logger = logging.getLogger(__name__)

# Initialized by init_db(). `SessionLocal` is a callable that resolves the
# current sessionmaker at call time, so modules that import it early (before
# init_db() runs) still get a working factory instead of a stale None.
class _SessionFactory:
    def __init__(self) -> None:
        self._sessionmaker = None

    def __call__(self, **kwargs):
        if self._sessionmaker is None:
            raise RuntimeError("Database not initialized; call init_db() first")
        return self._sessionmaker(**kwargs)

    def configure(self, sessionmaker) -> None:
        self._sessionmaker = sessionmaker


engine = None
SessionLocal = _SessionFactory()
_db_path = None


def init_db() -> None:
    """Initialize the database engine, run migrations, create tables, and seed data."""
    global engine, _db_path

    _db_path = config.get_db_path()
    _db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{_db_path}",
        connect_args={"check_same_thread": False},
    )

    SessionLocal.configure(sessionmaker(autocommit=False, autoflush=False, bind=engine))

    run_migrations(engine)
    Base.metadata.create_all(bind=engine)

    # Create default audio channel if it doesn't exist
    db = SessionLocal()
    try:
        default_channel = db.query(AudioChannel).filter(AudioChannel.is_default == True).first()
        if not default_channel:
            default_channel = AudioChannel(
                id=str(uuid.uuid4()),
                name="Default",
                is_default=True,
            )
            db.add(default_channel)

            for profile in db.query(VoiceProfile).all():
                db.add(ProfileChannelMapping(
                    profile_id=profile.id,
                    channel_id=default_channel.id,
                ))
            db.commit()
    finally:
        db.close()

    backfill_generation_versions(SessionLocal, Generation, GenerationVersion)
    seed_builtin_presets(SessionLocal, EffectPreset)


def get_db():
    """Yield a database session (FastAPI dependency)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
