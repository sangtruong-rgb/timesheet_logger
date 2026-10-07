# R03: Serialize shared exports and protect interrupted bundles

Different timesheet/snapshot directories can share an AI export. Previously their
independent primary locks allowed one failed writer to restore old export bytes
after another writer had already succeeded.

`directory_lock(primary, extra_paths=...)` now locks the canonical primary and all
external-file parent directories in sorted order. A single timeout bounds the
whole lock acquisition. Validation, prior-byte reads, writing, rollback and recovery
occur while all participating locks are held. `write_bundle` checks that every
target parent was declared/locked, and recovery checks its lock scope before
restoring any file. Snapshot and timesheet writers use this shared lock API.

Before creating the recoverable journal or changing data, a bundle reserves each
participating directory with `.timesheet-pending.json`. If the process exits while
the journal exists, another cooperating writer must stop instead of updating a
shared file. This also applies to single-file writers using `directory_lock`, such
as AI export tools and token CSV updates. Recover the original output bundle with
its original external paths, then retry the blocked operation:

```python
with directory_lock(original_output_dir, extra_paths=original_external_paths):
    # Recovery has finished; proceed with the intended update.
    ...
```

Reservations whose journal is already gone are stale and can be cleaned under
their directory lock without restoring any data. Post-commit marker-cleanup failure
does not turn a successful commit into an alleged rollback. Corrupt journals or
markers block updates and remain for review. Pending metadata is ignored by Git
and reserved from AI exports.

## Verification

`test_storage_concurrency.py` launches real Python processes and uses actual POSIX
fcntl locks. Its worker records real BlockingIOError events to prove contention;
it does not substitute successful lock results or mock process environments.
Synthetic filesystem failures/process exits are injected to reproduce the bug
safely; every fixture stays in a temporary directory.

Cases cover shared-export rollback for timesheets and snapshots, crashes before
completion and after journal deletion, owner recovery, blocked single-file writers,
full lock acquisition before recovery, deterministic lock order, corrupt/stale
markers, marker-creation failure, undeclared external files and token CSV updates.
The token CSV case runs in dependent PR #62/#63 where run-scoped CSV storage exists;
it is explicitly skipped in #61.

```bash
python3 -m unittest discover -s tests -p 'test_storage_concurrency.py'
python3 -m unittest discover -s tests
```

This protects cooperating writers using the shared storage API and handles the
tested process-crash cases. Unlocked readers may still observe a bundle between
individual atomic replacements. It is not an instantaneous multi-file database
transaction, and these tests do not simulate power loss. Live-source validation
and before/after regression evidence are reported separately in the workspace R03
result report. R04/Claude usage acceptance and deferred D02 remain open.
