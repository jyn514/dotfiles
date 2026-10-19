(ns scripts.jj-split-patch-integration-test
  (:require [babashka.fs :as fs]
            [babashka.process :as process]
            [cheshire.core :as json]
            [clojure.string :as str]
            [clojure.test :refer [deftest is use-fixtures]]))

(load-file "tools/agent-split/tests/fixtures/repo.clj")
(require '[scripts.agent-split-test-repo :as fixture])

(def script (str (fs/canonicalize "tools/agent-split/src/scripts/agent-split.clj")))

(load-file script)

(defn- ^:needs/git shell!
  [dir & args]
  (let [result (apply process/shell
                      {:dir (str dir)
                       :out :string
                       :err :string
                       :shutdown nil
                       :continue true}
                      args)]
    (is (zero? (:exit result))
        (str "stdout:\n" (:out result) "\nstderr:\n" (:err result)))
    result))

(defn- ^:needs/git run
  [dir & args]
  (apply process/shell
         {:dir (str dir)
          :out :string
          :err :string
          :shutdown nil
          :continue true}
         args))

(defn- write-file! [path content]
  (fs/create-dirs (fs/parent path))
  (spit (str path) content))

(defn- temp-root []
  (fs/create-temp-dir {:prefix "flower-jj-split-patch"}))

(defn- init-base! [repo]
  ;; A failed producer must never publish a partially prepared common base.
  (let [checked! (fn [result]
                   (when-not (zero? (:exit result))
                     (throw (ex-info "cannot prepare common test base" {:result result})))
                   result)]
    (fs/create-dirs repo)
    (let [init-result (run repo "jj" "git" "init" "--colocate")]
      (when-not (zero? (:exit init-result))
        (checked! (shell! repo "jj" "git" "init"))))
    (write-file! (fs/file repo ".gitignore") "target/\n")
    (write-file! (fs/file repo "note.txt")
                 (str "one\n"
                      "two\n"
                      "three\n"
                      "four\n"
                      "five\n"
                      "six\n"
                      "seven\n"
                      "eight\n"
                      "nine\n"
                      "ten\n"))
    (checked! (run repo "jj" "file" "track" ".gitignore" "note.txt"))
    (checked! (shell! repo "jj" "commit" "-m" "base"))))

(def ^:dynamic *copy-base!* nil)

(use-fixtures :once
  (fn [f]
    (fixture/with-templates {:note init-base!}
      (fn [copy!]
        (binding [*copy-base!* copy!] (f))))))

(defn- init-repo! [repo]
  (*copy-base!* :note repo)
  (write-file! (fs/file repo "note.txt")
               (str "one\n"
                    "TWO\n"
                    "three\n"
                    "four\n"
                    "five\n"
                    "six\n"
                    "seven\n"
                    "eight\n"
                    "nine\n"
                    "TEN\n")))

(defn- init-rename-repo! [repo]
  (fs/create-dirs repo)
  (let [init-result (run repo "jj" "git" "init" "--colocate")]
    (when-not (zero? (:exit init-result))
      (shell! repo "jj" "git" "init")))
  (write-file! (fs/file repo ".gitignore") "target/\n")
  (write-file! (fs/file repo "old.txt") "same\n")
  (write-file! (fs/file repo "note.txt") "before\n")
  (run repo "jj" "file" "track" ".gitignore" "old.txt" "note.txt")
  (shell! repo "jj" "commit" "-m" "base")
  (fs/move (fs/file repo "old.txt") (fs/file repo "new.txt"))
  (write-file! (fs/file repo "note.txt") "after\n"))

(defn- init-new-file-repo! [repo]
  (fs/create-dirs repo)
  (let [init-result (run repo "jj" "git" "init" "--colocate")]
    (when-not (zero? (:exit init-result))
      (shell! repo "jj" "git" "init")))
  (write-file! (fs/file repo ".gitignore") "target/\n")
  (write-file! (fs/file repo "note.txt") "before\n")
  (run repo "jj" "file" "track" ".gitignore" "note.txt")
  (shell! repo "jj" "commit" "-m" "base")
  (write-file! (fs/file repo "added.txt") "selected\n")
  (write-file! (fs/file repo "note.txt") "after\n"))

(defn- init-duplicate-change-repo! [repo]
  (fs/create-dirs repo)
  (let [init-result (run repo "jj" "git" "init" "--colocate")]
    (when-not (zero? (:exit init-result))
      (shell! repo "jj" "git" "init")))
  (write-file! (fs/file repo ".gitignore") "target/\n")
  (write-file! (fs/file repo "note.txt") "first\nold\nmiddle\nold\nlast\n")
  (run repo "jj" "file" "track" ".gitignore" "note.txt")
  (shell! repo "jj" "commit" "-m" "base")
  (write-file! (fs/file repo "note.txt") "first\nnew\nmiddle\nnew\nlast\n"))

(defn- init-deleted-symlink-repo! [repo]
  (fs/create-dirs repo)
  (let [init-result (run repo "jj" "git" "init" "--colocate")]
    (when-not (zero? (:exit init-result))
      (shell! repo "jj" "git" "init")))
  (write-file! (fs/file repo ".gitignore") "target/\n")
  (write-file! (fs/file repo "note.txt") "unchanged\n")
  (fs/create-sym-link (fs/file repo "link") "missing-target")
  (run repo "jj" "file" "track" ".gitignore" "link" "note.txt")
  (shell! repo "jj" "commit" "-m" "base")
  (fs/delete (fs/file repo "link"))
  (write-file! (fs/file repo "note.txt") "remaining\n"))

(def selected-patch
  (str "diff --git a/note.txt b/note.txt\n"
       "--- a/note.txt\n"
       "+++ b/note.txt\n"
       "@@ -1,5 +1,5 @@\n"
       " one\n"
       "-two\n"
       "+TWO\n"
       " three\n"
       " four\n"
       " five\n"))

(defn- with-repo* [f]
  (let [root (temp-root)
        repo (fs/file root "repo")]
    (try
      (init-repo! repo)
      (f {:root root
          :repo repo})
      (finally
        (fs/delete-tree root)))))

(defn- with-rename-repo* [f]
  (let [root (temp-root)
        repo (fs/file root "repo")]
    (try
      (init-rename-repo! repo)
      (f {:root root
          :repo repo})
      (finally
        (fs/delete-tree root)))))

(defn- with-new-file-repo* [f]
  (let [root (temp-root)
        repo (fs/file root "repo")]
    (try
      (init-new-file-repo! repo)
      (f {:root root :repo repo})
      (finally
        (fs/delete-tree root)))))

(defn- with-duplicate-change-repo* [f]
  (let [root (temp-root)
        repo (fs/file root "repo")]
    (try
      (init-duplicate-change-repo! repo)
      (f {:root root :repo repo})
      (finally
        (fs/delete-tree root)))))

(defn- with-deleted-symlink-repo* [f]
  (let [root (temp-root)
        repo (fs/file root "repo")]
    (try
      (init-deleted-symlink-repo! repo)
      (f {:root root
          :repo repo})
      (finally
        (fs/delete-tree root)))))

(defn- run-wrapper-with-args [{:keys [repo]} patch-content & args]
  (let [patch (fs/file repo "target" "jj-split" "selected.patch")]
    (write-file! patch patch-content)
    (apply run repo "env" "-u" "SANDBOX_PROXY_DIR"
           "SANDBOX_PROXY_DEFAULT_DIR=/nonexistent"
           "bb" script (concat args [(str patch) "-m" "selected"]))))

(defn- run-wrapper [ctx patch-content]
  (run-wrapper-with-args ctx patch-content))

(deftest ^:needs/bb ^:needs/git ^:needs/jj jj-split-patch-preserves-message-paragraphs
  (with-repo*
    (fn [{:keys [repo]}]
      (let [patch (fs/file repo "target" "jj-split" "selected.patch")
            _ (write-file! patch selected-patch)
            result (run repo "env" "-u" "SANDBOX_PROXY_DIR"
                        "SANDBOX_PROXY_DEFAULT_DIR=/nonexistent"
                        "bb" script "--json" (str patch)
                        "-m" "Extract selected change"
                        "-m" "Keep the other hunk separate."
                        "-m" "--json" "@")]
        (is (zero? (:exit result)) (:err result))
        (when (zero? (:exit result))
          (let [{:keys [selected remaining]} (json/parse-string (:out result) true)]
            (is (= "Extract selected change\n\nKeep the other hunk separate.\n\n--json\n"
                   (:out (shell! repo "jj" "log" "-r" selected "--no-graph"
                                 "-T" "description"))))
            (is (= "one\nTWO\nthree\nfour\nfive\nsix\nseven\neight\nnine\nten\n"
                   (:out (shell! repo "jj" "file" "show" "-r" selected "note.txt"))))
            (is (= "one\nTWO\nthree\nfour\nfive\nsix\nseven\neight\nnine\nTEN\n"
                   (:out (shell! repo "jj" "file" "show" "-r" remaining "note.txt"))))))))))

(deftest jj-split-patch-recounts-without-accepting-invented-content
  (doseq [replacement ["TWO" "INVENTED"]]
    (with-repo*
      (fn [{:keys [repo] :as ctx}]
        (let [before (:out (shell! repo "jj" "log" "-r" "@" "--no-graph" "-T" "commit_id"))
              patch (-> selected-patch
                        (str/replace "-1,5 +1,5" "-1,9 +1,2")
                        (str/replace "TWO" replacement))
              result (run-wrapper ctx patch)]
          (if (= replacement "TWO")
            (do
              (is (zero? (:exit result)) (:err result))
              (is (= "one\nTWO\nthree\nfour\nfive\nsix\nseven\neight\nnine\nten\n"
                     (:out (shell! repo "jj" "file" "show" "-r" "@-" "note.txt")))))
            (do
              (is (= 1 (:exit result)))
              (is (str/includes? (:err result) "not contained"))
              (is (= before (:out (shell! repo "jj" "log" "-r" "@" "--no-graph" "-T" "commit_id"))))))
          (is (= "one\nTWO\nthree\nfour\nfive\nsix\nseven\neight\nnine\nTEN\n"
                 (slurp (str (fs/file repo "note.txt"))))))))))

(deftest jj-split-patch-preflight-errors-identify-the-resolved-target-without-mutating-history
  (doseq [options [[] ["--json"]]
          {:keys [patch revision reason diagnostic]}
          [{:patch (str/replace selected-patch "-two" "-obsolete")
            :revision "@" :reason "patch dry-run failed"}
           {:patch (str/replace selected-patch "+TWO" "+INVENTED")
            :revision "@" :reason "not contained"
            :diagnostic "selected base line 2; original edit at base line 2: added lines differ"}
           {:patch selected-patch :revision "@-" :reason "patch dry-run failed"}]]
    (with-repo*
      (fn [{:keys [repo]}]
        (let [patch-file (fs/file repo "target" "jj-split" "selected.patch")
              _ (write-file! patch-file patch)
              before (:out (shell! repo "jj" "log" "-r" "@" "--no-graph" "-T" "commit_id"))
              operation (:out (shell! repo "jj" "op" "log" "--limit" "1" "--no-graph" "-T" "id"))
              commit (:out (shell! repo "jj" "log" "-r" revision "--no-graph" "-T" "commit_id"))
              parents (str/split-lines (:out (shell! repo "jj" "log" "-r" (str "parents(" revision ")")
                                                    "--no-graph" "-T" "commit_id ++ \"\\n\"")))
              result (apply run repo "env" "-u" "SANDBOX_PROXY_DIR"
                            "SANDBOX_PROXY_DEFAULT_DIR=/nonexistent" "bb" script
                            (concat options [(str patch-file) "-m" "selected" revision]))]
          (is (= 1 (:exit result)))
          (is (= "" (:out result)) "failure diagnostics stay on stderr, including in JSON mode")
          (is (str/includes? (:err result) reason) (:err result))
          (when diagnostic (is (str/includes? (:err result) diagnostic) (:err result)))
          (is (str/includes? (:err result) (str "Preflight target: " revision "\n")))
          (is (str/includes? (:err result) (str "Resolved commit: " commit "\n")))
          (doseq [parent parents]
            (is (str/includes? (:err result) parent)))
          (is (str/includes? (:err result) "No split was run."))
          (is (= before (:out (shell! repo "jj" "log" "-r" "@" "--no-graph" "-T" "commit_id"))))
          (is (= operation (:out (shell! repo "jj" "op" "log" "--limit" "1" "--no-graph" "-T" "id"))))
          (is (= "one\nTWO\nthree\nfour\nfive\nsix\nseven\neight\nnine\nTEN\n"
                 (slurp (str (fs/file repo "note.txt"))))))))))

(deftest jj-split-patch-selects-header-like-content
  (with-repo*
    (fn [{:keys [repo] :as ctx}]
      (write-file! (fs/file repo "comment.lua") "-- comment\ncontext\n")
      (shell! repo "jj" "commit" "-m" "comment base")
      (write-file! (fs/file repo "comment.lua") "++ selected\ncontext\n")
      (write-file! (fs/file repo "note.txt") "remaining\n")
      (let [patch (:out (shell! repo "jj" "diff" "--git" "--" "comment.lua"))
            result (run-wrapper ctx patch)]
        (is (zero? (:exit result)) (:err result))
        (is (= "++ selected\ncontext\n"
               (:out (shell! repo "jj" "file" "show" "-r" "@-" "comment.lua"))))
        (is (= "remaining\n" (slurp (str (fs/file repo "note.txt")))))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj jj-split-patch-splits-selected-hunk-and-verifies-remainder
  (with-repo*
    (fn [{:keys [repo] :as ctx}]
      (let [{:keys [exit out err]} (run-wrapper ctx selected-patch)]
        (is (zero? exit)
            (str "stdout:\n" out "\nstderr:\n" err))
        (is (str/includes? out "note.txt (1 hunk)"))
        (is (not (str/includes? out "Selected changes")))
        (is (str/includes? (:out (shell! repo "jj" "diff" "--git" "-r" "@-"))
                           "+TWO"))
        (is (not (str/includes? (:out (shell! repo "jj" "diff" "--git" "-r" "@-"))
                                "+TEN")))
        (is (str/includes? (:out (shell! repo "jj" "diff" "--git" "-r" "@"))
                           "+TEN"))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj jj-split-patch-json-output-is-machine-readable
  (with-repo*
    (fn [{:keys [repo] :as ctx}]
      (let [{:keys [exit out err]} (run-wrapper-with-args ctx selected-patch "--json")
            ids (json/parse-string out true)
            expected-selected (str/trim-newline
                               (:out (shell! repo "jj" "log" "-r" "@-" "--no-graph"
                                             "-T" "change_id.short(32)")))
            expected-remaining (str/trim-newline
                                (:out (shell! repo "jj" "log" "-r" "@" "--no-graph"
                                              "-T" "change_id.short(32)")))]
        (is (zero? exit)
            (str "stdout:\n" out "\nstderr:\n" err))
        (is (= {:selected expected-selected :remaining expected-remaining} ids))
        (is (every? #(= 32 (count %)) (vals ids)))
        (is (str/blank? err))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj jj-split-patch-describes-the-remainder
  (with-repo*
    (fn [{:keys [repo] :as ctx}]
      (let [{:keys [exit out err]} (run-wrapper-with-args
                                     ctx selected-patch "--json"
                                     "--remaining-message" "Keep the other hunk")
            {:keys [selected remaining]} (json/parse-string out true)]
        (is (zero? exit)
            (str "stdout:\n" out "\nstderr:\n" err))
        (is (= "Keep the other hunk"
               (str/trim-newline
                (:out (shell! repo "jj" "log" "-r" remaining "--no-graph"
                              "-T" "description")))))
        (is (= "selected"
               (str/trim-newline
                (:out (shell! repo "jj" "log" "-r" selected "--no-graph"
                              "-T" "description")))))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj jj-split-patch-rejects-an-already-applied-split
  (with-repo*
    (fn [{:keys [repo] :as ctx}]
      (let [first-result (run-wrapper ctx selected-patch)
            selected (str/trim-newline
                      (:out (shell! repo "jj" "log" "-r" "@-" "--no-graph"
                                    "-T" "change_id ++ \"\\n\"")))
            second-result (run repo "env" "-u" "SANDBOX_PROXY_DIR"
                               "SANDBOX_PROXY_DEFAULT_DIR=/nonexistent"
                               "bb" script
                               (str (fs/file repo "target" "jj-split" "selected.patch"))
                               "-m" "selected" selected)]
        (is (zero? (:exit first-result)))
        (is (= 1 (:exit second-result))
            (str "stdout:\n" (:out second-result) "\nstderr:\n" (:err second-result)))
        (is (str/includes? (:err second-result) "already describe revision"))
        (is (str/includes? (:err second-result) "continue with child"))
        (is (str/includes? (:err second-result) (str "Preflight target: " selected "\n")))
        (is (str/includes? (:err second-result)
                           (str "Resolved commit: "
                                (:out (shell! repo "jj" "log" "-r" selected "--no-graph" "-T" "commit_id")) "\n")))
        (is (str/includes? (:err second-result) "No split was run."))
        (is (= 1 (count (str/split-lines
                         (:out (shell! repo "jj" "log" "-r" (str "children(" selected ")")
                                       "--no-graph" "-T" "change_id ++ \"\\n\""))))))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj jj-split-patch-selects-new-file
  (with-new-file-repo*
    (fn [{:keys [repo] :as ctx}]
      (let [patch (:out (shell! repo "jj" "diff" "--git" "--" "added.txt"))
            {:keys [exit out err]} (run-wrapper ctx patch)]
        (is (zero? exit)
            (str "stdout:\n" out "\nstderr:\n" err))
        (is (str/includes? (:out (shell! repo "jj" "diff" "--git" "-r" "@-"))
                           "new file mode"))
        (is (str/includes? (:out (shell! repo "jj" "diff" "--git" "-r" "@"))
                           "+after"))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj jj-split-patch-verifies-duplicate-diff-lines-by-tree
  (with-duplicate-change-repo*
    (fn [{:keys [repo] :as ctx}]
      (let [patch (str "diff --git a/note.txt b/note.txt\n"
                       "--- a/note.txt\n"
                       "+++ b/note.txt\n"
                       "@@ -1,4 +1,4 @@\n"
                       " first\n"
                       "-old\n"
                       "+new\n"
                       " middle\n"
                       " old\n")
            {:keys [exit out err]} (run-wrapper ctx patch)]
        (is (zero? exit)
            (str "stdout:\n" out "\nstderr:\n" err))
        (is (str/includes? (:out (shell! repo "jj" "diff" "--git" "-r" "@"))
                           "-old\n+new"))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj jj-split-patch-selects-pure-rename
  (with-rename-repo*
    (fn [{:keys [repo] :as ctx}]
      (let [patch (:out (shell! repo "jj" "diff" "--git" "--" "old.txt" "new.txt"))
            {:keys [exit out err]} (run-wrapper ctx patch)
            selected (:out (shell! repo "jj" "diff" "--git" "-r" "@-"))
            remaining (:out (shell! repo "jj" "diff" "--git" "-r" "@"))]
        (is (zero? exit)
            (str "stdout:\n" out "\nstderr:\n" err))
        (is (str/includes? selected "rename from old.txt"))
        (is (str/includes? selected "rename to new.txt"))
        (is (not (str/includes? selected "+after")))
        (is (str/includes? remaining "+after"))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj jj-split-patch-selects-deleted-dangling-symlink
  (with-deleted-symlink-repo*
    (fn [{:keys [repo] :as ctx}]
      (let [patch (:out (shell! repo "jj" "diff" "--git" "--" "link"))
            {:keys [exit out err]} (run-wrapper ctx patch)
            selected (:out (shell! repo "jj" "diff" "--git" "-r" "@-"))
            remaining (:out (shell! repo "jj" "diff" "--git" "-r" "@"))]
        (is (zero? exit)
            (str "stdout:\n" out "\nstderr:\n" err))
        (is (str/includes? out "link (1 hunk)"))
        (is (str/includes? selected "deleted file mode 120000"))
        (is (not (str/includes? selected "+remaining")))
        (is (str/includes? remaining "+remaining"))))))

(def wrappers (str (fs/canonicalize "libexec/agent-wrappers")))
(def route-helper (str (fs/canonicalize "tools/jj-proxy/route.py")))

(defn- mounted-proxy-env! [root]
  (let [proxy (fs/file root "proxy")
        socket (fs/file proxy "jj" "socket")
        model-file (fs/file root "pi-model.json")]
    ;; Presence alone activates routing; no proxy connection is allowed for local splits.
    (fs/create-dirs (fs/parent socket))
    ;; Leave a real socket inode after closing its listener. Both consumers discover it,
    ;; but an accidental proxy connection fails rather than hanging the test.
    (shell! root "python3" "-c"
            "import socket,sys; s=socket.socket(socket.AF_UNIX); s.bind(sys.argv[1]); s.close()"
            (str socket))
    (write-file! model-file
                 (json/generate-string {:session_id "agent-split-test-session"
                                        :provider "test" :modelId "agent-split-test-model"}))
    {"PI_MODEL_FILE" (str model-file)
     "PI_MODEL_SESSION_ID" "agent-split-test-session"
     "PATH" (str wrappers ":" (System/getenv "PATH"))
     "BB_REAL" (or (not-empty (System/getenv "DOTFILES_TEST_BB_REAL")) (str (fs/which "bb")))
     "JJ_REAL" (or (not-empty (System/getenv "DOTFILES_TEST_JJ_REAL")) (str (fs/which "jj")))
     "JJ_ROUTE_HELPER" route-helper
     "JJ_AGENT" "pi"
     "SANDBOX_PROXY_DEFAULT_DIR" (str proxy)}))

(defn- run-mounted [repo env & args]
  (apply process/shell {:dir (str repo) :extra-env env
                        :out :string :err :string :shutdown nil :continue true}
         "env" "-u" "SANDBOX_PROXY_DIR" "bb" args))

(deftest ^:needs/bb ^:needs/git ^:needs/jj local-split-with-default-proxy-discovery
  (doseq [configured-helper? [true false]]
    (with-repo*
      (fn [{:keys [root repo]}]
        (let [env (cond-> (mounted-proxy-env! root)
                    (not configured-helper?) (assoc "JJ_ROUTE_HELPER" ""))
            patch (fs/file repo "target/jj-split/selected.patch")
            _ (write-file! patch selected-patch)
            result (run-mounted repo env script "--json" (str patch) "-m" "selected" "@")]
        (is (zero? (:exit result)) (:err result))
        (when (zero? (:exit result))
          (let [{:keys [selected remaining]} (json/parse-string (:out result) true)
                identity (:out (shell! repo "jj" "log" "--ignore-working-copy"
                                       "-r" selected "--no-graph" "-T"
                                       "self.author().name() ++ \"|\" ++ self.author().email() ++ \"|\" ++ self.committer().name() ++ \"|\" ++ self.committer().email()"))]
            (is (= (str "Pi agent-split-test-model|"
                        "325577925+one-esk-nineteen@users.noreply.github.com|"
                        "Pi agent-split-test-model|"
                        "325577925+one-esk-nineteen@users.noreply.github.com")
                   identity))
            (is (str/blank? (:err result)))
            (is (= "one\nTWO\nthree\nfour\nfive\nsix\nseven\neight\nnine\nten\n"
                   (:out (shell! repo "jj" "file" "show" "-r" selected "note.txt"))))
            (is (= (slurp (str (fs/file repo "note.txt")))
                   (:out (shell! repo "jj" "file" "show" "-r" remaining "note.txt")))))))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj mounted-native-verification-failure-keeps-results-and-cleans-up
  (doseq [json? [false true]]
    (with-repo*
      (fn [{:keys [root repo]}]
        (let [helper-temp (fs/file root "helpers")
              _ (fs/create-dirs helper-temp)
              env (assoc (mounted-proxy-env! root) "TMPDIR" (str helper-temp))
              patch (fs/file repo "target/jj-split/selected.patch")
              _ (write-file! patch selected-patch)
              driver (str (fs/canonicalize "tools/agent-split/tests/fixtures/concurrent_split.clj"))
              args (cond-> [(str driver) script "verify-failure" "unrelated" (str patch) "-m" "selected" "@"]
                     json? (conj "--json"))
              result (apply run-mounted repo env args)]
          (is (= 3 (:exit result)) (:err result))
          (is (str/blank? (:out result)))
          (is (str/includes? (:err result) "remainder mismatch: injected loss"))
          (is (str/includes? (:err result) "split left intact; no automatic recovery attempted"))
          (doseq [label ["Selected change: " "Remaining change: "]]
            (is (re-find (re-pattern (str label "[k-z]{32}")) (:err result))))
          (doseq [label ["Selected commit: " "Remaining commit: " "Split input commit: "]]
            (is (re-find (re-pattern (str label "[0-9a-f]{40}")) (:err result))))
          (is (empty? (fs/list-dir helper-temp)))
          (is (= "one\nTWO\nthree\nfour\nfive\nsix\nseven\neight\nnine\nTEN\n"
                 (slurp (fs/file repo "note.txt"))))
          (is (not (str/blank? (:out (shell! repo "jj" "log" "-r" "description(substring:\"selected\")"
                                            "--no-graph" "-T" "commit_id"))))))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj concurrent-unselected-edits-survive-preflight-and-verification
  ;; The writer changes both another file and an unselected hunk in the same
  ;; file. A real JJ snapshot runs on each side of the split boundary.
  (doseq [phase ["before" "after"]]
    (with-repo*
      (fn [{:keys [repo]}]
        (let [patch (fs/file repo "target/jj-split/selected.patch")
              _ (write-file! patch selected-patch)
              driver (str (fs/canonicalize "tools/agent-split/tests/fixtures/concurrent_split.clj"))
              result (run repo "bb" driver script phase "unrelated" (str patch) "--json" "-m" "selected" "@")]
          (is (zero? (:exit result)) (:err result))
          (when (zero? (:exit result))
            (let [{:keys [selected remaining]} (json/parse-string (:out result) true)]
              (is (re-matches #"[k-z]{32}" selected))
              (is (re-matches #"[k-z]{32}" remaining))
              (is (= "one\nTWO\nthree\nfour\nfive\nsix\nseven\neight\nnine\nten\n"
                     (:out (shell! repo "jj" "file" "show" "-r" selected "note.txt"))))
              (is (= "another writer's edit\n" (slurp (str (fs/file repo "other.txt")))))
              (is (= "one\nTWO\nthree\nfour\nfive\nsix\nseven\neight\nnine\nNEW TEN\n"
                     (slurp (str (fs/file repo "note.txt")))))
              (is (= "another writer's edit\n"
                     (:out (shell! repo "jj" "file" "show" "-r" "@" "other.txt"))))
              (when (= phase "before")
                (is (str/includes? (:err result) "concurrent edits observed"))
                (is (= "another writer's edit\n"
                       (:out (shell! repo "jj" "file" "show" "-r" remaining "other.txt"))))))))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj verification-failure-preserves-concurrent-edits-and-reports-both-results
  (with-repo*
    (fn [{:keys [repo]}]
      (let [patch (fs/file repo "target/jj-split/selected.patch")
            _ (write-file! patch selected-patch)
            driver (str (fs/canonicalize "tools/agent-split/tests/fixtures/concurrent_split.clj"))
            result (run repo "bb" driver script "before-failure" "unrelated" (str patch) "--json" "-m" "selected" "@")]
        (is (= 3 (:exit result)) (:err result))
        (is (str/blank? (:out result)) "failure must not emit a success JSON object")
        (is (str/includes? (:err result) "remainder mismatch: injected loss"))
        (is (str/includes? (:err result) "concurrent edits observed; split left intact; no automatic recovery attempted"))
        (doseq [label ["Selected change: " "Remaining change: "]]
          (is (re-find (re-pattern (str label "[k-z]{32}")) (:err result))))
        (doseq [label ["Selected commit: " "Remaining commit: " "Split input commit: "]]
          (is (re-find (re-pattern (str label "[0-9a-f]{40}")) (:err result))))
        (is (= "another writer's edit\n" (slurp (str (fs/file repo "other.txt")))))
        (is (str/includes? (slurp (str (fs/file repo "note.txt"))) "NEW TEN"))
        (is (not (str/blank? (:out (shell! repo "jj" "log" "-r" "description(substring:\"selected\")"
                                          "--no-graph" "-T" "commit_id")))))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj concurrent-selected-source-change-is-rejected-without-losing-the-writer
  (with-repo*
    (fn [{:keys [repo]}]
      (let [patch (fs/file repo "target/jj-split/selected.patch")
            _ (write-file! patch selected-patch)
            driver (str (fs/canonicalize "tools/agent-split/tests/fixtures/concurrent_split.clj"))
            result (run repo "bb" driver script "before" "selected" (str patch) "-m" "selected" "@")]
        (is (= 2 (:exit result)) (:err result))
        (is (str/includes? (:err result) "not contained in original diff"))
        (is (str/includes? (slurp (str (fs/file repo "note.txt"))) "DIFFERENT TWO"))
        (is (str/blank? (:out (shell! repo "jj" "log" "-r" "description(substring:\"selected\")"
                                     "--no-graph" "-T" "commit_id"))))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj protected-structured-split-uses-public-wrapper-and-never-native-recovery
  (with-repo*
    (fn [{:keys [root repo]}]
      (let [env (mounted-proxy-env! root)
            bin (fs/file root "bin")
            calls (fs/file root "jj-calls.jsonl")
            helper-temp (fs/file root "helpers")
            _ (fs/create-dirs helper-temp)
            patch (fs/file repo "target/jj-split/selected.patch")
            _ (write-file! patch selected-patch)
            jj (fs/file bin "jj")
            fixture (str (fs/canonicalize "tools/agent-split/tests/fixtures/structured_jj.py"))
            _ (fs/create-dirs bin)
            _ (shell! root "cp" fixture (str jj))
            _ (shell! root "cmp" fixture (str jj))
            _ (.setExecutable (fs/file jj) true)
            env (assoc env "PATH" (str bin ":" (get env "PATH"))
                       "JJ_PROXY_REPO" (str repo)
                       "STRUCTURED_JJ_WORKSPACE" (str repo)
                       "STRUCTURED_JJ_LOG" (str calls)
                       "TMPDIR" (str helper-temp) "CALLER_MARKER" "preserved")
            message "opaque --message\nsecond paragraph"
            result (run-mounted repo env script (str patch) "-m" message "@")
            requests (map #(json/parse-string % true) (str/split-lines (slurp (str calls))))
            commands (map :args requests)]
        (is (= 2 (:exit result)) (:err result))
        (is (every? #(not-any? (fn [arg] (str/starts-with? arg "--ignore-working-copy")) (:args %))
                    requests))
        (is (every? #(= (:inspect %) (not (#{"status" "--agent-split"} (first (:args %)))))
                    requests)
            "only revision queries carry inspection mode")
        (is (= "status" (ffirst commands)) "one normal initial snapshot precedes queries")
        (is (= ["--agent-split" (str patch) message "@"] (last commands)))
        (is (not-any? #(= "op" (first %)) commands))
        (is (= 1 (count (filter #(= "--agent-split" (first %)) commands))))
        (is (not-any? #(= "split" (first %)) commands))
        (is (empty? (fs/list-dir helper-temp)))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj protected-split-verifies-the-actual-input-and-rejects-changed-selected-source
  ;; Exercise the actual protected shell editor with path relocation only. It
  ;; applies the patch without native containment, so wrapper revalidation is
  ;; required when another writer changes selected source after preflight.
  (doseq [mutation ["unrelated" "selected"]]
    (with-repo*
      (fn [{:keys [root repo]}]
        (let [env (mounted-proxy-env! root)
              bin (fs/file root "bin")
              patch (fs/file repo "target/jj-split/selected.patch")
              calls (fs/file root "jj-calls.jsonl")
              _ (write-file! patch selected-patch)
              jj (fs/file bin "jj")
              fixture (str (fs/canonicalize "tools/agent-split/tests/fixtures/structured_jj.py"))
              editor (fs/file root "protected-editor")
              source (str (fs/canonicalize "tools/jj-proxy/agent-split-editor"))
              _ (fs/create-dirs bin)
              _ (shell! root "cp" fixture (str jj))
              _ (shell! root "cmp" fixture (str jj))
              _ (.setExecutable (fs/file jj) true)
              _ (shell! root "cp" source (str editor))
              _ (shell! root "cmp" source (str editor))
              _ (spit editor (-> (slurp editor)
                                 (str/replace "#!/trusted/bin/sh" "#!/bin/sh")
                                 (str/replace "patch=/tmp/jj-config/agent-split.patch"
                                              (str "patch=" patch))))
              _ (.setExecutable (fs/file editor) true)
              env (assoc env "PATH" (str bin ":" (get env "PATH"))
                         "JJ_PROXY_REPO" (str repo) "STRUCTURED_JJ_WORKSPACE" (str repo)
                         "STRUCTURED_JJ_LOG" (str calls) "CALLER_MARKER" "preserved"
                         "STRUCTURED_JJ_EDITOR" (str editor) "STRUCTURED_JJ_SPLIT_RUN" mutation)
              result (run-mounted repo env script (str patch) "--json" "-m" "selected" "@")
              requests (map #(json/parse-string % true) (str/split-lines (slurp calls)))]
          (is (some #(and (= "evolog" (first (:args %))) (:inspect %)) requests))
          (is (not-any? #(= "op" (first (:args %))) requests) "no native recovery through a proxy")
          (if (= mutation "selected")
            (do
              (is (= 3 (:exit result)) (:err result))
              (is (str/blank? (:out result)))
              (is (str/includes? (:err result) "selected source changed since preflight"))
              (is (str/includes? (:err result) "no automatic recovery attempted"))
              (is (re-find #"Selected change: [k-z]{32}" (:err result)))
              (is (re-find #"Remaining change: [k-z]{32}" (:err result)))
              (is (str/includes? (slurp (fs/file repo "note.txt")) "DIFFERENT TWO")))
            (do
              (is (zero? (:exit result)) (:err result))
              (when (zero? (:exit result))
                (let [{:keys [selected remaining]} (json/parse-string (:out result) true)]
                  (is (str/includes? (:err result) "concurrent edits observed"))
                  (is (= "one\nTWO\nthree\nfour\nfive\nsix\nseven\neight\nnine\nten\n"
                         (:out (shell! repo "jj" "file" "show" "-r" selected "note.txt"))))
                  (is (= "protected writer's edit\n"
                         (:out (shell! repo "jj" "file" "show" "-r" remaining "other.txt")))))))))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj post-split-read-failure-and-late-writer-never-restore-older-history
  ;; The first case fails before concurrency can be inspected. The second
  ;; writer starts after a clean concurrency check, during verification.
  (doseq [phase ["before-read-failure" "during-verify-failure"]]
    (with-repo*
      (fn [{:keys [root repo]}]
        (let [helper-temp (fs/file root "helpers")
              _ (fs/create-dirs helper-temp)
              env (assoc (mounted-proxy-env! root) "TMPDIR" (str helper-temp))
              patch (fs/file repo "target/jj-split/selected.patch")
              _ (write-file! patch selected-patch)
              driver (str (fs/canonicalize "tools/agent-split/tests/fixtures/concurrent_split.clj"))
              result (run-mounted repo env driver script phase "unrelated" (str patch) "-m" "selected" "@")]
          (is (= 3 (:exit result)) (:err result))
          (is (str/includes? (:err result) "split left intact; no automatic recovery attempted"))
          (is (str/includes? (:err result)
                             (if (= phase "before-read-failure")
                               "injected discovery read failure" "remainder mismatch: injected loss")))
          (is (re-find #"Selected change: [k-z]{32}" (:err result)))
          (when (= phase "before-read-failure")
            (is (str/includes? (:err result) "Remaining change: unavailable")))
          (is (= "another writer's edit\n" (slurp (fs/file repo "other.txt"))))
          (is (str/includes? (slurp (fs/file repo "note.txt")) "NEW TEN"))
          (is (= "another writer's edit\n"
                 (:out (shell! repo "jj" "file" "show" "-r" "@" "other.txt"))))
          (is (empty? (fs/list-dir helper-temp))))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj native-materialization-shares-only-its-symlink-source-lookups
  (with-repo*
    (fn [{:keys [root repo]}]
      (let [target (fs/file root "materialized")
            binary [0 -1 -128 13 10]
            links {"first-link" " missing target\n" "second-link" "also-missing"}
            calls (atom [])
            original-shell process/shell
            materialize! (ns-resolve 'scripts.jj-split-patch 'materialize-patch-paths!)]
        (doseq [[path value] links]
          (fs/create-sym-link (fs/file repo path) value))
        (java.nio.file.Files/write (fs/path repo "binary") (byte-array binary)
                                   (make-array java.nio.file.OpenOption 0))
        (write-file! (fs/file repo "run.sh") "#!/bin/sh\n")
        (is (.setExecutable (fs/file repo "run.sh") true false))
        (shell! repo "jj" "status")
        (with-redefs [process/shell
                      (fn [opts & args]
                        (swap! calls conj (vec args))
                        (apply original-shell (assoc opts :dir (str repo)) args))]
          ;; Each materialization still inventories and reads the target revision.
          (materialize! "@" ["first-link" "second-link" "binary" "run.sh"] target))
        (is (= 1 (count (filter #(= ["jj" "git"] (subvec % 0 2)) @calls))))
        (is (= 1 (count (filter #(= ["jj" "log"] (subvec % 0 2)) @calls))))
        (is (= 1 (count (filter #(= ["jj" "file" "--ignore-working-copy" "list"]
                                      (vec (take 4 %))) @calls))))
        (is (<= (count (filter #(and (= "git" (first %)) (= "cat-file" (nth % 2))) @calls)) 2))
        (doseq [[path value] links]
          (is (fs/sym-link? (fs/file target path)))
          (is (= value (str (fs/read-link (fs/file target path))))))
        (is (= binary (vec (java.nio.file.Files/readAllBytes (fs/path target "binary")))))
        (is (= "#!/bin/sh\n" (slurp (fs/file target "run.sh"))))
        (is (fs/executable? (fs/file target "run.sh")))))))

(deftest common-base-builders-publish-only-after-success
  ;; A failed --colocate attempt can still use the existing compatibility fallback.
  (let [published? (atom false)]
    (with-redefs [run (fn [_ & args]
                        {:exit (if (= ["jj" "git" "init" "--colocate"] (vec args)) 1 0)
                         :out "" :err ""})
                  shell! (fn [& _] {:exit 0 :out "" :err ""})]
      (fixture/with-templates {:note init-base!}
        (fn [_] (reset! published? true))))
    (is (true? @published?) "successful fallback can publish a complete base"))
  (doseq [failed-step [:init :track :commit]]
    (let [published? (atom false)
          command (fn [_ & args]
                    {:exit (if (= failed-step
                                  (case (vec (take 3 args))
                                    ["jj" "git" "init"] :init
                                    ["jj" "file" "track"] :track
                                    :commit)) 1 0)
                     :out "" :err "controlled producer failure"})]
      (with-redefs [run command shell! command]
        (is (thrown-with-msg? clojure.lang.ExceptionInfo #"cannot prepare common test base"
                             (fixture/with-templates {:note init-base!}
                               (fn [_] (reset! published? true))))))
      (is (false? @published?) (str failed-step " failure prevents publication")))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj matching-description-does-not-hide-unselected-paths
  (with-repo*
    (fn [{:keys [repo] :as ctx}]
      ;; The selected path already matches the desired selection in full, but
      ;; another changed file means this is not an already-completed split.
      (write-file! (fs/file repo "note.txt")
                   "one\nTWO\nthree\nfour\nfive\nsix\nseven\neight\nnine\nten\n")
      (write-file! (fs/file repo "other.txt") "keep in remainder\n")
      (shell! repo "jj" "describe" "-m" "selected")
      (let [result (run-wrapper-with-args ctx selected-patch "--json")]
        (is (= 0 (:exit result)) (:err result))
        (when (zero? (:exit result))
          (let [{:strs [selected remaining]} (json/parse-string (:out result))]
            (is (= "note.txt\n" (:out (shell! repo "jj" "diff" "-r" selected "--name-only"))))
            (is (= "keep in remainder\n"
                   (:out (shell! repo "jj" "file" "show" "-r" remaining "other.txt"))))))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj unrelated-changes-do-not-add-blob-reads
  ;; Preserve every input byte, but do not fetch unrelated blobs to select note.txt.
  ;; Both new and modified files matter: the latter also exist in the parent.
  (let [reads-per-run (atom [])]
    (doseq [unrelated-count [0 32]]
      (with-repo*
        (fn [{:keys [root repo]}]
          (let [note (slurp (fs/file repo "note.txt"))]
            (write-file! (fs/file repo "note.txt")
                         "one\ntwo\nthree\nfour\nfive\nsix\nseven\neight\nnine\nten\n")
            (doseq [n (range unrelated-count)]
              (write-file! (fs/file repo (str "existing/" n ".txt")) "before\n"))
            (shell! repo "jj" "commit" "-m" "unrelated base")
            (write-file! (fs/file repo "note.txt") note))
          (doseq [n (range unrelated-count)]
            (write-file! (fs/file repo (str "existing/" n ".txt")) "after\n")
            (write-file! (fs/file repo (str "added/" n ".txt")) "new\n"))
          (let [input (str/trim (:out (shell! repo "jj" "log" "-r" "@" "--no-graph" "-T" "commit_id")))
                patch (fs/file repo "target/jj-split/selected.patch")
                log (fs/file root "reads.jsonl")
                driver (str (fs/canonicalize "tools/agent-split/tests/fixtures/record_reads.clj"))
                _ (write-file! patch selected-patch)
                result (run repo "env" "-u" "SANDBOX_PROXY_DIR"
                            "SANDBOX_PROXY_DEFAULT_DIR=/nonexistent"
                            "bb" driver script (str log) "--json" (str patch) "-m" "selected")
                reads (map #(json/parse-string %) (str/split-lines (slurp log)))
                blob-reads (filter #(= ["file" "show"] (vec (take 2 %))) reads)]
            (is (= 0 (:exit result)) (:err result))
            (swap! reads-per-run conj (count blob-reads))
            (is (seq blob-reads) "recording observes actual JJ blob reads")
            (is (every? #(= "note.txt" (last %)) blob-reads)
                "only selected paths cross the per-file read boundary")
            (when (zero? (:exit result))
              (let [{:strs [selected remaining]} (json/parse-string (:out result))]
                (is (= "note.txt\n" (:out (shell! repo "jj" "diff" "-r" selected "--name-only"))))
                (is (= "one\nTWO\nthree\nfour\nfive\nsix\nseven\neight\nnine\nten\n"
                       (:out (shell! repo "jj" "file" "show" "-r" selected "note.txt"))))
                (is (str/blank? (:out (shell! repo "jj" "diff" "--from" input "--to" remaining "--name-only")))
                    "the remainder preserves the entire input tree, including unrelated edits")))))))
    (is (apply = @reads-per-run) "adding unrelated changes does not add per-file reads")))
