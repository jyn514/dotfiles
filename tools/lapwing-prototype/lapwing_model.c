#include "lapwing_model.h"

#include <string.h>

#define LW_MODEL_HEADER_SIZE 36u
#define LW_MODEL_VERSION 4u
#define LW_EXCEPTION_RECORD_SIZE 5u
#define LW_EXCEPTION_HASH_MASK 0x1fffffffu
#define LW_EXCEPTION_ID_MASK 0x7ffu
#define LW_DAWG_LEAF_OFFSET 0x1fffu
static const char alphabet[] = "abcdefghijklmnopqrstuvwxyz'-";

static uint16_t read_u16(const uint8_t *data) {
    return (uint16_t)data[0] | ((uint16_t)data[1] << 8);
}

static uint32_t read_u24(const uint8_t *data) {
    return (uint32_t)data[0] | ((uint32_t)data[1] << 8) | ((uint32_t)data[2] << 16);
}

static uint32_t read_u32(const uint8_t *data) {
    return read_u24(data) | ((uint32_t)data[3] << 24);
}

static uint32_t edge_count(const lw_model_t *model);

static uint64_t read_u40(const uint8_t *data) {
    return (uint64_t)read_u32(data) | ((uint64_t)data[4] << 32);
}

static uint32_t read_edge(const lw_model_t *model, uint32_t index) {
    const uint8_t *data = model->data + LW_MODEL_HEADER_SIZE;
    uint32_t bit_offset = index * 20u;
    uint32_t byte_offset = bit_offset / 8u;
    uint8_t shift = bit_offset % 8u;
    uint32_t available = (edge_count(model) * 20u + 7u) / 8u;
    uint32_t value = 0;
    for (uint8_t byte = 0; byte < 4u && byte_offset + byte < available; ++byte)
        value |= (uint32_t)data[byte_offset + byte] << (byte * 8u);
    return (value >> shift) & 0xfffffu;
}

static uint32_t hash32(const char *text) {
    uint32_t value = 2166136261u;
    while (*text) value = (value ^ (uint8_t)*text++) * 16777619u;
    value ^= value >> 16;
    value *= 0x7feb352du;
    value ^= value >> 15;
    return value;
}

static bool decode_letters(const uint8_t **cursor, const uint8_t *end,
                           char *output, uint16_t length) {
    uint16_t byte_count = (length * 5u + 7u) / 8u;
    if ((size_t)(end - *cursor) < byte_count) return false;
    const uint8_t *start = *cursor;
    for (uint16_t index = 0; index < length; ++index) {
        uint16_t bit = index * 5u;
        uint16_t byte = bit / 8u;
        uint16_t value = start[byte];
        if (byte + 1u < byte_count) value |= (uint16_t)start[byte + 1u] << 8;
        uint8_t letter = (value >> (bit % 8u)) & 0x1fu;
        if (letter >= sizeof(alphabet) - 1u) return false;
        output[index] = alphabet[letter];
    }
    *cursor += byte_count;
    return true;
}

static uint16_t read_varint(const uint8_t **cursor, const uint8_t *end,
                            bool *valid) {
    uint16_t value = 0;
    uint8_t shift = 0;
    while (*cursor < end && shift < 16) {
        uint8_t byte = *(*cursor)++;
        value |= (uint16_t)(byte & 0x7fu) << shift;
        if (!(byte & 0x80u)) return value;
        shift += 7;
    }
    *valid = false;
    return 0;
}

static uint32_t edge_count(const lw_model_t *model) { return read_u32(model->data + 12); }
static uint32_t root_offset(const lw_model_t *model) { return read_u32(model->data + 16); }
static uint32_t exception_count(const lw_model_t *model) { return read_u32(model->data + 20); }
static uint32_t word_count(const lw_model_t *model) { return read_u32(model->data + 24); }
static uint32_t exceptions_offset(const lw_model_t *model) { return read_u32(model->data + 28); }
static uint32_t blocks_offset(const lw_model_t *model) { return read_u32(model->data + 32); }

bool lw_model_valid(const lw_model_t *model) {
    if (!model || !model->data || model->size < LW_MODEL_HEADER_SIZE) return false;
    if (memcmp(model->data, "LWMD", 4) != 0 || model->data[4] != LW_MODEL_VERSION)
        return false;
    uint8_t block_words = model->data[6];
    uint32_t edges = edge_count(model);
    uint32_t root = root_offset(model);
    uint32_t exceptions = exception_count(model);
    uint32_t words = word_count(model);
    uint32_t exception_start = exceptions_offset(model);
    uint32_t block_start = blocks_offset(model);
    uint32_t block_count = block_words ? (words + block_words - 1u) / block_words : 0;
    if (!block_words || !read_u32(model->data + 8) || !edges) return false;
    if (root >= edges
        || exception_start != LW_MODEL_HEADER_SIZE + (edges * 20u + 7u) / 8u)
        return false;
    if (block_start != exception_start + exceptions * LW_EXCEPTION_RECORD_SIZE) return false;
    if ((size_t)block_start + block_count * 2u > model->size) return false;
    return true;
}

