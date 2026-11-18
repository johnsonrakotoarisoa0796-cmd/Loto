# Loto Lab — analyse du Loto 5/35

Application web en français pour enregistrer les tirages 5/35 et suivre les fréquences, répétitions, écarts, paires, scores exploratoires et audits statistiques. L'interface est responsive (ordinateur, tablette et mobile) et propose trois apparences : automatique, claire et sombre. L'application ne prétend pas prédire un tirage aléatoire ni garantir un gain.

## Fonctions

- Saisie, modification et suppression d'un tirage (5 numéros distincts de 1 à 35, une date unique).
- Import CSV et export CSV de tout l'historique.
- Tableau de bord : volume de données, fréquences, dernier résultat et répétitions entre dates calendaires consécutives.
- Analyses : fréquences des 35 numéros, retours au tirage enregistré suivant, paires récurrentes et distribution des numéros communs.
- Laboratoire multi-modèles : trois classements distincts et fixes (historique + récence, fréquence globale lissée, récence courte) avec indices relatifs base 100, jamais interprétés comme des probabilités.
- Évolution des rangs : comparaison du classement hybride courant avec celui calculé avant le dernier tirage, pour afficher les numéros en progression et en recul.
- Scénarios alternatifs issus des deux autres modèles statistiques, et non de combinaisons pseudo-aléatoires.
- Backtest chronologique comparant les trois méthodes à la référence aléatoire de 0,714 numéro touché en moyenne par combinaison de cinq. L'apprentissage commence après 30 tirages ; les résultats sont explicitement qualifiés de très courts ou exploratoires lorsque l'échantillon de test est petit.
- Tendances directionnelles : comparaison de deux fenêtres de 5 tirages à partir de 10 tirages, avec un seuil fixe pour limiter les faux signaux sur de petits échantillons.
- Laboratoire climat & cosmos : signe zodiacal symbolique, phase lunaire approximative, prévisions horaires Open-Meteo, archives météo et événements sismiques du catalogue USGS autour du lieu du tirage.
- Étude de corrélations exploratoires : indicateurs du tirage (somme, amplitude, parité, petits/grands numéros, répétitions) comparés aux variables externes par Spearman, permutation déterministe et correction de Holm.
- Modèle contextuel expérimental : compare la météo prévue, la phase lunaire, le signe zodiacal symbolique et l'activité sismique récente aux contextes historiques similaires, puis combine les fréquences contextuelles avec le classement historique/récence. Le poids est plafonné à 25 % et le modèle exige au moins 30 contextes historiques horaires utilisables.
- Le backtest contextuel est chronologique et compare sa performance au modèle historique ainsi qu'à la référence aléatoire de 0,714 numéro touché en moyenne. Les résultats restent expérimentaux et ne prouvent aucun avantage prédictif.
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


### Laboratoire climat & cosmos

La page **Climat & cosmos** étudie le contexte associé aux dates historiques des tirages. Un modèle contextuel expérimental peut également utiliser ces observations pour ajuster prudemment le classement principal, lorsque l'historique et la prévision météo sont suffisants.

Pour activer les données météorologiques et sismiques, ajoute au fichier .env local ou à **Render → Environment** les variables suivantes :

~~~env
DRAW_LOCATION_NAME=Antaninarenina, Antananarivo (approximatif)
DRAW_LOCATION_LAT=-18.9103
DRAW_LOCATION_LON=47.52502
DRAW_LOCATION_IS_ESTIMATE=true
DRAW_TIME=16:35
DRAW_TIMEZONE=Indian/Antananarivo
SEISMIC_RADIUS_KM=200
SEISMIC_MIN_MAGNITUDE=2.5
~~~

Le réglage initial est **provisoire** : la documentation Bet261 indique que le Loto 5/35 peut être suivi en direct à Antaninarenina. Le point géographique utilisé correspond au centre approximatif du quartier (pas à l'emplacement vérifié d'une machine de tirage). Il doit être remplacé dans **Render → Environment** si l'opérateur ou le lieu officiel est différent. Après remplacement des coordonnées, règle DRAW_LOCATION_IS_ESTIMATE=false. Les coordonnées du lieu de tirage ne doivent jamais être remplacées par celles de l'utilisateur ou du serveur. Le fuseau par défaut est Indian/Antananarivo et l'heure de référence est 16:35.

