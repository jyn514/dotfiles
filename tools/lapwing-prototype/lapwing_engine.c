#include "lapwing_engine.h"

#include <string.h>

static const char *punctuation(const char *outline) {
    if (strcmp(outline, "TP-PL") == 0) return ".";
    if (strcmp(outline, "KW-BG") == 0) return ",";
    if (strcmp(outline, "STPH-FPLT") == 0) return "?";
    if (strcmp(outline, "SKWR-RBGS") == 0) return "!";
    return NULL;
}

static bool translate(lw_engine_t *engine, const char *outline,
                      char output[LW_MAX_WORD + 1]) {
    const char *mark = punctuation(outline);
    if (mark) {
        strcpy(output, mark);
        return true;
    }
    char candidates[1][LW_MAX_WORD + 1];
    if (!lw_model_translate(engine->model, outline, candidates, 1)) return false;
    strcpy(output, candidates[0]);
    return true;
}

void lw_engine_init(lw_engine_t *engine, const lw_model_t *model,
                    lw_emit_fn emit, lw_backspace_fn backspace, void *context) {
    memset(engine, 0, sizeof(*engine));
    engine->model = model;
    engine->emit = emit;
    engine->backspace = backspace;
    engine->io_context = context;
    engine->capitalize_next = true;
}

void lw_engine_cancel(lw_engine_t *engine) {
    engine->outline[0] = '\0';
    engine->pending[0] = '\0';
}

static void remember(lw_engine_t *engine, uint8_t emitted) {
    if (engine->history_count == LW_HISTORY_SIZE) {
        memmove(engine->history, engine->history + 1,
                (LW_HISTORY_SIZE - 1) * sizeof(engine->history[0]));
        --engine->history_count;
    }
    engine->history[engine->history_count++] = (lw_history_entry_t) {
        .emitted = emitted,
        .had_text = engine->has_text,
        .capitalize = engine->capitalize_next,
    };
}

void lw_engine_commit(lw_engine_t *engine) {
    if (!engine->pending[0]) {
        lw_engine_cancel(engine);
        return;
    }
    bool mark = strchr(".,?!", engine->pending[0]) && !engine->pending[1];
    char text[LW_MAX_WORD + 2];
    uint8_t length = 0;
    if (!mark && engine->has_text) text[length++] = ' ';
    size_t word_length = strlen(engine->pending);
    memcpy(text + length, engine->pending, word_length + 1);
    if (!mark && engine->capitalize_next && text[length] >= 'a' && text[length] <= 'z')
        text[length] -= 'a' - 'A';
    length += (uint8_t)word_length;
    remember(engine, length);
    engine->emit(engine->io_context, text);
    engine->has_text = true;
    engine->capitalize_next = mark && strchr(".?!", engine->pending[0]);
    lw_engine_cancel(engine);
}

void lw_engine_undo(lw_engine_t *engine) {
    if (engine->pending[0]) {
        lw_engine_cancel(engine);
        return;
    }
    if (!engine->history_count) return;
    lw_history_entry_t entry = engine->history[--engine->history_count];
    engine->backspace(engine->io_context, entry.emitted);
    engine->has_text = entry.had_text;
    engine->capitalize_next = entry.capitalize;
}

void lw_engine_stroke(lw_engine_t *engine, const char *stroke, uint32_t now) {
    if (!stroke || !stroke[0]) return;
    if (strcmp(stroke, "PWR") == 0) {
        lw_engine_commit(engine);
        return;
    }
    if (strcmp(stroke, "*") == 0) {
        lw_engine_undo(engine);
        return;
    }

    char proposed[sizeof(engine->outline)];
    size_t current = strlen(engine->outline);
    size_t addition = strlen(stroke);
    if (current + (current ? 1u : 0u) + addition >= sizeof(proposed)) {
        lw_engine_commit(engine);
        current = 0;
    }
    if (current) {
        memcpy(proposed, engine->outline, current);
        proposed[current++] = '/';
    }
    memcpy(proposed + current, stroke, addition + 1);

    char translated[LW_MAX_WORD + 1];
    if (!translate(engine, proposed, translated) && engine->pending[0]) {
        lw_engine_commit(engine);
        strcpy(proposed, stroke);
    }
    strcpy(engine->outline, proposed);
    engine->last_stroke_time = now;
    if (translate(engine, proposed, translated))
        strcpy(engine->pending, translated);
    else
        engine->pending[0] = '\0';
}

void lw_engine_tick(lw_engine_t *engine, uint32_t now) {
    if (engine->pending[0] && (uint32_t)(now - engine->last_stroke_time) >= LW_COMMIT_DELAY_MS)
        lw_engine_commit(engine);
}