static int alphabet_index(char character) {
    const char *found = strchr(alphabet, character);
    return found ? (int)(found - alphabet) : -1;
}

static bool walk_word(const lw_model_t *model, const char *word, bool require_terminal) {
    if (!lw_model_valid(model) || !word || !word[0]) return false;
    uint32_t state = root_offset(model);
    bool terminal = false;
    while (*word) {
        int wanted = alphabet_index(*word++);
        if (wanted < 0 || state == LW_DAWG_LEAF_OFFSET || state >= edge_count(model))
            return false;
        bool matched = false;
        for (uint32_t index = state; index < edge_count(model); ++index) {
            uint32_t edge = read_edge(model, index);
            if ((int)(edge & 0x1fu) == wanted) {
                state = (edge >> 5) & LW_DAWG_LEAF_OFFSET;
                terminal = (edge & (1u << 18)) != 0;
                matched = true;
                break;
            }
            if (edge & (1u << 19)) break;
        }
        if (!matched) return false;
    }
    return !require_terminal || terminal;
}

bool lw_model_contains(const lw_model_t *model, const char *word) {
    return walk_word(model, word, true);
}

bool lw_model_has_prefix(const lw_model_t *model, const char *prefix) {
    return walk_word(model, prefix, false);
}

static bool decode_word(const lw_model_t *model, uint16_t id,
                        char output[LW_MAX_WORD + 1]) {
    uint32_t words = word_count(model);
    uint8_t block_words = model->data[6];
    if (id >= words) return false;
    uint32_t block = id / block_words;
    uint32_t first_id = block * block_words;
    const uint8_t *blocks = model->data + blocks_offset(model);
    uint32_t block_count = (words + block_words - 1u) / block_words;
    uint32_t words_start = blocks_offset(model) + block_count * 2u;
    uint32_t offset = read_u16(blocks + block * 2u);
    if ((size_t)words_start + offset >= model->size) return false;
    const uint8_t *cursor = model->data + words_start + offset;
    const uint8_t *end = model->data + model->size;
    uint16_t length = 0;
    bool valid = true;
    for (uint32_t current = first_id; current <= id && valid; ++current) {
        if (current == first_id) {
            length = read_varint(&cursor, end, &valid);
            if (!valid || length > LW_MAX_WORD
                || !decode_letters(&cursor, end, output, length)) return false;
        } else {
            uint16_t prefix = read_varint(&cursor, end, &valid);
            uint16_t suffix = read_varint(&cursor, end, &valid);
            if (!valid || prefix > length || prefix + suffix > LW_MAX_WORD
                || !decode_letters(&cursor, end, output + prefix, suffix)) return false;
            length = prefix + suffix;
        }
        output[length] = '\0';
    }
    return valid;
}

bool lw_model_exception(const lw_model_t *model, const char *outline,
                        char output[LW_MAX_WORD + 1]) {
    if (!lw_model_valid(model) || !outline || !outline[0]) return false;
    uint32_t wanted = hash32(outline) & LW_EXCEPTION_HASH_MASK;
    uint32_t low = 0;
    uint32_t high = exception_count(model);
    const uint8_t *records = model->data + exceptions_offset(model);
    while (low < high) {
        uint32_t middle = low + (high - low) / 2u;
        uint64_t packed = read_u40(records + middle * LW_EXCEPTION_RECORD_SIZE);
        uint32_t found = (uint32_t)(packed >> 11);
        if (found < wanted) low = middle + 1u;
        else high = middle;
    }
    if (low >= exception_count(model)) return false;
    const uint8_t *record = records + low * LW_EXCEPTION_RECORD_SIZE;
    uint64_t packed = read_u40(record);
    if ((uint32_t)(packed >> 11) != wanted) return false;
    return decode_word(model, (uint16_t)(packed & LW_EXCEPTION_ID_MASK), output);
}

static bool accept_model_prefix(void *context, const char *prefix) {
    return lw_model_has_prefix(context, prefix);
}

static bool is_repair_consonant(char character) {
    return character >= 'a' && character <= 'z'
        && strchr("aeiou", character) == NULL;
}

static bool accept_repair(const lw_model_t *model, const char *candidate,
                          char output[LW_MAX_WORD + 1]) {
    if (!lw_model_contains(model, candidate)) return false;
    strcpy(output, candidate);
    return true;
}

