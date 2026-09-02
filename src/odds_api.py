"""
Client partage pour The Odds API: cache disque, suivi du quota, maths no-vig.

Pourquoi un client partage plutot que le _get() prive de chaque fetcher:

  1. QUOTA. Le quota est MENSUEL et depend du palier de l'abonnement; on ne
     le devine pas, on le lit dans l'en-tete `x-requests-remaining` de chaque
     reponse. Sur l'endpoint /sports/{sport}/odds un appel coute 1 credit par
     (marche x region). Sur l'endpoint event (/events/{id}/odds), celui des
     props joueurs, il coute 10 credits par (marche x region): un slate de 15
     matchs sur pitcher_strikeouts en us+eu = 15 x 2 x 10 = 300 credits pour
     UNE execution, donc 7200 par jour en cron horaire. Un quota epuise
     renvoie 401/429, qui se traduisait par une liste de props vide et des
     bets enregistres avec cote 0 — une panne silencieuse.

     D'ou le rythme adaptatif (voir affordable_events): la depense autorisee
     par execution vient du quota REELLEMENT restant et du nombre de jours
     jusqu'a la fin du mois. Sur un gros palier, la couverture reste complete;
     sur un petit, elle se reduit d'elle-meme au lieu d'epuiser le mois.
  2. CACHE. Plusieurs modules demandent les memes evenements dans une meme
     execution (props MLB, moneyline, CLV). Sans cache partage on paie deux fois.
  3. VISIBILITE. Le quota restant doit apparaitre dans les logs et dans le
     dashboard, sinon la panne est silencieuse.

Reglages par variables d'environnement:
  ODDS_REGIONS            regions demandees (defaut "us,eu"; Pinnacle est en eu)
  ODDS_CACHE_TTL          duree du cache en secondes (defaut 1800 = 30 min)
  ODDS_CACHE_DIR          repertoire du cache (defaut <depot>/.cache/odds)
  ODDS_QUOTA_RESERVE      credits gardes en reserve (defaut 40)
  ODDS_MAX_PROP_EVENTS    plafond dur d'evenements props par execution (defaut 15)
  ODDS_USAGE_PATH         fichier de suivi quotidien (defaut docs/odds_usage.json)
  ODDS_PROPS_ENABLED      "0" pour couper les appels props (defaut actif)
  ODDS_PROPS_HOURS_ET     fenetre horaire ET ou les props sont payees
                          (defaut "10-23": pas de depense la nuit)
"""
from __future__ import annotations

import hashlib
import json
import os
import time

import requests

BASE_URL = "https://api.the-odds-api.com/v4"

PINNACLE = "pinnacle"

# Cout en credits d'un appel, par (marche x region).
COST_PER_MARKET_REGION      = 1
COST_PER_MARKET_REGION_PROP = 10

_HERE = os.path.dirname(os.path.abspath(__file__))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def regions() -> str:
    """Regions demandees. Pinnacle n'existe que dans la region `eu`."""
    return os.environ.get("ODDS_REGIONS", "us,eu")


def cache_ttl() -> int:
    return _env_int("ODDS_CACHE_TTL", 1800)


def cache_dir() -> str:
    return os.environ.get("ODDS_CACHE_DIR") or os.path.join(_HERE, "..", ".cache", "odds")


def quota_reserve() -> int:
    return _env_int("ODDS_QUOTA_RESERVE", 40)


def max_prop_events() -> int:
    """Plafond DUR, indepedant du quota. 15 = tous les matchs d'un slate MLB."""
    return _env_int("ODDS_MAX_PROP_EVENTS", 15)


def props_enabled() -> bool:
    """Interrupteur global des appels props (mode economie)."""
    return os.environ.get("ODDS_PROPS_ENABLED", "1") not in ("0", "false", "False")


def props_window() -> tuple:
    """Fenetre horaire ET pendant laquelle on accepte de payer des props."""
    raw = os.environ.get("ODDS_PROPS_HOURS_ET", "10-23")
    try:
        a, b = raw.split("-")
        return int(a), int(b)
    except Exception:
        return 10, 23


_window_warned = False


