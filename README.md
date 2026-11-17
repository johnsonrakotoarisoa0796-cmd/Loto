# Loto Lab — analyse du Loto 5/35

Application web en français pour enregistrer les tirages 5/35 et suivre les fréquences, répétitions, écarts, paires, scores exploratoires et audits statistiques. L'interface est responsive (ordinateur, tablette et mobile) et propose trois apparences : automatique, claire et sombre. L'application ne prétend pas prédire un tirage aléatoire ni garantir un gain.

## Fonctions

- Saisie, modification et suppression d'un tirage (5 numéros distincts de 1 à 35, une date unique).
- Import CSV et export CSV de tout l'historique.
- Tableau de bord : volume de données, fréquences, dernier résultat et répétitions entre dates calendaires consécutives.
- Analyses : fréquences des 35 numéros, retours au tirage enregistré suivant, paires récurrentes et distribution des numéros communs.
- Scores exploratoires recalculés après chaque changement de l’historique ; la tendance ne donne pas de direction avant 10 tirages, compare ensuite deux fenêtres de 5 tirages et utilise un seuil de 20 points pour limiter les faux signaux sur de petits échantillons.
- Audit scientifique : tests exacts des 35 fréquences et 595 paires, contrôle Holm-Bonferroni des comparaisons multiples, dépendances aux retards 1 à 5 et validation chronologique hors échantillon.
- Thème Automatique / Clair / Sombre, mémorisé dans le navigateur et synchronisé entre la connexion, le tableau de bord et l’audit scientifique.
- Enregistrement horodaté des pronostics et évaluation automatique contre le premier tirage suivant.
- Backtest chronologique : chaque prédiction n'utilise que les tirages antérieurs.
- Protection par mot de passe activée dès que `APP_PASSWORD` est défini ; cookies de session signés et protection CSRF des actions API.
- Base SQLite en local et PostgreSQL sur Render.

## Données initiales

Au premier démarrage d'une base vide, l'application insère les 7 tirages communiqués pour les dates du 8 au 14 novembre 2026. Si la base contient déjà au moins un tirage, aucun jeu de données n'est ajouté. Ces lignes peuvent être modifiées ou supprimées depuis l'historique.

## Lancer en local

Python 3.11+ recommandé.

```bash
python -m venv .venv
# Windows : .venv\Scripts\activate
# macOS/Linux : source .venv/bin/activate
pip install -r requirements.txt
```

Copie `.env.example` vers `.env`, puis définis au minimum `APP_PASSWORD` et `SECRET_KEY`. Pour lancer dans ton terminal, charge les variables d'environnement ou utilise un outil comme `python-dotenv` (non requis par l'application). Exemple PowerShell :

```powershell
$env:APP_PASSWORD = "ton-mot-de-passe"
$env:SECRET_KEY = "une-cle-longue-et-aleatoire"
uvicorn app.main:app --reload
```

Ouvre ensuite `http://127.0.0.1:8000`. Le sélecteur **Apparence** en haut de l’écran permet de choisir Automatique, Clair ou Sombre ; le choix est conservé dans ce navigateur. L’audit scientifique est disponible à `/science`.

Pour un essai local sans écran de connexion, laisse `APP_PASSWORD` vide. Ne fais pas cela pour une instance publique.

## CSV

Format recommandé :

```csv
date,n1,n2,n3,n4,n5,source,notes
2026-11-15,1,7,13,22,35,Source officielle,
```

Formats de date acceptés : `AAAA-MM-JJ` ou `JJ/MM/AAAA`. Le fichier doit être encodé en UTF-8. Un doublon parfaitement identique est ignoré ; si une date existe avec des numéros différents, l'import est refusé et le conflit est signalé.

## Tests

```bash
pytest -q
```

## Publier le code sur GitHub

Après extraction du ZIP, ouvre PowerShell dans le dossier `loto-analytics` :

```powershell
git init
git branch -M main
git remote add origin https://github.com/johnsonrakotoarisoa0796-cmd/Loto.git
git add .
git commit -m "Initial Loto Lab 5/35 application"
git push -u origin main
```

Le dépôt cible doit être vide. Si GitHub demande une authentification, utilise le compte qui possède le dépôt ou un compte auquel l'accès **Write** a été accordé.

## Déploiement Render avec Supabase

