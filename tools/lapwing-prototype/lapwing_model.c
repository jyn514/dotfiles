#include "lapwing_model.h"

#include <string.h>

#define LW_MODEL_HEADER_SIZE 48u
#define LW_MODEL_VERSION 10u
#define LW_EXCEPTION_HASH_BITS 29u
#define LW_EXCEPTION_HASH_MASK 0x1fffffffu
#define LW_EXCEPTION_CHECKPOINT_STRIDE 64u
#define LW_LOUDS_CHECKPOINT_STRIDE 64u
static const char alphabet[] = "abcdefghijklmnopqrstuvwxyz'-";
static lw_model_t loaded_model;
static bool loaded_model_valid;

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
static uint32_t morphology_offset(const lw_model_t *model);

static uint32_t louds_node_count(const lw_model_t *model) {
    return edge_count(model) + 1u;
}

static uint32_t louds_label_bytes(const lw_model_t *model) {
    return (edge_count(model) * 5u + 7u) / 8u;
}

static uint32_t louds_topology_bits(const lw_model_t *model) {
    return 2u * louds_node_count(model) - 1u;
}

static uint32_t louds_topology_bytes(const lw_model_t *model) {
    return (louds_topology_bits(model) + 7u) / 8u;
}

static uint32_t louds_terminal_bytes(const lw_model_t *model) {
    return (louds_node_count(model) + 7u) / 8u;
}

static uint32_t louds_checkpoint_count(const lw_model_t *model) {
    return louds_node_count(model) / LW_LOUDS_CHECKPOINT_STRIDE
        + (louds_node_count(model) % LW_LOUDS_CHECKPOINT_STRIDE != 0u);
}

static const uint8_t *louds_labels(const lw_model_t *model) {
    return model->data + LW_MODEL_HEADER_SIZE;
}

static const uint8_t *louds_topology(const lw_model_t *model) {
    return louds_labels(model) + louds_label_bytes(model);
}

static const uint8_t *louds_terminals(const lw_model_t *model) {
    return louds_topology(model) + louds_topology_bytes(model);
}

static const uint8_t *louds_checkpoints(const lw_model_t *model) {
    return louds_terminals(model) + louds_terminal_bytes(model);
}

static uint32_t packed_bits(const uint8_t *data, uint32_t bit, uint8_t width) {
    uint32_t value = 0;
    for (uint8_t index = 0; index < width; ++index)
        value |= (uint32_t)((data[(bit + index) / 8u]
                           >> ((bit + index) % 8u)) & 1u) << index;
    return value;
}

static bool louds_select_zero(const lw_model_t *model, uint32_t node,
                              uint32_t *position) {
    if (node >= louds_node_count(model)) return false;
    uint32_t block = node / LW_LOUDS_CHECKPOINT_STRIDE;
    uint32_t remaining = node % LW_LOUDS_CHECKPOINT_STRIDE;
    uint32_t found = read_u24(louds_checkpoints(model) + block * 3u);
    while (remaining) {
        if (++found >= louds_topology_bits(model)) return false;
        if (!packed_bits(louds_topology(model), found, 1u)) --remaining;
    }
    *position = found;
    return true;
}

static bool louds_child_interval(const lw_model_t *model, uint32_t node,
                                 uint32_t *first, uint32_t *end) {
    uint32_t end_zero, start;
    if (!louds_select_zero(model, node, &end_zero)) return false;
    if (!node) start = 0;
    else {
        if (!louds_select_zero(model, node - 1u, &start)) return false;
        ++start;
    }
    if (end_zero < start || start < node) return false;
    *first = start - node;
    *end = *first + end_zero - start;
    return *end <= edge_count(model);
}

static bool louds_node_depth(const lw_model_t *model, uint32_t wanted,
                             uint8_t *depth) {
    uint32_t first_node = 0, end_node = 1;
    for (uint8_t level = 0; level <= 31u && first_node < end_node; ++level) {
        if (wanted >= first_node && wanted < end_node) {
            *depth = level;
            return true;
        }
        uint32_t first_edge, ignored, last_edge;
        if (!louds_child_interval(model, first_node, &first_edge, &ignored)
            || !louds_child_interval(model, end_node - 1u, &ignored, &last_edge))
            return false;
        first_node = first_edge + 1u;
        end_node = last_edge + 1u;
    }
    return false;
}

static uint8_t louds_label(const lw_model_t *model, uint32_t edge) {
    return (uint8_t)packed_bits(louds_labels(model), edge * 5u, 5u);
}

