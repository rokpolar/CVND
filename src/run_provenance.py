"""Offline source fingerprints, including staged and untracked implementation files."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATHS = ('src', 'scripts', 'tests', 'requirements.txt', 'requirements-lock.txt',
                'README.md', 'docs', 'PROJECT_CONTEXT.md')


def sha256(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def source_record(root=ROOT):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root)
    names = git('ls-files', '-z', '--cached', '--others', '--exclude-standard',
                '--', *SOURCE_PATHS).decode().split('\0')
    files = {name: sha256(root / name) if (root / name).is_file() else None
             for name in sorted(set(names) - {''})}
    diff = git('diff', '--no-ext-diff', '--binary', 'HEAD', '--', *SOURCE_PATHS)
    return {
        'git_head': git('rev-parse', 'HEAD').decode().strip(),
        'git_dirty': bool(git('status', '--porcelain')),
        'source_files_sha256': files,
        'source_tree_sha256': hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
        'source_diff_sha256': hashlib.sha256(diff).hexdigest(),
    }
