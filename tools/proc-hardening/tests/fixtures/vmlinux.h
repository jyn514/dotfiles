#ifndef PROC_GUARD_TEST_VMLINUX_H
#define PROC_GUARD_TEST_VMLINUX_H
typedef unsigned int __u32;
typedef struct { __u32 val; } kuid_t;
typedef struct { __u32 val; } kgid_t;
struct group_info { int ngroups; kgid_t gid[]; };
struct cred {
    kuid_t uid;
    kgid_t gid, egid, sgid, fsgid;
    struct group_info *group_info;
};
struct task_struct {
    struct cred *cred;
    int tgid;
    struct task_struct *real_parent, *group_leader;
};
#endif
