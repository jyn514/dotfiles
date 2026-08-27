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
    size_t count = lw_model_translate(&model, "KAT", output, 4);
    bool found = false;
    for (size_t i = 0; i < count; ++i) found |= strcmp(output[i], "cat") == 0;
    if (!found) result |= fail("rule vocabulary translation failed");
    lw_model_t truncated = {data, 12};
    if (lw_model_valid(&truncated)) result |= fail("truncated model accepted");
    free(data);
    return result;
}
