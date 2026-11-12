#include <errno.h>
#include <grp.h>
#include <limits.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include <bpf/bpf.h>
#include <bpf/libbpf.h>

#include "proc-read-guard.skel.h"

#define BPF_PIN_ROOT "/sys/fs/bpf/proc-read-guard"
#define PROGRAM_NAME "proc_read_guard"
#define YAMA_PTRACE_SCOPE "/proc/sys/kernel/yama/ptrace_scope"
#define TRUSTED_READER_GROUP "onepassword"

_Static_assert(offsetof(struct proc_read_guard_bpf__rodata, protected_uid) == 0,
	       "protected_uid must remain the compatible recovery prefix");

static void usage(FILE *stream)
{
	fprintf(stream, "usage: proc-read-guard {load|unload|status} UID\n");
}

static int report_errno(const char *operation, int error)
{
	fprintf(stderr, "proc-read-guard: %s: %s\n", operation, strerror(error));
	return 1;
}

static int report_libbpf_error(const char *operation, int error)
{
	return report_errno(operation, -error);
}

static int report_unexpected_link(const char *path, __u32 uid, const char *reason)
{
	fprintf(stderr, "proc-read-guard: %s is not proc-read-guard for uid %u: %s\n",
		path, uid, reason);
	return 1;
}

static bool is_ascii_space(char ch)
{
	return ch == ' ' || ch == '\t' || ch == '\n' ||
	       ch == '\r' || ch == '\f' || ch == '\v';
}

static bool parse_uid(const char *text, __u32 *uid)
{
	char *end = NULL;
	unsigned long value;

	if (!text[0] || text[0] < '0' || text[0] > '9')
		return false;
	errno = 0;
	value = strtoul(text, &end, 10);
	if (errno != 0 || *end != '\0' || value > UINT32_MAX)
		return false;
	*uid = (__u32)value;
	return true;
}

static bool path_exists(const char *path)
{
	return access(path, F_OK) == 0;
}

static bool format_paths(__u32 uid, char *uid_dir, size_t uid_dir_size,
			 char *link_path, size_t link_path_size)
{
	int written;

	written = snprintf(uid_dir, uid_dir_size, "%s/%u", BPF_PIN_ROOT, uid);
	if (written < 0 || (size_t)written >= uid_dir_size)
		return false;
	written = snprintf(link_path, link_path_size, "%s/link", uid_dir);
	return written >= 0 && (size_t)written < link_path_size;
}

static int ensure_directory(const char *path)
{
	struct stat info;

	if (mkdir(path, 0755) == 0)
		return 0;
	if (errno != EEXIST)
		return report_errno(path, errno);
	if (stat(path, &info) != 0)
		return report_errno(path, errno);
	if (!S_ISDIR(info.st_mode)) {
		fprintf(stderr, "proc-read-guard: %s exists and is not a directory\n", path);
		return 1;
	}
	return 0;
}

static void remove_empty_directory(const char *path)
{
	if (rmdir(path) != 0 && errno != ENOENT && errno != ENOTEMPTY)
		fprintf(stderr, "proc-read-guard: could not remove %s: %s\n",
			path, strerror(errno));
}

static void close_bpf_fd(int fd, const char *description)
{
	if (fd >= 0 && close(fd) != 0)
		fprintf(stderr, "proc-read-guard: close %s: %s\n",
			description, strerror(errno));
}

static void release_link_reference(struct bpf_link *link)
{
	int error;

	if (!link)
		return;
	bpf_link__disconnect(link);
	error = bpf_link__destroy(link);
	if (error != 0)
		fprintf(stderr, "proc-read-guard: close pinned BPF link: %s\n",
			strerror(-error));
}

static __u32 read_trusted_reader_gid(void)
{
	struct group *group;

	errno = 0;
	group = getgrnam(TRUSTED_READER_GROUP);
	if (!group) {
		if (errno != 0 && errno != ENOENT && errno != ESRCH)
			fprintf(stderr, "proc-read-guard: cannot resolve %s: %s; "
				"group exemption disabled\n", TRUSTED_READER_GROUP,
				strerror(errno));
		return UINT32_MAX;
	}
	return (__u32)group->gr_gid;
}

static void configure_rodata(struct proc_read_guard_bpf *skel, __u32 uid,
			     __u32 trusted_gid)
{
	skel->rodata->protected_uid = uid;
	skel->rodata->trusted_reader_gid = trusted_gid;
}

