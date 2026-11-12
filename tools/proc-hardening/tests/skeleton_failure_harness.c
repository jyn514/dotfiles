/* Exercise actual generated cleanup and loader error reporting without root.
 * Kernel-facing calls in the update-path test use private fake descriptors.
 */
#define _GNU_SOURCE
#define main guard_loader_main
#include "../proc-read-guard.c"
#undef main

#include <fcntl.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include "wrapper_types.h"

#define TEST_UID 2345U

static unsigned int allocations;
static unsigned int fail_at;
static bool counting;
static bool fault_fired;
static bool loader_test;
static int link_fd = -1;
static int program_fd = -1;
static int map_fd = -1;
static max_align_t link_token;

extern void *__real_calloc(size_t, size_t);
extern int __real_close(int);
extern int __real_access(const char *, int);
extern FILE *__real_fopen(const char *, const char *);

void *__wrap_calloc(size_t count, size_t size)
{
	if (counting && ++allocations == fail_at) {
		fault_fired = true;
		errno = ENOMEM;
		return NULL;
	}
	return __real_calloc(count, size);
}

int __wrap_close(int fd)
{
	int result = __real_close(fd);

	if (loader_test && fault_fired && fd == program_fd) {
		errno = EIO;
		return -1;
	}
	return result;
}

char *__wrap_strerror(int error)
{
	static char message[48];

	snprintf(message, sizeof(message), "errno-%d", error);
	return message;
}

int __wrap_access(const char *path, int mode)
{
	char expected[PATH_MAX];

	snprintf(expected, sizeof(expected), BPF_PIN_ROOT "/%u/link", TEST_UID);
	if (loader_test && strcmp(path, expected) == 0)
		return 0;
	return __real_access(path, mode);
}

/* A failed fixture must never fall through to real privileged effects. */
int __wrap_mkdir(const char *path, mode_t mode)
{
	(void)path;
	(void)mode;
	errno = EPERM;
	return -1;
}

int __wrap_rmdir(const char *path)
{
	(void)path;
	errno = EPERM;
	return -1;
}

int __wrap_bpf_object__load_skeleton(struct bpf_object_skeleton *skeleton)
{
	(void)skeleton;
	return -EPERM;
}

int __wrap_bpf_object__attach_skeleton(struct bpf_object_skeleton *skeleton)
{
	(void)skeleton;
	return -EPERM;
}

int __wrap_bpf_link_update(int old_fd, int new_fd, const struct bpf_link_update_opts *opts)
{
	(void)old_fd;
	(void)new_fd;
	(void)opts;
	errno = EPERM;
	return -1;
}

int __wrap_bpf_link__pin(struct bpf_link *link, const char *path)
{
	(void)link;
	(void)path;
	return -EPERM;
}

int __wrap_bpf_link__unpin(struct bpf_link *link)
{
	(void)link;
	return -EPERM;
}

FILE *__wrap_fopen(const char *path, const char *mode)
{
	static char scope[] = "1\n";

	if (loader_test && strcmp(path, YAMA_PTRACE_SCOPE) == 0)
		return fmemopen(scope, sizeof(scope) - 1, "r");
	return __real_fopen(path, mode);
}

struct bpf_link *__wrap_bpf_link__open(const char *path)
{
	(void)path;
	link_fd = open("/dev/null", O_RDONLY | O_CLOEXEC);
	return link_fd < 0 ? NULL : (struct bpf_link *)&link_token;
}

int __wrap_bpf_link__fd(const struct bpf_link *link)
{
	(void)link;
	return link_fd;
}

void __wrap_bpf_link__disconnect(struct bpf_link *link)
{
	(void)link;
}

int __wrap_bpf_link__destroy(struct bpf_link *link)
{
	(void)link;
	if (link_fd >= 0) {
		__real_close(link_fd);
		link_fd = -1;
	}
	errno = EACCES;
	return 0;
}

int __wrap_bpf_link_get_info_by_fd(int fd, struct bpf_link_info *info, __u32 *size)
{
	(void)fd;
	(void)size;
	info->prog_id = 77;
	return 0;
}

int __wrap_bpf_prog_get_fd_by_id(__u32 id)
{
	(void)id;
	program_fd = open("/dev/null", O_RDONLY | O_CLOEXEC);
	return program_fd;
}

int __wrap_bpf_prog_get_info_by_fd(int fd, struct bpf_prog_info *info, __u32 *size)
{
	(void)fd;
	(void)size;
	info->type = BPF_PROG_TYPE_LSM;
	memcpy(info->name, PROGRAM_NAME, sizeof(PROGRAM_NAME));
	info->nr_map_ids = 1;
	if (info->map_ids)
		*(__u32 *)(uintptr_t)info->map_ids = 88;
	return 0;
}

int __wrap_bpf_map_get_fd_by_id(__u32 id)
{
	(void)id;
	map_fd = open("/dev/null", O_RDONLY | O_CLOEXEC);
	return map_fd;
}

int __wrap_bpf_map_get_info_by_fd(int fd, struct bpf_map_info *info, __u32 *size)
{
	(void)fd;
	(void)size;
	info->type = BPF_MAP_TYPE_ARRAY;
	info->key_size = sizeof(__u32);
	info->max_entries = 1;
	/* The update path must also accept an older UID-only rodata map. */
	info->value_size = sizeof(__u32);
	memcpy(info->name, "fixture.rodata", sizeof("fixture.rodata"));
	return 0;
}

int __wrap_bpf_map_lookup_elem(int fd, const void *key, void *value)
{
	__u32 uid = TEST_UID;

	(void)fd;
	(void)key;
	memcpy(value, &uid, sizeof(uid));
	/* Start fault injection after the real compatibility checks complete. */
	allocations = 0;
	counting = true;
	return 0;
}

int main(int argc, char **argv)
{
	struct rlimit no_core = {0, 0};
	struct proc_read_guard_bpf *object;

	if (argc != 3 || setrlimit(RLIMIT_CORE, &no_core) || prctl(PR_SET_DUMPABLE, 0))
		return 2;
	fail_at = (unsigned int)strtoul(argv[2], NULL, 10);
	loader_test = strcmp(argv[1], "errno") == 0;
	if (loader_test)
		return load_guard(TEST_UID);
	if (strcmp(argv[1], "allocation") != 0)
		return 2;

	counting = true;
	object = proc_read_guard_bpf__open();
	if (fail_at == 0) {
		if (!object)
			return 3;
		proc_read_guard_bpf__destroy(object);
	} else if (object || !fault_fired || errno != ENOMEM) {
		proc_read_guard_bpf__destroy(object);
		return 4;
	}
	printf("%u\n", allocations);
	return 0;
}
