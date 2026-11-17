from pathlib import Path

import app.database as database


def test_default_sqlite_database_path_does_not_depend_on_working_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    expected = Path(database.__file__).resolve().parents[1] / "loto.db"
    assert database._database_url() == f"sqlite:///{expected.as_posix()}"



def test_render_requires_database_url(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import pytest
    with pytest.raises(RuntimeError, match="DATABASE_URL is required on Render"):
        database._database_url()


def test_render_rejects_sqlite_database(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./loto.db")
    import pytest
    with pytest.raises(RuntimeError, match="SQLite is not supported"):
        database._database_url()


def test_render_accepts_supabase_postgresql_url(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres.example:secret@aws-0-region.pooler.supabase.com:5432/postgres",
    )
    assert database._database_url().startswith("postgresql+psycopg://")
