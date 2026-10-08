"""Regressions for scoped identities, real PR action times, and local-day collection."""

import datetime
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from activity_settings import day_bounds, identity_match, settings
from collection_result import SourceUnavailable
from get_git_activity import filter_commits, get_commits_for_repo, normalize_api_commits
from get_pr_activity import collect_pr_activity, deduplicate_prs, query_gh_prs
from github_api import GitHubAPI, GitHubAPIError
from normalize_activity import normalize_all
from build_time_blocks import build_time_blocks
from prepare_ai_input import prepare_all_blocks

DATE = datetime.date(2026, 10, 6)
TZ = ZoneInfo('Asia/Ho_Chi_Minh')
IDENTITY = {'github_users': ['account-one', 'account-two'], 'names': ['Sang Truong', 'Xuan Sang'], 'emails': ['me@example.test']}


def pull(number=1, author='account-one', created='2026-10-06T02:00:00Z', merged=None, updated='2026-10-07T04:00:00Z'):
    return {'number': number, 'title': 'Real work', 'user': {'login': author},
            'html_url': f'https://github.com/team/project/pull/{number}',
            'created_at': created, 'updated_at': updated, 'merged_at': merged}


def review(number, actor='account-two', submitted='2026-10-06T03:00:00Z'):
    return {'id': number, 'user': {'login': actor}, 'submitted_at': submitted, 'state': 'APPROVED'}


class API:
    def __init__(self, pulls, reviews=None, mergers=None):
        self.pulls = pulls
        self.reviews = reviews or {}
        self.mergers = mergers or {}
        self.calls = []

    def pages(self, endpoint, **parameters):
        self.calls.append((endpoint, parameters))
        yield self.pulls

    def items(self, endpoint):
        self.calls.append((endpoint, {}))
        number = int(endpoint.split('/')[-2])
        yield from self.reviews.get(number, [])

    def get(self, endpoint):
        self.calls.append((endpoint, {}))
        if endpoint == 'user':
            return {'login': 'account-one'}
        return {'merged_by': {'login': self.mergers.get(int(endpoint.split('/')[-1]), 'someone-else')}}


class TestPersonalIdentity(unittest.TestCase):
    def test_both_accounts_are_personal(self):
        for login in ['account-one', 'ACCOUNT-TWO']:
            self.assertEqual(identity_match({'github_author': login}, IDENTITY), 'github_login')

    def test_foreign_login_cannot_match_our_same_name(self):
        self.assertIsNone(identity_match({'github_author': 'outsider', 'author': 'Sang Truong', 'email': 'me@example.test'}, IDENTITY))

    def test_unlinked_author_needs_exact_confirmed_alias(self):
        self.assertEqual(identity_match({'github_author': None, 'author': 'Sang Truong'}, IDENTITY), 'name')
        self.assertIsNone(identity_match({'author': 'Sang Truong Jr'}, IDENTITY))
        self.assertIsNone(identity_match({'author': 'Sang'}, IDENTITY))

    def test_email_alias_is_exact(self):
        self.assertEqual(identity_match({'email': 'ME@example.test'}, IDENTITY), 'email')
        self.assertIsNone(identity_match({'email': 'other-me@example.test'}, IDENTITY))

    def test_identity_provenance_survives_normalization(self):
        raw = [{'sha': 'a'*40, 'author': {'login': 'account-two'}, 'commit': {
            'author': {'name': 'Different Name', 'email': 'unknown@test', 'date': '2026-10-06T02:00:00Z'}, 'message': 'work'}}]
        commits = normalize_api_commits(raw, 'team/project', DATE, IDENTITY, TZ)
        model = normalize_all(str(DATE), commits, [], [], 'Asia/Ho_Chi_Minh')
        self.assertEqual(model['commits'][0]['github_author'], 'account-two')
        self.assertEqual(model['commits'][0]['identity_match'], 'github_login')

    def test_invalid_config_is_rejected(self):
        for config in [{'author': {'names': '*'}}, {'github': {'users': ['@me']}}, {'author': {'names': ['*']}}, {'timezone': 'invalid/timezone'}, {'timezone': 7}, {'repositories': 'team/project'}, {'repositories': []}]:
            with self.subTest(config=config), self.assertRaises((ValueError, KeyError)):
                settings(config)

    def test_local_git_missing_identity_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(['git', '-C', directory, 'init', '-q'], check=True)
            with patch('get_git_activity.get_git_user', return_value={'name': '', 'email': ''}):
                with self.assertRaises(SourceUnavailable):
                    get_commits_for_repo(directory, DATE, tz=TZ)

    def test_real_local_git_matches_aliases_not_substrings(self):
        with tempfile.TemporaryDirectory() as directory:
            def git(*args, **kw):
                return subprocess.run(['git', '-C', directory, *args], capture_output=True, check=True, **kw)
            git('init', '-q')
            for name in ['Sang Truong', 'Xuan Sang', 'Sang Truong Jr']:
                env = dict(os.environ, GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL='unknown@test',
                           GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL='unknown@test',
                           GIT_AUTHOR_DATE='2026-10-06T02:00:00Z', GIT_COMMITTER_DATE='2026-10-06T02:00:00Z')
                git('commit', '--allow-empty', '-qm', name, env=env)
            commits = get_commits_for_repo(directory, DATE, IDENTITY, TZ)
        self.assertEqual({x['author'] for x in commits}, {'Sang Truong', 'Xuan Sang'})
        self.assertEqual(len(commits), 2)


