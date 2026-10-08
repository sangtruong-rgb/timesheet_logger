"""Subprocess integration: one profile governs Git and PR identity/repo/date."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from cli_fixture import write_python_cli

ROOT = Path(__file__).resolve().parent.parent
DATE = '2026-10-06'


class TestGitHubPipeline(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.output = self.directory / 'out'
        self.output.mkdir()
        self.final = self.output / f'{DATE}.json'
        self.final.write_text('EXISTING FINAL OUTPUT')
        self.ai = self.directory / 'ai.json'
        self.ai.write_text('EXISTING AI INPUT')
        self.config = self.directory / 'profile.json'
        self.config.write_text(json.dumps({'repositories': ['team/project'], 'timezone': 'Asia/Ho_Chi_Minh',
            'author': {'names': ['Sang Truong']}, 'github': {'users': ['account-one', 'account-two']}}))
        binary = self.directory / 'bin'
        binary.mkdir()
        cli = binary / 'gh'
        write_python_cli(cli, '''import json, os, sys
if sys.argv[1] == 'auth': sys.exit(0)
endpoint = sys.argv[4]
with open(os.environ['REQUEST_LOG'], 'a') as log: log.write(endpoint+'\\n')
if os.environ.get('FAIL_ENDPOINT') and os.environ['FAIL_ENDPOINT'] in endpoint: sys.exit(1)
if '/commits?' in endpoint:
    def commit(sha, login, name):
        return {'sha': sha*40, 'author': {'login': login} if login else None,
                'commit': {'author': {'name': name, 'email': 'test@test', 'date': '2026-10-05T17:01:00Z'}, 'message': 'work'}}
    print(json.dumps([commit('a', 'account-two', 'Another Name'), commit('b', None, 'Sang Truong'), commit('c', 'outsider', 'Sang Truong')]))
elif '/reviews?' in endpoint: print('[]')
elif '/pulls?' in endpoint:
    def pull(number, login):
        return {'number': number, 'title': 'work', 'user': {'login': login}, 'html_url': 'https://github.com/team/project/pull/'+str(number),
                'created_at': '2026-10-05T17:01:00Z', 'updated_at': '2026-10-06T03:00:00Z', 'merged_at': None}
    print(json.dumps([pull(1, 'account-one'), pull(2, 'account-two'), pull(3, 'outsider')]))
else: sys.exit(1)
''')
        self.requests = self.directory / 'requests.txt'
        self.env = dict(os.environ, PATH=str(binary)+os.pathsep+'/usr/bin:/bin', TZ='UTC', REQUEST_LOG=str(self.requests))
        for name in ['GH_TOKEN', 'GITHUB_TOKEN', 'PYTHONPATH']:
            self.env.pop(name, None)

    def run_pipeline(self):
        return subprocess.run([sys.executable, str(ROOT/'scripts/run_pipeline.py'), '--config', str(self.config),
            '--date', DATE, '--output-dir', str(self.output), '--export-ai-input', str(self.ai)],
            cwd=self.directory, env=self.env, capture_output=True, text=True, timeout=30)

    def draft(self):
        self.assertEqual(self.final.read_text(), 'EXISTING FINAL OUTPUT')
        self.assertEqual(self.ai.read_text(), 'EXISTING AI INPUT')
        return json.loads((self.output/'drafts'/f'{DATE}.json').read_text())

    def test_profile_applies_to_both_collectors_in_a_different_cwd(self):
        response = self.run_pipeline()
        self.assertEqual(response.returncode, 2, response.stderr)
        draft = self.draft()
        self.assertEqual(draft['collection']['sources']['git']['count'], 2)
        self.assertEqual(draft['collection']['sources']['pull_requests']['count'], 2)
        self.assertEqual(draft['activity']['timezone'], 'Asia/Ho_Chi_Minh')
        self.assertEqual({x['identity_match'] for x in draft['activity']['commits']}, {'github_login', 'name'})
        self.assertTrue(all(x['timestamp'].startswith('2026-10-06T00:01:00+07:00') for x in draft['activity']['commits']))
        self.assertTrue(all(x['repository']=='team/project' for x in draft['activity']['pull_requests']))
        self.assertTrue(all(line.startswith('repos/team/project/') for line in self.requests.read_text().splitlines()))

    def test_review_endpoint_failure_does_not_save_partial_pr_success(self):
        self.env['FAIL_ENDPOINT'] = '/reviews'
        self.assertEqual(self.run_pipeline().returncode, 2)
        draft = self.draft()
        self.assertEqual(draft['collection']['sources']['pull_requests']['status'], 'error')
        self.assertEqual(draft['activity']['pull_requests'], [])
        self.assertEqual(len(draft['activity']['commits']), 2)

    def test_remote_git_failure_is_explicit_in_pipeline_draft(self):
        self.env['FAIL_ENDPOINT'] = '/commits?'
        self.assertEqual(self.run_pipeline().returncode, 2)
        draft = self.draft()
        self.assertEqual(draft['collection']['sources']['git']['status'], 'error')
        self.assertEqual(draft['activity']['commits'], [])
        self.assertEqual(len(draft['activity']['pull_requests']), 2)


if __name__ == '__main__':
    unittest.main()
