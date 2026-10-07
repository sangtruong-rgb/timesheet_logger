"""Real subprocess worker for synthetic R03 disk-failure/crash regressions."""
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import atomic_storage
from atomic_storage import directory_lock, atomic_write
from save_timesheet import save_timesheet
from activity_snapshot import save_snapshot
from normalize_activity import normalize_all
from build_time_blocks import build_time_blocks
from prepare_ai_input import prepare_activity_input

config = json.loads(Path(sys.argv[1]).read_text())
shared = Path(config['shared'])
original = atomic_storage.atomic_write
paused = False
real_flock = atomic_storage.fcntl.flock

def observed_flock(fd, operation):
    try:
        return real_flock(fd, operation)
    except BlockingIOError:
        Path(config['blocked']).write_text('real OS lock contention')
        raise

atomic_storage.fcntl.flock = observed_flock

def controlled_write(path, content):
    global paused
    path = Path(path)
    if config.get('fault') == 'marker_failure' and path.name == atomic_storage.PENDING and path.parent == shared.parent:
        raise OSError('intentional synthetic marker-write failure')
    if config.get('fault') == 'timesheet_failure' and path.name == '2026-10-07.json':
        raise OSError('intentional synthetic disk failure')
    original(path, content)
    if path == shared and config.get('pause') and not paused:
        paused = True
        Path(config['ready']).write_text('ready')
        if config.get('fault') == 'crash':
            os._exit(73)
        deadline = time.monotonic() + 8
        while not Path(config['release']).exists():
            if time.monotonic() >= deadline:
                raise OSError('test synchronization deadline exceeded')
            time.sleep(0.01)
        if config.get('fault') == 'snapshot_failure':
            raise OSError('intentional synthetic snapshot failure')

atomic_storage.atomic_write = controlled_write
if config.get('fault') == 'after_commit_crash':
    atomic_storage.clear_pending = lambda directories, journal: os._exit(74)
try:
    if config.get('mode') == 'single':
        with directory_lock(shared.parent):
            atomic_write(shared, config['value'])
    elif config.get('mode') in ('csv', 'timesheet-token'):
        from collect_token_usage import update_csv, make_record
        record = make_record('2026-10-07', config['value'], (10, 2, 3), '{"source":"synthetic"}')
        if config['mode'] == 'csv':
            update_csv(shared, [record])
        else:
            save_timesheet([], config['output'], target_date='2026-10-07', collection_status='complete',
                token_records=[record], token_csv=shared)
    elif config.get('mode') == 'snapshot':
        model = normalize_all('2026-10-07', [], [], [], 'Asia/Ho_Chi_Minh')
        review = []
        blocks = build_time_blocks(model, unassigned_activity=review)
        save_snapshot(Path(config['output']) / 'activity.json', model, {'status': 'complete', 'sources': {}},
            blocks, review, prepare_activity_input(blocks, review), shared)
    else:
        save_timesheet([], config['output'], target_date='2026-10-07', collection_status='complete',
            extra_files={shared: config['value']})
    Path(config['done']).write_text('success')
except Exception as exc:
    Path(config['done']).write_text(type(exc).__name__)
    sys.exit(2)
