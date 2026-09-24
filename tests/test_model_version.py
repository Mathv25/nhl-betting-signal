"""
MODEL_VERSION: ecrite dans chaque ligne du journal, et impossible de changer
un parametre de modele sans l'incrementer (empreinte). Aucun appel reseau.
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import model_version as MV       # noqa: E402
import predictions_log as PL      # noqa: E402
import record_prediction as RP    # noqa: E402


class TestModelVersion(unittest.TestCase):

    def test_parameters_changed_without_bumping_the_version(self):
        self.assertEqual(
            MV.fingerprint(), MV.FINGERPRINT,
            "Un parametre de modele a change: incrementer MODEL_VERSION, ajouter une ligne "
            "au CHANGELOG et mettre FINGERPRINT a jour (model_version.py).")

    def test_changelog_ends_on_the_current_version(self):
        self.assertEqual(MV.CHANGELOG[-1][0], MV.MODEL_VERSION)
        versions = [v for v, _ in MV.CHANGELOG]
        self.assertEqual(versions, sorted(versions), "versions dans l'ordre")
        self.assertEqual(len(versions), len(set(versions)), "pas de version en double")

    def test_every_written_row_carries_the_version(self):
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        os.remove(path)
        try:
            start = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
            PL.upsert([{"id": "a", "sport": "mlb", "marche": "mlb_ml", "selection": "a",
                        "prob_modele": 0.5, "commence_time": start, "version_modele": "vieux"}], path)
            RP.record({"sport": "nfl", "marche": "nfl_ml", "selection": "b", "date": "2026-09-27",
                       "prob_modele": 0.5, "cote_prise": 2.1}, path)
            for r in PL.load(path):
                self.assertEqual(r["version_modele"], MV.MODEL_VERSION, r["id"])
        finally:
            if os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestBump(unittest.TestCase):

    def test_bump_rewrites_version_changelog_and_fingerprint(self):
        import datetime, importlib.util, shutil
        src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "model_version.py")
        d = tempfile.mkdtemp()
        dst = os.path.join(d, "model_version_copy.py")
        shutil.copy(src, dst)
        spec = importlib.util.spec_from_file_location("mv_copy", dst)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        new = mod.bump("essai", today=datetime.date(2031, 1, 2))
        self.assertEqual(new, "2031.01.02.1")
        spec2 = importlib.util.spec_from_file_location("mv_copy2", dst)
        mod2 = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(mod2)
        self.assertEqual(mod2.MODEL_VERSION, "2031.01.02.1")
        self.assertEqual(mod2.CHANGELOG[-1], ("2031.01.02.1", "essai"))
        self.assertEqual(mod2.FINGERPRINT, mod2.fingerprint())
        self.assertEqual(mod2.bump("encore", today=datetime.date(2031, 1, 2)), "2031.01.02.2")
