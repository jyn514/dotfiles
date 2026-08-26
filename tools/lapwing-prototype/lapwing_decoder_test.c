#include "lapwing_decoder.h"

#include <stdio.h>
#include <string.h>

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
    return failed != 0;
}
