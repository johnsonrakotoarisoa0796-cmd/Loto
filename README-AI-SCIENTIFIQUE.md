# LOTO LAB — Mise à niveau « Laboratoire scientifique »

Cette extension ajoute un espace séparé **Audit scientifique** à l'application existante.

## Ce que fait le moteur

- Teste les 35 fréquences individuelles avec le modèle marginal binomial `p = 1/7`.
- Teste les 595 cooccurrences de paires avec `p = 2/119`.
- Examine les dépendances aux retards 1 à 5 avec la loi hypergéométrique des recouvrements de deux tirages 5/35.
- Applique une correction globale Holm-Bonferroni pour limiter les faux positifs provoqués par les comparaisons multiples.
- Évalue le classement par des prévisions chronologiques hors échantillon : chaque prévision n'utilise que les tirages antérieurs.
- Utilise un lissage bayésien fort, des paramètres fixes et aucune optimisation sur la période de test.
- N'annonce un avantage candidat que si la performance dépasse le hasard dans deux périodes de test séparées et avec un seuil statistique strict.

## Installation sur Windows

1. Fais une copie de sauvegarde de `E:\LOTO\Loto-Lab-5-35`.
2. Extrais le contenu de ce ZIP directement dans `E:\LOTO\Loto-Lab-5-35`, en conservant les sous-dossiers `app` et `tests`.
3. Ouvre PowerShell dans ce dossier.
4. Exécute :

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\APPLIQUER-MAJ-IA.ps1
```

Le script crée automatiquement des copies `.bak` de `app/main.py`, `app/templates/index.html`, `app/static/style.css` et `analysis_engine.py` avant de les modifier. Il renforce aussi le lissage du classement historique (prior 70 tirages, demi-vie 40 tirages) et repousse le début du backtest à 60 tirages d’apprentissage.

## Tests et publication

```powershell
python -m pytest tests -q
git status
git add .
git commit -m "Add conservative scientific anomaly audit"
git -c http.version=HTTP/1.1 push
```

Le push déclenchera le redéploiement Render si l'auto-déploiement est activé.

Après le déploiement, ouvre `https://loto-ca93.onrender.com/science` ou utilise le nouveau lien **Audit scientifique** dans le menu latéral.

## Interprétation

Un p-value ajusté faible signale une observation à répliquer, pas une preuve de manipulation. Une absence de signal ne prouve pas le caractère parfaitement aléatoire. Le tirage théorique équitable demeure indépendant : chaque numéro conserve une probabilité marginale de 1/7 à chaque tirage et chaque combinaison de 5 numéros distincts garde la même probabilité.

Le module est volontairement un moteur statistique explicable, et non un réseau neuronal opaque : empiler un modèle plus complexe sur un historique court augmenterait le risque de surapprentissage sans créer d'information prédictive.
