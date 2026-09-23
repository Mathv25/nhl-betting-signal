"""
Analyse IA (ai_analyst.py): modele Sonnet 5, lecture du texte quand un bloc de
reflexion arrive en premier. Faux module `anthropic`: aucun appel reseau.
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))


class _Block:
    def __init__(self, type_, text=""):
        self.type, self.text = type_, text


def _fake_anthropic(blocks, stop="end_turn", sink=None):
    mod = types.ModuleType("anthropic")

    class _Msgs:
        def create(self, **kw):
            if sink is not None:
                sink.update(kw)
            m = types.SimpleNamespace(content=blocks, stop_reason=stop, _request_id="req_test")
            return m

    class Anthropic:
        def __init__(self, api_key=None):
            self.messages = _Msgs()

    for name in ("AuthenticationError", "RateLimitError", "APIStatusError", "APIConnectionError"):
        setattr(mod, name, type(name, (Exception,), {}))
    mod.Anthropic = Anthropic
    return mod


SIGNAL = {"date": "2026-09-23", "mlb_ml_analysis": [{"bets": [{"equipe": "X"}]}]}


class TestAIAnalyst(unittest.TestCase):

    def _run(self, blocks, stop="end_turn"):
        sink = {}
        sys.modules["anthropic"] = _fake_anthropic(blocks, stop, sink)
        sys.modules.pop("ai_analyst", None)
        os.environ["ANTHROPIC_API_KEY"] = "test"
        try:
            import ai_analyst
            return ai_analyst.run_analysis(SIGNAL), sink
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)
            sys.modules.pop("anthropic", None)
            sys.modules.pop("ai_analyst", None)

    def test_uses_sonnet_5_with_room_for_thinking(self):
        _, kw = self._run([_Block("text", '{"resume": "ok", "bets": []}')])
        self.assertEqual(kw["model"], "claude-sonnet-5")
        self.assertGreaterEqual(kw["max_tokens"], 8000)
        self.assertNotIn("temperature", kw)
        self.assertNotIn("thinking", kw, "budget_tokens est refuse sur Sonnet 5")

    def test_text_after_a_thinking_block_is_read(self):
        res, _ = self._run([_Block("thinking"), _Block("text", '{"resume": "ok", "bets": [1]}')])
        self.assertEqual(res["resume"], "ok")

    def test_refusal_returns_empty(self):
        res, _ = self._run([], stop="refusal")
        self.assertEqual(res, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
