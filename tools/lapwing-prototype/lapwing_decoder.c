#include "lapwing_decoder.h"

#include <string.h>

#include "lapwing_rules.generated.h"

#define LW_MAX_SEGMENTS 48

typedef struct {
    char left[9];
    char vowel[5];
    char right[9];
    bool star;
} lw_stroke_t;

typedef struct {
    char words[LW_MAX_SEGMENTS][LW_MAX_WORD + 1];
    uint16_t count;
} lw_segments_t;

typedef struct {
    lw_segments_t initials;
    lw_segments_t finals;
    lw_candidates_t states;
    lw_candidates_t next;
    lw_candidates_t analyses;
    lw_candidates_t decoded;
    lw_candidates_t roots;
} lw_workspace_t;

/* The embedded decoder is deliberately single-owner and non-reentrant. QMK's
 * main processing thread is the sole caller; large bounded buffers live in BSS
 * rather than consuming the firmware's small call stack. */
static lw_workspace_t workspace;
static lw_prefix_accept_fn active_prefix;
static void *active_prefix_context;

static bool copy_word(char output[LW_MAX_WORD + 1], const char *input) {
    size_t length = strlen(input);
    if (length > LW_MAX_WORD) return false;
    memcpy(output, input, length + 1);
    return true;
}

static bool append_word(char output[LW_MAX_WORD + 1], const char *addition) {
    size_t left = strlen(output);
    size_t right = strlen(addition);
    if (left + right > LW_MAX_WORD) return false;
    memcpy(output + left, addition, right + 1);
    return true;
}

static bool add_unique(lw_candidates_t *result, const char *word) {
    if (!word[0] || strlen(word) > LW_MAX_WORD) return false;
    if (active_prefix && !active_prefix(active_prefix_context, word)) return true;
    for (uint16_t i = 0; i < result->count; ++i) {
        if (strcmp(result->words[i], word) == 0) return true;
    }
    if (result->count >= LW_MAX_CANDIDATES) return false;
    copy_word(result->words[result->count++], word);
    return true;
}

static bool add_segment(lw_segments_t *result, const char *word) {
    if (!word[0] || strlen(word) > LW_MAX_WORD) return false;
    for (uint16_t i = 0; i < result->count; ++i) {
        if (strcmp(result->words[i], word) == 0) return true;
    }
    if (result->count >= LW_MAX_SEGMENTS) return false;
    copy_word(result->words[result->count++], word);
    return true;
}

static const char *rule_key(const lw_rule_entry_t *rule) {
    return lw_rule_strings + rule->key_offset;
}

static const char *rule_value(const lw_rule_entry_t *rule, uint8_t index) {
    return lw_rule_strings + lw_rule_value_offsets[rule->first_value + index];
}

static const lw_rule_entry_t *find_rule(const lw_rule_entry_t *rules,
                                        size_t count, const char *key) {
    for (size_t i = 0; i < count; ++i) {
        if (strcmp(rule_key(&rules[i]), key) == 0) return &rules[i];
    }
    return NULL;
}

static char fingerspelling_letter(const char *stroke) {
    static const char *const outlines[] = {
        "A*", "PW*", "KR*", "TK*", "E*", "TP*", "TKPW*", "H*", "EU*",
        "SKWR*", "K*", "HR*", "PH*", "TPH*", "O*", "P*", "KW*", "R*",
        "S*", "T*", "U*", "SR*", "W*", "KP*", "KWH*", "STKPW*",
    };
    for (uint8_t index = 0; index < 26u; ++index)
        if (strcmp(stroke, outlines[index]) == 0) return (char)('a' + index);
    return '\0';
}

static bool is_vowel_key(char key) {
    return key == 'A' || key == 'O' || key == 'E' || key == 'U';
}

