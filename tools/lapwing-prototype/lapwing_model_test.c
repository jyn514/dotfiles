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
    lw_model_t model = {data, size};
    char output[4][LW_MAX_WORD + 1];
    int result = 0;
    if (!lw_model_valid(&model)) result |= fail("model rejected");
    if (!lw_model_contains(&model, "cat")) result |= fail("cat absent");
    if (!lw_model_contains(&model, "python")) result |= fail("python absent");
    if (!lw_model_has_prefix(&model, "py")) result |= fail("python prefix absent");
    if (lw_model_has_prefix(&model, "zz")) result |= fail("non-prefix accepted");
    if (lw_model_exception(&model, "P", output[0]) == false
        || strcmp(output[0], "people") != 0) result |= fail("exception lookup failed");
    if (lw_model_translate(&model, "P", output, 4) != 1
        || strcmp(output[0], "people") != 0) result |= fail("exception priority failed");
    if (lw_model_translate(&model, "#SKWRO*PB", output, 4) != 1
        || strcmp(output[0], "John") != 0) result |= fail("proper noun capitalization failed");
    if (!lw_model_exception(&model, "DUMMY399", output[0])
        || strcmp(output[0], "qapj") != 0) result |= fail("large restart block lookup failed");
    if (lw_model_translate(&model, "#KAT", output, 4) != 1
        || strcmp(output[0], "Cat") != 0) result |= fail("proper rule capitalization failed");
    size_t count = lw_model_translate(&model, "KAT", output, 4);
    bool found = false;
    for (size_t i = 0; i < count; ++i) found |= strcmp(output[i], "cat") == 0;
    if (!found) result |= fail("rule vocabulary translation failed");
    if (lw_model_translate(&model, "KAT/-Z", output, 4) != 1
        || strcmp(output[0], "cats") != 0)
        result |= fail("licensed grouped morphology failed");
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
    lw_model_t truncated = {data, 12};
    if (lw_model_valid(&truncated)) result |= fail("truncated model accepted");
    uint32_t morph_offset = (uint32_t)data[32] | ((uint32_t)data[33] << 8)
        | ((uint32_t)data[34] << 16) | ((uint32_t)data[35] << 24);
    uint8_t saved = data[morph_offset];
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
