(def targets #{:codex :claude})
(def option-keys #{:match :reason :targets})

(defn one-of [& values]
  {:one-of (vec values)})

(defn rule [decision pattern options]
  (let [unknown-options (remove option-keys (keys options))]
    (when (seq unknown-options)
      (throw (ex-info "unknown policy options" {:options (vec unknown-options)})))
    {:decision decision
     :match (or (:match options) :prefix)
     :pattern pattern
     :reason (:reason options)
     :targets (set (or (:targets options) targets))}))

(defn allow [pattern & options]
  (rule :allow pattern (apply hash-map options)))

(defn deny [pattern & options]
  (rule :deny pattern (apply hash-map options)))

(defn policy [& rules]
  (vec rules))

(defn deny-codex [pattern reason]
  (deny pattern :reason reason :targets [:codex]))

(defn allow-claude-exact [pattern]
  (allow pattern :match :exact :targets [:claude]))

(defn allow-claude-descendants [pattern]
  (allow pattern :match :descendants :targets [:claude]))

(policy
  (deny ["sed"] :reason "`sed` is unavailable. Use head/tail for line selection, `perl -pe` for substitutions, or `rg` for searches.")

  ;; agent-room
  (allow ["curl" "http://localhost:3000"])

  (allow ["jj" (one-of "status" "diff" "log" "show" "interdiff" "root" "help" "--version")])
  (allow ["jj" "file" (one-of "list" "show" "annotate")])
  (allow ["jj" "config" (one-of "list" "get")])
  (allow ["jj" "bookmark" "list"])
  (allow ["jj" "bookmark" "advance" "--help"])
  (allow ["jj" "workspace" "list"])
  (allow ["jj" "op" "log"])

  (allow ["git" (one-of "ls-remote" "cherry" "cat-file" "fetch" "diff" "show" "status" "check-ignore")])
  (allow ["git" "push" "--dry-run"])

  (allow [(one-of "true" "false" "cat" "grep" "rg" "jq" "head" "tail" "ps" "echo" "wc" "diff" "ls" "sort" "nl" "sleep" "diff-check" "stat" "file" "df" "du" "lsof" "uname" "id" "xxd")])
  (allow ["mise" "activate"])
  (allow ["command" "-v"])

  (allow ["gh" "pr" (one-of "diff" "checks" "list" "status" "view")])
  (allow ["gh" "issue" (one-of "list" "view")])

  (allow [(one-of "vm_stat" "iostat" "sw_vers")])
  (allow ["sysctl" (one-of "-a" "-n")])
  (allow ["launchctl" "print"])
  (allow ["scutil" "--dns"])
  (allow ["log" "show"])
  (allow ["xcrun" "--find"])
  (allow ["xcode-select" "-p"])

  (allow ["git" (one-of "bug" "clone")])
  (allow ["git" "submodule" "update"])
  (allow ["jj" (one-of "commit" "split" "squash" "duplicate")])
  (allow ["jj" "git" (one-of "clone" "export" "fetch" "init")])
  (allow ["jj" "workspace" "add"])
  (allow ["jj" "bookmark" "create"])
  (allow ["bb" "agent-split"])

  (allow [(one-of "podman" "docker") (one-of "ps" "images" "inspect" "logs" "stats" "version" "info")])
  (allow [(one-of "podman" "docker") "image" "list"])
  (allow [(one-of "podman" "docker") "network" (one-of "ls" "inspect" "list")])
  (allow [(one-of "podman" "docker") "volume" (one-of "ls" "inspect")])
  (allow [(one-of "podman" "docker") "system" "df"])
  (allow [(one-of "podman" "docker") (one-of "port" "top")])
  (allow ["podman" "machine" (one-of "list" "inspect")])

  (allow [(one-of "pgrep" "jcmd" "lpstat" "lpinfo" "clj-kondo" "typst")])
  (allow ["bb" "tasks"])
  (allow ["zola" "build"])
  (allow ["gofmt"])
  (allow ["yt-dlp" "--list-subs"])
  (allow ["tea" "issue" (one-of "list" "ls" "--help" "-h")])
  (allow ["skopeo" (one-of "inspect" "list-tags")])
  (allow ["extract-chat-share"])
  (allow ["extract-chat"])
  (allow ["watchman" (one-of "watch-list" "version" "get-config" "subscription-list" "since" "query" "debug-get-subscriptions" "find")])
  (allow ["tmux" (one-of "show-option" "show-hooks" "list-keys" "list-commands" "info" "display-message" "list-panes")])
  (allow ["tmux" "source-file" "-n"])

  ;; Claude-only rules retain the exact or descendants-only behavior of its
  ;; native permission syntax. General Codex prefixes above are shared.
  (allow-claude-exact ["python3" "-m" "json.tool"])
  (allow-claude-exact ["clojure" "-Spath"])
  (allow-claude-exact ["clojure" "-Stree"]))
