import json
import sqlite3
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class InstallerDefinitionTests(unittest.TestCase):
    def test_packaging_definitions_include_runtime_payload(self):
        spec = (PROJECT_ROOT / "installer" / "TheologiaSearch.spec").read_text(encoding="utf-8")
        iss = (PROJECT_ROOT / "installer" / "TheologiaSearch.iss").read_text(encoding="utf-8")
        build_script = (PROJECT_ROOT / "installer" / "build_installer.ps1").read_text(encoding="utf-8")
        verifier = (PROJECT_ROOT / "installer" / "verify_package.py").read_text(encoding="utf-8")
        self.assertIn('semantic_index.sqlite', spec)
        self.assertNotIn('morphology_terms.json', spec)
        self.assertNotIn('concept_query_lexicon.json', spec)
        self.assertNotIn('author_periods.json', spec)
        self.assertIn('assets', spec)
        self.assertIn('console=False', spec)
        self.assertIn('PrivilegesRequired=lowest', iss)
        self.assertIn('Theologia Search Setup', iss)
        self.assertIn('--self-test', build_script)
        self.assertIn('dataset_version', verifier)
        self.assertIn('obsolete_resources', verifier)
        self.assertNotIn('morphology_config_digest', verifier)
        self.assertIn('evidence_mentioned_authors', verifier)

    def test_packaged_source_statistics_match_manifest(self):
        manifest = json.loads((PROJECT_ROOT / "generated" / "index_manifest.json").read_text(encoding="utf-8"))
        with sqlite3.connect(PROJECT_ROOT / "generated" / "semantic_index.sqlite") as con:
            sqlite_version = con.execute(
                "SELECT value FROM metadata WHERE key = 'dataset_version'"
            ).fetchone()[0]
            self.assertEqual(manifest["evidence_count"], con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0])
            self.assertEqual(manifest["author_period_count"], con.execute("SELECT COUNT(*) FROM author_periods").fetchone()[0])
            self.assertEqual(manifest["dataset_version"], sqlite_version)
            self.assertGreaterEqual(con.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 287)
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertNotIn("morphology_forms", tables)
            self.assertNotIn("evidence_morphology", tables)
            self.assertNotIn("morphology_stats", tables)


if __name__ == "__main__":
    unittest.main()
