#include "lapwing_model.h"

#include <string.h>

#define LW_MODEL_HEADER_SIZE 48u
#define LW_MODEL_VERSION 9u
#define LW_EXCEPTION_RECORD_SIZE 5u
#define LW_EXCEPTION_HASH_MASK 0x1fffffffu
#define LW_EXCEPTION_ID_MASK 0x7ffu
#define LW_LOUDS_CHECKPOINT_STRIDE 64u
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
    uint32_t found = read_u16(louds_checkpoints(model) + block * 2u);
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

static uint64_t read_u40(const uint8_t *data) {
    return (uint64_t)read_u32(data) | ((uint64_t)data[4] << 32);
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
static uint32_t word_count(const lw_model_t *model) { return read_u32(model->data + 24); }
static uint32_t reserved_count(const lw_model_t *model) { return read_u32(model->data + 28); }
static uint32_t morphology_count(const lw_model_t *model) { return read_u32(model->data + 32); }
static uint32_t morphology_offset(const lw_model_t *model) { return read_u32(model->data + 36); }
static uint32_t exceptions_offset(const lw_model_t *model) { return read_u32(model->data + 40); }
static uint32_t blocks_offset(const lw_model_t *model) { return read_u32(model->data + 44); }

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
    uint32_t words = word_count(model);
    uint32_t morph_start = morphology_offset(model);
    uint32_t exception_start = exceptions_offset(model);
    uint32_t block_start = blocks_offset(model);
    uint32_t block_count = block_words ? (words + block_words - 1u) / block_words : 0;
    size_t expected_morph_start = LW_MODEL_HEADER_SIZE
        + (size_t)louds_label_bytes(model)
        + louds_topology_bytes(model)
        + louds_terminal_bytes(model)
        + (size_t)louds_checkpoint_count(model) * 2u;
    if (!block_words || !vocabulary
        || root_offset(model) != 0u || reserved_count(model) != 0u
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
                    || read_u16(louds_checkpoints(model) + checkpoint * 2u) != position)
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

    size_t records_end = (size_t)exception_start
        + (size_t)exceptions * LW_EXCEPTION_RECORD_SIZE;
    if (words >= 1u << 11 || records_end != block_start
        || records_end > model->size
        || (size_t)block_start + (size_t)block_count * 2u > model->size)
        return false;
    const uint8_t *records = model->data + exception_start;
    uint32_t previous_fingerprint = 0;
    for (uint32_t index = 0; index < exceptions; ++index) {
        uint64_t record = read_u40(records + index * LW_EXCEPTION_RECORD_SIZE);
        uint32_t fingerprint = (uint32_t)(record >> 11);
        if ((index && fingerprint < previous_fingerprint)
            || (record & LW_EXCEPTION_ID_MASK) >= words) return false;
        previous_fingerprint = fingerprint;
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
    return lw_model_valid(model)
        && walk_word_unchecked(model, word, require_terminal);
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

static bool decode_word(const lw_model_t *model, uint16_t id,
                        char output[LW_MAX_WORD + 1]) {
    uint32_t words = word_count(model);
    uint16_t block_words = read_u16(model->data + 6);
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
            if (cursor >= end) return false;
            uint8_t delta = *cursor++;
            uint16_t prefix, suffix;
            if (delta == 0xffu) {
                prefix = read_varint(&cursor, end, &valid);
                suffix = read_varint(&cursor, end, &valid);
            } else {
                prefix = delta >> 4;
                suffix = delta & 0x0fu;
            }
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
    if (!output_capacity || !lw_model_valid(model)) return 0;
    char normalized[LW_MAX_STROKES * 20];
    if (outline && outline[0] == '#' && outline[1] == '/') {
        size_t length = strlen(outline);
        if (length >= sizeof(normalized)) return 0;
        normalized[0] = '#';
        memcpy(normalized + 1, outline + 2, length - 1u);
        outline = normalized;
    }
    bool proper_noun = outline && outline[0] == '#';
    if (lw_model_exception(model, outline, output[0])) {
        if (proper_noun && output[0][0] >= 'a' && output[0][0] <= 'z')
            output[0][0] = (char)(output[0][0] - 'a' + 'A');
        return 1;
    }
    lw_candidates_t candidates;
    lw_decode_outline_pruned(outline, accept_model_prefix, (void *)model, &candidates);
    size_t count = 0;
    for (uint16_t index = 0; index < candidates.count && count < output_capacity; ++index) {
        if (lw_model_contains(model, candidates.words[index]))
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
