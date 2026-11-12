/* Run the actual BPF policy as native C, replacing only kernel access helpers. */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Model the configuration that libbpf writes before loading the real program. */
#define const
#include "../proc-read-guard.bpf.c"
#undef const

struct task_struct *test_current;

static void task_init(struct task_struct *task, struct cred *cred, int tgid,
                      struct task_struct *parent)
{
    task->cred = cred;
    task->tgid = tgid;
    task->group_leader = task;
    task->real_parent = parent;
}

int main(int argc, char **argv)
{
    static struct cred reader = {
        .uid = {1000}, .gid = {42}, .egid = {42}, .sgid = {42}, .fsgid = {42},
    };
    static struct cred other, root_cred;
    static struct task_struct root, common, current, target, thread;
    static struct task_struct chain[34];
    struct task_struct *subject = &target;
    struct group_info *groups = NULL;
    unsigned int access_mode = PTRACE_MODE_READ;
    int earlier_result = 0;
    const char *scenario;
    int result;

    if (argc < 2)
        return 2;
    scenario = argv[1];
    protected_uid = 1000;
    trusted_reader_gid = 1001;
    other = reader;
    root_cred = reader;
    root_cred.uid.val = 0;
    task_init(&root, &root_cred, 1, &root);
    task_init(&common, &other, 10, &root);
    task_init(&current, &reader, 20, &common);
    task_init(&target, &other, 30, &common);
    test_current = &current;

    if (!strcmp(scenario, "ordinary") || !strcmp(scenario, "renamed-impostor")) {
        /* A process name or executable ownership is not an access credential. */
    } else if (!strcmp(scenario, "real-group")) {
        reader.gid.val = 1001;
    } else if (!strcmp(scenario, "effective-group")) {
        reader.egid.val = 1001;
    } else if (!strcmp(scenario, "saved-group")) {
        reader.sgid.val = 1001;
    } else if (!strcmp(scenario, "filesystem-group")) {
        reader.fsgid.val = 1001;
    } else if (!strcmp(scenario, "inherited-group")) {
        reader.gid.val = reader.egid.val = reader.sgid.val = reader.fsgid.val = 1001;
    } else if (!strcmp(scenario, "trusted-parent-target")) {
        reader.sgid.val = 1001;
        subject = &common;
    } else if (!strcmp(scenario, "trusted-unrelated-target")) {
        reader.sgid.val = 1001;
        target.real_parent = &root;
    } else if (!strcmp(scenario, "disabled-group")) {
        reader.sgid.val = 1001;
        trusted_reader_gid = (__u32)-1;
    } else if (!strcmp(scenario, "root-group")) {
        reader.sgid.val = 0;
        trusted_reader_gid = 0;
    } else if (!strcmp(scenario, "prior-denial")) {
        reader.sgid.val = 1001;
        earlier_result = -13;
    } else if (!strcmp(scenario, "attach")) {
        access_mode = 2;
    } else if (!strcmp(scenario, "read-fscreds")) {
        reader.sgid.val = 1001;
        access_mode |= 8;
    } else if (!strcmp(scenario, "same-process")) {
        target.tgid = current.tgid;
    } else if (!strcmp(scenario, "parent-reader")) {
        target.real_parent = &current;
    } else if (!strcmp(scenario, "threaded-parent-reader")) {
        task_init(&thread, &reader, current.tgid, &common);
        thread.group_leader = &current;
        target.real_parent = &thread;
        test_current = &thread;
    } else if (!strcmp(scenario, "other-caller-uid")) {
        reader.uid.val = 2000;
    } else if (!strcmp(scenario, "root-caller")) {
        reader.uid.val = 0;
    } else if (!strcmp(scenario, "other-target-uid")) {
        other.uid.val = 2000;
    } else if (!strcmp(scenario, "ancestor")) {
        int depth;
        if (argc != 3)
            return 2;
        depth = atoi(argv[2]);
        if (depth < 1 || depth > 33)
            return 2;
        task_init(&chain[0], &reader, 100, &root);
        for (int i = 1; i <= depth; i++)
            task_init(&chain[i], &other, 100 + i, &chain[i - 1]);
        test_current = &chain[0];
        subject = &chain[depth];
    } else if (!strcmp(scenario, "supplementary")) {
        int count;
        if (argc != 4)
            return 2;
        count = atoi(argv[2]);
        if (count < 0 || count > 65536)
            return 2;
        trusted_reader_gid = (__u32)strtoul(argv[3], NULL, 10);
        groups = calloc(1, sizeof(*groups) + (size_t)count * sizeof(kgid_t));
        if (!groups)
            return 3;
        groups->ngroups = count;
        for (int i = 0; i < count; i++)
            groups->gid[i].val = 100 + 2 * (__u32)i;
        reader.group_info = groups;
    } else {
        return 2;
    }

    result = proc_read_guard(subject, access_mode, earlier_result);
    printf("%d\n", result);
    free(groups);
    reader.group_info = NULL;
    return 0;
}
