#include "lapwing_model.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int fail(const char *message) {
    fprintf(stderr, "%s\n", message);
    return 1;
}

int main(int argc, char **argv) {
    if (argc != 2) return fail("expected model path");
    FILE *file = fopen(argv[1], "rb");
    if (!file) return fail("cannot open model");
    if (fseek(file, 0, SEEK_END) || ftell(file) < 0) return fail("cannot size model");
    size_t size = (size_t)ftell(file);
    rewind(file);
    uint8_t *data = malloc(size);
    if (!data || fread(data, 1, size, file) != size) return fail("cannot read model");
    fclose(file);
    lw_model_t model = {.data = data, .size = size};
    char output[4][LW_MAX_WORD + 1];
    int result = 0;
    if (!lw_model_valid(&model)) result |= fail("model rejected");
    const lw_model_t *loaded = lw_model_load(data, size);
    if (!loaded || lw_model_load(data, size) != loaded)
        result |= fail("immutable model load failed");
    if (lw_model_load(data + 1u, size - 1u))
        result |= fail("different second model load accepted");
    if (!lw_model_contains(&model, "cat")) result |= fail("cat absent");
    if (!lw_model_contains(&model, "python")) result |= fail("python absent");
    if (!lw_model_contains(&model, "zzzppzxw")) result |= fail("overflow word absent");
    if (!lw_model_has_prefix(&model, "py")) result |= fail("python prefix absent");
    if (lw_model_has_prefix(&model, "$")) result |= fail("non-prefix accepted");
    if (lw_model_exception(&model, "P", output[0]) == false
        || strcmp(output[0], "people") != 0) result |= fail("exception lookup failed");
    if (!lw_model_exception(&model, "LONG2", output[0])
        || strcmp(output[0], "abcdefghijklmnopqr") != 0)
        result |= fail("long exception node reconstruction failed");
    if (lw_model_translate(&model, "P", output, 4) != 1
        || strcmp(output[0], "people") != 0) result |= fail("exception priority failed");
    if (lw_model_translate(&model, "#SKWRO*PB", output, 4) != 1
        || strcmp(output[0], "John") != 0) result |= fail("proper noun capitalization failed");
    if (lw_model_translate(&model, "#/SKWRO*PB", output, 4) != 1
        || strcmp(output[0], "John") != 0) result |= fail("prefixed proper noun failed");
    if (!lw_model_exception(&model, "DUMMY399", output[0])
        || strcmp(output[0], "qapj") != 0) result |= fail("large Elias-Fano lookup failed");
    if (lw_model_translate(&model, "#KAT", output, 4) != 1
        || strcmp(output[0], "Cat") != 0) result |= fail("proper rule capitalization failed");
    size_t count = lw_model_translate(&model, "KAT", output, 4);
    bool found = false;
    for (size_t i = 0; i < count; ++i) found |= strcmp(output[i], "cat") == 0;
    if (!found) result |= fail("rule vocabulary translation failed");
    if (lw_model_translate(&model, "KAT/-Z", output, 4) != 1
        || strcmp(output[0], "cats") != 0)
        result |= fail("licensed grouped morphology failed");
    if (lw_model_translate(&model, "TPHRAEUPL", output, 4) != 1
        || strcmp(output[0], "flame") != 0)
        result |= fail("atomic initial cluster failed");
    if (lw_model_translate(&model, "PO/SES", output, 4) != 1
        || strcmp(output[0], "possess") != 0)
        result |= fail("doubled-s spelling failed");
    count = lw_model_translate(&model, "TKOG/-Z", output, 4);
    for (size_t i = 0; i < count; ++i)
        if (strcmp(output[i], "dogs") == 0)
            result |= fail("unlicensed morphology/nonword accepted");
    if (lw_model_translate(&model, "TRAPBS/PHEUGS", output, 4) != 1
        || strcmp(output[0], "transmission") != 0)
        result |= fail("orthographic repair failed");
    if (lw_model_translate(&model, "WAUFP", output, 4) != 1
        || strcmp(output[0], "watch") != 0)
        result |= fail("orthographic deletion repair failed");
    if (lw_model_translate(&model, "TKO*EPBT", output, 4) != 1
        || strcmp(output[0], "don't") != 0)
        result |= fail("apostrophe insertion repair failed");
    if (lw_model_translate(&model, "SEL/PWRAEUGS", output, 4) != 1
        || strcmp(output[0], "celebration") != 0)
        result |= fail("celebration-family repair failed");
    if (lw_model_translate(&model, "KAUL/-D", output, 4) != 1
        || strcmp(output[0], "called") != 0)
        result |= fail("broad-vowel repair failed");
    if (lw_model_translate(&model, "KHRAOEPB", output, 4) != 1
        || strcmp(output[0], "clean") != 0)
        result |= fail("folded-l repair failed");
    if (lw_model_translate(&model, "KO/HREPBLG", output, 4) != 1
        || strcmp(output[0], "college") != 0)
        result |= fail("folded-coll repair failed");
    if (lw_model_translate(&model, "TAUBG", output, 4) != 1
        || strcmp(output[0], "talk") != 0)
        result |= fail("broad-vowel l repair failed");
    if (lw_model_translate(&model, "HROF", output, 4) != 1
        || strcmp(output[0], "love") != 0)
        result |= fail("voiced silent-e repair failed");
    if (lw_model_translate(&model, "PHAEUBGZ", output, 4) != 1
        || strcmp(output[0], "makes") != 0)
        result |= fail("plural spelling repair failed");
    if (lw_model_translate(&model, "PHRAEUFD", output, 4) != 1
        || strcmp(output[0], "placed") != 0)
        result |= fail("soft-c spelling repair failed");
    if (lw_model_translate(&model, "HRAOEUT", output, 4) != 1
        || strcmp(output[0], "light") != 0)
        result |= fail("silent-gh repair failed");
    if (lw_model_translate(&model, "TKO*G", output, 4) != 1
        || strcmp(output[0], "doing") != 0)
        result |= fail("folded-ing repair failed");
    if (lw_model_translate(&model, "KAT/TPEURB", output, 4) != 1
        || strcmp(output[0], "cat-fish") != 0)
        result |= fail("hyphenated composition failed");
    if (lw_model_translate(&model, "HO/TPHOR", output, 4) != 1
        || strcmp(output[0], "honour") != 0)
        result |= fail("british our repair failed");
    if (lw_model_translate(&model, "SEPB/TER", output, 4) != 1
        || strcmp(output[0], "centre") != 0)
        result |= fail("british re repair failed");
    if (lw_model_translate(&model, "TRAFLD", output, 4) != 1
        || strcmp(output[0], "travelled") != 0)
        result |= fail("british doubled-l repair failed");
    lw_model_t truncated = {.data = data, .size = 12};
    if (lw_model_valid(&truncated)) result |= fail("truncated model accepted");
    uint32_t edges = (uint32_t)data[12] | ((uint32_t)data[13] << 8)
        | ((uint32_t)data[14] << 16) | ((uint32_t)data[15] << 24);
    uint32_t nodes = edges + 1u;
    uint32_t label_bytes = (edges * 5u + 7u) / 8u;
    uint32_t topology_bytes = (2u * nodes - 1u + 7u) / 8u;
    uint32_t terminal_bytes = (nodes + 7u) / 8u;
    uint32_t terminal_offset = 48u + label_bytes + topology_bytes;
    uint32_t checkpoint_offset = terminal_offset + terminal_bytes;
    uint8_t saved = data[48];
    data[48] = (uint8_t)(data[48] & 0xe0u) | 0x1fu;
    if (lw_model_valid(&model)) result |= fail("invalid LOUDS label accepted");
    data[48] = saved;
    saved = data[checkpoint_offset];
    data[checkpoint_offset] ^= 1u;
    if (lw_model_valid(&model)) result |= fail("invalid LOUDS checkpoint accepted");
    data[checkpoint_offset] = saved;
    saved = data[terminal_offset];
    data[terminal_offset] |= 1u;
    if (lw_model_valid(&model)) result |= fail("terminal root accepted");
    data[terminal_offset] = saved;
    uint8_t saved_exceptions[4] = {data[20], data[21], data[22], data[23]};
    data[20] = data[21] = data[22] = data[23] = 0xffu;
    if (lw_model_valid(&model)) result |= fail("overflowing exception count accepted");
    memcpy(data + 20, saved_exceptions, sizeof(saved_exceptions));
    uint32_t exception_count = (uint32_t)data[20] | ((uint32_t)data[21] << 8)
        | ((uint32_t)data[22] << 16) | ((uint32_t)data[23] << 24);
    uint32_t low_bits = (uint32_t)data[24] | ((uint32_t)data[25] << 8)
        | ((uint32_t)data[26] << 16) | ((uint32_t)data[27] << 24);
    uint32_t exception_offset = (uint32_t)data[40] | ((uint32_t)data[41] << 8)
        | ((uint32_t)data[42] << 16) | ((uint32_t)data[43] << 24);
    uint32_t buckets = 1u << (29u - low_bits);
    uint32_t low_bytes = (exception_count * low_bits + 7u) / 8u;
    uint32_t high_bytes = (exception_count + buckets + 7u) / 8u;
    uint32_t exception_checkpoint_offset = exception_offset + low_bytes + high_bytes;
    saved = data[exception_checkpoint_offset];
    data[exception_checkpoint_offset] ^= 1u;
    if (lw_model_valid(&model)) result |= fail("corrupt exception checkpoint accepted");
    data[exception_checkpoint_offset] = saved;
    uint32_t reference_offset = exception_checkpoint_offset
        + 2u * ((buckets + 63u) / 64u);
    uint8_t saved_reference[2] = {data[reference_offset], data[reference_offset + 1u]};
    data[reference_offset] = data[reference_offset + 1u] = 0u;
    if (lw_model_valid(&model)) result |= fail("nonterminal exception reference accepted");
    memcpy(data + reference_offset, saved_reference, sizeof(saved_reference));
    uint32_t morph_offset = (uint32_t)data[36] | ((uint32_t)data[37] << 8)
        | ((uint32_t)data[38] << 16) | ((uint32_t)data[39] << 24);
    saved = data[morph_offset];
    data[morph_offset] = 32u;
    if (lw_model_valid(&model)) result |= fail("corrupt morphology accepted");
    data[morph_offset] = saved;
    saved = data[4];
    data[4] = 4u;
    if (lw_model_valid(&model)) result |= fail("wrong model version accepted");
    data[4] = saved;
    free(data);
    return result;
}