static bool parse_stroke(const char *text, lw_stroke_t *stroke) {
    size_t length = strlen(text);
    if (length == 0 || length > 19) return false;
    memset(stroke, 0, sizeof(*stroke));

    char clean[20];
    size_t clean_length = 0;
    int dash = -1;
    int star = -1;
    for (size_t i = 0; i < length; ++i) {
        if (text[i] == '*') {
            if (star >= 0) return false;
            star = (int)clean_length;
            stroke->star = true;
        } else if (text[i] == '-') {
            if (dash >= 0) return false;
            dash = (int)clean_length;
        } else {
            clean[clean_length++] = text[i];
        }
    }
    clean[clean_length] = '\0';

    size_t left_end = 0;
    size_t vowel_end = 0;
    if (dash >= 0) {
        left_end = (size_t)dash;
        vowel_end = left_end;
    } else {
        size_t first_vowel = clean_length;
        size_t last_vowel = clean_length;
        for (size_t i = 0; i < clean_length; ++i) {
            if (is_vowel_key(clean[i])) {
                if (first_vowel == clean_length) first_vowel = i;
                last_vowel = i;
            }
        }
        if (first_vowel != clean_length) {
            left_end = first_vowel;
            vowel_end = last_vowel + 1;
        } else if (star >= 0) {
            left_end = (size_t)star;
            vowel_end = left_end;
        } else {
            left_end = clean_length;
            vowel_end = clean_length;
        }
    }

    size_t vowel_length = vowel_end - left_end;
    size_t right_length = clean_length - vowel_end;
    if (left_end >= sizeof(stroke->left) || vowel_length >= sizeof(stroke->vowel)
        || right_length >= sizeof(stroke->right)) return false;
    memcpy(stroke->left, clean, left_end);
    memcpy(stroke->vowel, clean + left_end, vowel_length);
    memcpy(stroke->right, clean + vowel_end, right_length);
    return true;
}

static void segment_visit(const char *text, size_t offset,
                          const lw_rule_entry_t *rules, size_t rule_count,
                          char current[LW_MAX_WORD + 1], lw_segments_t *result) {
    if (result->count >= LW_MAX_SEGMENTS) return;
    if (!text[offset]) {
        add_segment(result, current);
        return;
    }
    size_t current_length = strlen(current);
    size_t remaining = strlen(text + offset);
    for (size_t wanted = remaining; wanted > 0; --wanted) {
        for (size_t i = 0; i < rule_count; ++i) {
            const char *key = rule_key(&rules[i]);
            size_t key_length = strlen(key);
            if (key_length != wanted || strncmp(text + offset, key, wanted) != 0)
                continue;
            for (uint8_t value = 0; value < rules[i].value_count; ++value) {
                current[current_length] = '\0';
                if (!append_word(current, rule_value(&rules[i], value))) continue;
                segment_visit(text, offset + wanted, rules, rule_count, current, result);
                if (result->count >= LW_MAX_SEGMENTS) return;
            }
        }
    }
    current[current_length] = '\0';
}

static void segment(const char *text, const lw_rule_entry_t *rules,
                    size_t rule_count, lw_segments_t *result) {
    result->count = 0;
    if (!text[0]) {
        result->words[0][0] = '\0';
        result->count = 1;
        return;
    }
    char current[LW_MAX_WORD + 1] = "";
    segment_visit(text, 0, rules, rule_count, current, result);
}

static void add_rule_values(lw_segments_t *result, const lw_rule_entry_t *rule,
                            bool prepend) {
    if (!rule) return;
    if (prepend) {
        for (int value = (int)rule->value_count - 1; value >= 0; --value) {
            if (result->count >= LW_MAX_SEGMENTS) break;
            memmove(result->words + 1, result->words,
                    result->count * sizeof(result->words[0]));
            copy_word(result->words[0], rule_value(rule, (uint8_t)value));
            ++result->count;
        }
    } else {
        for (uint8_t value = 0; value < rule->value_count; ++value)
            add_segment(result, rule_value(rule, value));
    }
}

static bool ends_with(const char *word, const char *ending) {
    size_t word_length = strlen(word);
    size_t ending_length = strlen(ending);
    return word_length >= ending_length
        && strcmp(word + word_length - ending_length, ending) == 0;
}