static bool louds_terminal(const lw_model_t *model, uint32_t node) {
    return packed_bits(louds_terminals(model), node, 1u) != 0u;
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

static uint32_t read_varint32(const uint8_t **cursor, const uint8_t *end,
                              bool *valid) {
    uint32_t value = 0;
    uint8_t shift = 0;
    while (*cursor < end && shift < 32u) {
        uint8_t byte = *(*cursor)++;
        value |= (uint32_t)(byte & 0x7fu) << shift;
        if (!(byte & 0x80u)) return value;
        shift += 7u;
    }
    *valid = false;
    return 0;
}

static uint32_t edge_count(const lw_model_t *model) { return read_u32(model->data + 12); }
static uint32_t root_offset(const lw_model_t *model) { return read_u32(model->data + 16); }
static uint32_t exception_count(const lw_model_t *model) { return read_u32(model->data + 20); }
static uint32_t exception_low_bits(const lw_model_t *model) { return read_u32(model->data + 24); }
static uint32_t exception_node_bits(const lw_model_t *model) { return read_u32(model->data + 28); }
static uint32_t morphology_count(const lw_model_t *model) { return read_u32(model->data + 32); }
static uint32_t morphology_offset(const lw_model_t *model) { return read_u32(model->data + 36); }
static uint32_t exceptions_offset(const lw_model_t *model) { return read_u32(model->data + 40); }
static uint32_t encoded_model_size(const lw_model_t *model) { return read_u32(model->data + 44); }

static bool padding_zero(const uint8_t *data, uint32_t bits) {
    uint8_t remainder = bits % 8u;
    if (!remainder) return true;
    return (data[bits / 8u] & (uint8_t)(0xffu << remainder)) == 0u;
}

bool lw_model_valid(const lw_model_t *model) {
    if (!model || !model->data || model->size < LW_MODEL_HEADER_SIZE) return false;
    if (memcmp(model->data, "LWMD", 4) != 0 || model->data[4] != LW_MODEL_VERSION)
        return false;
    uint16_t block_words = read_u16(model->data + 6);
    uint32_t vocabulary = read_u32(model->data + 8);
    uint32_t edges = edge_count(model);
    if (!edges || edges >= UINT16_MAX) return false;
    uint32_t nodes = louds_node_count(model);
    uint32_t exceptions = exception_count(model);
    uint32_t low_bits = exception_low_bits(model);
    uint32_t node_bits = exception_node_bits(model);
    uint32_t morph_start = morphology_offset(model);
    uint32_t exception_start = exceptions_offset(model);
    size_t expected_morph_start = LW_MODEL_HEADER_SIZE
        + (size_t)louds_label_bytes(model)
        + louds_topology_bytes(model)
        + louds_terminal_bytes(model)
        + (size_t)louds_checkpoint_count(model) * 3u;
    if (block_words != LW_EXCEPTION_CHECKPOINT_STRIDE || !vocabulary
        || root_offset(model) != 0u || encoded_model_size(model) != model->size
        || expected_morph_start > model->size || morph_start != expected_morph_start
        || exception_start < morph_start || exception_start > model->size)
        return false;

    uint32_t topology_bits = louds_topology_bits(model);
    uint32_t ones = 0, zeros = 0, degree = 0, checkpoint = 0;
    for (uint32_t position = 0; position < topology_bits; ++position) {
        if (packed_bits(louds_topology(model), position, 1u)) {
            if (++degree >= sizeof(alphabet)) return false;
            ++ones;
        } else {
            if (zeros % LW_LOUDS_CHECKPOINT_STRIDE == 0u) {
                if (checkpoint >= louds_checkpoint_count(model)
                    || read_u24(louds_checkpoints(model) + checkpoint * 3u) != position)
                    return false;
                ++checkpoint;
            }
            ++zeros;
            degree = 0;
        }
    }
    if (ones != edges || zeros != nodes
        || checkpoint != louds_checkpoint_count(model)
        || !padding_zero(louds_topology(model), topology_bits)
        || !padding_zero(louds_terminals(model), nodes)) return false;
    for (uint32_t edge = 0; edge < edges; ++edge)
        if (louds_label(model, edge) >= sizeof(alphabet) - 1u) return false;
    uint32_t terminal_count = 0;
    for (uint32_t node = 0; node < nodes; ++node)
        terminal_count += louds_terminal(model, node);
    if (terminal_count != vocabulary || louds_terminal(model, 0u)
        || !padding_zero(louds_labels(model), edges * 5u)) return false;

    if (exceptions >= UINT16_MAX) return false;
    if (!exceptions) {
        if (low_bits || node_bits || exception_start != model->size) return false;
    } else {
        uint32_t expected_low_bits = 0;
        for (uint32_t ratio = (1u << LW_EXCEPTION_HASH_BITS) / exceptions;
             ratio > 1u; ratio >>= 1u) ++expected_low_bits;
        uint32_t expected_node_bits = 0;
        for (uint32_t value = nodes - 1u; value; value >>= 1u)
            ++expected_node_bits;
        if (low_bits != expected_low_bits || node_bits != expected_node_bits
            || !node_bits || node_bits > 16u) return false;
        uint32_t buckets = 1u << (LW_EXCEPTION_HASH_BITS - low_bits);
        size_t low_bytes = ((size_t)exceptions * low_bits + 7u) / 8u;
        uint32_t high_bits = exceptions + buckets;
        size_t high_bytes = ((size_t)high_bits + 7u) / 8u;
        uint32_t checkpoint_count = (buckets + LW_EXCEPTION_CHECKPOINT_STRIDE - 1u)
            / LW_EXCEPTION_CHECKPOINT_STRIDE;
        size_t checkpoint_bytes = (size_t)checkpoint_count * 2u;
        size_t reference_bytes = ((size_t)exceptions * node_bits + 7u) / 8u;
        size_t expected_end = (size_t)exception_start + low_bytes + high_bytes
            + checkpoint_bytes + reference_bytes;
        if (expected_end != model->size) return false;
        const uint8_t *lows = model->data + exception_start;
        const uint8_t *highs = lows + low_bytes;
        const uint8_t *checkpoints = highs + high_bytes;
        const uint8_t *references = checkpoints + checkpoint_bytes;
        uint32_t ones_seen = 0, zeros_seen = 0, checkpoint_index = 0;
        uint32_t previous_fingerprint = 0;
        for (uint32_t position = 0; position < high_bits; ++position) {
            if (packed_bits(highs, position, 1u)) {
                if (ones_seen >= exceptions) return false;
                uint32_t fingerprint = (zeros_seen << low_bits)
                    | packed_bits(lows, ones_seen * low_bits, (uint8_t)low_bits);
                if (ones_seen && fingerprint <= previous_fingerprint) return false;
                previous_fingerprint = fingerprint;
                uint32_t node = packed_bits(
                    references, ones_seen * node_bits, (uint8_t)node_bits
                );
                uint8_t depth;
                if (!node || node >= nodes || !louds_terminal(model, node)
                    || !louds_node_depth(model, node, &depth)
                    || !depth || depth > LW_MAX_WORD) return false;
                ++ones_seen;
            } else {
                if (zeros_seen % LW_EXCEPTION_CHECKPOINT_STRIDE == 0u) {
                    if (checkpoint_index >= checkpoint_count
                        || read_u16(checkpoints + checkpoint_index * 2u) != position)
                        return false;
                    ++checkpoint_index;
                }
                ++zeros_seen;
            }
        }
        if (ones_seen != exceptions || zeros_seen != buckets
            || checkpoint_index != checkpoint_count
            || !padding_zero(lows, exceptions * low_bits)
            || !padding_zero(highs, high_bits)
            || !padding_zero(references, exceptions * node_bits)) return false;
    }
    const uint8_t *cursor = model->data + morph_start;
    const uint8_t *morph_end = model->data + exception_start;
    for (uint32_t group = 0; group < morphology_count(model); ++group) {
        if ((size_t)(morph_end - cursor) < 2u) return false;
        uint8_t root_length = *cursor++, output_length = *cursor++;
        char ignored[32];
        if (root_length > 31u || output_length > 31u
            || !decode_letters(&cursor, morph_end, ignored, root_length)
            || !decode_letters(&cursor, morph_end, ignored, output_length)) return false;
        bool valid = true;
        uint32_t count = read_varint32(&cursor, morph_end, &valid), id = 0;
        if (!valid || !count) return false;
        for (uint32_t index = 0; index < count; ++index) {
            uint32_t delta = read_varint32(&cursor, morph_end, &valid);
            if (!valid || !delta || UINT32_MAX - id < delta) return false;
            id += delta;
            uint32_t node = id >> 5;
            uint8_t depth;
            if (node >= nodes || (id & 31u) == 0u
                || !louds_terminal(model, node)
                || !louds_node_depth(model, node, &depth)
                || depth != (id & 31u)) return false;
        }
    }
    return cursor == morph_end;
}

const lw_model_t *lw_model_load(const uint8_t *data, size_t size) {
    if (loaded_model_valid)
        return loaded_model.data == data && loaded_model.size == size
            ? &loaded_model : NULL;
    lw_model_t candidate = {.data = data, .size = size};
    if (!lw_model_valid(&candidate)) return NULL;
    loaded_model = candidate;
    loaded_model_valid = true;
    return &loaded_model;
}

static bool model_ready(const lw_model_t *model) {
    return model && ((model == &loaded_model && loaded_model_valid)
                     || lw_model_valid(model));
}

static int alphabet_index(char character) {
    const char *found = strchr(alphabet, character);
    return found ? (int)(found - alphabet) : -1;
}

static bool walk_word_unchecked(const lw_model_t *model, const char *word,
                                bool require_terminal) {
    if (!word || !word[0]) return false;
    uint32_t node = root_offset(model);
    while (*word) {
        int wanted = alphabet_index(*word++);
        if (wanted < 0) return false;
        uint32_t first, end;
        if (!louds_child_interval(model, node, &first, &end)) return false;
        bool matched = false;
        for (uint32_t edge = first; edge < end; ++edge) {
            if ((int)louds_label(model, edge) == wanted) {
                node = edge + 1u;
                matched = true;
                break;
            }
        }
        if (!matched) return false;
    }
    return !require_terminal || louds_terminal(model, node);
}

static bool walk_word(const lw_model_t *model, const char *word,
                      bool require_terminal) {
    return model_ready(model) && walk_word_unchecked(model, word, require_terminal);
}

bool lw_model_contains(const lw_model_t *model, const char *word) {
    return walk_word(model, word, true);
}

static bool primary_identity(const lw_model_t *model, const char *word,
                             uint32_t *identity) {
    uint32_t node = root_offset(model);
    size_t length = 0;
    while (word[length]) {
        int wanted = alphabet_index(word[length]);
        if (wanted < 0) return false;
        uint32_t first, end;
        if (!louds_child_interval(model, node, &first, &end)) return false;
        bool matched = false;
        for (uint32_t edge = first; edge < end; ++edge) {
            if ((int)louds_label(model, edge) == wanted) {
                node = edge + 1u;
                ++length;
                matched = true;
                break;
            }
        }
        if (!matched) return false;
    }
    if (!length || length > 31u || !louds_terminal(model, node)) return false;
    *identity = (node << 5) | (uint32_t)length;
    return true;
}

static bool morphology_accepts(const lw_model_t *model, const char *word) {
    const uint8_t *cursor = model->data + morphology_offset(model);
    const uint8_t *end = model->data + exceptions_offset(model);
    size_t word_length = strlen(word);
    for (uint32_t group = 0; group < morphology_count(model); ++group) {
        if ((size_t)(end - cursor) < 2u) return false;
        uint8_t root_length = *cursor++, output_length = *cursor++;
        char root_tail[32], output_tail[32], root[LW_MAX_WORD + 1];
        if (!decode_letters(&cursor, end, root_tail, root_length)
            || !decode_letters(&cursor, end, output_tail, output_length)) return false;
        root_tail[root_length] = output_tail[output_length] = '\0';
        bool valid = true;
        uint16_t count = read_varint(&cursor, end, &valid);
        uint32_t wanted_id = UINT32_MAX;
        if (valid && word_length >= output_length
            && memcmp(word + word_length - output_length, output_tail, output_length) == 0
            && word_length - output_length + root_length <= LW_MAX_WORD) {
            size_t prefix = word_length - output_length;
            memcpy(root, word, prefix);
            memcpy(root + prefix, root_tail, root_length + 1u);
            (void)primary_identity(model, root, &wanted_id);
        }
        uint32_t id = 0;
        for (uint16_t index = 0; index < count; ++index) {
            uint32_t delta = read_varint32(&cursor, end, &valid);
            if (!valid || UINT32_MAX - id < delta) return false;
            id += delta;
            if (id == wanted_id) return true;
        }
    }
    return false;
}

bool lw_model_has_prefix(const lw_model_t *model, const char *prefix) {
    return walk_word(model, prefix, false);
}

static bool louds_parent(const lw_model_t *model, uint32_t child,
                         uint32_t *parent) {
    if (!child || child >= louds_node_count(model)) return false;
    uint32_t wanted_edge = child - 1u;
    uint32_t low = 0, high = child;
    while (low < high) {
        uint32_t middle = low + (high - low) / 2u;
        uint32_t first, end;
        if (!louds_child_interval(model, middle, &first, &end)) return false;
        if (end <= wanted_edge) low = middle + 1u;
        else high = middle;
    }
    uint32_t first, end;
    if (low >= child || !louds_child_interval(model, low, &first, &end)
        || wanted_edge < first || wanted_edge >= end) return false;
    *parent = low;
    return true;
}

static bool decode_trie_node(const lw_model_t *model, uint32_t node,
                             char output[LW_MAX_WORD + 1]) {
    if (!node || node >= louds_node_count(model) || !louds_terminal(model, node))
        return false;
    size_t length = 0;
    while (node) {
        if (length >= LW_MAX_WORD) return false;
        uint8_t label = louds_label(model, node - 1u);
        if (label >= sizeof(alphabet) - 1u) return false;
        output[length++] = alphabet[label];
        if (!louds_parent(model, node, &node)) return false;
    }
    for (size_t left = 0, right = length - 1u; left < right; ++left, --right) {
        char saved = output[left];
        output[left] = output[right];
        output[right] = saved;
    }
    output[length] = '\0';
    return true;
}

static bool exception_select_zero(const uint8_t *highs, uint32_t high_bits,
                                  const uint8_t *checkpoints, uint32_t quotient,
                                  uint32_t *position) {
    uint32_t block = quotient / LW_EXCEPTION_CHECKPOINT_STRIDE;
    uint32_t remaining = quotient % LW_EXCEPTION_CHECKPOINT_STRIDE;
    uint32_t found = read_u16(checkpoints + block * 2u);
    while (remaining) {
        if (++found >= high_bits) return false;
        if (!packed_bits(highs, found, 1u)) --remaining;
    }
    *position = found;
    return true;
}

static bool model_exception_unchecked(const lw_model_t *model, const char *outline,
                                      char output[LW_MAX_WORD + 1]) {
    if (!outline || !outline[0] || !exception_count(model)) return false;
    uint32_t count = exception_count(model);
    uint32_t low_width = exception_low_bits(model);
    uint32_t node_width = exception_node_bits(model);
    uint32_t buckets = 1u << (LW_EXCEPTION_HASH_BITS - low_width);
    size_t low_bytes = ((size_t)count * low_width + 7u) / 8u;
    uint32_t high_bits = count + buckets;
    size_t high_bytes = ((size_t)high_bits + 7u) / 8u;
    uint32_t checkpoint_count = (buckets + LW_EXCEPTION_CHECKPOINT_STRIDE - 1u)
        / LW_EXCEPTION_CHECKPOINT_STRIDE;
    const uint8_t *lows = model->data + exceptions_offset(model);
    const uint8_t *highs = lows + low_bytes;
    const uint8_t *checkpoints = highs + high_bytes;
    const uint8_t *references = checkpoints + checkpoint_count * 2u;

    uint32_t wanted = hash32(outline) & LW_EXCEPTION_HASH_MASK;
    uint32_t quotient = wanted >> low_width;
    uint32_t remainder = wanted & ((1u << low_width) - 1u);
    uint32_t zero, previous_zero;
    if (!exception_select_zero(highs, high_bits, checkpoints, quotient, &zero))
        return false;
    uint32_t end = zero - quotient;
    uint32_t start = 0;
    if (quotient) {
        if (!exception_select_zero(
                highs, high_bits, checkpoints, quotient - 1u, &previous_zero))
            return false;
        start = previous_zero - (quotient - 1u);
    }
    uint32_t low = start, high = end;
    while (low < high) {
        uint32_t middle = low + (high - low) / 2u;
        uint32_t found = packed_bits(lows, middle * low_width, (uint8_t)low_width);
        if (found < remainder) low = middle + 1u;
        else high = middle;
    }
    if (low >= end
        || packed_bits(lows, low * low_width, (uint8_t)low_width) != remainder)
        return false;
    uint32_t node = packed_bits(references, low * node_width, (uint8_t)node_width);
    return decode_trie_node(model, node, output);
}

bool lw_model_exception(const lw_model_t *model, const char *outline,
                        char output[LW_MAX_WORD + 1]) {
    return model_ready(model) && model_exception_unchecked(model, outline, output);
}

static bool accept_model_prefix(void *context, const char *prefix) {
    return walk_word_unchecked(context, prefix, false);
}

static bool is_repair_consonant(char character) {
    return character >= 'a' && character <= 'z'
        && strchr("aeiou", character) == NULL;
}

static bool accept_repair(const lw_model_t *model, const char *candidate,
                          char output[LW_MAX_WORD + 1]) {
    if (!walk_word_unchecked(model, candidate, true)) return false;
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

static bool insert_fragment(const lw_model_t *model, const char *word,
                            const char *fragment,
                            char output[LW_MAX_WORD + 1]) {
    size_t word_length = strlen(word);
    size_t fragment_length = strlen(fragment);
    if (word_length + fragment_length > LW_MAX_WORD) return false;
    char repaired[LW_MAX_WORD + 1];
    for (size_t index = 1; index < word_length; ++index) {
        memcpy(repaired, word, index);
        memcpy(repaired + index, fragment, fragment_length);
        strcpy(repaired + index + fragment_length, word + index);
        if (accept_repair(model, repaired, output)) return true;
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
    if (insert_fragment(model, word, "gh", output)) return true;
    if (insert_fragment(model, word, "in", output)) return true;
    if (replace_fragment(model, word, "or", "our", output)) return true;
    if (replace_fragment(model, word, "iz", "is", output)) return true;
    if (length >= 2u && strcmp(word + length - 2u, "er") == 0) {
        memcpy(repaired, word, length - 2u);
        strcpy(repaired + length - 2u, "re");
        if (accept_repair(model, repaired, output)) return true;
    }
    if (length < LW_MAX_WORD) {
        for (size_t index = 1; index + 2u < length; ++index) {
            if (word[index] != 'l'
                || (strcmp(word + index + 1u, "ed") != 0
                    && strcmp(word + index + 1u, "ing") != 0))
                continue;
            memcpy(repaired, word, index);
            repaired[index] = 'l';
            strcpy(repaired + index + 1u, word + index);
            if (accept_repair(model, repaired, output)) return true;
        }
    }
    return false;
}

size_t lw_model_translate(const lw_model_t *model, const char *outline,
                          char output[][LW_MAX_WORD + 1], size_t output_capacity) {
    if (!output_capacity || !model_ready(model)) return 0;
    char normalized[LW_MAX_STROKES * 20];
    if (outline && outline[0] == '#' && outline[1] == '/') {
        size_t length = strlen(outline);
        if (length >= sizeof(normalized)) return 0;
        normalized[0] = '#';
        memcpy(normalized + 1, outline + 2, length - 1u);
        outline = normalized;
    }
    bool proper_noun = outline && outline[0] == '#';
    if (model_exception_unchecked(model, outline, output[0])) {
        if (proper_noun && output[0][0] >= 'a' && output[0][0] <= 'z')
            output[0][0] = (char)(output[0][0] - 'a' + 'A');
        return 1;
    }
    lw_candidates_t candidates;
    lw_decode_outline_pruned(outline, accept_model_prefix, (void *)model, &candidates);
    size_t count = 0;
    for (uint16_t index = 0; index < candidates.count && count < output_capacity; ++index) {
        if (walk_word_unchecked(model, candidates.words[index], true))
            strcpy(output[count++], candidates.words[index]);
    }
    if (count) {
        if (proper_noun) {
            for (size_t index = 0; index < count; ++index)
                if (output[index][0] >= 'a' && output[index][0] <= 'z')
                    output[index][0] = (char)(output[index][0] - 'a' + 'A');
        }
        return count;
    }
    lw_decode_outline_final_unpruned(outline, accept_model_prefix,
                                     (void *)model, &candidates);
    for (uint16_t index = 0; index < candidates.count; ++index) {
        if (morphology_accepts(model, candidates.words[index])) {
            strcpy(output[0], candidates.words[index]);
            if (proper_noun && output[0][0] >= 'a' && output[0][0] <= 'z')
                output[0][0] = (char)(output[0][0] - 'a' + 'A');
            return 1;
        }
        if (repair_candidate(model, candidates.words[index], output[0])) {
            if (proper_noun && output[0][0] >= 'a' && output[0][0] <= 'z')
                output[0][0] = (char)(output[0][0] - 'a' + 'A');
            return 1;
        }
    }
    return 0;
}
