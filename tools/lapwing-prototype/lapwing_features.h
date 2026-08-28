#pragma once

#include <stdbool.h>
#include <stdint.h>

/* Host-independent keys produced by embedded feature dictionaries. */
typedef enum {
    LW_KEY_NONE = 0,
    LW_KEY_A, LW_KEY_B, LW_KEY_C, LW_KEY_D, LW_KEY_E, LW_KEY_F, LW_KEY_G,
    LW_KEY_H, LW_KEY_I, LW_KEY_J, LW_KEY_K, LW_KEY_L, LW_KEY_M, LW_KEY_N,
    LW_KEY_O, LW_KEY_P, LW_KEY_Q, LW_KEY_R, LW_KEY_S, LW_KEY_T, LW_KEY_U,
    LW_KEY_V, LW_KEY_W, LW_KEY_X, LW_KEY_Y, LW_KEY_Z,
    LW_KEY_0, LW_KEY_1, LW_KEY_2, LW_KEY_3, LW_KEY_4,
    LW_KEY_5, LW_KEY_6, LW_KEY_7, LW_KEY_8, LW_KEY_9,
    LW_KEY_F0, LW_KEY_F1, LW_KEY_F2, LW_KEY_F3, LW_KEY_F4, LW_KEY_F5,
    LW_KEY_F6, LW_KEY_F7, LW_KEY_F8, LW_KEY_F9, LW_KEY_F10, LW_KEY_F11,
    LW_KEY_F12,
    LW_KEY_TAB, LW_KEY_BACKSPACE, LW_KEY_DELETE, LW_KEY_ESCAPE,
    LW_KEY_UP, LW_KEY_LEFT, LW_KEY_RIGHT, LW_KEY_DOWN,
    LW_KEY_PAGE_UP, LW_KEY_HOME, LW_KEY_END, LW_KEY_PAGE_DOWN,
    LW_KEY_AUDIO_PLAY, LW_KEY_AUDIO_PREV, LW_KEY_AUDIO_NEXT, LW_KEY_AUDIO_STOP,
    LW_KEY_AUDIO_MUTE, LW_KEY_AUDIO_DOWN, LW_KEY_AUDIO_UP,
    LW_KEY_ENTER, LW_KEY_SPACE,
    LW_KEY_EXCLAM, LW_KEY_QUOTEDBL, LW_KEY_HASH, LW_KEY_DOLLAR,
    LW_KEY_PERCENT, LW_KEY_AMPERSAND, LW_KEY_APOSTROPHE,
    LW_KEY_PAREN_LEFT, LW_KEY_LESS, LW_KEY_BRACKET_LEFT, LW_KEY_BRACE_LEFT,
    LW_KEY_PAREN_RIGHT, LW_KEY_GREATER, LW_KEY_BRACKET_RIGHT, LW_KEY_BRACE_RIGHT,
    LW_KEY_ASTERISK, LW_KEY_PLUS, LW_KEY_COMMA, LW_KEY_MINUS, LW_KEY_PERIOD,
    LW_KEY_SLASH, LW_KEY_COLON, LW_KEY_SEMICOLON, LW_KEY_EQUAL,
    LW_KEY_QUESTION, LW_KEY_AT, LW_KEY_BACKSLASH, LW_KEY_CARET,
    LW_KEY_UNDERSCORE, LW_KEY_GRAVE, LW_KEY_PIPE, LW_KEY_TILDE,
} lw_key_t;

enum {
    LW_MOD_SHIFT = 1u << 0,
    LW_MOD_CONTROL = 1u << 1,
    LW_MOD_ALT = 1u << 2,
    LW_MOD_SUPER = 1u << 3,
};

typedef struct {
    lw_key_t key; /* LW_KEY_NONE means tap the modifiers by themselves. */
    uint8_t modifiers;
    uint8_t repeat;
} lw_key_mod_result_t;

bool lw_emily_modifier_lookup(const char *stroke, lw_key_mod_result_t *result);
bool lw_movement_lookup(const char *stroke, bool continuation,
                        lw_key_mod_result_t *result);
