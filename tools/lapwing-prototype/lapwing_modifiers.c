#include "lapwing_features.h"

#include <stddef.h>
#include <string.h>

typedef struct { const char *stroke; lw_key_t key; } key_entry_t;
typedef struct { const char *stroke; lw_key_t variants[4]; } symbol_entry_t;

#define COUNT(array) (sizeof(array) / sizeof((array)[0]))

static const key_entry_t spelling[] = {
    {"A", LW_KEY_A}, {"PW", LW_KEY_B}, {"KR", LW_KEY_C},
    {"TK", LW_KEY_D}, {"E", LW_KEY_E}, {"TP", LW_KEY_F},
    {"TKPW", LW_KEY_G}, {"H", LW_KEY_H}, {"EU", LW_KEY_I},
    {"AOEU", LW_KEY_I}, {"SKWR", LW_KEY_J}, {"SKWRAEU", LW_KEY_J},
    {"K", LW_KEY_K}, {"HR", LW_KEY_L}, {"PH", LW_KEY_M},
    {"TPH", LW_KEY_N}, {"O", LW_KEY_O}, {"P", LW_KEY_P},
    {"KW", LW_KEY_Q}, {"R", LW_KEY_R}, {"S", LW_KEY_S},
    {"T", LW_KEY_T}, {"U", LW_KEY_U}, {"SR", LW_KEY_V},
    {"W", LW_KEY_W}, {"KP", LW_KEY_X}, {"KWH", LW_KEY_Y},
    {"STKPW", LW_KEY_Z}, {"STKPWHR", LW_KEY_Z},
};

/* Unsupported non-US symbols are intentionally LW_KEY_NONE. The ordinary
 * variant and all ASCII variants remain available. */
