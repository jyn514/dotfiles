; https://github.com/helix-editor/helix/pull/8675/files#diff-e77c51b1f881599d34b0b1ab7d1be5106caffbc6f38382e3d4c0c0a497366d5b
(require "steel/editor.scm")
(require (prefix-in helix. "steel/commands.scm"))
(require (prefix-in helix.static. "steel/static.scm"))

(provide 
  open-helix-scm open-init-scm ep
  run-highlight shell
  open-remote-url git-url url
  Q logs)

(define Q helix.quit)
(define logs helix.log-open)

;;@doc
;; Specialized shell implementation, where % is a wildcard for the current file
(define (shell cx . args)
  ;; Replace the % with the current file
  (define expanded (map (lambda (x) (if (equal? x "%") (current-path cx) x)) args))
  (apply helix.run-shell-command expanded))

;; Functions to assist with the above
(define (editor-get-doc-if-exists doc-id)
  (if (editor-doc-exists? doc-id) (editor->get-document doc-id) #f))

(define (current-path)
  (let* ([focus (editor-focus)]
         [focus-doc-id (editor->doc-id focus)]
         [document (editor-get-doc-if-exists focus-doc-id)])
    (if document (Document-path document) #f)))

;;@doc
;; Open the helix.scm file
(define (open-helix-scm)
  (helix.open (helix.static.get-helix-scm-path)))
(define ep open-helix-scm)

;;@doc
;; Opens the init.scm file
(define (open-init-scm)
  (helix.open (helix.static.get-init-scm-path)))

;;@doc
;; Opens the remote git URL for the currently selected line in the browser.
;; If the line does not exist on the remote, falls back to the line number (instead of following code movements).
;; Note that "does not exist" is very strict; if the line is not identical it is counted as entirely new.
(define (open-remote-url)
  (let ((file (current-path))
        (line (to-string (+ 1 (helix.static.get-current-line-number)))))
    (helix.run-shell-command "remote-git-url" file line)))
(define git-url open-remote-url)
(define url open-remote-url)

(define (run-highlight)
  (helix.static.enqueue-expression-in-engine (helix.static.current-highlighted-text!)))
