"""Read-only GitHub REST access via the existing gh login or an environment token."""

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from collection_result import SourceUnavailable


class GitHubAPIError(RuntimeError):
    pass


def check_gh_cli():
    if not shutil.which("gh"):
        return False
    try:
        return subprocess.run(["gh", "auth", "status"], capture_output=True,
                              text=True, check=False, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class GitHubAPI:
    def __init__(self, use_git_credentials=False):
        self.token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        self.use_gh = not self.token and check_gh_cli()
        if not self.token and not self.use_gh and use_git_credentials:
            try:
                credential = subprocess.run(
                    ["git", "-c", "credential.interactive=false", "credential", "fill"],
                    input="protocol=https\nhost=github.com\n\n", capture_output=True, text=True,
                    check=False, timeout=20, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
                if credential.returncode == 0:
                    fields = dict(line.split("=", 1) for line in credential.stdout.splitlines() if "=" in line)
                    self.token = fields.get("password")
            except (OSError, subprocess.TimeoutExpired):
                pass
        if not self.token and not self.use_gh:
            raise SourceUnavailable("Authenticate gh, set GH_TOKEN/GITHUB_TOKEN, or opt in to an existing Git credential helper")

    def get(self, endpoint):
        if self.use_gh:
            response = subprocess.run(["gh", "api", "--method", "GET", endpoint,
                                       "-H", "Accept: application/vnd.github+json"],
                                      capture_output=True, text=True, check=False, timeout=45)
            if response.returncode:
                # No raw subprocess diagnostic is copied: it may contain private response data.
                raise GitHubAPIError(f"GitHub GET failed for {endpoint.split('?')[0]} (gh exit {response.returncode})")
            data = json.loads(response.stdout)
        else:
            request = urllib.request.Request("https://api.github.com/" + endpoint, headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "User-Agent": "personal-timesheet-logger",
                "X-GitHub-Api-Version": "2026-03-10",
            })
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    data = json.load(response)
            except urllib.error.HTTPError as exc:
                raise GitHubAPIError(f"GitHub GET failed for {endpoint.split('?')[0]} (HTTP {exc.code}); check access/rate limits") from exc
            except urllib.error.URLError as exc:
                raise GitHubAPIError("GitHub request failed; check network connectivity") from exc
        if not isinstance(data, (dict, list)):
            raise ValueError("Invalid GitHub JSON response")
        return data

    def pages(self, endpoint, **parameters):
        page = 1
        while True:
            query = urllib.parse.urlencode({**parameters, "per_page": 100, "page": page})
            items = self.get(endpoint + "?" + query)
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ValueError(f"Invalid list response for {endpoint}")
            yield items
            if len(items) < 100:
                return
            page += 1

    def items(self, endpoint, **parameters):
        for page in self.pages(endpoint, **parameters):
            yield from page
