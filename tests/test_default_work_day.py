"""Single-clock shorthand freezes noon lunch, five afternoon hours and default OT."""
import json
import unittest

import test_commit_intervals as fixture
from test_commit_intervals import DATE, commit
from activity_snapshot import read_snapshot
from work_windows import default_work_day_windows


WINDOWS = [{'start': '08:30', 'end': '12:00'}, {'start': '13:30', 'end': '18:30'}]


class TestDefaultWorkDay(unittest.TestCase):
    def test_morning_clocks_resolve_without_afternoon_ambiguity(self):
        for text in ('08:30', '8:30', '8h30', '8:30 AM'):
            with self.subTest(text=text):
                self.assertEqual(default_work_day_windows(text), WINDOWS)
        for text in ('09:00', '11:59', '00:00'):
            windows = default_work_day_windows(text)
            self.assertEqual(windows[0]['start'], text)
            self.assertEqual(windows[0]['end'], '12:00')
            self.assertEqual(windows[1], WINDOWS[1])

    def test_invalid_or_nonmorning_input_cannot_be_reinterpreted(self):
        for text in ('12:00', '13:30', '8:30 PM', '24:00', '08:60', '',
                     '08:30-12:00', '08:30,09:00', None):
            with self.subTest(text=text), self.assertRaises(ValueError):
                default_work_day_windows(text)