class TestPRActionCollection(unittest.TestCase):
    def collect(self, api, repos=None):
        return deduplicate_prs(query_gh_prs(DATE, repos or ['team/project'], IDENTITY['github_users'], TZ, api))

    def test_two_accounts_with_shared_repository_scope(self):
        api = API([pull(1), pull(2, 'account-two'), pull(3, 'outsider')])
        prs = self.collect(api, ['team/project', 'https://github.com/team/project'])
        self.assertEqual([p['id'] for p in prs], [1, 2])
        self.assertEqual(len([c for c in api.calls if c[0] == 'repos/team/project/pulls']), 1)
        self.assertTrue(all(c[0].startswith('repos/team/project/') for c in api.calls))

    def test_creation_time_is_not_later_update_time(self):
        prs = self.collect(API([pull(updated='2026-10-07T04:00:00Z')]))
        self.assertEqual(prs[0]['timestamp'], '2026-10-06T09:00:00+07:00')

    def test_old_review_plus_today_update_is_not_today_review(self):
        api = API([pull(author='outsider', created='2026-10-01T02:00:00Z')],
                  {1: [review(10, submitted='2026-10-05T03:00:00Z')]})
        self.assertEqual(self.collect(api), [])

    def test_open_review_and_merge_keep_all_action_times(self):
        api = API([pull(merged='2026-10-06T04:00:00Z')], {1: [review(10)]}, {1: 'account-one'})
        prs = self.collect(api)
        self.assertEqual(len(prs), 1)
        self.assertEqual(prs[0]['status'], 'merged')
        self.assertEqual(prs[0]['timestamp'], '2026-10-06T11:00:00+07:00')
        self.assertEqual([(e['action'], e['timestamp']) for e in prs[0]['events']], [
            ('opened', '2026-10-06T09:00:00+07:00'), ('reviewed', '2026-10-06T10:00:00+07:00'), ('merged', '2026-10-06T11:00:00+07:00')])
        normalized = normalize_all(str(DATE), [], prs, [], 'Asia/Ho_Chi_Minh')
        self.assertEqual(normalized['pull_requests'][0]['events'], prs[0]['events'])

    def test_merge_commit_sha_survives_collection_dedup_and_normalization(self):
        api = API([pull(merged='2026-10-06T04:00:00Z')])
        original_get = api.get
        api.get = lambda endpoint: {**original_get(endpoint), 'merge_commit_sha': 'a' * 40}
        prs = self.collect(api)
        self.assertEqual(prs[0]['merge_commit_sha'], 'a' * 40)
        model = normalize_all(str(DATE), [], prs, [], 'Asia/Ho_Chi_Minh')
        self.assertEqual(model['pull_requests'][0]['merge_commit_sha'], 'a' * 40)
        with self.assertRaises(ValueError):
            deduplicate_prs([prs[0], {**prs[0], 'merge_commit_sha': 'b' * 40}])

    def test_actions_are_associated_with_their_own_blocks(self):
        api = API([pull(merged='2026-10-06T08:00:00Z')], {1: [review(10)]})
        model = normalize_all(str(DATE), [], self.collect(api), [], 'Asia/Ho_Chi_Minh')
        blocks = build_time_blocks(model)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(len(blocks[0]['prs']), 1)
        self.assertEqual([e['action'] for e in blocks[0]['prs'][0]['events']], ['opened', 'reviewed'])
        self.assertEqual([e['action'] for e in blocks[1]['prs'][0]['events']], ['merged'])
        self.assertTrue(all(len(p['prs']) == 1 for p in prepare_all_blocks(blocks)))

    def test_multiple_reviews_are_not_collapsed(self):
        api = API([pull(author='outsider')], {1: [review(10), review(11, submitted='2026-10-06T04:00:00Z')]})
        self.assertEqual(len(self.collect(api)[0]['events']), 2)

    def test_foreign_pr_merged_by_us_is_relevant(self):
        api = API([pull(author='outsider', merged='2026-10-06T04:00:00Z')], mergers={1: 'account-two'})
        self.assertEqual([e['action'] for e in self.collect(api)[0]['events']], ['merged'])

    def test_old_personal_review_makes_today_merge_relevant(self):
        api = API([pull(author='outsider', merged='2026-10-06T04:00:00Z')], {1: [review(10, submitted='2026-10-05T03:00:00Z')]})
        self.assertEqual([e['action'] for e in self.collect(api)[0]['events']], ['merged'])

    def test_review_after_merge_does_not_establish_merge_relevance(self):
        api = API([pull(author='outsider', merged='2026-10-06T02:00:00Z')], {1: [review(10)]})
        self.assertEqual([e['action'] for e in self.collect(api)[0]['events']], ['reviewed'])

    def test_local_midnight_bounds_are_half_open(self):
        api = API([pull(1, created='2026-10-05T17:00:00Z'), pull(2, created='2026-10-06T16:59:59Z'),
                   pull(3, created='2026-10-06T17:00:00Z'), pull(4, created='2026-10-05T16:59:59Z')])
        self.assertEqual([p['id'] for p in self.collect(api)], [1, 2])

    def test_duplicate_event_and_normalizer_preserve_qualified_refs(self):
        raw = {'id': 1, 'repository': 'alice/shared', 'title': 'A', 'status': 'opened', 'timestamp': '2026-10-06T09:00:00+07:00'}
        prs = deduplicate_prs([raw, raw, {**raw, 'repository': 'bob/shared'}])
        self.assertEqual(len(prs), 2)
        self.assertTrue(all(len(p['events']) == 1 for p in prs))

    def test_partial_review_failure_discards_source_success(self):
        api = API([pull()])
        api.items = Mock(side_effect=GitHubAPIError('Review endpoint failed'))
        with patch('get_pr_activity.GitHubAPI', return_value=api):
            result = collect_pr_activity(DATE, repos=['team/project'], users=IDENTITY['github_users'], tz=TZ)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['items'], [])

    def test_pending_review_is_not_submitted_activity(self):
        api = API([pull(author='outsider')], {1: [{**review(10), 'submitted_at': None, 'state': 'PENDING'}]})
        self.assertEqual(self.collect(api), [])

    def test_malformed_pr_is_not_empty_success(self):
        api = API([{'number': 1}])
        with patch('get_pr_activity.GitHubAPI', return_value=api):
            result = collect_pr_activity(DATE, repos=['team/project'], users=IDENTITY['github_users'], tz=TZ)
        self.assertEqual(result['status'], 'error')


