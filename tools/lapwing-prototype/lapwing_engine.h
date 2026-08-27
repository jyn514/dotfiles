#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "lapwing_model.h"

#ifndef LW_COMMIT_DELAY_MS
#define LW_COMMIT_DELAY_MS 240u
#endif
#ifndef LW_HISTORY_SIZE
#define LW_HISTORY_SIZE 8
#endif

typedef void (*lw_emit_fn)(void *context, const char *text);
typedef void (*lw_backspace_fn)(void *context, uint8_t count);

typedef struct {
    uint8_t emitted;
    bool had_text;
    bool capitalize;
} lw_history_entry_t;

typedef struct {
    const lw_model_t *model;
    lw_emit_fn emit;
    lw_backspace_fn backspace;
    void *io_context;
    char outline[LW_MAX_STROKES * 20];
    char pending[LW_MAX_WORD + 1];
    uint32_t last_stroke_time;
    uint8_t history_count;
    bool has_text;
    bool capitalize_next;
    lw_history_entry_t history[LW_HISTORY_SIZE];
} lw_engine_t;

void lw_engine_init(lw_engine_t *engine, const lw_model_t *model,
                    lw_emit_fn emit, lw_backspace_fn backspace, void *context);
void lw_engine_stroke(lw_engine_t *engine, const char *stroke, uint32_t now);
void lw_engine_tick(lw_engine_t *engine, uint32_t now);
void lw_engine_commit(lw_engine_t *engine);
void lw_engine_cancel(lw_engine_t *engine);
void lw_engine_undo(lw_engine_t *engine);