def props_window_open(hour_et: int = None) -> bool:
    """
    Le budget du jour est fini: autant le depenser sur des cotes qui servent.

    Le cron tourne 24 fois par jour, mais une cote captee a 3h du matin aura
    bouge avant le premier lancer, et c'est la depense du jour qui aura ete
    consommee — les executions de l'apres-midi trouveraient la caisse vide.
    On ne paie donc des props que dans la fenetre ou le slate est proche
    (defaut 10h-23h ET, reglable par ODDS_PROPS_HOURS_ET).
    """
    global _window_warned
    from datetime import datetime, timedelta, timezone
    h = hour_et if hour_et is not None else (
        datetime.now(timezone.utc) - timedelta(hours=4)).hour
    start, end = props_window()
    ok = start <= h <= end
    if not ok and not _window_warned:
        _window_warned = True
        print(f"  [Odds API] {h}h ET hors de la fenetre props {start}h-{end}h — "
              f"aucun credit props depense cette execution "
              f"(ODDS_PROPS_HOURS_ET pour changer)")
    return ok


def usage_path() -> str:
    """
    Fichier de suivi de la depense du JOUR. Il vit dans docs/ pour etre commite
    par le workflow: en CI chaque execution repart d'un disque vide, donc le
    cache et un compteur en memoire ne survivent pas d'une heure a l'autre.
    Le seul etat qui traverse les executions est le depot lui-meme.
    """
    return os.environ.get("ODDS_USAGE_PATH") or os.path.join(
        _HERE, "..", "docs", "odds_usage.json")


def today_et() -> str:
    """Date ET: le signal raisonne en jour de calendrier ET, pas en UTC."""
    from datetime import datetime, timedelta, timezone
    # -4h/-5h selon l'heure avancee; l'approximation -4h suffit pour dater un
    # compteur quotidien (la bascule tombe entre 20h et 21h ET, hors des
    # heures ou le slate est actif).
    return (datetime.now(timezone.utc) - timedelta(hours=4)).strftime("%Y-%m-%d")


def days_left_in_month(now=None) -> int:
    """Jours restants dans le mois courant, aujourd'hui inclus (minimum 1)."""
    import calendar
    from datetime import date
    d = now or date.today()
    return max(calendar.monthrange(d.year, d.month)[1] - d.day + 1, 1)