static void join_into(lw_candidates_t *result, const char *root,
                      const char *addition, bool affix) {
    char word[LW_MAX_WORD + 1];
    if (copy_word(word, root) && append_word(word, addition)) add_unique(result, word);

    size_t root_length = strlen(root);
    if (root_length && addition[0] && root[root_length - 1] == addition[0]) {
        if (copy_word(word, root) && append_word(word, addition + 1)) add_unique(result, word);
    }
    if (!affix && strcmp(addition, "l") == 0) {
        if (copy_word(word, root) && append_word(word, "el")) add_unique(result, word);
    }
    if (affix && ends_with(root, "e") && strchr("aeiouy", addition[0])) {
        if (copy_word(word, root)) {
            word[root_length - 1] = '\0';
            if (append_word(word, addition)) add_unique(result, word);
        }
    }
    if (affix && ends_with(root, "y") && strcmp(addition, "y") != 0) {
        if (copy_word(word, root)) {
            word[root_length - 1] = 'i';
            if (append_word(word, addition)) add_unique(result, word);
        }
    }
    if (affix && strcmp(addition, "s") == 0) {
        if (ends_with(root, "s") || ends_with(root, "x") || ends_with(root, "z")
            || ends_with(root, "ch") || ends_with(root, "sh")) {
            if (copy_word(word, root) && append_word(word, "es")) add_unique(result, word);
        }
        if (ends_with(root, "y") && copy_word(word, root)) {
            word[root_length - 1] = '\0';
            if (append_word(word, "ies")) add_unique(result, word);
        }
    }
    if (affix && strcmp(addition, "ed") == 0) {
        if (ends_with(root, "e") && copy_word(word, root)
            && append_word(word, "d")) add_unique(result, word);
        if (ends_with(root, "y") && copy_word(word, root)) {
            word[root_length - 1] = '\0';
            if (append_word(word, "ied")) add_unique(result, word);
        }
    }
    if (affix && strcmp(addition, "ing") == 0 && ends_with(root, "e")
        && copy_word(word, root)) {
        word[root_length - 1] = '\0';
        if (append_word(word, "ing")) add_unique(result, word);
    }
    if (affix && (strcmp(addition, "ing") == 0 || strcmp(addition, "ed") == 0)
        && root_length >= 3) {
        char last = root[root_length - 1];
        char middle = root[root_length - 2];
        char first = root[root_length - 3];
        if (!strchr("aeiouwxy", last) && strchr("aeiou", middle)
            && !strchr("aeiou", first) && copy_word(word, root)) {
            char doubled[2] = {last, '\0'};
            if (append_word(word, doubled) && append_word(word, addition)) add_unique(result, word);
        }
    }
}

static bool silent_e_vowel(const char *vowel) {
    return strcmp(vowel, "AEU") == 0 || strcmp(vowel, "AOEU") == 0
        || strcmp(vowel, "OE") == 0 || strcmp(vowel, "AOU") == 0
        || strcmp(vowel, "AOE") == 0;
}

static void decode_basic_stroke(const char *stroke_text, lw_candidates_t *result) {
    result->count = 0;
    const lw_rule_entry_t *whole = find_rule(lw_whole_rules, LW_WHOLE_RULE_COUNT, stroke_text);
    if (whole) {
        for (uint8_t i = 0; i < whole->value_count; ++i)
            add_unique(result, rule_value(whole, i));
    }

    lw_stroke_t stroke;
    if (!parse_stroke(stroke_text, &stroke)) return;
    lw_segments_t *initials = &workspace.initials;
    lw_segments_t *finals = &workspace.finals;
    segment(stroke.left, lw_initial_rules, LW_INITIAL_RULE_COUNT, initials);
    segment(stroke.right, lw_final_rules, LW_FINAL_RULE_COUNT, finals);
    if (stroke.star) {
        add_rule_values(initials, find_rule(lw_star_initial_rules,
                        LW_STAR_INITIAL_RULE_COUNT, stroke.left), true);
        add_rule_values(finals, find_rule(lw_star_final_rules,
                        LW_STAR_FINAL_RULE_COUNT, stroke.right), true);
    }
    if (strcmp(stroke.left, "KWR") == 0) {
        const char *values[] = {"i", "y", ""};
        for (size_t i = 0; i < 3; ++i) {
            if (initials->count >= LW_MAX_SEGMENTS) break;
            memmove(initials->words + 1, initials->words,
                    initials->count * sizeof(initials->words[0]));
            copy_word(initials->words[0], values[i]);
            ++initials->count;
        }
    }
    const lw_rule_entry_t *vowels = find_rule(lw_vowel_rules, LW_VOWEL_RULE_COUNT, stroke.vowel);
    if (!vowels) return;
    for (uint16_t left = 0; left < initials->count; ++left) {
        for (uint8_t vowel = 0; vowel < vowels->value_count; ++vowel) {
            for (uint16_t right = 0; right < finals->count; ++right) {
                char word[LW_MAX_WORD + 1];
                if (!copy_word(word, initials->words[left])
                    || !append_word(word, rule_value(vowels, vowel))
                    || !append_word(word, finals->words[right])) continue;
                add_unique(result, word);
                size_t length = strlen(word);
                if (silent_e_vowel(stroke.vowel) && stroke.right[0] && length
                    && !strchr("aeiouy", word[length - 1]) && append_word(word, "e"))
                    add_unique(result, word);
            }
        }
    }
}

