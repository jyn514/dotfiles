#!/usr/bin/env python3
"""Run a standalone wrapper where the router's Python-only dependency is absent."""
import builtins
import runpy
import sys

original_import = builtins.__import__


def without_tomllib(name, *args, **kwargs):
    if name == 'tomllib':
        raise ImportError('standalone fixture: tomllib is unavailable')
    return original_import(name, *args, **kwargs)


builtins.__import__ = without_tomllib
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