class TestDefaultWorkDayPipeline(unittest.TestCase):
    setUp = fixture.TestPipelineCommitIntervals.setUp
    invoke = fixture.TestPipelineCommitIntervals.invoke

    def prepare(self, start='08:30', *extra):
        return self.invoke('--phase', 'prepare', '--snapshot', str(self.snapshot),
                           '--work-day-start', start, *extra)

    def rows(self):
        return json.loads((self.output / f'{DATE}.json').read_text())

    def test_only_prestart_commits_generate_ot_without_normal_placeholders(self):
        self.activities = [commit('07:30', 'early')]
        profile_before = self.profile.read_bytes()
        self.assertEqual(self.prepare(), (0, 3))
        snapshot = read_snapshot(self.snapshot)
        self.assertEqual(snapshot['schema_version'], 10)
        self.assertEqual(snapshot['normalized']['work_confirmation']['windows'], WINDOWS)
        self.assertEqual(snapshot['normalized']['overtime_review']['confirmed_windows'],
                         [{'start': '06:30', 'end': '07:30'}])
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot)), (0, 0))
        rows = self.rows()
        self.assertEqual(sum(r['entry']['duration_minutes'] for r in rows if r['work_type'] == 'NORMAL'), 0)
        self.assertEqual(sum(r['entry']['duration_minutes'] for r in rows if r['work_type'] == 'OT'), 60)
        self.assertEqual({c['hash'] for r in rows for c in r['sources']['commits']}, {'early'})
        self.assertEqual(snapshot['unassigned_activity'], [])
        self.assertTrue(all(r['time_basis'] == 'estimated' for r in rows))
        self.assertTrue(snapshot['ai_input']['blocks'])
        self.assertEqual(self.profile.read_bytes(), profile_before)

    def test_no_commits_leave_approved_hours_empty_with_no_ai_call(self):
        self.activities = []
        self.assertEqual(self.prepare(), (0, 3))
        snapshot = read_snapshot(self.snapshot)
        self.assertEqual(snapshot['normalized']['overtime_review']['status'], 'not_needed')
        self.assertEqual(snapshot['ai_input']['blocks'], [])
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot)), (0, 0))
        rows = self.rows()
        self.assertEqual(rows, [])
        manifest = json.loads((self.output / f'{DATE}.collection.json').read_text())
        self.assertEqual(manifest['token_usage']['status'], 'unknown')

    def test_ot_before_morning_during_lunch_and_after_five_afternoon_hours(self):
        self.activities = [commit('07:30', 'early'), commit('12:20', 'lunch'), commit('18:50', 'late')]
        self.assertEqual(self.prepare(), (0, 3))
        snapshot = read_snapshot(self.snapshot)
        self.assertEqual(snapshot['normalized']['overtime_review']['confirmed_windows'], [
            {'start': '06:30', 'end': '07:30'},
            {'start': '18:30', 'end': '18:50'}])
        blocks = snapshot['blocks']
        self.assertEqual(sum(b['duration_minutes'] for b in blocks if b['work_type'] == 'NORMAL'), 510)
        self.assertEqual(sum(b['duration_minutes'] for b in blocks if b['work_type'] == 'OT'), 80)
        self.assertTrue(snapshot['unassigned_activity'])
        for block in blocks:
            self.assertTrue(block['end_time'] <= '12:00' or block['start_time'] >= '13:30')

    def test_shorthand_excludes_lunch_even_with_profile_breaks_disabled(self):
        profile = json.loads(self.profile.read_text())
        profile['work_schedule'] = {'breaks': []}
        self.profile.write_text(json.dumps(profile))
        self.activities = [commit('13:09', 'lunch')]
        self.assertEqual(self.prepare(), (0, 3))
        snapshot = read_snapshot(self.snapshot)
        self.assertEqual(snapshot['normalized']['overtime_review']['confirmed_windows'], [])
        self.assertEqual(snapshot['blocks'], [])

    def test_afternoon_end_commit_is_normal_not_ot(self):
        self.activities = [commit('18:30', 'closing')]
        self.assertEqual(self.prepare(), (0, 3))
        snapshot = read_snapshot(self.snapshot)
        self.assertEqual(snapshot['normalized']['overtime_review']['confirmed_windows'], [])
        self.assertEqual(snapshot['unassigned_activity'], [])
        self.assertTrue(all(b['work_type'] == 'NORMAL' for b in snapshot['blocks']))

    def test_rerun_uses_frozen_hours_without_profile_or_recollection(self):
        self.assertEqual(self.prepare(), (0, 3))
        self.profile.write_text('{broken')
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot)), (0, 0))
        files = {p: p.read_bytes() for p in self.output.iterdir() if p.is_file()}
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot)), (0, 0))
        self.assertEqual({p: p.read_bytes() for p in files}, files)

    def test_invalid_or_conflicting_request_fails_before_source_collection(self):
        self.assertEqual(self.prepare(), (0, 3))
        before = self.snapshot.read_bytes()
        for start, extra in (('12:00', ()), ('08:60', ()),
                             ('08:30', ('--work-start', '08:30')),
                             ('08:30', ('--work-end', '17:30')),
                             ('08:30', ('--work-windows', '08:30-12:00'))):
            with self.subTest(start=start, extra=extra):
                self.assertEqual(self.prepare(start, *extra), (2, 0))
                self.assertEqual(self.snapshot.read_bytes(), before)

    def test_frozen_phases_cannot_accept_new_default_hours(self):
        self.assertEqual(self.prepare(), (0, 3))
        before = self.snapshot.read_bytes()
        for phase in ('assemble', 'confirm-ot'):
            self.assertEqual(self.invoke('--phase', phase, '--snapshot', str(self.snapshot),
                                         '--work-day-start', '09:00'), (2, 0))
        self.assertEqual(self.snapshot.read_bytes(), before)

    def test_old_python_start_only_keeps_its_original_snapshot_semantics(self):
        self.activities = [commit('07:30', 'early')]
        self.assertEqual(self.invoke('--phase', 'prepare', '--snapshot', str(self.snapshot),
                                     '--work-start', '08:30'), (0, 3))
        snapshot = read_snapshot(self.snapshot)
        self.assertNotIn('windows', snapshot['normalized']['work_confirmation'])
        self.assertNotIn('overtime_review', snapshot['normalized'])
        self.assertEqual(snapshot['blocks'], [])


if __name__ == '__main__':
    unittest.main()