static const symbol_entry_t symbols[] = {
    {"TR", {LW_KEY_TAB, LW_KEY_BACKSPACE, LW_KEY_DELETE, LW_KEY_ESCAPE}},
    {"KPWR", {LW_KEY_UP, LW_KEY_LEFT, LW_KEY_RIGHT, LW_KEY_DOWN}},
    {"TKPWR", {LW_KEY_PAGE_UP, LW_KEY_HOME, LW_KEY_END, LW_KEY_PAGE_DOWN}},
    {"TKWR", {LW_KEY_AUDIO_PLAY, LW_KEY_AUDIO_PREV, LW_KEY_AUDIO_NEXT,
               LW_KEY_AUDIO_STOP}},
    {"TKW", {LW_KEY_AUDIO_MUTE, LW_KEY_AUDIO_DOWN, LW_KEY_AUDIO_UP, LW_KEY_NONE}},
    {"", {LW_KEY_NONE, LW_KEY_ENTER, LW_KEY_TAB, LW_KEY_SPACE}},
    {"TK", {LW_KEY_EXCLAM, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"TP", {LW_KEY_QUOTEDBL, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"TKHR", {LW_KEY_HASH, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"KPWH", {LW_KEY_DOLLAR, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"TKPW", {LW_KEY_PERCENT, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"TWR", {LW_KEY_AMPERSAND, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"T", {LW_KEY_APOSTROPHE, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"TPH", {LW_KEY_PAREN_LEFT, LW_KEY_LESS, LW_KEY_BRACKET_LEFT,
              LW_KEY_BRACE_LEFT}},
    {"KWR", {LW_KEY_PAREN_RIGHT, LW_KEY_GREATER, LW_KEY_BRACKET_RIGHT,
              LW_KEY_BRACE_RIGHT}},
    {"H", {LW_KEY_ASTERISK, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"R", {LW_KEY_PLUS, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"W", {LW_KEY_COMMA, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"PH", {LW_KEY_MINUS, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"K", {LW_KEY_PERIOD, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"KP", {LW_KEY_SLASH, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"HR", {LW_KEY_COLON, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"KW", {LW_KEY_SEMICOLON, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"PWHR", {LW_KEY_EQUAL, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"TPW", {LW_KEY_QUESTION, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"TKPWHR", {LW_KEY_AT, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"TW", {LW_KEY_BACKSLASH, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"KPR", {LW_KEY_CARET, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"WR", {LW_KEY_UNDERSCORE, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"P", {LW_KEY_GRAVE, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"PW", {LW_KEY_PIPE, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
    {"TPWR", {LW_KEY_TILDE, LW_KEY_NONE, LW_KEY_NONE, LW_KEY_NONE}},
};

static bool take_group(const char **cursor, const char *characters,
                       char *output, size_t *length, size_t capacity) {
    while (**cursor && strchr(characters, **cursor)) {
        if (*length + 1u >= capacity) return false;
        output[(*length)++] = *(*cursor)++;
    }
    output[*length] = '\0';
    return true;
}

static lw_key_t find_key(const key_entry_t *entries, size_t count,
                         const char *stroke) {
    for (size_t index = 0; index < count; ++index)
        if (strcmp(entries[index].stroke, stroke) == 0) return entries[index].key;
    return LW_KEY_NONE;
}

bool lw_emily_modifier_lookup(const char *stroke, lw_key_mod_result_t *result) {
    if (!stroke || !result) return false;
    const char *cursor = stroke;
    char pattern[20] = {0};
    char separator[3] = {0};
    char modifier_keys[5] = {0};
    size_t pattern_length = 0, separator_length = 0, modifier_length = 0;
    if (!take_group(&cursor, "#STKPWHR", pattern, &pattern_length, sizeof(pattern))
        || !take_group(&cursor, "AO", pattern, &pattern_length, sizeof(pattern))
        || !take_group(&cursor, "*-", separator, &separator_length, sizeof(separator))
        || !take_group(&cursor, "EU", pattern, &pattern_length, sizeof(pattern))
        || !take_group(&cursor, "FRPB", modifier_keys, &modifier_length,
                       sizeof(modifier_keys))
        || strcmp(cursor, "LGTS") != 0 || modifier_length == 0u)
        return false;

    lw_key_t key = LW_KEY_NONE;
    if (separator_length && strchr(separator, '*')) {
        char shape[9] = {0};
        size_t shape_length = 0, index = 0;
        while (pattern[index] && strchr("STKPWHR", pattern[index])) {
            if (shape_length + 1u >= sizeof(shape)) return false;
            shape[shape_length++] = pattern[index++];
        }
        unsigned variant = 0;
        while (pattern[index] && strchr("AO", pattern[index])) {
            variant += pattern[index++] == 'A' ? 1u : 2u;
        }
        while (pattern[index] && strchr("EU", pattern[index])) ++index;
        if (pattern[index]) return false;
        bool found = false;
        for (size_t entry = 0; entry < COUNT(symbols); ++entry) {
            if (strcmp(shape, symbols[entry].stroke) != 0) continue;
            key = symbols[entry].variants[variant];
            found = true;
            break;
        }
        if (!found || key == LW_KEY_NONE) return false;
    } else if (pattern[0]) {
        char shape[9] = {0};
        size_t shape_length = 0, index = 0;
        while (pattern[index] && strchr("STKPWHR", pattern[index])) {
            if (shape_length + 1u >= sizeof(shape)) return false;
            shape[shape_length++] = pattern[index++];
        }
        char number[3] = {0};
        size_t number_length = 0;
        while (pattern[index] && strchr("AO", pattern[index])) {
            if (number_length + 1u >= sizeof(number)) return false;
            number[number_length++] = pattern[index++];
        }
        size_t vowels = 0;
        while (pattern[index] && strchr("EU", pattern[index])) {
            ++vowels;
            ++index;
        }
        if (pattern[index]) return false;
        if (strcmp(number, "AO") == 0 && vowels == 0u) {
            unsigned value = 0;
            if (strchr(shape, 'R')) value += 1u;
            if (strchr(shape, 'W')) value += 2u;
            if (strchr(shape, 'K')) value += 4u;
            if (strchr(shape, 'S')) value += 8u;
            bool function = strchr(shape, 'T') && strchr(shape, 'P');
            if ((function && (value == 0u || value > 12u))
                || (!function && value > 9u)) return false;
            key = (lw_key_t)((function ? LW_KEY_F0 : LW_KEY_0) + value);
        } else {
            key = find_key(spelling, COUNT(spelling), pattern);
            if (key == LW_KEY_NONE) return false;
        }
    }

    uint8_t modifiers = 0;
    if (strchr(modifier_keys, 'R')) modifiers |= LW_MOD_SHIFT;
    if (strchr(modifier_keys, 'F')) modifiers |= LW_MOD_CONTROL;
    if (strchr(modifier_keys, 'B')) modifiers |= LW_MOD_ALT;
    if (strchr(modifier_keys, 'P')) modifiers |= LW_MOD_SUPER;
    result->key = key;
    result->modifiers = modifiers;
    return true;
}
