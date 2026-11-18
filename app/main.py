from __future__ import annotations

import csv
import hmac
import io
import json
import os
import secrets
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Generator

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from analysis_engine import analyze_draws
from scientific_engine import audit_draws
from contextual_study import build_contextual_study
from contextual_predictor import build_contextual_prediction
from app.database import Base, Draw, PredictionRun, SessionLocal, engine

BASE_DIR = Path(__file__).resolve().parent
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
SECRET_KEY = os.getenv("SECRET_KEY", "development-secret-change-before-deploy")

app = FastAPI(title="Loto 5/35 Analytics", version="1.3.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="loto_session",
    same_site="lax",
    https_only=os.getenv("COOKIE_SECURE", "false").lower() == "true",
    max_age=60 * 60 * 24 * 14,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SEED_DRAWS = [
    (date(2026, 11, 8), [3, 8, 15, 19, 34]),
    (date(2026, 11, 9), [10, 24, 25, 28, 29]),
    (date(2026, 11, 10), [3, 12, 15, 20, 25]),
    (date(2026, 11, 11), [2, 3, 16, 20, 27]),
    (date(2026, 11, 12), [10, 13, 21, 27, 34]),
    (date(2026, 11, 13), [14, 21, 22, 26, 34]),
    (date(2026, 11, 14), [15, 18, 20, 23, 26]),
]


class DrawPayload(BaseModel):
    date: date
    numbers: list[int] = Field(min_length=5, max_length=5)
    source: str = Field(default="Saisie manuelle", max_length=120)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("numbers")
    @classmethod
    def validate_numbers(cls, values: list[int]) -> list[int]:
        if len(set(values)) != 5:
            raise ValueError("Les cinq numéros doivent être distincts.")
        if any(n < 1 or n > 35 for n in values):
            raise ValueError("Chaque numéro doit être compris entre 1 et 35.")
        return sorted(values)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_auth(request: Request) -> None:
    if APP_PASSWORD and not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Connexion requise.")


def require_csrf(request: Request) -> None:
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        expected = request.session.get("csrf_token")
        supplied = request.headers.get("x-csrf-token", "")
        if not expected or not hmac.compare_digest(expected, supplied):
            raise HTTPException(status_code=403, detail="Jeton de sécurité invalide. Actualise la page.")


def as_draw_dict(draw: Draw) -> dict:
    return {
        "id": draw.id,
        "date": draw.draw_date.isoformat(),
        "numbers": json.loads(draw.numbers_json),
        "source": draw.source,
        "notes": draw.notes,
        "created_at": draw.created_at.isoformat() if draw.created_at else None,
    }


def load_draws(db: Session) -> list[dict]:
    records = db.scalars(select(Draw).order_by(Draw.draw_date.asc(), Draw.id.asc())).all()
    return [{"date": r.draw_date, "numbers": json.loads(r.numbers_json)} for r in records]


def evaluate_pending_predictions(db: Session) -> int:
    """Reconcile saved forecasts with the first currently recorded later draw."""
    forecasts = db.scalars(select(PredictionRun).order_by(PredictionRun.created_at.asc())).all()
    changed = 0
    for forecast in forecasts:
        actual = db.scalar(
            select(Draw).where(Draw.draw_date > forecast.based_on_latest_date)
            .order_by(Draw.draw_date.asc(), Draw.id.asc()).limit(1)
        )
        if actual:
            predicted_numbers = set(json.loads(forecast.numbers_json))
            actual_numbers = json.loads(actual.numbers_json)
            actual_numbers_json = json.dumps(actual_numbers)
            hits = len(predicted_numbers.intersection(actual_numbers))
            if (forecast.actual_draw_date != actual.draw_date
                    or forecast.actual_numbers_json != actual_numbers_json
                    or forecast.hits != hits
                    or forecast.evaluated_at is None):
                forecast.actual_draw_date = actual.draw_date
                forecast.actual_numbers_json = actual_numbers_json
                forecast.hits = hits
                forecast.evaluated_at = datetime.now(timezone.utc)
                changed += 1
        elif forecast.evaluated_at is not None:
            forecast.actual_draw_date = None
            forecast.actual_numbers_json = None
            forecast.hits = None
            forecast.evaluated_at = None
            changed += 1
    if changed:
        db.commit()
    return changed


def as_prediction_dict(item: PredictionRun) -> dict:
    return {
        "id": item.id,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "based_on_draw_count": item.based_on_draw_count,
        "based_on_latest_date": item.based_on_latest_date.isoformat(),
        "numbers": json.loads(item.numbers_json),
        "model_name": item.model_name,
        "actual_draw_date": item.actual_draw_date.isoformat() if item.actual_draw_date else None,
        "actual_numbers": json.loads(item.actual_numbers_json) if item.actual_numbers_json else None,
        "hits": item.hits,
        "evaluated": item.evaluated_at is not None,
    }


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        existing = db.scalar(select(Draw.id).limit(1))
        if existing is None:
            for draw_date, numbers in SEED_DRAWS:
                db.add(Draw(
                    draw_date=draw_date,
                    numbers_json=json.dumps(numbers),
                    source="Historique fourni au démarrage",
                ))
            db.commit()


@app.on_event("startup")
def startup() -> None:
    if os.getenv("RENDER", "").strip().lower() == "true":
        if not APP_PASSWORD:
            raise RuntimeError("APP_PASSWORD must be configured in Render before exposing Loto Lab.")
        if not os.getenv("SECRET_KEY", "").strip():
            raise RuntimeError("SECRET_KEY must be configured in Render before exposing Loto Lab.")
    initialize_database()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health() -> dict:
    """Render health check: report healthy only when the configured DB is reachable."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        # Do not expose driver errors or connection details in the public response.
        raise HTTPException(
            status_code=503,
            detail="Base de données indisponible. Vérifie DATABASE_URL et la connexion Supabase.",
        ) from exc
    return {"status": "ok", "database": "ok", "service": "loto-5-35"}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if not APP_PASSWORD:
        return RedirectResponse(url="/", status_code=303)
    if request.session.get("authenticated"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login(request: Request, password: str = Form(...)):
    if APP_PASSWORD and hmac.compare_digest(password, APP_PASSWORD):
        request.session.clear()
        request.session["authenticated"] = True
        request.session["csrf_token"] = secrets.token_urlsafe(32)
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {
        "error": "Mot de passe incorrect. Réessaie.",
    }, status_code=401)


@app.post("/logout", dependencies=[Depends(require_auth), Depends(require_csrf)])
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if APP_PASSWORD and not request.session.get("authenticated"):
        return RedirectResponse(url="/login", status_code=303)
    request.session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return templates.TemplateResponse(request, "index.html", {
        "csrf_token": request.session["csrf_token"],
        "password_protected": bool(APP_PASSWORD),
    })


@app.get("/api/config", dependencies=[Depends(require_auth)])
def config(request: Request):
    request.session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return {"csrf_token": request.session["csrf_token"], "password_protected": bool(APP_PASSWORD)}


@app.get("/api/draws", dependencies=[Depends(require_auth)])
def get_draws(db: Session = Depends(get_db)):
    rows = db.scalars(select(Draw).order_by(Draw.draw_date.desc(), Draw.id.desc())).all()
    return {"draws": [as_draw_dict(r) for r in rows]}


@app.post("/api/draws", dependencies=[Depends(require_auth), Depends(require_csrf)])
def create_draw(payload: DrawPayload, db: Session = Depends(get_db)):
    existing = db.scalar(select(Draw).where(Draw.draw_date == payload.date))
    if existing:
        raise HTTPException(status_code=409, detail="Un tirage existe déjà à cette date. Modifie-le au lieu de le dupliquer.")
    row = Draw(
        draw_date=payload.date,
        numbers_json=json.dumps(payload.numbers),
        source=payload.source.strip() or "Saisie manuelle",
        notes=payload.notes.strip() if payload.notes else None,
    )
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
        evaluate_pending_predictions(db)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Un tirage existe déjà à cette date.")
    return {"draw": as_draw_dict(row)}


@app.put("/api/draws/{draw_id}", dependencies=[Depends(require_auth), Depends(require_csrf)])
def update_draw(draw_id: int, payload: DrawPayload, db: Session = Depends(get_db)):
    row = db.get(Draw, draw_id)
    if not row:
        raise HTTPException(status_code=404, detail="Tirage introuvable.")
    duplicate = db.scalar(select(Draw).where(Draw.draw_date == payload.date, Draw.id != draw_id))
    if duplicate:
        raise HTTPException(status_code=409, detail="Un autre tirage existe déjà à cette date.")
    row.draw_date = payload.date
    row.numbers_json = json.dumps(payload.numbers)
    row.source = payload.source.strip() or "Saisie manuelle"
    row.notes = payload.notes.strip() if payload.notes else None
    db.commit()
    db.refresh(row)
    evaluate_pending_predictions(db)
    return {"draw": as_draw_dict(row)}


@app.delete("/api/draws/{draw_id}", dependencies=[Depends(require_auth), Depends(require_csrf)])
def delete_draw(draw_id: int, db: Session = Depends(get_db)):
    row = db.get(Draw, draw_id)
    if not row:
        raise HTTPException(status_code=404, detail="Tirage introuvable.")
    db.delete(row)
    db.commit()
    evaluate_pending_predictions(db)
    return {"deleted": True}


@app.get("/api/analysis", dependencies=[Depends(require_auth)])
def get_analysis(db: Session = Depends(get_db)):
    return analyze_draws(load_draws(db))


def _apply_contextual_model(
    analysis: dict,
    contextual: dict,
) -> dict:
    prediction = analysis["prediction"]
    prediction["contextual_model"] = contextual
    prediction["active_model_id"] = "hybrid"
    if not contextual.get("ready"):
        return analysis

    model = {
        "id": "contextual",
        "label": "Historique + météo + Lune + sismicité",
        "description": (
            "Classement expérimental : historique/récence combinés aux contextes "
            "météo, lunaires et sismiques les plus proches."
        ),
        "numbers": contextual["numbers"],
        "score_index": contextual["score_index"],
        "score_note": "Indice relatif et contextuel, pas une probabilité.",
    }
    prediction["models"] = [
        item for item in prediction.get("models", []) if item.get("id") != "contextual"
    ] + [model]
    prediction["numbers"] = contextual["numbers"]
    prediction["ranked"] = contextual["ranked"]
    prediction["active_model_id"] = "contextual"
    prediction["method"] = (
        "Modèle contextuel expérimental : historique + récence + contexte "
        "météorologique, lunaire et sismique."
    )
    prediction["alternatives"] = [
        item["numbers"] for item in prediction["models"] if item["id"] != "contextual"
    ]
    analysis.setdefault("backtest", {})["contextual_comparison"] = contextual.get("backtest")
    return analysis


def _effective_prediction(draws: list[dict]) -> dict:
    analysis = analyze_draws(draws)
    try:
        contextual = build_contextual_prediction(draws)
    except Exception as exc:
        contextual = {
            "ready": False,
            "status": "context_error",
            "reason": "Le calcul contextuel est momentanément indisponible ; le classement historique est conservé.",
            "detail": type(exc).__name__,
        }
    return _apply_contextual_model(analysis, contextual)["prediction"]


@app.get("/api/predictions", dependencies=[Depends(require_auth)])
def get_predictions(db: Session = Depends(get_db)):
    return _effective_prediction(load_draws(db))


@app.post("/api/predictions/record", dependencies=[Depends(require_auth), Depends(require_csrf)])
def record_prediction(db: Session = Depends(get_db)):
    draws = load_draws(db)
    if not draws:
        raise HTTPException(status_code=400, detail="Ajoute au moins un tirage avant d'enregistrer une prévision.")
    prediction = _effective_prediction(draws)
    latest_date = draws[-1]["date"]
    existing = db.scalar(
        select(PredictionRun).where(
            PredictionRun.based_on_draw_count == len(draws),
            PredictionRun.based_on_latest_date == latest_date,
            PredictionRun.numbers_json == json.dumps(prediction["numbers"]),
        ).limit(1)
    )
    if existing:
        return {"prediction": as_prediction_dict(existing), "already_recorded": True}
    row = PredictionRun(
        based_on_draw_count=len(draws),
        based_on_latest_date=latest_date,
        numbers_json=json.dumps(prediction["numbers"]),
        model_name=(
            "Historique + météo + Lune + sismicité"
            if prediction.get("active_model_id") == "contextual"
            else "Historique + récence"
        ),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"prediction": as_prediction_dict(row), "already_recorded": False}


@app.get("/api/prediction-history", dependencies=[Depends(require_auth)])
def prediction_history(db: Session = Depends(get_db)):
    rows = db.scalars(select(PredictionRun).order_by(PredictionRun.created_at.desc()).limit(100)).all()
    return {"predictions": [as_prediction_dict(row) for row in rows]}


def _parse_date(value: str) -> date:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Date invalide : {value}. Formats acceptés : AAAA-MM-JJ ou JJ/MM/AAAA.")


def _parse_csv(file_text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(file_text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError("Le fichier CSV ne contient pas d'en-têtes.")
    headers = {h.strip().lower(): h for h in reader.fieldnames if h}
    date_key = next((headers[k] for k in ("date", "draw_date", "jour") if k in headers), None)
    number_keys = None
    for candidate in (("n1", "n2", "n3", "n4", "n5"), ("num1", "num2", "num3", "num4", "num5"),
                      ("numero1", "numero2", "numero3", "numero4", "numero5")):
        if all(k in headers for k in candidate):
            number_keys = [headers[k] for k in candidate]
            break
    packed_key = next((headers[k] for k in ("numbers", "numeros", "tirage") if k in headers), None)
    if not date_key or (not number_keys and not packed_key):
        raise ValueError("Colonnes attendues : date,n1,n2,n3,n4,n5 (ou date,numbers).")

    results = []
    for line, row in enumerate(reader, start=2):
        if not any((v or "").strip() for v in row.values()):
            continue
        try:
            draw_date = _parse_date(row[date_key] or "")
            raw_numbers = [row[k] for k in number_keys] if number_keys else (row[packed_key] or "").replace(";", "-").replace(",", "-").replace(" ", "-").split("-")
            numbers = sorted(int(str(x).strip()) for x in raw_numbers if str(x).strip())
            if len(numbers) != 5 or len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
                raise ValueError("il faut exactement 5 numéros distincts compris entre 1 et 35")
            results.append({
                "date": draw_date,
                "numbers": numbers,
                "source": (row.get(headers.get("source", ""), "") or "Import CSV").strip() or "Import CSV",
                "notes": (row.get(headers.get("notes", ""), "") or "").strip() or None,
                "line": line,
            })
        except Exception as exc:
            raise ValueError(f"Ligne {line} : {exc}") from exc
    return results


@app.post("/api/import", dependencies=[Depends(require_auth), Depends(require_csrf)])
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Sélectionne un fichier .csv.")
    raw = await file.read(2_000_001)
    if len(raw) > 2_000_000:
        raise HTTPException(status_code=413, detail="Le fichier dépasse la limite de 2 Mo.")
    try:
        rows = _parse_csv(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Le CSV doit être encodé en UTF-8.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    inserted = 0
    ignored = 0
    seen_in_file: dict[date, list[int]] = {}
    try:
        for item in rows:
            previous_in_file = seen_in_file.get(item["date"])
            if previous_in_file is not None:
                if previous_in_file != item["numbers"]:
                    raise ValueError(f"Conflit dans le fichier à la date {item['date'].isoformat()} : deux tirages différents.")
                ignored += 1
                continue
            seen_in_file[item["date"]] = item["numbers"]
            current = db.scalar(select(Draw).where(Draw.draw_date == item["date"]))
            if current:
                current_numbers = json.loads(current.numbers_json)
                if current_numbers != item["numbers"]:
                    raise ValueError(f"Conflit à la date {item['date'].isoformat()} : le tirage enregistré est différent.")
                ignored += 1
                continue
            db.add(Draw(
                draw_date=item["date"],
                numbers_json=json.dumps(item["numbers"]),
                source=item["source"],
                notes=item["notes"],
            ))
            inserted += 1
        db.commit()
        evaluate_pending_predictions(db)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflit de dates pendant l'import. Aucun changement n'a été conservé.")
    return {"inserted": inserted, "ignored_duplicates": ignored, "read": len(rows)}


@app.get("/api/export.csv", dependencies=[Depends(require_auth)])
def export_csv(db: Session = Depends(get_db)):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "n1", "n2", "n3", "n4", "n5", "source", "notes"])
    rows = db.scalars(select(Draw).order_by(Draw.draw_date.asc())).all()
    for row in rows:
        numbers = json.loads(row.numbers_json)
        writer.writerow([row.draw_date.isoformat(), *numbers, row.source, row.notes or ""])
    content = "\ufeff" + output.getvalue()
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=loto-5-35-historique.csv"},
    )

# --- LOTO LAB: scientific audit engine ---
@app.get("/science", response_class=HTMLResponse)
def science_page(request: Request):
    if APP_PASSWORD and not request.session.get("authenticated"):
        return RedirectResponse(url="/login", status_code=303)
    request.session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return templates.TemplateResponse(request, "science.html", {
        "csrf_token": request.session["csrf_token"],
        "password_protected": bool(APP_PASSWORD),
    })


@app.get("/api/science", dependencies=[Depends(require_auth)])
def get_scientific_audit(db: Session = Depends(get_db)):
    return audit_draws(load_draws(db))
# --- END LOTO LAB: scientific audit engine ---


@app.get("/api/contextual-study", dependencies=[Depends(require_auth)])
def get_contextual_study(db: Session = Depends(get_db)):
    """Return the raw astronomical, weather and seismic study."""
    try:
        return build_contextual_study(load_draws(db))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/contextual-prediction", dependencies=[Depends(require_auth)])
def get_contextual_prediction(db: Session = Depends(get_db)):
    """Return an experimental next-draw ranking using pre-draw external context."""
    try:
        return build_contextual_prediction(load_draws(db))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
