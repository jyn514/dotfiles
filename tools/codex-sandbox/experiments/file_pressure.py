"""Read macOS file-table pressure without scanning shared trees or dropping caches."""

import argparse
import ctypes
import datetime
import json
import platform
import subprocess
import time


class FileDescriptor(ctypes.Structure):
    _fields_ = [('fd', ctypes.c_int32), ('kind', ctypes.c_uint32)]


def descriptor_count(lib, pid):
    # PROC_PIDLISTFDS can grow between sizing and reading. Never report a
    # truncated list as a complete count, or a failed query as zero handles.
    size = lib.proc_pidinfo(pid, 1, 0, None, 0)
    if size <= 0:
        raise OSError(ctypes.get_errno(), 'cannot size process descriptor list')
    for _ in range(4):
        size += max(size // 2, 65536)
        buffer = ctypes.create_string_buffer(size)
        used = lib.proc_pidinfo(pid, 1, 0, buffer, size)
        if used <= 0:
            raise OSError(ctypes.get_errno(), 'cannot read process descriptor list')
        if used + ctypes.sizeof(FileDescriptor) < size:
            return used // ctypes.sizeof(FileDescriptor)
    raise RuntimeError('descriptor list kept growing during sampling')


def sample(lib):
    limits = {}
    output = subprocess.check_output(
        ['sysctl', 'kern.num_files', 'kern.maxfiles', 'kern.maxfilesperproc'], text=True)
    for line in output.splitlines():
        name, value = line.split(':', 1)
        limits[name] = int(value)
    processes = []
    output = subprocess.check_output(['ps', '-axo', 'pid=,comm='], text=True)
    for line in output.splitlines():
        pid, command = line.strip().split(None, 1)
        if 'com.apple.Virtualization.VirtualMachine' not in command:
            continue
        entry = {'pid': int(pid)}
        try:
            entry['descriptors'] = descriptor_count(lib, int(pid))
        except (OSError, RuntimeError) as error:
            entry['error'] = str(error)
        processes.append(entry)
    return {'time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'host': limits, 'virtual_machines': processes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=1)
    parser.add_argument('--interval', type=float, default=1)
    args = parser.parse_args()
    if platform.system() != 'Darwin':
        parser.error('requires macOS libproc')
    if not 1 <= args.samples <= 3600 or not 0 < args.interval <= 60:
        parser.error('samples must be 1..3600 and interval must be >0..60 seconds')
    lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                ctypes.c_void_p, ctypes.c_int]
    lib.proc_pidinfo.restype = ctypes.c_int
    for index in range(args.samples):
        if index:
            time.sleep(args.interval)
        print(json.dumps(sample(lib)), flush=True)


if __name__ == '__main__':
    main()
