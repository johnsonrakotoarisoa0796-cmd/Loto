from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "app" / "main.py"
INDEX = ROOT / "app" / "templates" / "index.html"
STYLE = ROOT / "app" / "static" / "style.css"
ANALYSIS = ROOT / "analysis_engine.py"

ROUTES = '''\n\n# --- LOTO LAB: scientific audit engine ---\n@app.get("/science", response_class=HTMLResponse)\ndef science_page(request: Request):\n    if APP_PASSWORD and not request.session.get("authenticated"):\n        return RedirectResponse(url="/login", status_code=303)\n    request.session.setdefault("csrf_token", secrets.token_urlsafe(32))\n    return templates.TemplateResponse(request, "science.html", {\n        "csrf_token": request.session["csrf_token"],\n        "password_protected": bool(APP_PASSWORD),\n    })\n\n\n@app.get("/api/science", dependencies=[Depends(require_auth)])\ndef get_scientific_audit(db: Session = Depends(get_db)):\n    return audit_draws(load_draws(db))\n# --- END LOTO LAB: scientific audit engine ---\n'''


def backup(path: Path) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(path.name + f".before-science-{stamp}.bak")
    shutil.copy2(path, target)
    print(f"Sauvegarde : {target.name}")


def main() -> None:
    for path in (MAIN, INDEX, STYLE, ANALYSIS):
        if not path.exists():
            raise SystemExit(f"Fichier introuvable : {path}")
    if not (ROOT / "scientific_engine.py").exists():
        raise SystemExit("scientific_engine.py manque. Extrais d'abord tout le ZIP dans la racine du projet.")
    if not (ROOT / "app" / "templates" / "science.html").exists():
        raise SystemExit("app/templates/science.html manque.")
    if not (ROOT / "app" / "static" / "science.js").exists() or not (ROOT / "app" / "static" / "science.css").exists():
        raise SystemExit("Les fichiers statiques de l'audit scientifique sont incomplets.")

    main_text = MAIN.read_text(encoding="utf-8")
    if "from scientific_engine import audit_draws" not in main_text:
        anchor = "from analysis_engine import analyze_draws"
        if anchor not in main_text:
            raise SystemExit("Impossible de localiser l'import du moteur d'analyse dans app/main.py. Aucun fichier existant n'a été modifié.")
        main_text = main_text.replace(anchor, anchor + "\nfrom scientific_engine import audit_draws", 1)
    if "# --- LOTO LAB: scientific audit engine ---" not in main_text:
        main_text = main_text.rstrip() + ROUTES

    index_text = INDEX.read_text(encoding="utf-8")
    if 'class="nav-item science-link"' not in index_text:
        pattern = r'(<button class="nav-item" data-view="prediction".*?</button>)'
        replacement = r'\1\n        <a class="nav-item science-link" href="/science" title="Audit scientifique"><span class="nav-icon">⚛</span>Audit scientifique</a>'
        updated, count = re.subn(pattern, replacement, index_text, count=1, flags=re.DOTALL)
        if count != 1:
            raise SystemExit("Impossible de localiser le menu Laboratoire de scores dans index.html. Aucun fichier existant n'a été modifié.")
        index_text = updated

    analysis_text = ANALYSIS.read_text(encoding="utf-8")
    analysis_replacements = {
        "PRIOR_DRAWS = 20.0": "PRIOR_DRAWS = 70.0",
        "RECENCY_HALF_LIFE = 20.0": "RECENCY_HALF_LIFE = 40.0",
        "score = 0.65 * overall + 0.35 * recent": "score = 0.70 * overall + 0.30 * recent",
        "def _backtest(draws: Sequence[dict], min_training: int = 12)": "def _backtest(draws: Sequence[dict], min_training: int = 60)",
    }
    for old_value, new_value in analysis_replacements.items():
        if old_value in analysis_text:
            analysis_text = analysis_text.replace(old_value, new_value, 1)
        elif new_value not in analysis_text:
            raise SystemExit(f"Version inattendue de analysis_engine.py : élément non trouvé : {old_value}. Aucun fichier existant n'a été modifié.")

    style_text = STYLE.read_text(encoding="utf-8")
    if ".side-nav .science-link" not in style_text:
        style_text += "\n\n/* Loto Lab scientific audit navigation */\n"
        style_text += ".side-nav .science-link{text-decoration:none;display:flex;align-items:center;color:#aeb9cc;background:transparent;border:0;font:inherit;border-radius:10px;padding:12px 14px}.side-nav .science-link:hover{background:#ffffff0c;color:#fff}\n"
        style_text += "@media(max-width:560px){.side-nav .nav-item{width:20%}.side-nav .science-link{justify-content:center;padding:5px 2px;font-size:8px}}\n"

    backup(MAIN)
    backup(INDEX)
    backup(STYLE)
    backup(ANALYSIS)
    MAIN.write_text(main_text, encoding="utf-8", newline="\n")
    INDEX.write_text(index_text, encoding="utf-8", newline="\n")
    STYLE.write_text(style_text, encoding="utf-8", newline="\n")
    ANALYSIS.write_text(analysis_text, encoding="utf-8", newline="\n")
    print("Mise à jour appliquée : audit scientifique, API /api/science, menu latéral et classement lissé.")
    print("Aucun mot de passe ni aucune variable secrète n'ont été ajoutés aux fichiers.")
    print("Prochaine étape : python -m pytest tests puis git add/commit/push.")


if __name__ == "__main__":
    main()