Le service web Render utilise **Supabase PostgreSQL comme base externe**. Aucun service PostgreSQL Render payant n'est créé par ce Blueprint. Le fichier `render.yaml` déclare la variable `DATABASE_URL` comme secret à fournir manuellement.

### 1. Préparer Supabase

1. Ouvre le projet Supabase qui contient l'historique Loto Lab.
2. Dans **Project Settings → Database**, récupère la chaîne de connexion PostgreSQL (Connection string).
3. Utilise le mode **Session pooler** si ton application se connecte via IPv4 ou si tu suis les recommandations de Supabase pour un hébergement applicatif persistant.
4. Ne colle jamais cette URL dans GitHub, dans le code ou dans un message public. Si le mot de passe de base a déjà été partagé, réinitialise-le dans Supabase avant de continuer.

### 2. Configurer Render

Dans le Web Service Render existant, ouvre **Environment** et vérifie les variables :

- `DATABASE_URL` : URI PostgreSQL de Supabase, avec le mot de passe actuel. L'application convertit automatiquement les URI `postgresql://` et `postgres://` au pilote psycopg 3.
- `APP_PASSWORD` : mot de passe d'accès à Loto Lab, à définir obligatoirement.
- `SECRET_KEY` : secret long et aléatoire pour signer les sessions. Render peut le générer.
- `COOKIE_SECURE=true` : active les cookies HTTPS.
- `PYTHON_VERSION=3.12.8` : version Python utilisée au build.

**Important :** le démarrage échoue volontairement sur Render si `DATABASE_URL` est absent, si la valeur pointe vers SQLite, ou si les secrets applicatifs ne sont pas définis. Cela évite de faire croire que les tirages sont sauvegardés durablement alors qu'ils seraient stockés sur le disque éphémère de Render.

### 3. Déployer et contrôler

1. Pousse la branche corrigée puis fusionne la Pull Request après vérification.
2. Laisse Render déployer le commit sur le service existant. Ne crée pas une nouvelle base Render.
3. Ouvre `https://TON-SERVICE.onrender.com/health`. La réponse doit indiquer `"status":"ok"` et `"database":"ok"`.
4. Connecte-toi et vérifie que l'historique attendu est présent avant toute opération d'écriture.
5. Ajoute un tirage de test uniquement si tu peux ensuite le supprimer, puis vérifie l'export CSV.

La route `/health` exécute maintenant une requête SQL réelle. Elle renvoie HTTP 503 si la base n'est pas joignable, sans exposer le détail de la chaîne de connexion.

## Limites statistiques importantes

Pour un tirage équitable de 5 numéros parmi 35 :

- La probabilité qu'un numéro précis sorte est `5/35 = 14,29 %` à chaque tirage.
- La probabilité qu'au moins un numéro soit commun entre deux tirages indépendants est `1 - C(30,5)/C(35,5)`, soit environ `56,1 %`.
- Le nombre moyen de numéros communs entre deux tirages est `25/35 = 0,714`.
- Une combinaison précise de 5 numéros a une probabilité de `1/C(35,5) = 1/324 632`.

Le classement combine les fréquences historiques et une composante récente plus réactive, avec un lissage modéré pour limiter les emballements dus aux petits échantillons. Les scores ne sont pas des probabilités de gain. Si le mécanisme est équitable et indépendant, aucune méthode fondée uniquement sur les anciens tirages ne peut garantir une meilleure chance au prochain tirage.

## Structure

```text
.
├── analysis_engine.py       # Statistiques descriptives et classement exploratoire
├── scientific_engine.py     # Audit scientifique et validation hors échantillon
├── app/
│   ├── database.py          # SQLAlchemy / SQLite / PostgreSQL
│   ├── main.py              # API FastAPI, import/export, authentification
│   ├── templates/           # Interface HTML
│   └── static/              # CSS, JavaScript et thème partagé
│       └── theme.js         # Apparence Auto / Clair / Sombre
├── tests/                   # Tests statistiques et tests de l’audit
├── render.yaml
├── requirements.txt
├── INSTALLER-LOTO-LAB-PRO.ps1
├── RESTAURER-LOTO-LAB.ps1
└── sample_draws.csv
```

## Démarrage simplifié sous Windows

Après extraction du ZIP et installation de Python 3.11+, double-clique sur `DEMARRER-LOTO-LAB.bat`. Le script crée l'environnement Python, installe les dépendances et démarre l'application sur `http://127.0.0.1:8000`. Voir `GUIDE-DEMARRAGE-WINDOWS.txt`.