static int read_expected_prog_tag(__u32 uid, __u32 trusted_gid,
				  __u8 tag[BPF_TAG_SIZE])
{
	struct proc_read_guard_bpf *skel = NULL;
	struct bpf_prog_info prog_info = {};
	__u32 info_len = sizeof(prog_info);
	int prog_fd;
	int error;

	skel = proc_read_guard_bpf__open();
	if (!skel)
		return report_errno("open expected BPF skeleton", errno ? errno : ENOMEM);
	configure_rodata(skel, uid, trusted_gid);
	error = proc_read_guard_bpf__load(skel);
	if (error != 0) {
		proc_read_guard_bpf__destroy(skel);
		return report_libbpf_error("load expected BPF program", error);
	}
	prog_fd = bpf_program__fd(skel->progs.proc_read_guard);
	if (prog_fd < 0) {
		error = report_libbpf_error("get expected BPF program fd", prog_fd);
		goto out;
	}
	if (bpf_prog_get_info_by_fd(prog_fd, &prog_info, &info_len) != 0) {
		error = report_errno("read expected BPF program info", errno);
		goto out;
	}
	memcpy(tag, prog_info.tag, BPF_TAG_SIZE);
	error = 0;

out:
	proc_read_guard_bpf__destroy(skel);
	return error;
}

enum link_validation_mode {
	/* Keep recovery working when later builds grow rodata or add maps. */
	LINK_VALIDATE_COMPATIBLE,
	LINK_VALIDATE_CURRENT,
};

static bool map_name_has_rodata(const char name[BPF_OBJ_NAME_LEN])
{
	char map_name[BPF_OBJ_NAME_LEN + 1] = {};

	memcpy(map_name, name, BPF_OBJ_NAME_LEN);
	return strstr(map_name, ".rodata") != NULL;
}

static int open_expected_link(const char *link_path, __u32 uid,
			      enum link_validation_mode mode, __u32 trusted_gid,
			      struct bpf_link **link_out, int *prog_fd_out)
{
	struct proc_read_guard_bpf__rodata rodata = {};
	struct bpf_link_info link_info = {};
	struct bpf_prog_info prog_info = {};
	struct bpf_map_info map_info = {};
	struct bpf_link *link = NULL;
	void *map_value = NULL;
	__u8 pinned_tag[BPF_TAG_SIZE] = {};
	__u8 expected_tag[BPF_TAG_SIZE] = {};
	__u32 info_len;
	__u32 *map_ids = NULL;
	__u32 map_count;
	__u32 map_key = 0;
	__u32 protected_uid = 0;
	__u32 i;
	bool found_rodata = false;
	int prog_fd = -1;
	int map_fd = -1;
	int link_fd;
	int error = 1;

