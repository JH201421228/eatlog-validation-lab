"""Archive the uncommitted service candidate and observed offline verification."""
from pathlib import Path
import difflib
import hashlib
import importlib.metadata
import json
import subprocess
import sys
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[3]
WORKTREE = WORKSPACE / 'AI_accuracy_candidate'
ORIGINAL = WORKSPACE / 'AI'
BASE = 'a860b2fb3a2c53a4484ddc6673d86d938f039171'
FILES = ['ai-server/app/gemini_client.py', 'ai-server/app/services/vision.py',
         'ai-server/tests/conftest.py', 'ai-server/tests/test_response_schema.py',
         'ai-server/tests/test_photo_model_policy.py']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo, *args):
    return subprocess.run(['git', '-c', f'safe.directory={repo.as_posix()}', '-C', str(repo), *args],
                          cwd=WORKTREE / 'ai-server', check=True, capture_output=True).stdout


def main():
    HERE.mkdir(parents=True, exist_ok=True)
    if git(ORIGINAL, 'rev-parse', 'HEAD').decode().strip() != BASE or git(ORIGINAL, 'status', '--porcelain', '--untracked-files=no').strip():
        raise RuntimeError('Original AI checkout is no longer the clean expected base')
    if git(WORKTREE, 'rev-parse', 'HEAD').decode().strip() != BASE:
        raise RuntimeError('Unexpected candidate base')
    git(WORKTREE, 'diff', '--check')
    patch = git(WORKTREE, 'diff', '--binary', 'HEAD').decode('utf-8')
    newfile = 'ai-server/tests/test_photo_model_policy.py'
    patch += f'diff --git a/{newfile} b/{newfile}\nnew file mode 100644\n'
    patch += ''.join(difflib.unified_diff([], (WORKTREE / newfile).read_text(encoding='utf-8').splitlines(keepends=True),
                                        fromfile='/dev/null', tofile='b/' + newfile))
    (HERE / 'candidate.patch').write_text(patch, encoding='utf-8', newline='\n')
    git(ORIGINAL, 'apply', '--check', str(HERE / 'candidate.patch'))
    for relative in FILES:
        target = HERE / 'files' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((WORKTREE / relative).read_bytes())
    sys.path.insert(0, str(WORKTREE / 'ai-server'))
    from app.services.vision import _build_prompt
    from app.schemas.model_response import ANALYZE_RESPONSE_SCHEMA
    prompt = _build_prompt('standard', 5).encode()
    schema = json.dumps(ANALYZE_RESPONSE_SCHEMA, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    verification = {'cwd': str(WORKTREE / 'ai-server'),
                    'command': str(ORIGINAL / 'ai-server/venv/Scripts/python.exe') + ' -m pytest -q',
                    'observed_exit_code': 0, 'observed_summary': '258 passed in 4.14s',
                    'diff_check': 'git diff --check: exit 0',
                    'patch_check': 'git apply --check against clean original base: exit 0; not applied',
                    'initial_test_fixture_correction': 'The new mocked package-label fixture initially omitted required per_100g; fixed the fixture, then ran the complete suite successfully.',
                    'coverage': ['Route conditions and explicit operator settings', 'Actual SDK MINIMAL/4096/temp0/seed config',
                                 'Actual selected model in success/provider/parse failure logs', 'Existing multi-image ordering and failure-index contracts',
                                 'Package label attachment and printed nutrition candidate contract', 'Frozen prompt bytes and semantic schema hashes'],
                    'limitation': 'Mocked contract/regression tests do not establish package-photo recognition accuracy; confirmation still required.'}
    (HERE / 'verification_results.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    freeze = {'frozen_at': datetime.now(timezone.utc).isoformat(), 'base_commit': BASE,
              'worktree': str(WORKTREE), 'branch': git(WORKTREE, 'branch', '--show-current').decode().strip(),
              'file_sha256': {name: digest(WORKTREE / name) for name in FILES}, 'patch_sha256': digest(HERE / 'candidate.patch'),
              'verification_sha256': digest(HERE / 'verification_results.json'),
              'prompt_sha256': hashlib.sha256(prompt).hexdigest(), 'schema_semantic_sha256': hashlib.sha256(schema).hexdigest(),
              'sdk_version_tested': importlib.metadata.version('google-genai'),
              'policy': {'model': 'gemini-3.5-flash-lite', 'thinking_level': 'MINIMAL', 'temperature': 0,
                         'seed': 20260722, 'max_output_tokens': 4096,
                         'route': 'One image, stripped empty user text, normalized standard depth, max_foods5; only baseline 2.5Flash/temp0/seed20260722/thinking0 settings'},
              'confirmation_labels_opened': False, 'committed': False, 'pushed_merged_deployed': False,
              'original_ai_tracked_clean': True, 'environment_config_or_dependencies_changed': False}
    (HERE / 'freeze.json').write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'freeze_sha256': digest(HERE / 'freeze.json'), 'patch_sha256': freeze['patch_sha256'],
                      'file_sha256': freeze['file_sha256']}, indent=2))


if __name__ == '__main__':
    main()