static bool rebuild_stroke(const lw_stroke_t *stroke, const char *right,
                           const char *vowel, char output[20]) {
    size_t left_length = strlen(stroke->left);
    size_t vowel_length = strlen(vowel);
    size_t right_length = strlen(right);
    bool dash = !vowel[0] && right[0];
    size_t length = left_length + vowel_length + right_length
                  + (stroke->star ? 1u : 0u) + (dash ? 1u : 0u);
    if (length >= 20) return false;
    char *cursor = output;
    memcpy(cursor, stroke->left, left_length);
    cursor += left_length;
    memcpy(cursor, vowel, vowel_length);
    cursor += vowel_length;
    if (stroke->star) *cursor++ = '*';
    if (dash) *cursor++ = '-';
    memcpy(cursor, right, right_length);
    cursor[right_length] = '\0';
    return true;
}

static void decode_stroke(const char *stroke_text, bool final_position,
                          lw_candidates_t *result) {
    decode_basic_stroke(stroke_text, result);
    lw_stroke_t stroke;
    if (!parse_stroke(stroke_text, &stroke)) return;
    struct folded { char marker; const char *values[3]; uint8_t count; } folds[] = {
        {'G', {"ing"}, 1}, {'D', {"ed"}, 1}, {'Z', {"s"}, 1}, {'S', {"s"}, 1},
        {'L', {"ly", "al"}, 2}, {'T', {"ity", "ty"}, 2},
        {'R', {"er", "or", "ar"}, 3},
    };
    for (size_t fold = 0; fold < sizeof(folds) / sizeof(folds[0]); ++fold) {
        if (folds[fold].marker == 'R' && !final_position) continue;
        size_t right_length = strlen(stroke.right);
        if (!right_length || stroke.right[right_length - 1] != folds[fold].marker) continue;
        if (fold < 4 && !stroke.left[0] && !stroke.vowel[0] && right_length == 1) continue;
        char base_right[sizeof(stroke.right)];
        memcpy(base_right, stroke.right, right_length);
        base_right[right_length - 1] = '\0';
        char base_stroke[20];
        if (!rebuild_stroke(&stroke, base_right, stroke.vowel, base_stroke)) continue;
        lw_candidates_t *roots = &workspace.roots;
        decode_basic_stroke(base_stroke, roots);
        for (uint16_t root = 0; root < roots->count; ++root)
            for (uint8_t ending = 0; ending < folds[fold].count; ++ending)
                join_into(result, roots->words[root], folds[fold].values[ending], true);
    }
    if (final_position) {
        const char *last_e = strrchr(stroke.vowel, 'E');
        if (last_e) {
            char base_vowel[sizeof(stroke.vowel)];
            size_t index = (size_t)(last_e - stroke.vowel);
            memcpy(base_vowel, stroke.vowel, index);
            strcpy(base_vowel + index, stroke.vowel + index + 1);
            char base_stroke[20];
            if (rebuild_stroke(&stroke, stroke.right, base_vowel, base_stroke)) {
                lw_candidates_t *roots = &workspace.roots;
                decode_basic_stroke(base_stroke, roots);
                for (uint16_t root = 0; root < roots->count; ++root)
                    join_into(result, roots->words[root], "y", true);
            }
        }
    }
}

