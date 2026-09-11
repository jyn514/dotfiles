#!/usr/bin/env python3
"""Fresh Bake inputs for a disposable base and dependent image."""

import hashlib
import json
from pathlib import Path

root = Path.cwd()
targets = {}
for name in ('base', 'proxy'):
    key = hashlib.sha256((root / (name + '.Dockerfile')).read_bytes() +
                         (root / (name + '-marker')).read_bytes()).hexdigest()
    targets[name] = {'context': '.', 'dockerfile': name + '.Dockerfile',
                     'tags': ['sandbox-fixture-' + name + ':' + key],
                     'platforms': ['${BUILDPLATFORM}']}
targets['proxy'].update(args={'BASE_IMAGE': 'base-context'}, contexts={'base-context': 'target:base'})
print(json.dumps({'variable': {'BUILDPLATFORM': {'default': 'linux/arm64'}}, 'target': targets}))