class TestGitHubTransportAndDates(unittest.TestCase):
    def test_list_pagination_reads_past_first_100(self):
        client = object.__new__(GitHubAPI)
        client.get = Mock(side_effect=[[{'id': i} for i in range(100)], [{'id': 100}]])
        self.assertEqual(len(list(client.items('repos/team/project/pulls', state='all'))), 101)
        self.assertIn('page=2', client.get.call_args_list[1].args[0])

    def test_invalid_page_shape_is_error(self):
        client = object.__new__(GitHubAPI)
        client.get = Mock(return_value={'items': []})
        with self.assertRaises(ValueError):
            list(client.items('repos/team/project/pulls'))

    def test_git_credentials_require_explicit_opt_in(self):
        with patch.dict(os.environ, {'GH_TOKEN': '', 'GITHUB_TOKEN': ''}), patch('github_api.check_gh_cli', return_value=False), patch('github_api.subprocess.run') as command:
            with self.assertRaises(SourceUnavailable):
                GitHubAPI()
            command.assert_not_called()
            command.return_value = Mock(returncode=0, stdout='username=user\npassword=test-not-a-real-secret\n')
            client = GitHubAPI(use_git_credentials=True)
            self.assertEqual(client.token, 'test-not-a-real-secret')
            self.assertEqual(command.call_args.kwargs['env']['GIT_TERMINAL_PROMPT'], '0')

    def test_no_identity_never_matches_everyone(self):
        self.assertEqual(filter_commits([{'author': 'Alice', 'timestamp': '2026-10-06T02:00:00Z'}], DATE, {}, TZ), [])

    def test_date_bounds_support_dst(self):
        start, end = day_bounds(datetime.date(2026, 11, 1), ZoneInfo('America/New_York'))
        self.assertEqual((end-start).total_seconds()/3600, 25)

    def test_git_and_pr_share_local_boundary(self):
        timestamps = ['2026-10-05T16:59:59Z', '2026-10-05T17:00:00Z', '2026-10-06T16:59:59Z', '2026-10-06T17:00:00Z']
        commits = [{'hash': str(i), 'author': 'Sang Truong', 'timestamp': t} for i, t in enumerate(timestamps)]
        selected = filter_commits(commits, DATE, IDENTITY, TZ)
        self.assertEqual([x['hash'] for x in selected], ['1', '2'])


if __name__ == '__main__':
    unittest.main()