	link = bpf_link__open(link_path);
	if (!link)
		return report_errno("open pinned BPF link", errno ? errno : EINVAL);
	link_fd = bpf_link__fd(link);
	if (link_fd < 0) {
		error = report_libbpf_error("get pinned BPF link fd", link_fd);
		goto out;
	}
	info_len = sizeof(link_info);
	if (bpf_link_get_info_by_fd(link_fd, &link_info, &info_len) != 0) {
		error = report_errno("read pinned BPF link info", errno);
		goto out;
	}
	if (link_info.prog_id == 0) {
		error = report_unexpected_link(link_path, uid, "missing program id");
		goto out;
	}
	prog_fd = bpf_prog_get_fd_by_id(link_info.prog_id);
	if (prog_fd < 0) {
		error = report_errno("open pinned BPF program", errno);
		goto out;
	}
	info_len = sizeof(prog_info);
	if (bpf_prog_get_info_by_fd(prog_fd, &prog_info, &info_len) != 0) {
		error = report_errno("read pinned BPF program info", errno);
		goto out;
	}
	if (prog_info.type != BPF_PROG_TYPE_LSM ||
	    strncmp(prog_info.name, PROGRAM_NAME, sizeof(prog_info.name)) != 0) {
		fprintf(stderr,
			"proc-read-guard: %s is not proc-read-guard for uid %u: "
			"found program %.*s type %u\n",
			link_path, uid, BPF_OBJ_NAME_LEN, prog_info.name, prog_info.type);
		goto out;
	}
	memcpy(pinned_tag, prog_info.tag, sizeof(pinned_tag));
	map_count = prog_info.nr_map_ids;
	if (map_count == 0 ||
	    (mode == LINK_VALIDATE_CURRENT && map_count != 1)) {
		error = report_unexpected_link(link_path, uid, "unexpected map count");
		goto out;
	}
	map_ids = calloc(map_count, sizeof(*map_ids));
	if (!map_ids) {
		error = report_errno("allocate pinned BPF map ids", ENOMEM);
		goto out;
	}
	memset(&prog_info, 0, sizeof(prog_info));
	prog_info.nr_map_ids = map_count;
	prog_info.map_ids = (__u64)(uintptr_t)map_ids;
	info_len = sizeof(prog_info);
	if (bpf_prog_get_info_by_fd(prog_fd, &prog_info, &info_len) != 0) {
		error = report_errno("read pinned BPF map ids", errno);
		goto out;
	}
	if (prog_info.nr_map_ids != map_count) {
		error = report_unexpected_link(link_path, uid, "map count changed during validation");
		goto out;
	}
	for (i = 0; i < map_count; i++) {
		if (map_ids[i] == 0) {
			error = report_unexpected_link(link_path, uid, "missing map id");
			goto out;
		}
		map_fd = bpf_map_get_fd_by_id(map_ids[i]);
		if (map_fd < 0) {
			error = report_errno("open pinned BPF map", errno);
			goto out;
		}
		memset(&map_info, 0, sizeof(map_info));
		info_len = sizeof(map_info);
		if (bpf_map_get_info_by_fd(map_fd, &map_info, &info_len) != 0) {
			error = report_errno("read pinned BPF map info", errno);
			goto out;
		}
		if (!map_name_has_rodata(map_info.name)) {
			close_bpf_fd(map_fd, "map fd");
			map_fd = -1;
			continue;
		}
		if (found_rodata) {
			error = report_unexpected_link(link_path, uid, "multiple rodata maps");
			goto out;
		}
		if (map_info.type != BPF_MAP_TYPE_ARRAY ||
		    map_info.key_size != sizeof(map_key) ||
		    map_info.max_entries != 1 ||
		    (mode == LINK_VALIDATE_CURRENT &&
		     map_info.value_size != sizeof(rodata)) ||
		    (mode == LINK_VALIDATE_COMPATIBLE &&
		     map_info.value_size < sizeof(protected_uid))) {
			error = report_unexpected_link(link_path, uid, "unexpected rodata map shape");
			goto out;
		}
		if (mode == LINK_VALIDATE_CURRENT) {
			if (bpf_map_lookup_elem(map_fd, &map_key, &rodata) != 0) {
				error = report_errno("read pinned BPF rodata map", errno);
				goto out;
			}
			protected_uid = rodata.protected_uid;
		} else {
			map_value = calloc(1, map_info.value_size);
			if (!map_value) {
				error = report_errno("allocate pinned BPF rodata map value", ENOMEM);
				goto out;
			}
			if (bpf_map_lookup_elem(map_fd, &map_key, map_value) != 0) {
				error = report_errno("read pinned BPF rodata map", errno);
				goto out;
			}
			memcpy(&protected_uid, map_value, sizeof(protected_uid));
			free(map_value);
			map_value = NULL;
		}
		found_rodata = true;
		close_bpf_fd(map_fd, "rodata map fd");
		map_fd = -1;
	}
	if (!found_rodata) {
		error = report_unexpected_link(link_path, uid, "missing rodata map");
		goto out;
	}
	if (protected_uid != uid) {
		fprintf(stderr,
			"proc-read-guard: %s protects uid %u, expected uid %u\n",
			link_path, protected_uid, uid);
		goto out;
	}
	if (mode == LINK_VALIDATE_CURRENT) {
		if (rodata.trusted_reader_gid != trusted_gid) {
			error = report_unexpected_link(link_path, uid,
						       "trusted-reader group changed; reload required");
			goto out;
		}
		if (read_expected_prog_tag(uid, trusted_gid, expected_tag) != 0)
			goto out;
		if (memcmp(pinned_tag, expected_tag, sizeof(pinned_tag)) != 0) {
			error = report_unexpected_link(link_path, uid,
						       "program tag does not match current build");
			goto out;
		}
	}

	free(map_ids);
	if (prog_fd_out) {
		*prog_fd_out = prog_fd;
		prog_fd = -1;
	}
	close_bpf_fd(prog_fd, "program fd");
	*link_out = link;
	return 0;

out:
	free(map_value);
	free(map_ids);
	close_bpf_fd(map_fd, "rodata map fd");
	close_bpf_fd(prog_fd, "program fd");
	release_link_reference(link);
	return error;
}

