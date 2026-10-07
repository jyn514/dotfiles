"""Local capture adapter for docker-py 7.2.0's ignore pattern implementation."""

import os

from docker.utils.build import Pattern
from docker.utils.fnmatch import fnmatchcase


class DockerIgnore:
    def __init__(self, contents):
        # Docker recognizes comments before stripping whitespace, and accepts a
        # UTF-8 BOM at the start of the file.
        lines = contents.decode('utf-8-sig').splitlines()
        self.patterns = []
        for line in lines:
            if line.startswith('#') or not line.strip():
                continue
            line = line.strip()
            if line == '!':
                raise ValueError('invalid lone ! in Docker ignore file')
            pattern = Pattern(line)
            if pattern.dirs:
                self.patterns.append(pattern)

    def ignored(self, relative):
        # SDK matching lowercases names and checks only one ancestor. Check
        # every ancestor with its case-sensitive matcher instead.
        parts = relative.split('/')
        candidates = ['/'.join(parts[:end]) for end in range(1, len(parts) + 1)]
        ignored = False
        for pattern in self.patterns:
            if any(fnmatchcase(path, pattern.cleaned_pattern) for path in candidates):
                ignored = not pattern.exclusion
        return ignored

    def may_reinclude(self, relative):
        prefix = relative + '/'
        for pattern in self.patterns:
            if not pattern.exclusion:
                continue
            # SDK pruning loses wildcard exceptions. A wildcard exception can
            # require walking an excluded ancestor; literal exceptions only
            # require walking their own ancestors.
            text = pattern.cleaned_pattern
            if any(char in text for char in '*?[') or text.startswith(prefix):
                return True
        return False

    def walk(self, root, required):
        def visit(directory):
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = directory / entry.name
                    relative = path.relative_to(root).as_posix()
                    ignored = self.ignored(relative)
                    if not ignored or relative in required:
                        yield path
                    if entry.is_dir(follow_symlinks=False) and (
                        not ignored or self.may_reinclude(relative)
                        or any(name.startswith(relative + '/') for name in required)
                    ):
                        yield from visit(path)
        return visit(root)
