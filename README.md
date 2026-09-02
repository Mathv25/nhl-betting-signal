# 🏒 NHL Betting Signal — bet365

Signal de paris sportifs quotidien sur la NHL, exclusivement sur **bet365**.

**Modèle actuariel** : Distribution de Poisson + Kelly criterion + Validation des alignements NHL en temps réel.

---

## 🌐 Voir le signal

Le signal est publié automatiquement sur GitHub Pages chaque matin à **9h ET** :

👉 **`https://[TON-USERNAME].github.io/nhl-betting-signal`**

---

## ⚙️ Installation (1 fois)

### Étape 1 — Fork ou clone ce repo

```bash
git clone https://github.com/[TON-USERNAME]/nhl-betting-signal.git
cd nhl-betting-signal
```

### Étape 2 — Clé API The Odds API

1. Crée un compte gratuit sur [https://the-odds-api.com](https://the-odds-api.com)
2. Copie ta clé API (format: `abc123xyz456...`)
3. Dans ton repo GitHub : **Settings → Secrets and variables → Actions**
4. Clique **New repository secret**
   - Name: `ODDS_API_KEY`
   - Value: ta clé API
5. Sauvegarde

### Étape 3 — Activer GitHub Pages

1. Dans ton repo : **Settings → Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` / Folder: `/docs`
4. Sauvegarde

### Étape 4 — Activer GitHub Actions

1. Va dans l'onglet **Actions** de ton repo
2. Clique **Enable workflows**
3. Le workflow `daily_signal.yml` tourne automatiquement chaque matin à 9h ET

### Étape 5 — Premier run manuel (optionnel)

Pour tester immédiatement sans attendre 9h :

1. Onglet **Actions** → **NHL Betting Signal — Quotidien**
2. Clique **Run workflow** → **Run workflow**
3. Attends ~30 secondes, puis va sur ton GitHub Pages

---

## 📁 Structure du projet

```
nhl-betting-signal/
├── .github/
│   └── workflows/
│       └── daily_signal.yml      ← GitHub Actions (9h ET chaque jour)
├── src/
│   ├── signal.py                 ← Script principal
│   ├── odds_fetcher.py           ← Récupère les cotes bet365 (The Odds API)
│   ├── lineup_checker.py         ← Valide les alignements (NHL.com officiel)
│   ├── edge_calculator.py        ← Modèle Poisson + calcul d'edge + Kelly
│   ├── report_generator.py       ← Génère le HTML pour GitHub Pages
│   ├── odds_api.py               ← Client The Odds API (devig, cache, quota)
│   └── bet_tracker.py            ← Suivi des paris pris (yield, CLV, calibration)
├── track.py                      ← CLI de suivi des paris (add / close / stats)
├── docs/
│   ├── index.html                ← Dashboard GitHub Pages (auto-généré)
│   ├── signal.json               ← Signal brut en JSON (auto-généré)
│   ├── results.json              ← Ce que le modèle a PROPOSÉ (backtester)
│   ├── bets.json                 ← Ce qui a été MISÉ (track.py)
│   └── odds_usage.json           ← Dépense quotidienne de crédits Odds API
├── requirements.txt
└── README.md
```

---

## 📊 Méthodologie

### Modèle de probabilité (Distribution de Poisson)

Pour chaque match, le modèle calcule le nombre de buts attendu par équipe :

```
λ_domicile = (GF_domicile × GA_visiteur) / moyenne_ligue × facteur_domicile(+6%)
λ_visiteur = (GF_visiteur × GA_domicile) / moyenne_ligue × facteur_visiteur(−6%)
```

La probabilité de victoire est calculée en sommant les probabilités Poisson pour tous les scores possibles.

### Calcul de l'edge

```
Edge% = (prob_modèle − prob_implicite_b365) / prob_implicite_b365 × 100
```

Un edge ≥ 3% est requis pour qu'un bet soit recommandé.

### Kelly criterion (demi-Kelly)

```
Kelly = ((b × p) − q) / b
Mise = Kelly / 2  ← demi-Kelly pour réduire la variance
```

où `b = cote − 1`, `p = prob_modèle`, `q = 1 − p`

### Validation des alignements

Avant de recommander un prop joueur, le système vérifie via l'API officielle NHL.com que le joueur est bien dans l'alignement du jour (pas blessé, pas scratch, pas sur IR).

---

## 🎯 Types de bets analysés

| Type | Marché The Odds API | Description |
|------|--------------------|----|
| Moneyline | `h2h` | Victoire en temps réglementaire + OT/SO |
| Puck Line | `spreads` | Handicap ±1.5 buts |
| Total buts | `totals` | Over/Under |
| Props — Points | `player_points` | Over/Under points joueur |
| Props — Buts | `player_goals` | Over/Under buts joueur |
| Props — Passes | `player_assists` | Over/Under passes joueur |
| Props — Shots | `player_shots_on_goal` | Over/Under shots on goal |
| Props — Saves | `player_saves` | Over/Under arrêts gardien |

---

## ⚠️ Avertissement

Ce projet est à des fins éducatives et analytiques. Les probabilités sont des **estimations statistiques** — aucun résultat n'est garanti. Le jeu comporte des risques financiers. Jouez de façon responsable. **18+**

---

## 🔧 Utilisation en local

```bash
pip install -r requirements.txt
export ODDS_API_KEY=ta_clé_ici
cd src
python signal.py
```

Le dashboard sera généré dans `docs/index.html`.

---

## 📒 Suivi des paris pris (`track.py`)

`results.json` suit ce que le **modèle a proposé**. `bets.json` suit ce qui a
été **misé** : la cote réellement obtenue, chez quel book, pour combien, et la
cote de fermeture. Sans ça, aucun yield réel ni CLV n'est mesurable.

```bash
# Enregistrer un pari (mode guidé, questions une à une)
python track.py add

# Ou tout en une ligne
python track.py add --date 2026-09-02 --sport mlb --market props_k \
  --selection "Tarik Skubal Over 6.5 K" --prob 58 --odds 1.95 \
  --book betano --stake 1

# Renseigner les cotes de fermeture et les résultats (mode guidé)
python track.py close

# Ou un pari précis
python track.py close --id "2026-09-02|mlb|props_k|Tarik Skubal Over 6.5 K" \
  --closing-odds 1.83 --result win

python track.py list --pending      # ce qui reste à régler
python track.py stats               # les mêmes chiffres que le dashboard
```

Les statistiques sont recalculées à **chaque écriture** et stockées dans
`docs/bets.json`, que l'onglet Performance lit tel quel — le CLI et le
dashboard ne peuvent donc pas afficher des chiffres différents. Il faut
committer et pousser `docs/bets.json` pour que le dashboard en ligne les voie.

Ce qui est calculé :

| Mesure | Définition | Pourquoi |
|---|---|---|
| **Yield** | profit total / mise totale | Le rendement réel, pas l'edge théorique |
| **IC 95%** | estimateur de ratio, `Y ± 1.96·SE` | Dit quand l'échantillon est trop petit pour conclure. Sous 30 paris → marqué non fiable ; si l'intervalle contient 0, le résultat n'est pas distinguable du hasard |
| **WR + cote moyenne** | toujours affichés ensemble | 53% est excellent à 2.10 et ruineux à 1.60. Le seuil de rentabilité de la cote moyenne est donné à côté |
| **CLV** | moyenne de `cote_prise / cote_fermeture − 1` | Se mesure sans attendre les résultats, et bien moins bruité que le yield |
| **Calibration** | tranches de 5% : annoncé contre observé, avec le n | Un modèle qui dit 60% et gagne 52% n'a pas un problème de chance mais d'échelle. Une tranche sous 20 paris est marquée *mince* |
| **ROI par marché** | par marché, avec WR et cote moyenne | Repérer quel marché porte le résultat |

Les `push` sont remboursés : profit 0, et leur mise sort du dénominateur du
yield (rien n'a été risqué au règlement). Leur nombre reste affiché.
