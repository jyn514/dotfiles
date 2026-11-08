"""Boundary-only session doubles for assembled launcher scheduling tests."""
from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from command_proxy_session import CommandProxySession
from sandbox_runtime import ContainerRuntime


def session_for(state, *, policy=None, shared=None):
    if getattr(state, "command_session", None) is None:
        state.command_session = mock.Mock(
            spec=CommandProxySession, shared=False, policy={"commands": {}},
            recovery_path=None, zuliprc=None, capabilities=frozenset())
    if policy is not None:
        state.command_session.policy = policy
    if shared is not None:
        state.command_session.shared = shared
    return state.command_session


def proxy_backend():
    """Existing low-level parser tests need no launcher namespace or state."""
    return CommandProxySession(ContainerRuntime(), Path("/fixture"))._backend
