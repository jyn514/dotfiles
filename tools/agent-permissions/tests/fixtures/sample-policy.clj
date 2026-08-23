(let [jj-reads (one-of "status" "diff")]
  (policy
    (allow ["jj" jj-reads])
    (allow ["git" "fetch"] :targets [:codex])
    (allow ["command" "-v"] :targets [:claude])
    (deny ["sed"] :reason "use structured tools")))
