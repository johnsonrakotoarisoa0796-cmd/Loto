from __future__ import annotations
import os
from pathlib import Path
from datetime import date, datetime, timezone
from sqlalchemy import create_engine, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def _database_url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    on_render = os.getenv("RENDER", "").strip().lower() == "true"

    # Render's filesystem is ephemeral: silently falling back to SQLite would
    # make draw history disappear on restart/redeploy. Require external Postgres.
    if not url:
        if on_render:
            raise RuntimeError(
                "DATABASE_URL is required on Render. Configure the Supabase "
                "PostgreSQL connection string in the Render Environment settings."
            )
        # Anchor local SQLite to the project root, not the shell working directory.
        db_path = Path(__file__).resolve().parents[1] / "loto.db"
        url = f"sqlite:///{db_path.as_posix()}"

    if on_render and url.lower().startswith("sqlite"):
        raise RuntimeError(
            "SQLite is not supported for persistent production storage on Render. "
            "Set DATABASE_URL to the Supabase PostgreSQL connection string."
        )

    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _database_url()
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class Draw(Base):
    __tablename__ = "draws"
    __table_args__ = (UniqueConstraint("draw_date", name="uq_draw_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    draw_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    numbers_json: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(120), nullable=False, default="Saisie manuelle")
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class PredictionRun(Base):
    __tablename__ = "prediction_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    based_on_draw_count: Mapped[int] = mapped_column(Integer, nullable=False)
    based_on_latest_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    numbers_json: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False, default="Historique + récence")
    actual_draw_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_numbers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    hits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
