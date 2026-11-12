#ifndef PROC_GUARD_TEST_HELPERS_H
#define PROC_GUARD_TEST_HELPERS_H
#ifndef __always_inline
#define __always_inline inline __attribute__((always_inline))
#endif
#define SEC(section)
extern struct task_struct *test_current;
static inline void *bpf_get_current_task_btf(void) { return test_current; }
#endif
