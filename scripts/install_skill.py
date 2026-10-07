#!/usr/bin/env python3
"""Install a symlink to this skill bundle without copying credentials or replacing files."""
import argparse
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent.parent


def install(destination):
    destination = Path(destination).expanduser().absolute()
    if destination.is_symlink() and destination.resolve() == ROOT:
        return destination
    if destination.exists() or destination.is_symlink():
        raise ValueError('Skill destination already exists and points elsewhere; existing files preserved')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Relative project symlink travels with the checkout; personal links use a stable absolute root.
    if destination == ROOT/'.claude/skills/personal-timesheet':
        destination.symlink_to('../..', target_is_directory=True)
    else:
        destination.symlink_to(ROOT, target_is_directory=True)
    return destination


def main():
    parser=argparse.ArgumentParser(description='Install personal-timesheet for Claude Code.')
    parser.add_argument('--scope',choices=('project','personal'),default='project')
    parser.add_argument('--destination',help='Explicit destination for an isolated installation')
    args=parser.parse_args()
    destination=args.destination or (ROOT/'.claude/skills/personal-timesheet' if args.scope=='project' else Path.home()/'.claude/skills/personal-timesheet')
    try: path=install(destination)
    except (ValueError,OSError) as exc:
        print(f'Installation blocked: {exc}',file=sys.stderr); return 2
    print(f'Skill bundle installed: {path}. CLI discovery/invocation still requires Claude Code.'); return 0


if __name__=='__main__': sys.exit(main())
