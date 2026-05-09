import unittest

from factcheck_core import Claim, Evidence, infer_verdict


def judge(claim_text: str, evidence_text: str) -> dict:
    claim = Claim(id=1, text=claim_text, kind="date", page=1, query="", values=[])
    evidence = [Evidence(title="Test source", url="https://example.com", snippet=evidence_text, source="example.com")]
    return infer_verdict(claim, evidence)


class SemanticVerificationTests(unittest.TestCase):
    def test_detects_world_cup_winner_contradiction(self):
        result = judge("India won FIFA World Cup 2022", "Argentina won the FIFA World Cup 2022 after defeating France.")
        self.assertEqual(result["verdict"], "False")
        self.assertEqual(result["semantic_relation"], "contradicts")

    def test_detects_founded_year_contradiction(self):
        result = judge("Google was founded in 2015", "Google was founded in 1998 by Larry Page and Sergey Brin.")
        self.assertEqual(result["verdict"], "False")
        self.assertEqual(result["semantic_relation"], "contradicts")

    def test_accepts_acquisition_paraphrase(self):
        result = judge("Microsoft acquired LinkedIn in 2016", "Microsoft completed its acquisition of LinkedIn in 2016.")
        self.assertEqual(result["verdict"], "Verified")
        self.assertEqual(result["semantic_relation"], "entails")


if __name__ == "__main__":
    unittest.main()
