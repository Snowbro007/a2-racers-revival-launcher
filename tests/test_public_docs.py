"""Public-documentation boundary tests use synthetic paths, never the private Git index."""
import contextlib
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from tools import check_public_docs as docs
from tools import prepare_public_release as export


class PublicDocsTests(unittest.TestCase):
    def test_allowed_user_and_build_docs_do_not_block_implementation_or_ci(self):
        paths = sorted(docs.PUBLIC_NARRATIVE_FILES) + [
            'tools/game_library.py', 'tests/test_game_library.py',
            '.github/workflows/installer-validation.yml',
            'assets/a2racer1/test.pcx', '.gitignore', 'public-release.json',
        ]
        self.assertEqual(docs.check_paths(paths), len(paths))
        self.assertEqual(len(docs.PUBLIC_DOCS), 9)

    def test_internal_documents_are_refused_in_docs_even_with_nontext_extensions(self):
        for path in ('docs/roadmap.md', 'docs/new-onboarding-20261021.md',
                     'docs/fan-distribution-review-20261021.md',
                     'docs/signing-preparation.md', 'docs/research/notes.json',
                     'docs/private.dat', 'docs/unknown'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'documentatie'):
                docs.check_paths([path])

    def test_narrative_documents_elsewhere_are_refused(self):
        for path in ('ROADMAP.md', 'notes/research.txt', 'tools/review.rst',
                     'tests/fixtures/history.adoc', '.github/internal.md'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'documentatie'):
                docs.check_paths([path])

    def test_case_variants_do_not_bypass_the_allowlist(self):
        for path in ('DOCS/updates.md', 'Docs/public-release.json',
                     'docs/Updates.md', 'README.MD', 'Tools/windows/msi/README.md'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'documentatie'):
                docs.check_paths([path])

    def test_ambiguous_or_unsafe_names_are_refused(self):
        for path in ('', '../README.md', '/README.md', 'docs//updates.md',
                     'docs/./updates.md', 'docs\\updates.md', 'C:/README.md',
                     'docs /private.json', 'docs/private.md ', 'docs/private.md.',
                     'tools/private\nfile.py', 'README.md\x00', None):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'bestandsnaam'):
                docs.check_paths([path])

    def test_public_export_refuses_internal_docs_even_if_added_to_package_records(self):
        for name in ('docs/roadmap.md', 'internal/research.txt', 'DOCS/private.json'):
            with self.subTest(name=name), patch.object(export.package, 'records',
                    return_value=[(name, Path('synthetic-unused-source'), None)]):
                with self.assertRaisesRegex(ValueError, 'documentatie'):
                    export.source_files(Path('synthetic-root'))

    def test_public_export_still_preserves_earlier_private_data_boundary(self):
        name = 'Gamebestanden/A2 Racer I/source.txt'
        with patch.object(export.package, 'records',
                return_value=[(name, Path('synthetic-unused-source'), None)]):
            with self.assertRaisesRegex(ValueError, 'Persoonlijk/game/componentbestand'):
                export.source_files(Path('synthetic-root'))

    def test_git_index_read_is_explicit_and_null_delimited(self):
        root = Path('synthetic-public-repository')
        with patch.object(docs.subprocess, 'check_output',
                return_value=b'README.md\x00tools/entry.py\x00') as called:
            self.assertEqual(docs.tracked_paths(root), ['README.md', 'tools/entry.py'])
        called.assert_called_once_with(['git', 'ls-files', '-z'], cwd=root)

    def test_cli_reports_synthetic_success_and_rejects_unknown_docs(self):
        stdout = io.StringIO()
        with patch.object(docs, 'tracked_paths', return_value=['README.md', 'tools/entry.py']), contextlib.redirect_stdout(stdout):
            self.assertEqual(docs.main(['--repository', 'synthetic-public']), 0)
        self.assertIn('2 getrackte bestanden', stdout.getvalue())
        stderr = io.StringIO()
        with patch.object(docs, 'tracked_paths', return_value=['docs/internal.md']), contextlib.redirect_stderr(stderr):
            self.assertEqual(docs.main(['--repository', 'synthetic-public']), 1)
        self.assertIn('docs/internal.md', stderr.getvalue())

    def test_cli_git_failure_does_not_claim_success(self):
        stderr = io.StringIO()
        with patch.object(docs, 'tracked_paths', side_effect=subprocess.CalledProcessError(128, ['git'])), contextlib.redirect_stderr(stderr):
            self.assertEqual(docs.main(['--repository', 'synthetic-public']), 1)
        self.assertTrue(stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
