from pathlib import Path

import app.database as database


def test_default_sqlite_database_path_does_not_depend_on_working_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    expected = Path(database.__file__).resolve().parents[1] / "loto.db"
    assert database._database_url() == f"sqlite:///{expected.as_posix()}"
