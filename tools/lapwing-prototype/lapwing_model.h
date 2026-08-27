#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "lapwing_decoder.h"

typedef struct {
    const uint8_t *data;
    size_t size;
} lw_model_t;

bool lw_model_valid(const lw_model_t *model);
bool lw_model_contains(const lw_model_t *model, const char *word);
bool lw_model_has_prefix(const lw_model_t *model, const char *prefix);
bool lw_model_exception(const lw_model_t *model, const char *outline,
                        char output[LW_MAX_WORD + 1]);

/* Exact exceptions take priority; otherwise return vocabulary-approved rules. */
size_t lw_model_translate(const lw_model_t *model, const char *outline,
                          char output[][LW_MAX_WORD + 1], size_t output_capacity);
