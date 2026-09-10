import runpy
import sys
import os
import faulthandler
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

def mark(label):
    print(f'Startup boundary: {label} @ {time.monotonic()}', file=sys.stderr, flush=True)

mark('Python fixture entered')
launcher = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'codex-sandbox'))
mark('launcher imported')
original = launcher['run_agent']
namespace = original.__globals__

def measured(name, function):
    def call(*args, **kwargs):
        mark(name + ' begin')
        result = function(*args, **kwargs)
        mark(name + ' end')
        return result
    return call

factory = namespace['image_runtime']
def image_runtime(*args, **kwargs):
    from lima.docker_host import DockerHost
    methods = {name: getattr(DockerHost, name) for name in ('machine', 'runtime_epoch', 'verify', 'guest')}
    faulthandler.dump_traceback_later(10, repeat=True)
    try:
        for name, method in methods.items():
            setattr(DockerHost, name, measured('runtime ' + name, method))
        return factory(*args, **kwargs)
    finally:
        faulthandler.cancel_dump_traceback_later()
        for name, method in methods.items():
            setattr(DockerHost, name, method)

namespace['image_runtime'] = image_runtime
for name in ('image_runtime', 'new_state', 'execute'):
    namespace[name] = measured(name, namespace[name])

def benchmark(state, arguments):
    mark('run_agent entered')
    runtime = namespace['OUTER_RUNTIME']
    if runtime.provider != 'lima-docker':
        return original(state, ['--env', 'PI_STARTUP_BENCHMARK=1', *arguments])
    # These operations are synchronous and on the agent's launch path. The
    # attached process still belongs to the normal workload/cleanup machinery.
    for name in ('inspect_image', 'workload_argv', 'popen'):
        setattr(runtime, name, measured(name, getattr(runtime, name)))
    original_environment = runtime.environment_file
    @contextmanager
    def environment_file(*args, **kwargs):
        mark('environment file begin')
        with original_environment(*args, **kwargs) as environment:
            mark('environment file ready')
            yield environment
    runtime.environment_file = environment_file
    original_workload = runtime.workload
    @contextmanager
    def workload(*args, before_start=None, **kwargs):
        callback = measured('monitor setup', before_start) if before_start else None
        with original_workload(*args, before_start=callback, **kwargs) as process:
            yield process
    runtime.workload = workload
    fixture = Path(__file__).resolve().parent
    profile = []
    if os.environ.get('PI_STARTUP_PROFILE'):
        target = fixture.parents[3] / 'target'
        target.mkdir(exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix='startup-profile-', dir=target))
        print('Startup profile: ' + str(output), file=sys.stderr, flush=True)
        profile = ['--env', 'PI_STARTUP_PROFILE=1', '--mount',
                   f'type=bind,src={output},dst=/startup-output']
    # Insert the wrapper after the image, leaving all Docker options intact.
    image_index = arguments.index(state.image)
    return original(state, ['--env', 'PI_STARTUP_BENCHMARK=1',
        *profile,
        '--mount', f'type=bind,src={fixture},dst=/startup-probe,readonly',
        '--entrypoint', '/bin/sh',
        '--env', 'NODE_OPTIONS=--require=/startup-probe/startup-node.cjs',
        *arguments[:image_index + 1], '/startup-probe/startup-entry.sh',
        *arguments[image_index + 1:]])

original.__globals__['run_agent'] = benchmark
raise SystemExit(launcher['main'](sys.argv[1:]))
