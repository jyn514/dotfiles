#include "lapwing_model.h"

#include <string.h>

#define LW_MODEL_HEADER_SIZE 36u
#define LW_MODEL_VERSION 2u
#define LW_EXCEPTION_RECORD_SIZE 6u
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

static uint32_t hash32(const char *text) {
    uint32_t value = 2166136261u;
    while (*text) value = (value ^ (uint8_t)*text++) * 16777619u;
    value ^= value >> 16;
    value *= 0x7feb352du;
    value ^= value >> 15;
    return value;
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
    if (root >= edges || exception_start != LW_MODEL_HEADER_SIZE + edges * 3u) return false;
    if (block_start != exception_start + exceptions * LW_EXCEPTION_RECORD_SIZE) return false;
    if ((size_t)block_start + block_count * 2u > model->size) return false;
    return true;
}

static int alphabet_index(char character) {
    const char *found = strchr(alphabet, character);
    return found ? (int)(found - alphabet) : -1;
}

bool lw_model_contains(const lw_model_t *model, const char *word) {
    if (!lw_model_valid(model) || !word || !word[0]) return false;
    uint32_t state = root_offset(model);
    bool terminal = false;
    const uint8_t *edges = model->data + LW_MODEL_HEADER_SIZE;
    while (*word) {
        int wanted = alphabet_index(*word++);
        if (wanted < 0 || state == LW_DAWG_LEAF_OFFSET || state >= edge_count(model))
            return false;
        bool matched = false;
        for (uint32_t index = state; index < edge_count(model); ++index) {
            uint32_t edge = read_u24(edges + index * 3u);
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
    return terminal;
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
            if (!valid || length > LW_MAX_WORD || (size_t)(end - cursor) < length)
                return false;
            memcpy(output, cursor, length);
            cursor += length;
        } else {
            uint16_t prefix = read_varint(&cursor, end, &valid);
            uint16_t suffix = read_varint(&cursor, end, &valid);
            if (!valid || prefix > length || prefix + suffix > LW_MAX_WORD
                || (size_t)(end - cursor) < suffix) return false;
            memcpy(output + prefix, cursor, suffix);
            cursor += suffix;
            length = prefix + suffix;
        }
        output[length] = '\0';
    }
    return valid;
}

bool lw_model_exception(const lw_model_t *model, const char *outline,
                        char output[LW_MAX_WORD + 1]) {
    if (!lw_model_valid(model) || !outline || !outline[0]) return false;
    uint32_t wanted = hash32(outline);
    uint32_t low = 0;
    uint32_t high = exception_count(model);
    const uint8_t *records = model->data + exceptions_offset(model);
    while (low < high) {
        uint32_t middle = low + (high - low) / 2u;
        uint32_t found = read_u32(records + middle * LW_EXCEPTION_RECORD_SIZE);
        if (found < wanted) low = middle + 1u;
        else high = middle;
    }
    if (low >= exception_count(model)) return false;
    const uint8_t *record = records + low * LW_EXCEPTION_RECORD_SIZE;
    if (read_u32(record) != wanted) return false;
    return decode_word(model, read_u16(record + 4), output);
}

static bool accept_model_word(void *context, const char *word) {
    return lw_model_contains(context, word);
}

size_t lw_model_translate(const lw_model_t *model, const char *outline,
                          char output[][LW_MAX_WORD + 1], size_t output_capacity) {
    if (!output_capacity) return 0;
    if (lw_model_exception(model, outline, output[0])) return 1;
    return lw_translate_outline(outline, accept_model_word, (void *)model,
                                output, output_capacity);
}
