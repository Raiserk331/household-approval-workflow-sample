"""Fresh-process checks, synthetic data only."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('workflow.py').resolve()


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic-draft-')
        self.folder = Path(self.temp.name)
        self.state = self.folder / 'state'
        self.value = {'meeting_id': 'example-001', 'notes': 'Synthetic discussion. Time not confirmed.',
                      'proposedDraft': 'Draft: Please confirm the time. Nothing has been sent or booked.'}
        self.input = self.folder / 'input.json'
        self.input.write_text(json.dumps(self.value))

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args, success=True):
        run = subprocess.run([sys.executable, str(SCRIPT), '--state', str(self.state), *args],
                             capture_output=True, text=True, timeout=5)
        self.assertEqual(run.returncode, 0 if success else 2, run.stderr + run.stdout)
        return json.loads(run.stdout)

    def approved(self):
        item = self.cli('ingest', str(self.input))
        self.cli('approve', self.value['meeting_id'], '--digest', item['digest'])
        return item

    def test_fresh_process_persistence_and_exact_draft_export(self):
        item = self.cli('ingest', str(self.input))
        self.assertEqual(self.cli('show', 'example-001')['content'], self.value)
        self.cli('approve', 'example-001', '--digest', item['digest'])
        exported = self.cli('export', 'example-001')
        self.assertEqual(Path(exported['file']).read_text(), self.value['proposedDraft'] + '\n')
        self.assertEqual(self.cli('show', 'example-001')['state'], 'exported')
        self.assertEqual(self.cli('export', 'example-001')['file'], exported['file'])

    def test_duplicate_is_durable_and_conflict_leaves_approval_unchanged(self):
        original = self.approved()
        repeat = self.cli('ingest', str(self.input))
        self.assertTrue(repeat['duplicate']); self.assertEqual(repeat['state'], 'approved')
        self.input.write_text(json.dumps({**self.value, 'proposedDraft': 'Different content'}))
        refused = self.cli('ingest', str(self.input), success=False)
        self.assertIn('conflicting content', refused['error'])
        saved = self.cli('show', 'example-001')
        self.assertEqual(saved['digest'], original['digest'])
        self.assertEqual(saved['state'], 'approved')
        with sqlite3.connect(self.state / 'workflow.sqlite') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM drafts').fetchone()[0], 1)

    def test_pending_cannot_export_and_wrong_digest_cannot_approve(self):
        self.cli('ingest', str(self.input))
        self.cli('export', 'example-001', success=False)
        self.cli('approve', 'example-001', '--digest', 'wrong', success=False)
        self.assertEqual(self.cli('show', 'example-001')['state'], 'pending')
        self.assertFalse((self.state / 'exports').exists())

    def test_stop_created_after_approval_blocks_export(self):
        self.approved(); (self.state / 'STOP').touch()
        self.cli('export', 'example-001', success=False)
        self.assertFalse((self.state / 'exports').exists())
        self.assertEqual(self.cli('show', 'example-001')['state'], 'approved')

    def test_storage_edit_with_or_without_updated_digest_invalidates_approval(self):
        item = self.approved()
        with sqlite3.connect(self.state / 'workflow.sqlite') as db:
            db.execute('UPDATE drafts SET payload=?', (json.dumps({**self.value, 'proposedDraft': 'Changed'}),))
        self.cli('export', 'example-001', success=False)
        # Even if the current-content hash is recomputed, old approval is for another digest.
        import hashlib
        changed = {**self.value, 'proposedDraft': 'Changed'}
        current = hashlib.sha256(json.dumps(changed, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertNotEqual(current, item['digest'])
        with sqlite3.connect(self.state / 'workflow.sqlite') as db:
            db.execute('UPDATE drafts SET digest=?', (current,))
        self.cli('export', 'example-001', success=False)
        self.assertFalse((self.state / 'exports').exists())

    def test_existing_conflicting_export_not_overwritten(self):
        self.approved(); (self.state / 'exports').mkdir()
        output = self.state / 'exports/example-001.md'; output.write_text('Unrelated existing file')
        self.cli('export', 'example-001', success=False)
        self.assertEqual(output.read_text(), 'Unrelated existing file')

    def test_path_like_id_and_duplicate_json_keys_rejected(self):
        self.input.write_text(json.dumps({**self.value, 'meeting_id': '../escape'}))
        self.cli('ingest', str(self.input), success=False)
        self.input.write_text('{"meeting_id":"example-001","notes":"a","notes":"b","proposedDraft":"c"}')
        self.cli('ingest', str(self.input), success=False)


if __name__ == '__main__':
    unittest.main()
