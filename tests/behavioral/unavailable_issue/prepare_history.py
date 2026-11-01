#!/usr/bin/env python3
"""Prepare an ancestor-only repository and original prompts from a Codex log."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

from prepare import REVISION, CHRONOLOGY_CAVEAT, sha256


def command(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True).stdout


def prepare(repository: Path, session: Path, output: Path):
    if output.exists():
        raise FileExistsError(output)
    records = [json.loads(line) for line in session.read_text().splitlines()]
    meta = next(r['payload'] for r in records if r['type'] == 'session_meta')
    turn = next(r['payload'] for r in records if r['type'] == 'turn_context')
    users = [r['payload'] for r in records if r['type'] == 'response_item'
             and r['payload'].get('role') == 'user'][:3]
    if len(users) != 3:
        raise ValueError('Expected original instructions, packet, and injected skill')
    calls = {r['payload']['call_id']: r['payload'] for r in records
             if r['payload'].get('type') == 'function_call'
             and any(s in r['payload'].get('arguments', '')
                     for s in ['bb bug show 6df95a2', 'git bug bug show 6df95a2'])}
    errors = [r['payload']['output'] for r in records
              if r['payload'].get('type') == 'function_call_output'
              and r['payload']['call_id'] in calls]
    diagnostic = 'Error: openat lock: operation not permitted\n'
    if len(errors) != 2 or not all('Process exited with code 1' in e
                                  and e.split('Output:\n')[-1] == diagnostic for e in errors):
        raise ValueError('Historical error does not match recorded exit/output')
    original = [''.join(part.get('text', '') for part in u['content']) for u in users]
    initial_developers = []
    for record in records:
        payload = record.get('payload', {})
        if record['type'] == 'response_item' and payload.get('role') == 'user':
            break
        if record['type'] == 'response_item' and payload.get('role') == 'developer':
            initial_developers.append(''.join(part.get('text', '') for part in payload.get('content', [])))
    # Keep the original instructions, including persona and retrieval wording.
    # Only workspace/report locations change for the disposable container.
    header = '# AGENTS.md instructions for '
    report_marker = '- The orchestrator will save that final message to: '
    if not original[0].startswith(header) or report_marker not in original[1]:
        raise ValueError('Original workspace/report declarations are missing')
    old_workspace = original[0].splitlines()[0].removeprefix(header)
    old_home_workspace = meta['cwd']
    old_report = original[1].split(report_marker, 1)[1].splitlines()[0]
    old_roots = [path.split('/target/flower-orchestrator-live/', 1)[0] for path in [old_workspace, old_home_workspace]]
    def relocate(text):
        text = text.replace(old_workspace, '/workspace/flower').replace(
            old_home_workspace, '/workspace/flower').replace(old_report, '/task/report.json')
        for root in old_roots:
            text = text.replace(root + '/.jj', '/workspace/flower/.jj')
        return text

    messages = [relocate(s) for s in original]
    initial_developers = [relocate(s) for s in initial_developers]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.history-fixture-') as tmp:
        stage = Path(tmp) / 'fixture'
        stage.mkdir()
        checkout = Path(tmp) / 'flower'
        command('jj', 'git', 'init', '--colocate', str(checkout))
        # Git transports only this commit and its ancestors. No source refs/config
        # or future commits are copied; all working-copy changes use Jujutsu.
        command('git', 'fetch', '--no-tags', str(repository.resolve()),
                f'{REVISION}:refs/heads/fixture', cwd=checkout)
        command('jj', 'git', 'import', cwd=checkout)
        command('jj', 'new', REVISION, cwd=checkout)
        count = int(command('git', 'rev-list', '--count', REVISION, cwd=checkout))
        head = command('git', 'rev-parse', 'HEAD', cwd=checkout).decode().strip()
        if head != REVISION or command('git', 'status', '--porcelain', cwd=checkout):
            raise ValueError('Historical working copy is not clean at selected revision')
        # These refs belong to temporary fixture preparation, not Flower history.
        # Drop them and their unreachable objects before archiving the Git store.
        shutil.rmtree(checkout / '.git/refs/jj', ignore_errors=True)
        shutil.rmtree(checkout / '.git/logs', ignore_errors=True)
        command('git', 'repack', '-a', '-d', cwd=checkout)
        command('git', 'prune', '--expire=now', cwd=checkout)
        if int(command('git', 'rev-list', '--all', '--count', cwd=checkout)) != count:
            raise ValueError('Preparation-created refs remain in historical repository')
        files = []
        for path in sorted(checkout.rglob('*')):
            relative = path.relative_to(checkout)
            if relative.parts[0] in ['.git', '.jj']:
                continue
            if path.is_symlink():
                files.append({'path': str(relative), 'symlink': path.readlink().as_posix()})
            elif path.is_file():
                files.append({'path': str(relative), 'sha256': sha256(path.read_bytes()),
                              'mode': path.stat().st_mode & 0o777})
        with tarfile.open(stage / 'flower.tar', 'w') as archive:
            # The installed container jj creates its own metadata at admission,
            # avoiding host-version and relocated-workspace metadata differences.
            archive.add(checkout, arcname='flower',
                        filter=lambda member: None if member.name == 'flower/.jj'
                        or member.name.startswith('flower/.jj/') else member)
        data = stage / 'data'
        shutil.copytree(Path(__file__).with_name('data'), data)
        (data / 'packet.md').write_text(messages[1])
        (data / 'worker-skill.md').write_text(messages[2])
        historical = {
            'model': turn['model'], 'thinking': turn['effort'],
            'recorded_provider': meta['model_provider'],
            'base_instructions': meta['base_instructions']['text'],
            'developer_instructions': initial_developers,
            'user_messages': messages,
            'issue_command': {'exit_code': 1, 'output': diagnostic},
            'repository_commit': REVISION, 'ancestor_count': count,
        }
        (data / 'historical.json').write_text(json.dumps(historical, indent=2) + '\n')
        (data / 'provenance.json').write_text(json.dumps({
            'source_session_id': meta['id'], 'source_sha256': sha256(session.read_bytes()),
            'purpose': 'Historical-model command-failure reconstruction',
            'adaptations': ['Workspace/report paths relocated; prompt text otherwise retained.',
                            'Native Pi tools replace Codex tools; bb/git issue reads are simulated.',
                            'Synthetic issue remains identical across unreadable/readable modes.'],
            'original_message_sha256': [sha256(s.encode()) for s in original],
            'captured_issue_errors': errors,
        }, indent=2) + '\n')
        manifest = {
            'schema_version': 2, 'revision': REVISION,
            'snapshot_kind': 'Git repository with complete selected ancestry and tracked symlinks',
            'chronology_caveat': CHRONOLOGY_CAVEAT, 'files': files, 'excluded_paths': [],
            'ancestor_count': count,
            'archive': {'path': 'flower.tar', 'sha256': sha256((stage / 'flower.tar').read_bytes())},
            'data_files': {p.name: sha256(p.read_bytes()) for p in sorted(data.iterdir())},
        }
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        stage.rename(output)
    print(f'Prepared historical fixture: {output} ({count} commits)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.repository, args.session, args.output)
