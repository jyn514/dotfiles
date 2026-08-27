#include "lapwing_engine.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { char text[256]; size_t length; } output_t;

static void emit(void *context, const char *text) {
    output_t *output = context;
    size_t length = strlen(text);
    memcpy(output->text + output->length, text, length + 1);
    output->length += length;
}

static void backspace(void *context, uint8_t count) {
    output_t *output = context;
    if (count > output->length) count = output->length;
    output->length -= count;
    output->text[output->length] = '\0';
}

static int expect(output_t *output, const char *expected) {
    if (strcmp(output->text, expected) == 0) return 0;
    fprintf(stderr, "expected %s, got %s\n", expected, output->text);
    return 1;
}

int main(int argc, char **argv) {
    if (argc != 2) return 1;
    FILE *file = fopen(argv[1], "rb");
    fseek(file, 0, SEEK_END);
    size_t size = (size_t)ftell(file);
    rewind(file);
    uint8_t *data = malloc(size);
    fread(data, 1, size, file);
    fclose(file);
    lw_model_t model = {data, size};
    output_t output = {{0}, 0};
    lw_engine_t engine;
    lw_engine_init(&engine, &model, emit, backspace, &output);

    lw_engine_stroke(&engine, "KAT", 0);
    lw_engine_tick(&engine, LW_COMMIT_DELAY_MS - 1);
    if (expect(&output, "")) return 1;
    lw_engine_tick(&engine, LW_COMMIT_DELAY_MS);
    if (expect(&output, "Cat")) return 1;

    lw_engine_stroke(&engine, "PAOEU", 1000);
    lw_engine_stroke(&engine, "THOPB", 1100);
    lw_engine_stroke(&engine, "PWR", 1101);
    if (expect(&output, "Cat python")) return 1;

    lw_engine_stroke(&engine, "TP-PL", 1200);
    lw_engine_commit(&engine);
    if (expect(&output, "Cat python.")) return 1;

    lw_engine_stroke(&engine, "KAT", 1300);
    lw_engine_commit(&engine);
    if (expect(&output, "Cat python. Cat")) return 1;
    lw_engine_stroke(&engine, "*", 1400);
    if (expect(&output, "Cat python.")) return 1;

    free(data);
    return 0;
}
