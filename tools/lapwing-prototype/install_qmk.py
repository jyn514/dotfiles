#!/usr/bin/env python3
"""Install the generated Lapwing translator into an exported Oryx keymap."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

SOURCES = (
    "lapwing_decoder.c", "lapwing_decoder.h", "lapwing_rules.generated.h",
    "lapwing_model.c", "lapwing_model.h", "lapwing_engine.c", "lapwing_engine.h",
    "lapwing_features.h", "lapwing_modifiers.c", "lapwing_movement.c",
    "lapwing_qmk.c", "lapwing_qmk.h",
)


def install(keymap: Path, model: Path) -> None:
    root = Path(__file__).parent
    for name in SOURCES:
        shutil.copy2(root / name, keymap / name)
    shutil.copy2(model, keymap / "lapwing_model.bin")
    (keymap / "lapwing_model_data.S").write_text(
        '.section .rodata.lapwing_model,"a",%progbits\n'
        '.balign 4\n.global lapwing_model_start\n.global lapwing_model_end\n'
        '.type lapwing_model_start, %object\nlapwing_model_start:\n'
        f'.incbin "keyboards/zsa/moonlander/keymaps/{keymap.name}/lapwing_model.bin"\n'
        'lapwing_model_end:\n'
        '.size lapwing_model_start, lapwing_model_end - lapwing_model_start\n'
    )

    rules = keymap / "rules.mk"
    text = rules.read_text()
    source_line = "SRC += lapwing_decoder.c lapwing_model.c lapwing_modifiers.c lapwing_movement.c lapwing_engine.c lapwing_qmk.c lapwing_model_data.S"
    if source_line not in text:
        rules.write_text(text.rstrip() + "\n\n" + source_line + "\n")

    keymap_c = keymap / "keymap.c"
    text = keymap_c.read_text()
    if '#include "lapwing_qmk.h"' not in text:
        text = text.replace("#include QMK_KEYBOARD_H",
                            '#include QMK_KEYBOARD_H\n#include "lapwing_qmk.h"', 1)
    init_marker = "void keyboard_post_init_user(void) {"
    if "lapwing_qmk_init();" not in text:
        if init_marker not in text:
            raise ValueError("keymap has no keyboard_post_init_user hook")
        text = text.replace(init_marker, init_marker + "\n    lapwing_qmk_init();", 1)
    if "lapwing_qmk_task();" not in text:
        task_marker = "void matrix_scan_user(void) {"
        if task_marker in text:
            text = text.replace(task_marker, task_marker + "\n    lapwing_qmk_task();", 1)
        else:
            text += "\nvoid matrix_scan_user(void) {\n    lapwing_qmk_task();\n}\n"
    keymap_c.write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("keymap", type=Path)
    parser.add_argument("model", type=Path)
    args = parser.parse_args()
    install(args.keymap, args.model)


if __name__ == "__main__":
    main()