- **Météo :** les archives Open-Meteo reconstruisent le contexte historique autour de 16:00 locale (température, humidité, pression, précipitations de l'heure précédente, vent et nébulosité). Pour le prochain tirage, le modèle récupère la prévision horaire à 16:00 locale. Les valeurs sont des estimations sur une grille, pas des mesures garanties à l'adresse exacte. Documentation : https://open-meteo.com/en/docs et https://open-meteo.com/en/docs/historical-weather-api
- **Sismicité :** le catalogue USGS fournit les événements, magnitudes, profondeurs, lieux et distances dans le rayon demandé. Pour l'apprentissage historique, seuls les événements des 24 heures précédant l'heure de coupure locale de 16:35 sont utilisés ; pour le prochain tirage, le modèle prend le snapshot connu au moment de l'actualisation. Il s'agit d'un catalogue d'événements, pas d'enregistrements de forme d'onde ou d'accélération du sol. Documentation : https://earthquake.usgs.gov/fdsnws/event/1/
- **Astronomie :** la phase lunaire et l'éclairement sont des approximations calculées à l'heure officielle du tirage, par défaut 16:35 heure de Madagascar. Indian/Antananarivo convertit cette heure locale vers UTC ; un autre fuseau IANA peut être configuré dans Render si le tirage est effectué ailleurs.
- **Astrologie :** le signe solaire est une étiquette zodiacale conventionnelle. Les résultats par signe sont descriptifs et ne constituent pas une preuve d'influence.
- **Modèle contextuel :** il exige au moins 30 tirages avec trois variables météo horaires ou plus disponibles et une prévision pour la prochaine date. Il utilise des voisins contextuels pondérés avec un lissage fort vers le classement historique/récence ; son poids ne dépasse jamais 25 %. Sans données suffisantes, le classement historique reste actif.
- **Validation :** le backtest contextuel est chronologique ; chaque date cible utilise uniquement les contextes précédant ce tirage et les valeurs horaires autour de 16:00. Un échantillon de test court ne permet pas de conclure ; il faut continuer à enregistrer les pronostics avant les tirages.
- **Astrologie :** le signe solaire est une étiquette conventionnelle, utilisée à titre symbolique et avec un poids faible. Il ne constitue pas une preuve d'influence physique.
- **Corrélations :** les tests de Spearman par permutation et la correction de Holm limitent les faux positifs exploratoires. Aucun résultat n'est présenté comme une causalité ou une garantie de prédiction.

Les archives externes sont mises en cache en mémoire pendant six heures. Aucune nouvelle table de base ni migration SQL n'est créée pour cette étude.

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
├── contextual_study.py      # Astrologie symbolique, Lune, météo et catalogue sismique
├── contextual_predictor.py  # Modèle contextuel pondéré et validation chronologique
├── app/
│   ├── database.py          # SQLAlchemy / SQLite / PostgreSQL
│   ├── main.py              # API FastAPI, import/export, authentification
│   ├── templates/           # Interface HTML
│   └── static/              # CSS, JavaScript et thème partagé
│       └── theme.js         # Apparence Auto / Clair / Sombre
├── tests/                   # Tests statistiques, audit et contexte externe
├── render.yaml
├── requirements.txt
├── INSTALLER-LOTO-LAB-PRO.ps1
├── RESTAURER-LOTO-LAB.ps1
└── sample_draws.csv
```

## Démarrage simplifié sous Windows

Après extraction du ZIP et installation de Python 3.11+, double-clique sur `DEMARRER-LOTO-LAB.bat`. Le script crée l'environnement Python, installe les dépendances et démarre l'application sur `http://127.0.0.1:8000`. Voir `GUIDE-DEMARRAGE-WINDOWS.txt`.
