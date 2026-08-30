const key_override_t delete_key_override = ko_make_basic(MOD_MASK_SHIFT, KC_BSPC, KC_DELETE);

const key_override_t *key_overrides[] = {
    &delete_key_override
};

bool process_detected_host_os_user(os_variant_t detected_os) {
    switch (detected_os) {
        case OS_LINUX:
            set_unicode_input_mode(UNICODE_MODE_LINUX);
            break;
        case OS_MACOS:
            set_unicode_input_mode(UNICODE_MODE_MACOS);
            break;
        case OS_WINDOWS:
            set_unicode_input_mode(UNICODE_MODE_WINCOMPOSE);
            break;
        case OS_IOS:
        case OS_UNSURE:
            break;
    }
    return true;
}
