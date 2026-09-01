"""
Chargeur .env minimal, sans dependance (pas de python-dotenv a installer).

Pourquoi: tous les scripts lisent os.environ.get("ODDS_API_KEY"). Ecrire la cle
dans un fichier .env ne suffisait pas — personne ne le lisait, et `python
signal.py` sortait sur "Variable ODDS_API_KEY manquante" malgre le fichier.

Regle importante: une variable deja presente dans l'environnement n'est JAMAIS
remplacee. En CI les secrets GitHub Actions arrivent par l'environnement et
doivent gagner sur tout fichier qui traine.
"""
import os

# Les scripts tournent avec cwd=src (`cd src && python signal.py`), donc le .env
# de la racine du depot est un cran au-dessus.
_HERE = os.path.dirname(os.path.abspath(__file__))


def _candidates(filename: str) -> list:
    return [
        os.path.join(os.getcwd(), filename),
        os.path.join(os.getcwd(), "..", filename),
        os.path.join(_HERE, "..", filename),
        os.path.join(_HERE, filename),
    ]


def _parse_line(line: str):
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[len("export "):].strip()
    if "=" not in line:
        return None
    key, _, value = line.partition("=")
    key   = key.strip()
    value = value.strip()
    # Retire les guillemets englobants, sans toucher au contenu.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    if not key:
        return None
    return key, value


def load_env(filename: str = ".env", verbose: bool = True) -> list:
    """
    Charge le premier .env trouve dans os.environ. Retourne la liste des cles
    effectivement injectees (donc pas celles deja definies dans l'environnement).
    Ne leve jamais: un .env absent est le cas normal en CI.
    """
    injected = []
    for path in _candidates(filename):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for raw in f:
                    pair = _parse_line(raw)
                    if not pair:
                        continue
                    key, value = pair
                    if key in os.environ:      # l'environnement a priorite
                        continue
                    os.environ[key] = value
                    injected.append(key)
        except Exception as e:
            print(f"  [env] Lecture de {path} impossible: {e}")
            return injected
        if verbose:
            # On affiche les NOMS des cles, jamais les valeurs.
            noms = ", ".join(injected) if injected else "aucune (deja definies)"
            print(f"  [env] {os.path.relpath(path)} charge → {noms}")
        return injected
    return injected