static bool replace_fragment(const lw_model_t *model, const char *word,
                             const char *from, const char *to,
                             char output[LW_MAX_WORD + 1]) {
    size_t word_length = strlen(word);
    size_t from_length = strlen(from);
    size_t to_length = strlen(to);
    if (word_length - from_length + to_length > LW_MAX_WORD) return false;
    const char *search = word;
    const char *match;
    char repaired[LW_MAX_WORD + 1];
    while ((match = strstr(search, from)) != NULL) {
        size_t prefix = (size_t)(match - word);
        memcpy(repaired, word, prefix);
        memcpy(repaired + prefix, to, to_length);
        strcpy(repaired + prefix + to_length, match + from_length);
        if (accept_repair(model, repaired, output)) return true;
        search = match + 1u;
    }
    return false;
}

static bool repair_candidate(const lw_model_t *model, const char *word,
                             char output[LW_MAX_WORD + 1]) {
    size_t length = strlen(word);
    char repaired[LW_MAX_WORD + 1];
    if (length < LW_MAX_WORD) {
        for (size_t index = 0; index < length; ++index) {
            if (!is_repair_consonant(word[index])) continue;
            memcpy(repaired, word, index);
            repaired[index] = word[index];
            strcpy(repaired + index + 1u, word + index);
            if (accept_repair(model, repaired, output)) return true;
        }
        for (size_t index = 1; index < length; ++index) {
            for (const char *insertion = "aeiou'"; *insertion; ++insertion) {
                memcpy(repaired, word, index);
                repaired[index] = *insertion;
                strcpy(repaired + index + 1u, word + index);
                if (accept_repair(model, repaired, output)) return true;
            }
        }
    }
    for (size_t index = 0; index < length; ++index) {
        memcpy(repaired, word, index);
        strcpy(repaired + index, word + index + 1u);
        if (accept_repair(model, repaired, output)) return true;
    }
    for (size_t index = 0; index + 1u < length; ++index) {
        if (word[index] == word[index + 1u]) continue;
        strcpy(repaired, word);
        repaired[index] = word[index + 1u];
        repaired[index + 1u] = word[index];
        if (accept_repair(model, repaired, output)) return true;
    }
    for (size_t index = 0; index < length; ++index) {
        const char *replacements = "";
        switch (word[index]) {
            case 'a': replacements = "eiou"; break;
            case 'e': replacements = "aiou"; break;
            case 'i': replacements = "aeou"; break;
            case 'o': replacements = "aeiu"; break;
            case 'u': replacements = "aeio"; break;
            case 'c': replacements = "ks"; break;
            case 'k': replacements = "c"; break;
            case 's': replacements = "c"; break;
            case 'g': replacements = "j"; break;
            case 'j': replacements = "g"; break;
            case 'f': replacements = "v"; break;
            case 'v': replacements = "f"; break;
            default: break;
        }
        for (; *replacements; ++replacements) {
            strcpy(repaired, word);
            repaired[index] = *replacements;
            if (accept_repair(model, repaired, output)) return true;
        }
    }
    const char *celebr = strstr(word, "selbr");
    if (celebr && length < LW_MAX_WORD) {
        size_t prefix = (size_t)(celebr - word);
        memcpy(repaired, word, prefix);
        memcpy(repaired + prefix, "celebr", 6u);
        strcpy(repaired + prefix + 6u, celebr + 5u);
        if (accept_repair(model, repaired, output)) return true;
    }
    if (replace_fragment(model, word, "o", "al", output)) return true;
    if (replace_fragment(model, word, "hr", "l", output)) return true;
    if (replace_fragment(model, word, "u", "l", output)) return true;
    if (replace_fragment(model, word, "hr", "oll", output)) return true;
    if (length && word[length - 1u] == 'f' && length < LW_MAX_WORD) {
        memcpy(repaired, word, length - 1u);
        strcpy(repaired + length - 1u, "ve");
        if (accept_repair(model, repaired, output)) return true;
    }
    if (length && word[length - 1u] == 'z' && length < LW_MAX_WORD) {
        memcpy(repaired, word, length - 1u);
        strcpy(repaired + length - 1u, "es");
        if (accept_repair(model, repaired, output)) return true;
    }
    if (replace_fragment(model, word, "f", "ce", output)) return true;
    return false;
}

size_t lw_model_translate(const lw_model_t *model, const char *outline,
                          char output[][LW_MAX_WORD + 1], size_t output_capacity) {
    if (!output_capacity) return 0;
    if (lw_model_exception(model, outline, output[0])) return 1;
    lw_candidates_t candidates;
    lw_decode_outline_pruned(outline, accept_model_prefix, (void *)model, &candidates);
    size_t count = 0;
    for (uint16_t index = 0; index < candidates.count && count < output_capacity; ++index) {
        if (lw_model_contains(model, candidates.words[index]))
            strcpy(output[count++], candidates.words[index]);
    }
    if (count) return count;
    lw_decode_outline_final_unpruned(outline, accept_model_prefix,
                                     (void *)model, &candidates);
    for (uint16_t index = 0; index < candidates.count; ++index) {
        if (repair_candidate(model, candidates.words[index], output[0])) return 1;
    }
    return 0;
}