void lw_decode_outline_pruned(const char *outline, lw_prefix_accept_fn accept_prefix,
                              void *context, lw_candidates_t *result) {
    result->count = 0;
    if (!outline || !outline[0]) return;
    char strokes[LW_MAX_STROKES][20];
    uint8_t stroke_count = 0;
    const char *start = outline;
    while (*start && stroke_count < LW_MAX_STROKES) {
        const char *slash = strchr(start, '/');
        size_t length = slash ? (size_t)(slash - start) : strlen(start);
        if (!length || length >= sizeof(strokes[0])) return;
        memcpy(strokes[stroke_count], start, length);
        strokes[stroke_count++][length] = '\0';
        if (!slash) break;
        start = slash + 1;
    }
    if (*start && stroke_count == LW_MAX_STROKES && strchr(start, '/')) return;

    char fingerspelled[LW_MAX_WORD + 1];
    bool all_fingerspelled = stroke_count > 0;
    for (uint8_t index = 0; index < stroke_count; ++index) {
        char letter = fingerspelling_letter(strokes[index]);
        if (!letter) {
            all_fingerspelled = false;
            break;
        }
        fingerspelled[index] = letter;
    }
    if (all_fingerspelled) {
        fingerspelled[stroke_count] = '\0';
        add_unique(result, fingerspelled);
        return;
    }
    if (stroke_count > 1u && strcmp(strokes[stroke_count - 1u], "AES") == 0) {
        bool possessive = true;
        for (uint8_t index = 0; index + 1u < stroke_count; ++index) {
            char letter = fingerspelling_letter(strokes[index]);
            if (!letter) {
                possessive = false;
                break;
            }
            fingerspelled[index] = letter;
        }
        if (possessive) {
            uint8_t length = stroke_count - 1u;
            fingerspelled[length++] = '\'';
            fingerspelled[length++] = 's';
            fingerspelled[length] = '\0';
            add_unique(result, fingerspelled);
            return;
        }
    }

    lw_candidates_t *states = &workspace.states;
    lw_candidates_t *next = &workspace.next;
    states->count = 1;
    states->words[0][0] = '\0';
    for (uint8_t stroke = 0; stroke < stroke_count; ++stroke) {
        lw_candidates_t *analyses = &workspace.analyses;
        analyses->count = 0;
        const lw_rule_entry_t *affix = NULL;
        if (stroke == 0)
            affix = find_rule(lw_prefix_rules, LW_PREFIX_RULE_COUNT, strokes[stroke]);
        else
            affix = find_rule(lw_suffix_rules, LW_SUFFIX_RULE_COUNT, strokes[stroke]);
        if (affix) {
            for (uint8_t i = 0; i < affix->value_count; ++i)
                add_unique(analyses, rule_value(affix, i));
        }
        uint16_t affix_count = analyses->count;
        lw_candidates_t *decoded = &workspace.decoded;
        decode_stroke(strokes[stroke], stroke + 1 == stroke_count, decoded);
        for (uint16_t i = 0; i < decoded->count; ++i)
            add_unique(analyses, decoded->words[i]);

        next->count = 0;
        active_prefix = accept_prefix;
        active_prefix_context = context;
        for (uint16_t state = 0; state < states->count; ++state) {
            for (uint16_t analysis = 0; analysis < analyses->count; ++analysis) {
                if (!states->words[state][0]) add_unique(next, analyses->words[analysis]);
                else join_into(next, states->words[state], analyses->words[analysis],
                               analysis < affix_count);
            }
        }
        active_prefix = NULL;
        active_prefix_context = NULL;
        lw_candidates_t *swap = states;
        states = next;
        next = swap;
        if (!states->count) break;
    }
    active_prefix = NULL;
    active_prefix_context = NULL;
    *result = *states;
}

void lw_decode_outline(const char *outline, lw_candidates_t *result) {
    lw_decode_outline_pruned(outline, NULL, NULL, result);
}

size_t lw_translate_outline(const char *outline, lw_word_accept_fn accept,
                            void *context, char output[][LW_MAX_WORD + 1],
                            size_t output_capacity) {
    lw_candidates_t candidates;
    lw_decode_outline(outline, &candidates);
    size_t count = 0;
    for (uint16_t i = 0; i < candidates.count && count < output_capacity; ++i) {
        if (!accept || accept(context, candidates.words[i]))
            copy_word(output[count++], candidates.words[i]);
    }
    return count;
}
