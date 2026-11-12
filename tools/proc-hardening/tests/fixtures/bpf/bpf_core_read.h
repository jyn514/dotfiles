#ifndef PROC_GUARD_TEST_CORE_READ_H
#define PROC_GUARD_TEST_CORE_READ_H
#define BPF_CORE_READ(source, field) ((source)->field)
static inline int bpf_core_read(void *destination, unsigned int size, void *source)
{
    memcpy(destination, source, size);
    return 0;
}
#endif
