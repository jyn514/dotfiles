#include "vmlinux.h"

#include <bpf/bpf_core_read.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>

#define EPERM 1
#define PTRACE_MODE_READ 0x01
#define MAX_PARENT_HOPS 16
#define MAX_SUPPLEMENTARY_GROUPS 65536
#define GROUP_SEARCH_STEPS 17

const volatile __u32 protected_uid = 0;
/* An invalid kernel gid disables the optional trusted-reader exemption. */
const volatile __u32 trusted_reader_gid = (__u32)-1;

static __always_inline bool task_has_protected_uid(struct task_struct *task)
{
	const struct cred *cred = BPF_CORE_READ(task, cred);
	__u32 uid = BPF_CORE_READ(cred, uid.val);

	return uid == protected_uid;
}

static __always_inline bool same_thread_group(struct task_struct *left,
					      struct task_struct *right)
{
	return BPF_CORE_READ(left, tgid) == BPF_CORE_READ(right, tgid);
}

static __always_inline struct task_struct *task_group_leader(struct task_struct *task)
{
	return BPF_CORE_READ(task, group_leader);
}

static __always_inline bool current_is_ancestor_of(struct task_struct *task)
{
	struct task_struct *current = (struct task_struct *)bpf_get_current_task_btf();
	struct task_struct *cursor = task;

	current = task_group_leader(current);

#pragma unroll
	for (int i = 0; i < MAX_PARENT_HOPS; i++) {
		if (!current || !cursor)
			return false;
		cursor = BPF_CORE_READ(cursor, real_parent);
		if (!cursor)
			return false;
		cursor = task_group_leader(cursor);
		if (!cursor)
			return false;
		if (cursor == current)
			return true;
	}

	return false;
}

static __always_inline bool current_has_trusted_reader_group(struct task_struct *current)
{
	const struct cred *cred;
	struct group_info *groups;
	int left = 0;
	int right;

	if (trusted_reader_gid == (__u32)-1)
		return false;
	cred = BPF_CORE_READ(current, cred);
	if (!cred)
		return false;
	/* Include saved credentials when a helper temporarily drops its group. */
	if (BPF_CORE_READ(cred, gid.val) == trusted_reader_gid ||
	    BPF_CORE_READ(cred, egid.val) == trusted_reader_gid ||
	    BPF_CORE_READ(cred, sgid.val) == trusted_reader_gid ||
	    BPF_CORE_READ(cred, fsgid.val) == trusted_reader_gid)
		return true;

	groups = BPF_CORE_READ(cred, group_info);
	if (!groups)
		return false;
	right = BPF_CORE_READ(groups, ngroups);
	if (right < 0 || right > MAX_SUPPLEMENTARY_GROUPS)
		return false;
	/* Kernel supplementary groups are sorted; 17 steps cover NGROUPS_MAX. */
#pragma unroll
	for (int step = 0; step < GROUP_SEARCH_STEPS; step++) {
		kgid_t group;
		int middle;

		if (left >= right)
			return false;
		middle = left + (right - left) / 2;
		if (bpf_core_read(&group, sizeof(group), &groups->gid[middle]) != 0)
			return false;
		if (group.val == trusted_reader_gid)
			return true;
		if (group.val < trusted_reader_gid)
			left = middle + 1;
		else
			right = middle;
	}
	return false;
}

SEC("lsm/ptrace_access_check")
int BPF_PROG(proc_read_guard, struct task_struct *child, unsigned int mode, int ret)
{
	struct task_struct *current = (struct task_struct *)bpf_get_current_task_btf();

	if (ret != 0)
		return ret;
	if ((mode & PTRACE_MODE_READ) == 0)
		return 0;
	if (!task_has_protected_uid(current) || !task_has_protected_uid(child))
		return 0;
	if (same_thread_group(current, child))
		return 0;
	if (current_is_ancestor_of(child))
		return 0;
	if (current_has_trusted_reader_group(current))
		return 0;
	return -EPERM;
}

char LICENSE[] SEC("license") = "GPL";
