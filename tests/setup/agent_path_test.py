"""Agent command wrappers must survive tool activation in login shells."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
WRAPPERS = ROOT / 'libexec/agent-wrappers'


class AgentPathTests(unittest.TestCase):
    def test_shell_profiles_preserve_inherited_wrappers_after_mise(self):
        for shell in ('bash', 'zsh', 'fish'):
            executable = shutil.which(shell)
            if executable is None:
                continue
            for agent in (False, True):
                with self.subTest(shell=shell, agent=agent), tempfile.TemporaryDirectory() as directory:
                    home = Path(directory)
                    tools = home / 'native tools'
                    tools.mkdir()
                    (tools / 'jj').symlink_to('/bin/true')
                    (tools / 'mise').symlink_to(ROOT / 'tests/setup/fixtures/mise_activation.sh')
                    (home / '.profile').symlink_to(ROOT / 'config/profile')
                    (home / '.bash_profile').symlink_to(home / '.profile')
                    (home / '.zprofile').symlink_to(home / '.profile')
                    fish_config = home / '.config/fish'
                    fish_config.mkdir(parents=True)
                    (fish_config / 'config.fish').symlink_to(ROOT / 'config/config.fish')
                    inherited = [str(tools), '/usr/bin', '/bin']
                    if agent:
                        inherited.insert(0, str(WRAPPERS))
                    environment = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'),
                        PATH=os.pathsep.join(inherited), PROFILE_MISE_TOOLS=str(tools),
                        SSH_AUTH_SOCK='present', ENV='', BASH_ENV='', ZDOTDIR=str(home),
                        TMUX='', TMUX_PANE='', KITTY_INSTALLATION_DIR='', FISH_UNIT_TESTS_RUNNING='1')
                    for name in ('MISE_SHELL', '__MISE_DIFF', '__MISE_SESSION', '__MISE_ORIG_PATH'):
                        environment.pop(name, None)
                    # Load the real user profile without /etc/profile replacing
                    # the inherited fixture PATH before the profile sees it.
                    if shell == 'fish':
                        command = [executable, '-lc', 'command -v jj']
                    else:
                        command = [executable, str(ROOT / 'tests/setup/fixtures/profile_command.sh'),
                                   'command -v jj']
                    result = subprocess.run(command,
                        env=environment, cwd=home, text=True, capture_output=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    expected = WRAPPERS / 'jj' if agent else tools / 'jj'
                    self.assertEqual(result.stdout.strip(), str(expected), result.stderr)


if __name__ == '__main__':
    unittest.main()
