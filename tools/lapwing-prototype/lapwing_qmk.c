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

static uint16_t qmk_keycode(lw_key_t key, uint8_t *implicit_modifiers) {
    if (key >= LW_KEY_A && key <= LW_KEY_Z)
        return (uint16_t)(KC_A + key - LW_KEY_A);
    if (key >= LW_KEY_F1 && key <= LW_KEY_F12)
        return (uint16_t)(KC_F1 + key - LW_KEY_F1);
    switch (key) {
        case LW_KEY_NONE: return KC_NO;
        case LW_KEY_0: return KC_0;
        case LW_KEY_1: return KC_1;
        case LW_KEY_2: return KC_2;
        case LW_KEY_3: return KC_3;
        case LW_KEY_4: return KC_4;
        case LW_KEY_5: return KC_5;
        case LW_KEY_6: return KC_6;
        case LW_KEY_7: return KC_7;
        case LW_KEY_8: return KC_8;
        case LW_KEY_9: return KC_9;
        case LW_KEY_TAB: return KC_TAB;
        case LW_KEY_BACKSPACE: return KC_BSPC;
        case LW_KEY_DELETE: return KC_DEL;
        case LW_KEY_ESCAPE: return KC_ESC;
        case LW_KEY_UP: return KC_UP;
        case LW_KEY_LEFT: return KC_LEFT;
        case LW_KEY_RIGHT: return KC_RGHT;
        case LW_KEY_DOWN: return KC_DOWN;
        case LW_KEY_PAGE_UP: return KC_PGUP;
        case LW_KEY_HOME: return KC_HOME;
        case LW_KEY_END: return KC_END;
        case LW_KEY_PAGE_DOWN: return KC_PGDN;
        case LW_KEY_AUDIO_PLAY: return KC_MPLY;
        case LW_KEY_AUDIO_PREV: return KC_MPRV;
        case LW_KEY_AUDIO_NEXT: return KC_MNXT;
        case LW_KEY_AUDIO_STOP: return KC_MSTP;
        case LW_KEY_AUDIO_MUTE: return KC_MUTE;
        case LW_KEY_AUDIO_DOWN: return KC_VOLD;
        case LW_KEY_AUDIO_UP: return KC_VOLU;
        case LW_KEY_ENTER: return KC_ENT;
        case LW_KEY_SPACE: return KC_SPC;
        case LW_KEY_APOSTROPHE: return KC_QUOT;
        case LW_KEY_COMMA: return KC_COMM;
        case LW_KEY_MINUS: return KC_MINS;
        case LW_KEY_PERIOD: return KC_DOT;
        case LW_KEY_SLASH: return KC_SLSH;
        case LW_KEY_SEMICOLON: return KC_SCLN;
        case LW_KEY_EQUAL: return KC_EQL;
        case LW_KEY_BACKSLASH: return KC_BSLS;
        case LW_KEY_BRACKET_LEFT: return KC_LBRC;
        case LW_KEY_BRACKET_RIGHT: return KC_RBRC;
        case LW_KEY_GRAVE: return KC_GRV;
        case LW_KEY_EXCLAM: *implicit_modifiers |= LW_MOD_SHIFT; return KC_1;
        case LW_KEY_QUOTEDBL: *implicit_modifiers |= LW_MOD_SHIFT; return KC_QUOT;
        case LW_KEY_HASH: *implicit_modifiers |= LW_MOD_SHIFT; return KC_3;
        case LW_KEY_DOLLAR: *implicit_modifiers |= LW_MOD_SHIFT; return KC_4;
        case LW_KEY_PERCENT: *implicit_modifiers |= LW_MOD_SHIFT; return KC_5;
        case LW_KEY_AMPERSAND: *implicit_modifiers |= LW_MOD_SHIFT; return KC_7;
        case LW_KEY_PAREN_LEFT: *implicit_modifiers |= LW_MOD_SHIFT; return KC_9;
        case LW_KEY_LESS: *implicit_modifiers |= LW_MOD_SHIFT; return KC_COMM;
        case LW_KEY_BRACE_LEFT: *implicit_modifiers |= LW_MOD_SHIFT; return KC_LBRC;
        case LW_KEY_PAREN_RIGHT: *implicit_modifiers |= LW_MOD_SHIFT; return KC_0;
        case LW_KEY_GREATER: *implicit_modifiers |= LW_MOD_SHIFT; return KC_DOT;
        case LW_KEY_BRACE_RIGHT: *implicit_modifiers |= LW_MOD_SHIFT; return KC_RBRC;
        case LW_KEY_ASTERISK: *implicit_modifiers |= LW_MOD_SHIFT; return KC_8;
        case LW_KEY_PLUS: *implicit_modifiers |= LW_MOD_SHIFT; return KC_EQL;
        case LW_KEY_COLON: *implicit_modifiers |= LW_MOD_SHIFT; return KC_SCLN;
        case LW_KEY_QUESTION: *implicit_modifiers |= LW_MOD_SHIFT; return KC_SLSH;
        case LW_KEY_AT: *implicit_modifiers |= LW_MOD_SHIFT; return KC_2;
        case LW_KEY_CARET: *implicit_modifiers |= LW_MOD_SHIFT; return KC_6;
        case LW_KEY_UNDERSCORE: *implicit_modifiers |= LW_MOD_SHIFT; return KC_MINS;
        case LW_KEY_PIPE: *implicit_modifiers |= LW_MOD_SHIFT; return KC_BSLS;
        case LW_KEY_TILDE: *implicit_modifiers |= LW_MOD_SHIFT; return KC_GRV;
        case LW_KEY_F0: return KC_NO;
    }
    return KC_NO;
}

static void emit_key(void *context, lw_key_t key, uint8_t modifiers) {
    (void)context;
    uint16_t keycode = qmk_keycode(key, &modifiers);
    uint8_t qmk_modifiers = 0;
    if (modifiers & LW_MOD_SHIFT) qmk_modifiers |= MOD_BIT(KC_LSFT);
    if (modifiers & LW_MOD_CONTROL) qmk_modifiers |= MOD_BIT(KC_LCTL);
    if (modifiers & LW_MOD_ALT) qmk_modifiers |= MOD_BIT(KC_LALT);
    if (modifiers & LW_MOD_SUPER) qmk_modifiers |= MOD_BIT(KC_LGUI);
    uint8_t added_modifiers = qmk_modifiers & (uint8_t)~get_mods();
    register_mods(added_modifiers);
    if (keycode != KC_NO) tap_code16(keycode);
    unregister_mods(added_modifiers);
}

void lapwing_qmk_init(void) {
    model.data = lapwing_model_start;
    model.size = (size_t)(lapwing_model_end - lapwing_model_start);
    lw_engine_init(&engine, &model, emit_text, emit_backspaces, emit_key, NULL);
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
    bool number = chord_has(chord, STN_N1) || chord_has(chord, STN_N2)
               || chord_has(chord, STN_N3) || chord_has(chord, STN_N4)
               || chord_has(chord, STN_N5) || chord_has(chord, STN_N6)
               || chord_has(chord, STN_N7) || chord_has(chord, STN_N8)
               || chord_has(chord, STN_N9) || chord_has(chord, STN_NA)
               || chord_has(chord, STN_NB) || chord_has(chord, STN_NC);
    if (number) append_key(stroke, &length, '#');
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
