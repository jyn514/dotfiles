#!/usr/bin/env python3
"""Substitute only the producer; use the production consumer validator."""
import importlib.util
import os
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location(
    '_jj_authoritative_route', Path(__file__).resolve().parents[3] / 'tools/jj-proxy/route.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
check_result = module.check_result


def route(argv, **kwargs):
    mode = os.environ['JJ_TEST_ROUTE_MODE']
    if mode == 'failed':
        print('jj route fixture: failed before returning result', file=sys.stderr)
        raise SystemExit(9)
    result = dict(backend='native', workspace=None, destination=None,
                  command=['status'], hooks=False)
    if mode == 'relative':
        result['workspace'] = 'relative'
    elif mode == 'duplicate':
        return [result, result]
    elif mode == 'extra':
        result['extra'] = True
    elif mode == 'missing':
        del result['hooks']
    elif mode == 'nul-command':
        result['command'] = ['sta\0tus']
    elif mode == 'nul-target':
        result['workspace'] = '/bad\0target'
    elif mode == 'empty':
        result.update(command=[], hooks=True)
    elif mode == 'empty-command':
        result.update(command=[''], hooks=True)
    return result
