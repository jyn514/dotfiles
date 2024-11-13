(define keymaps (#%module "helix/core/keymaps"))

(define (register-values module values)
  (map (lambda (ident) (#%module-add module (symbol->string ident) void)) values))

(register-values keymaps
                 '(helix-current-keymap *buffer-or-extension-keybindings*
                                        *reverse-buffer-map*
                                        helix-merge-keybindings
                                        helix-string->keymap
                                        *global-keybinding-map*
                                        helix-deep-copy-keymap))

(define typable-commands (#%module "helix/core/typable"))
(define static-commands (#%module "helix/core/static"))
(define editor (#%module "helix/core/editor"))

(register-values typable-commands '())

(#%ignore-unused-identifier "_")

keymaps
