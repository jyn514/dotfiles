#include "lapwing_qmk.h"

#include "lapwing_engine.h"
#include "process_steno.h"
#include "quantum.h"

#include <string.h>

extern const uint8_t lapwing_model_start[];
extern const uint8_t lapwing_model_end[];

static lw_model_t model;
static lw_engine_t engine;

static void emit_text(void *context, const char *text) {
    (void)context;
    send_string(text);
}

static void emit_backspaces(void *context, uint8_t count) {
    (void)context;
    while (count--) tap_code(KC_BSPC);
}

void lapwing_qmk_init(void) {
    model.data = lapwing_model_start;
    model.size = (size_t)(lapwing_model_end - lapwing_model_start);
    lw_engine_init(&engine, &model, emit_text, emit_backspaces, NULL);
}

void lapwing_qmk_task(void) {
    lw_engine_tick(&engine, timer_read32());
}

static bool chord_has(const uint8_t chord[MAX_STROKE_SIZE], uint16_t keycode) {
    uint8_t key = (uint8_t)(keycode - QK_STENO);
    uint8_t group = key / 7u;
    uint8_t bit = 1u << (6u - key % 7u);
    return (chord[group] & bit) != 0;
}

static void append_key(char *stroke, uint8_t *length, char key) {
    if (*length < 19u) stroke[(*length)++] = key;
}

static void chord_to_stroke(const uint8_t chord[MAX_STROKE_SIZE], char stroke[20]) {
    uint8_t length = 0;
    bool left_s = chord_has(chord, STN_S1) || chord_has(chord, STN_S2);
    bool star = chord_has(chord, STN_ST1) || chord_has(chord, STN_ST2)
             || chord_has(chord, STN_ST3) || chord_has(chord, STN_ST4);
    bool right = chord_has(chord, STN_FR) || chord_has(chord, STN_RR)
              || chord_has(chord, STN_PR) || chord_has(chord, STN_BR)
              || chord_has(chord, STN_LR) || chord_has(chord, STN_GR)
              || chord_has(chord, STN_TR) || chord_has(chord, STN_SR)
              || chord_has(chord, STN_DR) || chord_has(chord, STN_ZR);
    bool vowels = chord_has(chord, STN_A) || chord_has(chord, STN_O)
               || chord_has(chord, STN_E) || chord_has(chord, STN_U);

    if (chord_has(chord, STN_PWR)) {
        strcpy(stroke, "PWR");
        return;
    }
    if (left_s) append_key(stroke, &length, 'S');
    if (chord_has(chord, STN_TL)) append_key(stroke, &length, 'T');
    if (chord_has(chord, STN_KL)) append_key(stroke, &length, 'K');
    if (chord_has(chord, STN_PL)) append_key(stroke, &length, 'P');
    if (chord_has(chord, STN_WL)) append_key(stroke, &length, 'W');
    if (chord_has(chord, STN_HL)) append_key(stroke, &length, 'H');
    if (chord_has(chord, STN_RL)) append_key(stroke, &length, 'R');
    if (chord_has(chord, STN_A)) append_key(stroke, &length, 'A');
    if (chord_has(chord, STN_O)) append_key(stroke, &length, 'O');
    if (star) append_key(stroke, &length, '*');
    if (!vowels && right) append_key(stroke, &length, '-');
    if (chord_has(chord, STN_E)) append_key(stroke, &length, 'E');
    if (chord_has(chord, STN_U)) append_key(stroke, &length, 'U');
    if (chord_has(chord, STN_FR)) append_key(stroke, &length, 'F');
    if (chord_has(chord, STN_RR)) append_key(stroke, &length, 'R');
    if (chord_has(chord, STN_PR)) append_key(stroke, &length, 'P');
    if (chord_has(chord, STN_BR)) append_key(stroke, &length, 'B');
    if (chord_has(chord, STN_LR)) append_key(stroke, &length, 'L');
    if (chord_has(chord, STN_GR)) append_key(stroke, &length, 'G');
    if (chord_has(chord, STN_TR)) append_key(stroke, &length, 'T');
    if (chord_has(chord, STN_SR)) append_key(stroke, &length, 'S');
    if (chord_has(chord, STN_DR)) append_key(stroke, &length, 'D');
    if (chord_has(chord, STN_ZR)) append_key(stroke, &length, 'Z');
    stroke[length] = '\0';
}

bool send_steno_chord_user(steno_mode_t mode, uint8_t chord[MAX_STROKE_SIZE]) {
    (void)mode;
    char stroke[20];
    chord_to_stroke(chord, stroke);
    if (stroke[0]) lw_engine_stroke(&engine, stroke, timer_read32());
    return false;
}
