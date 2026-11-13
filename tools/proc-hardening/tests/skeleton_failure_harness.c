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
static max_align_t new_link_token;
static max_align_t pending_token;
static int pending_fd = -1;
static bool pending_exists, pending_ref, wrong_pending, unloading, validating_pending;
static bool reload_test, old_ref, old_pin, new_active, new_pin, published;
static const char *failure;

static void require_state(bool ok)
{
	if (!ok)
		abort();
}

extern void __real_bpf_object__destroy_skeleton(struct bpf_object_skeleton *);
void __wrap_bpf_object__destroy_skeleton(struct bpf_object_skeleton *s)
{
	if (reload_test && s && s->progs && s->progs[0].link &&
	    *s->progs[0].link == (struct bpf_link *)&new_link_token) {
		if (!new_pin && !published)
			new_active = false;
		*s->progs[0].link = NULL;
	}
	__real_bpf_object__destroy_skeleton(s);
}

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
	if ((loader_test || reload_test) && strcmp(path, expected) == 0) {
		if (reload_test && !old_pin) { errno = ENOENT; return -1; }
		return 0;
	}
	snprintf(expected, sizeof(expected), BPF_PIN_ROOT "/%u/link-next", TEST_UID);
	if (reload_test && strcmp(path, expected) == 0) {
		if (pending_exists) return 0;
		errno = ENOENT;
		return -1;
	}
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
	if (reload_test) {
		require_state(old_pin && old_ref);
		return strcmp(failure, "load") == 0 ? -EIO : 0;
	}
	return -EPERM;
}

int __wrap_bpf_object__attach_skeleton(struct bpf_object_skeleton *skeleton)
{
	if (reload_test) {
		require_state(old_pin && old_ref);
		if (strcmp(failure, "attach") == 0)
			return -EIO;
		new_active = true;
		*skeleton->progs[0].link = (struct bpf_link *)&new_link_token;
		return 0;
	}
	return -EPERM;
}

int __wrap_bpf_program__fd(const struct bpf_program *program)
{
	(void)program;
	return reload_test ? program_fd : -EINVAL;
}

int __wrap_bpf_link_update(int old_fd, int new_fd, const struct bpf_link_update_opts *opts)
{
	(void)old_fd;
	(void)new_fd;
	(void)opts;
	fprintf(stderr, "mock kernel: link update unsupported (EINVAL)\n");
	errno = EINVAL;
	return -EINVAL;
}

int __wrap_bpf_link__pin(struct bpf_link *link, const char *path)
{
	if (reload_test) {
		require_state(link == (struct bpf_link *)&new_link_token &&
			      old_pin && old_ref && new_active);
		require_state(strstr(path, "/link-next") != NULL);
		if (strcmp(failure, "pin") == 0)
			return -EEXIST;
		new_pin = true;
		return 0;
	}
	return -EPERM;
}

int __wrap_bpf_link__unpin(struct bpf_link *link)
{
	if (reload_test && link == (struct bpf_link *)&pending_token) {
		require_state(pending_exists && (!old_pin || old_ref));
		pending_exists = false;
		return 0;
	}
	if (reload_test && link == (struct bpf_link *)&link_token && unloading) {
		require_state(old_pin && !pending_exists);
		old_pin = false;
		return 0;
	}
	if (reload_test) {
		require_state(link == (struct bpf_link *)&new_link_token && new_pin && old_pin);
		new_pin = false;
		return 0;
	}
	return -EPERM;
}

int __wrap_rename(const char *old, const char *new)
{
	(void)old;
	(void)new;
	if (!reload_test) { errno = EPERM; return -1; }
	if (!old_pin && pending_exists && pending_ref) {
		if (strcmp(failure, "restore-fail") == 0) { errno = EIO; return -1; }
		pending_exists = false;
		old_pin = true;
		return 0;
	}
	require_state(old_pin && old_ref && new_active && new_pin);
	if (strcmp(failure, "publish") == 0) { errno = EIO; return -1; }
	old_pin = false;
	new_pin = false;
	published = true;
	return 0;
}

FILE *__wrap_fopen(const char *path, const char *mode)
{
	static char scope[] = "1\n";

	if ((loader_test || reload_test) && strcmp(path, YAMA_PTRACE_SCOPE) == 0)
		return fmemopen(scope, sizeof(scope) - 1, "r");
	return __real_fopen(path, mode);
}

struct bpf_link *__wrap_bpf_link__open(const char *path)
{
	if (reload_test && strstr(path, "/link-next")) {
		validating_pending = true;
		pending_ref = true;
		pending_fd = open("/dev/null", O_RDONLY | O_CLOEXEC);
		return (struct bpf_link *)&pending_token;
	}
	validating_pending = false;
	if (reload_test) old_ref = true;
	link_fd = open("/dev/null", O_RDONLY | O_CLOEXEC);
	return link_fd < 0 ? NULL : (struct bpf_link *)&link_token;
}

int __wrap_bpf_link__fd(const struct bpf_link *link)
{
	if (link == (struct bpf_link *)&pending_token) return pending_fd;
	return link_fd;
}

void __wrap_bpf_link__disconnect(struct bpf_link *link)
{
	(void)link;
	/* Disconnect skips closing the FD and would retain the old attachment. */
	require_state(!reload_test);
}

int __wrap_bpf_link__destroy(struct bpf_link *link)
{
	if (reload_test && link == (struct bpf_link *)&pending_token) {
		pending_ref = false;
		__real_close(pending_fd);
		pending_fd = -1;
		return 0;
	}
	if (reload_test) { require_state(old_pin || published || unloading); old_ref = false; }
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
	__u32 uid = TEST_UID + (reload_test && validating_pending && wrong_pending ? 1 : 0);

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
	reload_test = strcmp(argv[1], "reload") == 0 || strcmp(argv[1], "unload") == 0;
	unloading = strcmp(argv[1], "unload") == 0;
	if (reload_test) {
		int result;
		failure = argv[2];
		old_pin = strcmp(failure, "orphan") != 0 && strcmp(failure, "restore-fail") != 0;
		pending_exists = strcmp(failure, "stale") == 0 || strcmp(failure, "wrong") == 0 || !old_pin;
		wrong_pending = strcmp(failure, "wrong") == 0;
		result = unloading ? unload_guard(TEST_UID) : load_guard(TEST_UID);
		require_state(!old_ref && !pending_ref);
		if (strcmp(failure, "restore-fail") == 0) {
			require_state(result != 0 && !old_pin && pending_exists);
			return 0;
		}
		if (wrong_pending) {
			require_state(result != 0 && old_pin && pending_exists);
			return 0;
		}
		if (unloading) {
			require_state(result == 0 && !old_pin && !pending_exists);
			return 0;
		}
		if (strcmp(failure, "success") == 0 || strcmp(failure, "stale") == 0 || strcmp(failure, "orphan") == 0)
			require_state(result == 0 && published && new_active && !old_pin);
		else
			require_state(result != 0 && old_pin && !published && !new_active && !new_pin);
		return 0;
	}
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