static int read_yama_scope(unsigned int *scope)
{
	FILE *file;
	char buffer[32];
	char *end = NULL;
	unsigned long value;

	file = fopen(YAMA_PTRACE_SCOPE, "r");
	if (!file)
		return report_errno("open " YAMA_PTRACE_SCOPE, errno);
	if (!fgets(buffer, sizeof(buffer), file)) {
		int error = ferror(file) ? errno : EINVAL;

		fclose(file);
		return report_errno("read " YAMA_PTRACE_SCOPE, error);
	}
	if (fclose(file) != 0)
		return report_errno("close " YAMA_PTRACE_SCOPE, errno);
	errno = 0;
	value = strtoul(buffer, &end, 10);
	if (errno != 0 || end == buffer || value > UINT_MAX)
		return report_errno("parse " YAMA_PTRACE_SCOPE, EINVAL);
	while (*end) {
		if (!is_ascii_space(*end))
			return report_errno("parse " YAMA_PTRACE_SCOPE, EINVAL);
		end++;
	}
	*scope = (unsigned int)value;
	return 0;
}

static int require_yama_scope_one(void)
{
	unsigned int scope;

	if (read_yama_scope(&scope) != 0)
		return 1;
	if (scope != 1) {
		fprintf(stderr,
			"proc-read-guard: kernel.yama.ptrace_scope must be 1, found %u\n",
			scope);
		return 1;
	}
	return 0;
}

static int load_guard(__u32 uid)
{
	struct bpf_link *link = NULL;
	struct proc_read_guard_bpf *skel = NULL;
	struct bpf_link_update_opts update_opts = {
		.sz = sizeof(update_opts),
		.flags = BPF_F_REPLACE,
	};
	char uid_dir[PATH_MAX];
	char link_path[PATH_MAX];
	__u32 trusted_gid;
	int old_prog_fd = -1;
	int new_prog_fd;
	int link_fd;
	int error;

	if (require_yama_scope_one() != 0)
		return 1;
	trusted_gid = read_trusted_reader_gid();
	if (!format_paths(uid, uid_dir, sizeof(uid_dir), link_path, sizeof(link_path))) {
		fprintf(stderr, "proc-read-guard: pin path is too long\n");
		return 1;
	}
	if (path_exists(link_path)) {
		if (open_expected_link(link_path, uid, LINK_VALIDATE_COMPATIBLE,
				       trusted_gid, &link, &old_prog_fd) != 0)
			return 1;
		skel = proc_read_guard_bpf__open();
		if (!skel) {
			close_bpf_fd(old_prog_fd, "program fd");
			release_link_reference(link);
			return report_errno("open BPF skeleton", errno ? errno : ENOMEM);
		}
		configure_rodata(skel, uid, trusted_gid);
		error = proc_read_guard_bpf__load(skel);
		if (error != 0) {
			proc_read_guard_bpf__destroy(skel);
			close_bpf_fd(old_prog_fd, "program fd");
			release_link_reference(link);
			return report_libbpf_error("load BPF program", error);
		}
		new_prog_fd = bpf_program__fd(skel->progs.proc_read_guard);
		if (new_prog_fd < 0) {
			error = report_libbpf_error("get BPF program fd", new_prog_fd);
			proc_read_guard_bpf__destroy(skel);
			close_bpf_fd(old_prog_fd, "program fd");
			release_link_reference(link);
			return error;
		}
		link_fd = bpf_link__fd(link);
		if (link_fd < 0) {
			error = report_libbpf_error("get pinned BPF link fd", link_fd);
			proc_read_guard_bpf__destroy(skel);
			close_bpf_fd(old_prog_fd, "program fd");
			release_link_reference(link);
			return error;
		}
		update_opts.old_prog_fd = old_prog_fd;
		error = bpf_link_update(link_fd, new_prog_fd, &update_opts);
		proc_read_guard_bpf__destroy(skel);
		close_bpf_fd(old_prog_fd, "program fd");
		release_link_reference(link);
		if (error != 0)
			return report_libbpf_error("update pinned BPF link", error);
		printf("proc-read-guard: updated for uid %u at %s\n", uid, link_path);
		return 0;
	}
	if (ensure_directory(BPF_PIN_ROOT) != 0 || ensure_directory(uid_dir) != 0)
		return 1;

	skel = proc_read_guard_bpf__open();
	if (!skel)
		return report_errno("open BPF skeleton", errno ? errno : ENOMEM);
	configure_rodata(skel, uid, trusted_gid);
	error = proc_read_guard_bpf__load(skel);
	if (error != 0) {
		proc_read_guard_bpf__destroy(skel);
		remove_empty_directory(uid_dir);
		remove_empty_directory(BPF_PIN_ROOT);
		return report_libbpf_error("load BPF program", error);
	}
	error = proc_read_guard_bpf__attach(skel);
	if (error != 0) {
		proc_read_guard_bpf__destroy(skel);
		remove_empty_directory(uid_dir);
		remove_empty_directory(BPF_PIN_ROOT);
		return report_libbpf_error("attach BPF program", error);
	}
	error = bpf_link__pin(skel->links.proc_read_guard, link_path);
	if (error != 0) {
		proc_read_guard_bpf__destroy(skel);
		remove_empty_directory(uid_dir);
		remove_empty_directory(BPF_PIN_ROOT);
		return report_libbpf_error("pin BPF link", error);
	}
	bpf_link__disconnect(skel->links.proc_read_guard);
	proc_read_guard_bpf__destroy(skel);
	printf("proc-read-guard: loaded for uid %u at %s\n", uid, link_path);
	return 0;
}

