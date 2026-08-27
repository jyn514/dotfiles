#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifndef LW_MAX_WORD
#define LW_MAX_WORD 32
#endif
#ifndef LW_MAX_CANDIDATES
#define LW_MAX_CANDIDATES 64
#endif
#ifndef LW_MAX_STROKES
#define LW_MAX_STROKES 16
#endif

typedef bool (*lw_word_accept_fn)(void *context, const char *word);
typedef bool (*lw_prefix_accept_fn)(void *context, const char *prefix);

typedef struct {
    char words[LW_MAX_CANDIDATES][LW_MAX_WORD + 1];
    uint16_t count;
} lw_candidates_t;

/* Decode slash-separated canonical steno strokes without heap allocation. */
void lw_decode_outline(const char *outline, lw_candidates_t *result);
void lw_decode_outline_pruned(const char *outline, lw_prefix_accept_fn accept_prefix,
                              void *context, lw_candidates_t *result);
void lw_decode_outline_final_unpruned(const char *outline,
                                      lw_prefix_accept_fn accept_prefix,
                                      void *context, lw_candidates_t *result);

/* Return accepted candidates in generation order, up to output capacity. */
size_t lw_translate_outline(const char *outline, lw_word_accept_fn accept,
                            void *context, char output[][LW_MAX_WORD + 1],
                            size_t output_capacity);
