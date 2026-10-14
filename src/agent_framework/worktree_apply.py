"""Crash-recoverable application of controller-validated role file deltas.

The journal contains only controller-generated paths and content-addressed bytes.
It never executes role-provided commands. Unknown external edits stop recovery.
"""
from pathlib import Path
import stat

from .common import Conflict, FrameworkError, atomic_write, bytes_digest, contained, read_json, write_json


def _file(root, path):
    target = contained(root, path)
    if not target.exists():
        return None
    mode = target.lstat().st_mode
    if stat.S_ISDIR(mode):
        return None
    if not stat.S_ISREG(mode):
        raise FrameworkError('nonregular role application target: ' + path)
    return {'digest': bytes_digest(target.read_bytes()), 'mode': stat.S_IMODE(mode)}


def _replace(root, files, side, store):
    # Remove children before parents, and only empty directories. Never recurse
    # through unknown files or touch Git/controller metadata.
    for path in sorted(files, key=lambda p: (p.count('/'), p), reverse=True):
        target = contained(root, path)
        if target.is_file():
            target.unlink()
        parent = target if target.is_dir() else target.parent
        while parent != root and parent.is_relative_to(root):
            try:
                parent.rmdir()
            except (FileNotFoundError, OSError):
                break
            parent = parent.parent
    for path, versions in sorted(files.items()):
        value = versions[side]
        if value is not None:
            atomic_write(contained(root, path), store.read_blob(value['digest']), value['mode'])


def prepare(store, repo, job, paths, source, after):
    files = {}
    for path in paths:
        target = contained(repo.path, path)
        previous = _file(repo.path, path)
        if previous:
            store.blob(target.read_bytes())
        next_value = None
        if path in after:
            data = contained(source, path).read_bytes()
            next_value = {'digest': store.blob(data), 'mode': after[path][1]}
        files[path] = {'before': previous, 'after': next_value}
    journal = store.root / ('role-apply-' + job + '.json')
    value = {'schema_version': 1, 'job': job, 'checkout': str(repo.path),
             'expected_head': repo.head, 'files': files}
    write_json(journal, value)
    return journal, value


def apply(store, repo, value):
    _replace(repo.path, value['files'], 'after', store)


def rollback(store, repo, value):
    for path, versions in value['files'].items():
        actual = _file(repo.path, path)
        # A crash may also have occurred after unlink and before atomic replace.
        if actual is not None and actual not in versions.values():
            raise Conflict('unknown external edit prevents role recovery: ' + path)
    _replace(repo.path, value['files'], 'before', store)


def recover(store, repo):
    """Call under the controller lock. Roll back uncommitted deltas, retain jobs."""
    recovered = []
    for journal in sorted(store.root.glob('role-apply-JOB-*.json')):
        value = read_json(journal)
        if value['checkout'] != str(repo.path):
            continue
        if repo.head != value['expected_head']:
            raise Conflict('pending role application has a different checkout HEAD: ' + value['job'])
        if store.exists(value['job']):
            for path, versions in value['files'].items():
                if _file(repo.path, path) != versions['after']:
                    raise Conflict('committed role output differs from checkout: ' + path)
            action = 'completed'
        else:
            rollback(store, repo, value)
            action = 'rolled_back'
        store.event('role_application_recovered', {'job': value['job'], 'action': action})
        journal.unlink()
        recovered.append({'job': value['job'], 'action': action})
    return recovered
