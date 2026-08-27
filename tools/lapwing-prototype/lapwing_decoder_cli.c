#include "lapwing_decoder.h"

#include <stdio.h>
#include <string.h>

int main(void) {
    char outline[160];
    while (fgets(outline, sizeof(outline), stdin)) {
        outline[strcspn(outline, "\r\n")] = '\0';
        lw_candidates_t result;
        lw_decode_outline(outline, &result);
        printf("%s\t", outline);
        for (uint16_t i = 0; i < result.count; ++i)
            printf("%s%s", i ? "|" : "", result.words[i]);
        putchar('\n');
    }
    return 0;
}
