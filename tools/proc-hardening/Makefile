BUILD_DIR ?= ../../target/proc-hardening
VMLINUX_H := $(BUILD_DIR)/vmlinux.h
BPF_OBJECT := $(BUILD_DIR)/proc-read-guard.bpf.o
SKELETON_H := $(BUILD_DIR)/proc-read-guard.skel.h
LOADER := $(BUILD_DIR)/proc-read-guard

CLANG ?= clang
CC ?= cc
BPFTOOL ?= bpftool
PKG_CONFIG ?= pkg-config

CFLAGS ?= -O2 -g -Wall -Wextra -Werror
BPF_CFLAGS ?= -O2 -g -target bpf -Wno-missing-declarations
LIBBPF_CFLAGS := $(shell $(PKG_CONFIG) --cflags libbpf)
LIBBPF_LIBS := $(shell $(PKG_CONFIG) --libs libbpf)

.PHONY: all clean check-libbpf

all: $(LOADER)

check-libbpf:
	@$(PKG_CONFIG) --atleast-version=1.0 libbpf || \
		{ echo "libbpf >= 1.0 is required" >&2; exit 1; }

$(BUILD_DIR):
	mkdir -p $@

$(VMLINUX_H): check-libbpf | $(BUILD_DIR)
	$(BPFTOOL) btf dump file /sys/kernel/btf/vmlinux format c > $@.tmp
	mv $@.tmp $@

$(BPF_OBJECT): proc-read-guard.bpf.c $(VMLINUX_H) | $(BUILD_DIR)
	$(CLANG) $(BPF_CFLAGS) -I$(BUILD_DIR) -c $< -o $@

$(SKELETON_H): $(BPF_OBJECT) | $(BUILD_DIR)
	$(BPFTOOL) gen skeleton $< > $@.tmp
	mv $@.tmp $@

$(LOADER): proc-read-guard.c $(SKELETON_H) | $(BUILD_DIR) check-libbpf
	$(CC) $(CFLAGS) $(LIBBPF_CFLAGS) -I$(BUILD_DIR) $< -o $@ $(LIBBPF_LIBS)

clean:
	rm -rf $(BUILD_DIR)
