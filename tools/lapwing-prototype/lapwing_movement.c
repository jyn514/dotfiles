#include "lapwing_features.h"

#include <stddef.h>
#include <string.h>

typedef struct {
    const char *stroke;
    lw_key_t key;
    uint8_t modifiers;
    uint8_t repeat;
} movement_t;

#define M(stroke, key, modifiers, repeat) {stroke, key, modifiers, repeat}

static const movement_t movements[] = {
    M("*FR", LW_KEY_HOME, LW_MOD_SHIFT, 1),
    M("*FBL", LW_KEY_PAGE_DOWN, LW_MOD_SHIFT, 1),
    M("*R", LW_KEY_LEFT, LW_MOD_SHIFT, 1),
    M("*RPG", LW_KEY_PAGE_UP, LW_MOD_SHIFT, 1),
    M("*RB", LW_KEY_LEFT, LW_MOD_CONTROL | LW_MOD_SHIFT, 1),
    M("*P", LW_KEY_UP, LW_MOD_SHIFT, 1),
    M("*B", LW_KEY_DOWN, LW_MOD_SHIFT, 1),
    M("*BG", LW_KEY_RIGHT, LW_MOD_CONTROL | LW_MOD_SHIFT, 1),
    M("*LG", LW_KEY_END, LW_MOD_SHIFT, 1),
    M("*G", LW_KEY_RIGHT, LW_MOD_SHIFT, 1),
    M("-FR", LW_KEY_HOME, 0, 1),
    M("-FPL", LW_KEY_HOME, LW_MOD_CONTROL, 1),
    M("-FBL", LW_KEY_PAGE_DOWN, 0, 1),
    M("-R", LW_KEY_LEFT, 0, 1),
    M("-RPG", LW_KEY_PAGE_UP, 0, 1),
    M("-RB", LW_KEY_LEFT, LW_MOD_CONTROL, 1),
    M("-RBG", LW_KEY_END, LW_MOD_CONTROL, 1),
    M("-RBT", LW_KEY_LEFT, LW_MOD_CONTROL, 3),
    M("-RBTS", LW_KEY_LEFT, LW_MOD_CONTROL, 4),
    M("-RBS", LW_KEY_LEFT, LW_MOD_CONTROL, 2),
    M("-RT", LW_KEY_LEFT, 0, 3),
    M("-RTS", LW_KEY_LEFT, 0, 4),
    M("-RS", LW_KEY_LEFT, 0, 2),
    M("-P", LW_KEY_UP, 0, 1),
    M("-PT", LW_KEY_UP, 0, 3),
    M("-PTS", LW_KEY_UP, 0, 4),
    M("-PS", LW_KEY_UP, 0, 2),
    M("-B", LW_KEY_DOWN, 0, 1),
    M("-BG", LW_KEY_RIGHT, LW_MOD_CONTROL, 1),
    M("-BGT", LW_KEY_RIGHT, LW_MOD_CONTROL, 3),
    M("-BGTS", LW_KEY_RIGHT, LW_MOD_CONTROL, 4),
    M("-BGS", LW_KEY_RIGHT, LW_MOD_CONTROL, 2),
    M("-BT", LW_KEY_DOWN, 0, 3),
    M("-BTS", LW_KEY_DOWN, 0, 4),
    M("-BS", LW_KEY_DOWN, 0, 2),
    M("-LG", LW_KEY_END, 0, 1),
    M("-G", LW_KEY_RIGHT, 0, 1),
    M("-GT", LW_KEY_RIGHT, 0, 3),
    M("-GTS", LW_KEY_RIGHT, 0, 4),
    M("-GS", LW_KEY_RIGHT, 0, 2),
};

bool lw_movement_lookup(const char *stroke, bool continuation,
                        lw_key_mod_result_t *result) {
    if (!stroke || !result) return false;
    const char *suffix = stroke;
    if (!continuation) {
        if (strncmp(stroke, "STPH", 4) != 0 && strncmp(stroke, "#TPH", 4) != 0)
            return false;
        suffix += 4;
    }
    for (size_t index = 0; index < sizeof(movements) / sizeof(movements[0]); ++index) {
        if (strcmp(suffix, movements[index].stroke) != 0) continue;
        result->key = movements[index].key;
        result->modifiers = movements[index].modifiers;
        result->repeat = movements[index].repeat;
        return true;
    }
    return false;
}
