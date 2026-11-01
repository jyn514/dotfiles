#!/usr/bin/env python3
"""Derive a smaller, self-contained fixture without altering its source fixture."""
import argparse
import json
from pathlib import Path
import shutil
import tarfile
import tempfile

from prepare import sha256
from prepare_history import command


def reduce(source: Path, output: Path, drop_history: bool, prompt: str, keep: list[str], function_only=False, spec_section=False, no_repository=False, empty_workspace=False):
    if output.exists():
        raise FileExistsError(output)
    manifest = json.loads((source / 'manifest.json').read_text())
    if sha256((source / 'flower.tar').read_bytes()) != manifest['archive']['sha256']:
        raise ValueError('Source archive hash mismatch')
    for name, digest in manifest['data_files'].items():
        if sha256((source / 'data' / name).read_bytes()) != digest:
            raise ValueError(f'Source data hash mismatch: {name}')
    if (keep or function_only or spec_section or empty_workspace) and not (drop_history or no_repository):
        raise ValueError('File reduction requires a clean new snapshot repository')
    if any(p.startswith('/') or '..' in p.split('/') for p in keep):
        raise ValueError('Unsafe keep path')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.reduce-fixture-') as tmp:
        stage = Path(tmp) / 'fixture'
        stage.mkdir()
        root = Path(tmp) / 'flower'
        def selected(path):
            return not empty_workspace and (not keep or any(path == p or path.startswith(p.rstrip('/') + '/') for p in keep))
        with tarfile.open(source / 'flower.tar') as archive:
            members = []
            for member in archive:
                relative = member.name.removeprefix('flower/').rstrip('/')
                metadata = relative.split('/')[0] in ['.git', '.jj']
                if metadata and (drop_history or no_repository):
                    continue
                if member.isdir() or metadata or selected(relative):
                    members.append(member)
            archive.extractall(tmp, members=members, filter='data')
        if keep or empty_workspace:
            for path in sorted(root.rglob('*'), key=lambda p: len(p.parts), reverse=True):
                if not path.is_symlink() and path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
        shutil.copytree(source / 'data', stage / 'data')
        historical = json.loads((stage / 'data/historical.json').read_text())
        if function_only:
            path = root / 'src/flower/page/source.clj'
            text = path.read_text()
            start = text.index('(defn resolve-template ')
            end = text.index('\n(defn', start + 1)
            path.write_text('(ns flower.page.source)\n\n' + text[start:end].strip() + '\n')
        if spec_section:
            path = root / 'contributing/spec/language-syntax.typ'
            text = path.read_text()
            start = text.index('=== Template selection <template-selection>')
            end = text.index('\n==', start + 1)
            path.write_text(text[start:end].strip() + '\n')
        if no_repository:
            historical.update(repository_kind='none', repository_commit=None, ancestor_count=0)
            manifest.update(revision=None, ancestor_count=0)
        elif drop_history:
            command('jj', 'git', 'init', '--colocate', str(root))
            command('jj', '--config', 'user.name="Worker"', '--config',
                    'user.email="worker@example.invalid"', 'commit', '-m', 'Import project', cwd=root)
            revision = command('git', 'rev-parse', 'HEAD', cwd=root).decode().strip()
            historical.update(repository_kind='snapshot', repository_commit=revision, ancestor_count=1)
            manifest.update(revision=revision, ancestor_count=1)
            shutil.rmtree(root / '.git/refs/jj', ignore_errors=True)
            shutil.rmtree(root / '.git/logs', ignore_errors=True)
            command('git', 'repack', '-a', '-d', cwd=root)
            command('git', 'prune', '--expire=now', cwd=root)
            if int(command('git', 'rev-list', '--all', '--count', cwd=root)) != 1:
                raise ValueError('Snapshot repository contains extra history')
        if prompt == 'packet':
            historical['base_instructions'] = 'You are a coding agent.'
            historical['developer_instructions'] = []
            historical['user_messages'] = [(stage / 'data/packet.md').read_text()]
        elif prompt in ['brief', 'focused']:
            historical['base_instructions'] = 'You are a coding agent.'
            historical['developer_instructions'] = []
            historical['user_messages'] = [
                'Implement task template for issue 6df95a2.\n'
                'Read the issue with `bb bug show 6df95a2`.\n'
                'Allowed files: src/flower/page/source.clj and test/flower/page/source_test.clj.\n'
                + ('Gate expectations: focused tests reported by worker when relevant.\n' if prompt == 'focused' else '') +
                'Return a JSON report with status and summary.\n']
            (stage / 'data/packet.md').write_text(historical['user_messages'][0])
        (stage / 'data/historical.json').write_text(json.dumps(historical, indent=2) + '\n')
        provenance = json.loads((stage / 'data/provenance.json').read_text())
        if 'reduction' in provenance:
            provenance.setdefault('reductions', []).append(provenance.pop('reduction'))
        provenance.setdefault('reductions', []).append({
            'source_manifest_sha256': sha256((source / 'manifest.json').read_bytes()),
            'source_archive_sha256': manifest['archive']['sha256'],
            'source_data_files': manifest['data_files'],
            'drop_history': drop_history, 'prompt': prompt, 'keep_paths': keep,
            'function_only': function_only, 'spec_section': spec_section,
            'no_repository': no_repository,
            'empty_workspace': empty_workspace,
        })
        (stage / 'data/provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
        manifest['files'] = [entry for entry in manifest['files'] if selected(entry['path'])]
        for entry in manifest['files']:
            if 'sha256' in entry:
                entry['sha256'] = sha256((root / entry['path']).read_bytes())
        with tarfile.open(stage / 'flower.tar', 'w') as archive:
            archive.add(root, arcname='flower', filter=lambda member: None
                        if member.name == 'flower/.jj' or member.name.startswith('flower/.jj/') else member)
        manifest['archive']['sha256'] = sha256((stage / 'flower.tar').read_bytes())
        manifest['data_files'] = {p.name: sha256(p.read_bytes()) for p in sorted((stage / 'data').iterdir())}
        manifest['snapshot_kind'] = 'Reduced reconstruction; see provenance.reductions'
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        stage.rename(output)
    print(f'Prepared reduction: {output} ({len(manifest["files"])} files, {manifest["ancestor_count"]} commits)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--drop-history', action='store_true')
    parser.add_argument('--prompt', choices=['preserve', 'packet', 'brief', 'focused'], default='preserve')
    parser.add_argument('--keep', action='append', default=[])
    parser.add_argument('--function-only', action='store_true')
    parser.add_argument('--spec-section', action='store_true')
    parser.add_argument('--no-repository', action='store_true')
    parser.add_argument('--empty-workspace', action='store_true')
    args = parser.parse_args()
    reduce(args.source, args.output, args.drop_history, args.prompt, args.keep, args.function_only, args.spec_section, args.no_repository, args.empty_workspace)
