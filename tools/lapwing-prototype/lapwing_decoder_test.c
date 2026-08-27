#include "lapwing_decoder.h"

#include <stdio.h>
#include <string.h>

static bool reject_every_prefix(void *context, const char *prefix) {
    (void)context;
    (void)prefix;
    return false;
}

static int check_contains(const char *outline, const char *expected) {
    lw_candidates_t result;
    lw_decode_outline(outline, &result);
    for (uint16_t i = 0; i < result.count; ++i) {
        if (strcmp(result.words[i], expected) == 0) return 0;
    }
    fprintf(stderr, "%s: expected %s in %u candidates\n", outline, expected, result.count);
    for (uint16_t i = 0; i < result.count && i < 12; ++i)
        fprintf(stderr, "  %s\n", result.words[i]);
    return 1;
}

int main(void) {
    const struct { const char *outline; const char *word; } cases[] = {
        {"KAT", "cat"},
        {"STPHAEUBG", "snake"},
        {"PAOEU/THOPB", "python"},
        {"PRAOE/SRAOU", "preview"},
        {"STKPWAPG", "zapping"},
        {"EURPBT/STAEUT", "interstate"},
        {"PHAOEURBG/TPO*EPB", "microphone"},
        {"HEL/-P/-FL", "helpful"},
    };
    int failed = 0;
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i)
        failed += check_contains(cases[i].outline, cases[i].word);
    lw_candidates_t fingerspelled;
    lw_decode_outline_pruned("U*/S*/A*", reject_every_prefix, NULL, &fingerspelled);
    if (fingerspelled.count != 1 || strcmp(fingerspelled.words[0], "usa") != 0) {
        fprintf(stderr, "direct fingerspelling did not produce only usa\n");
        ++failed;
    }
    lw_decode_outline("W*/O*/R*/HR*/TK*/AES", &fingerspelled);
    if (fingerspelled.count != 1 || strcmp(fingerspelled.words[0], "world's") != 0) {
        fprintf(stderr, "direct possessive spelling did not produce world's\n");
        ++failed;
    }
    return failed != 0;
}