static int unload_guard(__u32 uid)
{
	struct bpf_link *link = NULL;
	char uid_dir[PATH_MAX];
	char link_path[PATH_MAX];
	int error;

	if (!format_paths(uid, uid_dir, sizeof(uid_dir), link_path, sizeof(link_path))) {
		fprintf(stderr, "proc-read-guard: pin path is too long\n");
		return 1;
	}
	if (!path_exists(link_path)) {
		printf("proc-read-guard: not loaded for uid %u\n", uid);
		remove_empty_directory(uid_dir);
		remove_empty_directory(BPF_PIN_ROOT);
		return 0;
	}
	if (open_expected_link(link_path, uid, LINK_VALIDATE_COMPATIBLE,
			       UINT32_MAX, &link, NULL) != 0)
		return 1;
	error = bpf_link__unpin(link);
	if (error != 0) {
		release_link_reference(link);
		return report_libbpf_error("unpin BPF link", error);
	}
	error = bpf_link__destroy(link);
	if (error != 0)
		return report_libbpf_error("destroy BPF link", error);
	remove_empty_directory(uid_dir);
	remove_empty_directory(BPF_PIN_ROOT);
	printf("proc-read-guard: unloaded for uid %u\n", uid);
	return 0;
}

static int status_guard(__u32 uid)
{
	struct bpf_link *link = NULL;
	char uid_dir[PATH_MAX];
	char link_path[PATH_MAX];
	unsigned int scope;
	__u32 trusted_gid;
	bool loaded;

	if (!format_paths(uid, uid_dir, sizeof(uid_dir), link_path, sizeof(link_path))) {
		fprintf(stderr, "proc-read-guard: pin path is too long\n");
		return 1;
	}
	if (read_yama_scope(&scope) != 0)
		return 1;
	trusted_gid = read_trusted_reader_gid();
	loaded = path_exists(link_path);
	if (loaded) {
		if (open_expected_link(link_path, uid, LINK_VALIDATE_CURRENT,
				       trusted_gid, &link, NULL) != 0)
			return 1;
		release_link_reference(link);
	}
	printf("proc-read-guard: uid=%u loaded=%s yama_ptrace_scope=%u pin=%s "
	       "trusted_reader_group=%s trusted_reader_gid=",
	       uid, loaded ? "yes" : "no", scope, link_path, TRUSTED_READER_GROUP);
	if (trusted_gid == UINT32_MAX)
		puts("disabled");
	else
		printf("%u\n", trusted_gid);
	return loaded && scope == 1 ? 0 : 1;
}

int main(int argc, char **argv)
{
	__u32 uid;

	if (argc == 2 && strcmp(argv[1], "--help") == 0) {
		usage(stdout);
		return 0;
	}
	if (argc != 3 || !parse_uid(argv[2], &uid)) {
		usage(stderr);
		return 2;
	}
	if (geteuid() != 0) {
		fprintf(stderr, "proc-read-guard: must run as root\n");
		return 1;
	}
	if (strcmp(argv[1], "load") == 0)
		return load_guard(uid);
	if (strcmp(argv[1], "unload") == 0)
		return unload_guard(uid);
	if (strcmp(argv[1], "status") == 0)
		return status_guard(uid);
	usage(stderr);
	return 2;
}