def load_usage() -> dict:
    """Etat du jour: {date, remaining_at_start, updated_at}. {} si absent."""
    try:
        with open(usage_path(), "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_usage(state: dict) -> None:
    try:
        path = usage_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print(f"  [Odds API] suivi quotidien non ecrit: {e}")


def daily_budget(remaining, now=None) -> int:
    """
    Credits que la JOURNEE peut depenser sans compromettre la fin du mois:

        (restant - reserve) / jours_restants_dans_le_mois

    Pourquoi par jour et non par execution: un budget par execution multiplie
    par 24 crons redonne une depense mensuelle enorme (1 appel props de 20
    credits par heure = ~14 000 credits par mois). Le quota etant mensuel,
    c'est la journee qui doit etre plafonnee, et les executions se partagent ce
    plafond via le compteur persiste.

    `remaining` inconnu -> None: aucun rythme impose, le premier appel paye
    revelera le quota.
    """
    if remaining is None:
        return None
    usable = remaining - quota_reserve()
    if usable <= 0:
        return 0
    return int(usable / days_left_in_month(now))


# ── Maths no-vig ─────────────────────────────────────────────────────────────

def implied(odds: float) -> float:
    """Probabilite implicite brute (avec vig) d'une cote decimale, en [0, 1]."""
    try:
        o = float(odds)
    except (TypeError, ValueError):
        return 0.0
    return (1.0 / o) if o > 1.0 else 0.0


def novig_two_way(over_odds: float, under_odds: float):
    """
    Probabilite no-vig du Over sur un marche a deux issues:
        p_novig = p_over / (p_over + p_under),  p = 1 / cote

    Retourne None si l'un des deux cotes manque: sans les deux faces on ne peut
    pas retirer la marge, et prendre 1/cote a la place surestime la probabilite
    du marche de ~2 a 5 points (c'est la vig qu'on s'attribuerait comme edge).
    """
    p_o = implied(over_odds)
    p_u = implied(under_odds)
    if p_o <= 0 or p_u <= 0:
        return None
    total = p_o + p_u
    if total <= 0:
        return None
    return p_o / total


def ev_pct(our_prob_pct: float, odds: float) -> float:
    """
    Esperance en % de la mise: (p x cote) - 1. C'est la formule demandee pour
    l'affichage du ladder, et la meme que celle du modele moneyline.
    Attention: ce n'est PAS la meme grandeur que `edge_pct` de l'analyzer, qui
    est un ecart relatif de probabilites ((p - p_marche) / p_marche).
    """
    try:
        o = float(odds)
        p = float(our_prob_pct) / 100.0
    except (TypeError, ValueError):
        return 0.0
    if o <= 1.0 or p <= 0:
        return 0.0
    return round((p * o - 1.0) * 100, 2)


# ── Client ───────────────────────────────────────────────────────────────────

class OddsAPIClient:
    """
    Un seul client par execution (voir get_client). Compte les credits, cache
    les reponses sur disque, et refuse les appels quand le quota approche de la
    reserve — un refus explicite vaut mieux qu'un 401 traduit en zero cote.
    """

    def __init__(self, api_key: str):
        self.api_key      = api_key or ""
        self.remaining    = None    # credits restants (depuis les en-tetes)
        self.used         = None
        self.calls        = 0       # appels reseau reellement effectues
        self.cache_hits   = 0
        self.credits_spent = 0
        self.refused      = 0       # appels bloques par la reserve de quota
        self.errors       = []      # messages courts, pour le dashboard
        self.key_invalid  = False
        self.quota_out    = False
        self._memo: dict  = {}
        self.prop_credits = 0      # credits depenses en props cette execution
        self._budget      = "?"    # "?" = pas encore calcule (voir day_budget)
        self._usage       = None   # etat du jour lu dans docs/odds_usage.json

    # ── cache ────────────────────────────────────────────────────────────────
    @staticmethod
    def _key(endpoint: str, params: dict) -> str:
        clean = {k: v for k, v in sorted((params or {}).items()) if k != "apiKey"}
        raw   = endpoint + "?" + json.dumps(clean, sort_keys=True)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> str:
        return os.path.join(cache_dir(), key + ".json")

    def _cache_read(self, key: str):
        if key in self._memo:
            return self._memo[key]
        path = self._cache_path(key)
        try:
            if not os.path.isfile(path):
                return None
            if (time.time() - os.path.getmtime(path)) > cache_ttl():
                return None
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self._memo[key] = payload
            return payload
        except Exception:
            return None

    def _cache_write(self, key: str, payload) -> None:
        self._memo[key] = payload
        try:
            os.makedirs(cache_dir(), exist_ok=True)
            tmp = self._cache_path(key) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, self._cache_path(key))
        except Exception:
            pass   # un cache non ecrit n'est pas une erreur fatale

    # ── requetes ─────────────────────────────────────────────────────────────
    def get(self, endpoint: str, params: dict, cost: int = 1):
        """
        Appel GET cache. `cost` est le cout estime en credits, utilise pour le
        garde-fou de reserve et le comptage. Retourne le JSON ou None.
        """
        key    = self._key(endpoint, params)
        cached = self._cache_read(key)
        if cached is not None:
            self.cache_hits += 1
            return cached

        if not self.api_key:
            self._note("cle absente")
            return None
        if self.key_invalid or self.quota_out:
            self.refused += 1
            return None
        if self.remaining is not None and (self.remaining - cost) < quota_reserve():
            self.refused += 1
            self._note(f"appel refuse: {self.remaining} credits restants "
                       f"< reserve {quota_reserve()} + cout {cost}")
            return None

        p = dict(params or {})
        p["apiKey"] = self.api_key
        try:
            r = requests.get(f"{BASE_URL}/{endpoint}", params=p, timeout=15)
        except Exception as e:
            self._note(f"reseau: {e}")
            return None

        self.calls += 1
        self.credits_spent += cost
        rem = r.headers.get("x-requests-remaining")
        use = r.headers.get("x-requests-used")
        if rem is not None:
            try:
                self.remaining = int(float(rem))
            except ValueError:
                pass
        if use is not None:
            try:
                self.used = int(float(use))
            except ValueError:
                pass

        if r.status_code == 200:
            try:
                payload = r.json()
            except Exception as e:
                self._note(f"JSON illisible: {e}")
                return None
            self._cache_write(key, payload)
            return payload

        if r.status_code == 401:
            self.key_invalid = True
            self._note("401: cle refusee (ODDS_API_KEY invalide ou revoquee)")
        elif r.status_code == 429:
            self.quota_out = True
            self._note("429: quota epuise")
        elif r.status_code not in (404, 422):
            # 404/422 = marche non offert pour cet evenement: cas normal.
            self._note(f"{r.status_code} sur {endpoint}")
        return None

    # ── rythme de depense ────────────────────────────────────────────────────
    def usage(self) -> dict:
        """
        Compteur du jour, cale sur le quota reel. `remaining_at_start` est le
        quota au debut de la journee ET; la depense du jour s'en deduit par
        soustraction, ce qui reste juste meme si une execution plante en cours
        de route (on ne fait jamais confiance a notre propre addition).
        """
        if self._usage is None:
            st  = load_usage()
            day = today_et()
            if st.get("date") != day or st.get("remaining_at_start") is None:
                st = {"date": day, "remaining_at_start": self.remaining}
            elif self.remaining is not None and self.remaining > st["remaining_at_start"]:
                # Le quota est remonte: renouvellement du plan en cours de mois.
                st["remaining_at_start"] = self.remaining
            self._usage = st
        if self._usage.get("remaining_at_start") is None:
            self._usage["remaining_at_start"] = self.remaining
        return self._usage

    def spent_today(self) -> int:
        st = self.usage()
        start = st.get("remaining_at_start")
        if start is None or self.remaining is None:
            return 0
        return max(start - self.remaining, 0)

    def day_budget(self):
        """
        Credits autorises pour la journee, fige des le premier calcul pour ne
        pas glisser a mesure que `remaining` diminue.
        None = quota encore inconnu, aucun rythme impose.
        """
        if self._budget == "?":
            self._budget = daily_budget(self.remaining)
        return self._budget

    def can_spend_props(self, cost: int) -> bool:
        """
        Autorise un appel props si la JOURNEE a encore du budget. Toutes les
        executions du jour se partagent ce plafond via le compteur persiste.

        Pas d'exception "premier appel": sur un petit palier, un appel props
        par execution horaire suffit a vider le quota du mois. Quand le budget
        du jour est plus petit qu'un seul appel, les props sont coupees et le
        dashboard bascule sur le calculateur manuel — c'est dit dans le log et
        dans le bandeau, pas silencieux.
        """
        budget = self.day_budget()
        if budget is None:
            return True
        return (self.spent_today() + self.prop_credits + cost) <= budget

    def note_props(self, cost: int) -> None:
        self.prop_credits += cost

    def persist_usage(self) -> None:
        """A appeler en fin d'execution: fige la journee pour les crons suivants."""
        st = dict(self.usage())
        st["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        st["remaining"]  = self.remaining
        st["spent_today"] = self.spent_today()
        st["day_budget"] = self.day_budget()
        save_usage(st)

    def _note(self, msg: str) -> None:
        if msg not in self.errors:
            self.errors.append(msg)
        print(f"  [Odds API] {msg}")

    # ── etat ─────────────────────────────────────────────────────────────────
    @property
    def healthy(self) -> bool:
        """False => les consommateurs doivent basculer sur le fallback manuel."""
        return bool(self.api_key) and not self.key_invalid and not self.quota_out

    def status(self) -> dict:
        return {
            "remaining":     self.remaining,
            "used":          self.used,
            "calls":         self.calls,
            "cache_hits":    self.cache_hits,
            "credits_spent": self.credits_spent,
            "refused":       self.refused,
            "day_budget":    self.day_budget(),
            "spent_today":   self.spent_today(),
            "prop_credits":  self.prop_credits,
            "regions":       regions(),
            "cache_ttl_s":   cache_ttl(),
            "healthy":       self.healthy,
            "errors":        list(self.errors),
        }

    def log_status(self, label: str = "") -> None:
        s = self.status()
        budget = s["day_budget"]
        print(f"  [Odds API] {label}quota restant: {s['remaining']} | "
              f"{s['calls']} appel(s) ~{s['credits_spent']} credits | "
              f"{s['cache_hits']} depuis le cache | {s['refused']} refuse(s) | "
              f"regions {s['regions']} | jour: {s['spent_today']}/"
              f"{'illimite' if budget is None else budget} credits")


_client: OddsAPIClient = None


def get_client(api_key: str = None) -> OddsAPIClient:
    """Client unique du process (cache et compteur de quota partages)."""
    global _client
    if _client is None:
        _client = OddsAPIClient(api_key or os.environ.get("ODDS_API_KEY", ""))
    elif api_key and not _client.api_key:
        _client.api_key = api_key
    return _client


def reset_client() -> None:
    """Pour les tests."""
    global _client
    _client = None


# ── Agregation multi-books ───────────────────────────────────────────────────

def summarize_two_way(books: list) -> dict:
    """
    Resume un marche Over/Under a partir des cotes de plusieurs books.

    `books` = [{"book": str, "over_odds": float, "under_odds": float}, ...]

    Retourne:
      best_over_odds / best_over_book : la cote Over la plus generreuse (c'est
          elle qui determine l'EV — on mise chez le book le plus cher)
      baseline_prob / baseline_source : probabilite no-vig de reference du
          marche. Pinnacle en priorite (le book le plus efficient, marge la plus
          faible); sinon la MEDIANE des probs no-vig des autres books, plus
          robuste qu'une moyenne face a un book aberrant.
      n_books / n_novig : nombre de books, dont ceux ou le devig est possible
    """
    entries = []
    for b in books or []:
        o = b.get("over_odds")
        u = b.get("under_odds")
        if not o:
            continue
        entries.append({
            "book":         b.get("book", ""),
            "over_odds":    float(o),
            "under_odds":   float(u) if u else None,
            "over_implied": round(implied(o) * 100, 2),
            "over_novig":   None,
        })
        nv = novig_two_way(o, u)
        if nv is not None:
            entries[-1]["over_novig"] = round(nv * 100, 2)

    if not entries:
        return {
            "books": [], "best_over_odds": 0, "best_over_book": "",
            "best_under_odds": 0, "baseline_prob": 0, "baseline_source": "aucune",
            "n_books": 0, "n_novig": 0,
        }

    best = max(entries, key=lambda e: e["over_odds"])
    best_under = max((e["under_odds"] for e in entries if e["under_odds"]), default=0)

    pin = next((e for e in entries if e["book"] == PINNACLE and e["over_novig"] is not None), None)
    if pin is not None:
        baseline, source = pin["over_novig"], PINNACLE
    else:
        novigs = sorted(e["over_novig"] for e in entries if e["over_novig"] is not None)
        if novigs:
            mid = len(novigs) // 2
            baseline = (novigs[mid] if len(novigs) % 2
                        else round((novigs[mid - 1] + novigs[mid]) / 2, 2))
            source = f"mediane no-vig ({len(novigs)} books)"
        else:
            # Aucun book ne donne les deux faces: on retombe sur la prob brute
            # du meilleur Over, en le signalant (elle contient la vig).
            baseline, source = best["over_implied"], "brute (vig incluse)"

    return {
        "books":            sorted(entries, key=lambda e: -e["over_odds"]),
        "best_over_odds":   round(best["over_odds"], 3),
        "best_over_book":   best["book"],
        "best_under_odds":  round(best_under, 3) if best_under else 0,
        "baseline_prob":    round(baseline, 2),
        "baseline_source":  source,
        "n_books":          len(entries),
        "n_novig":          sum(1 for e in entries if e["over_novig"] is not None),
    }
