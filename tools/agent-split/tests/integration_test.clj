(ns scripts.jj-split-patch-integration-test
  (:require [babashka.fs :as fs]
            [babashka.process :as process]
            [cheshire.core :as json]
            [clojure.string :as str]
            [clojure.test :refer [deftest is]]))

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

(defn- init-repo! [repo]
  (fs/create-dirs repo)
  (let [init-result (run repo "jj" "git" "init" "--colocate")]
    (when-not (zero? (:exit init-result))
      (shell! repo "jj" "git" "init")))
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
  (run repo "jj" "file" "track" ".gitignore" "note.txt")
  (shell! repo "jj" "commit" "-m" "base")
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

(deftest ^:needs/bb ^:needs/git ^:needs/jj mounted-native-verification-failure-recovers-and-cleans-up
  (doseq [recovery-fails? [false true]]
    (with-repo*
      (fn [{:keys [root repo]}]
        (let [env (mounted-proxy-env! root)
              helper-temp (fs/file root "helpers")
              _ (fs/create-dirs helper-temp)
              env (assoc env "TMPDIR" (str helper-temp))
              patch (fs/file repo "target/jj-split/selected.patch")
              _ (write-file! patch selected-patch)
              _ (shell! repo "jj" "status")
              captured-commit (fs/file root "captured-commit")
              runner (fs/file root "injected.clj")
              _ (write-file! runner
                             (str "(load-file " (pr-str script) ")\n"
                                  "(alter-var-root (ns-resolve 'scripts.jj-split-patch 'script-dir) (constantly (fn [] "
                                  (pr-str (str (fs/parent script))) ")))\n"
                                  "(let [v (ns-resolve 'scripts.jj-split-patch 'current-operation-id) original @v] "
                                  "(alter-var-root v (constantly (fn [route] (spit " (pr-str (str captured-commit))
                                  " ((ns-resolve 'scripts.jj-split-patch 'revision-commit-id) \"@\")) (original route)))))\n"
                                  "(alter-var-root (ns-resolve 'scripts.jj-split-patch 'verify!) "
                                  "(constantly (fn [& _] \"injected tree mismatch\")))\n"
                                  (when recovery-fails?
                                    "(alter-var-root (ns-resolve 'scripts.jj-split-patch 'restore-operation!) (constantly (fn [& _] (throw (Exception. \"injected recovery failure\")))))\n")
                                  "(scripts.jj-split-patch/main *command-line-args*)\n"))
              result (run-mounted repo env (str runner) (str patch) "-m" "selected" "@")]
          (is (= 3 (:exit result)) (:err result))
          (is (str/includes? (:err result) "injected tree mismatch"))
          (is (empty? (fs/list-dir helper-temp)))
          (if recovery-fails?
            (is (str/includes? (:err result) "automatic recovery was unavailable"))
            (do
              (is (str/includes? (:err result) "restored operation"))
              (is (= (slurp (str captured-commit))
                     (:out (shell! repo "jj" "log" "--ignore-working-copy"
                                   "-r" "@" "--no-graph" "-T" "commit_id")))))))))))

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
            commands (map #(json/parse-string %) (str/split-lines (slurp (str calls))))]
        (is (= 2 (:exit result)) (:err result))
        (is (= ["--agent-split" (str patch) message "@"] (last commands)))
        (is (not-any? #(= "op" (first %)) commands))
        (is (= 1 (count (filter #(= "--agent-split" (first %)) commands))))
        (is (not-any? #(= "split" (first %)) commands))
        (is (empty? (fs/list-dir helper-temp)))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj mounted-native-post-split-launch-failures-recover
  (doseq [failure-command ["log" "diff"]
          recovery-fails? [false true]]
    (with-repo*
      (fn [{:keys [root repo]}]
        (let [helper-temp (fs/file root "helpers")
              _ (fs/create-dirs helper-temp)
              env (assoc (mounted-proxy-env! root) "TMPDIR" (str helper-temp))
              patch (fs/file repo "target/jj-split/selected.patch")
              _ (write-file! patch selected-patch)
              captured-commit (fs/file root "captured-commit")
              captured-operation (fs/file root "captured-operation")
              commands-file (fs/file root "commands.jsonl")
              missing-verification (str (fs/file root "unavailable-verification-executable"))
              missing-recovery (str (fs/file root "unavailable-recovery-executable"))
              runner (fs/file root "launch-failure.clj")
              _ (write-file! runner
                  (str "(load-file " (pr-str script) ")\n"
                       "(require '[babashka.process :as process] '[cheshire.core :as json])\n"
                       "(def split-completed? (atom false))\n"
                       "(def injected? (atom false))\n"
                       "(alter-var-root (ns-resolve 'scripts.jj-split-patch 'script-dir) "
                       "(constantly (fn [] " (pr-str (str (fs/parent script))) ")))\n"
                       "(let [v (ns-resolve 'scripts.jj-split-patch 'current-operation-id) original @v] "
                       "(alter-var-root v (constantly (fn [route] "
                       "(spit " (pr-str (str captured-commit))
                       " ((ns-resolve 'scripts.jj-split-patch 'revision-commit-id) \"@\")) "
                       "(let [op (original route)] (spit " (pr-str (str captured-operation)) " op) op)))))\n"
                       "(let [v (ns-resolve 'scripts.jj-split-patch 'run-split!) original @v] "
                       "(alter-var-root v (constantly (fn [& args] "
                       "(apply original args) (reset! split-completed? true)))))\n"
                       "(alter-var-root #'process/shell "
                       "(fn [original] (fn [opts & argv] "
                       "(spit " (pr-str (str commands-file))
                       " (str (json/generate-string {:opts (select-keys opts [:dir]) :argv argv}) \"\\n\") :append true) "
                       "(cond "
                       "(and @split-completed? (= [\"jj\" " (pr-str failure-command)
                       "] (vec (take 2 argv))) (compare-and-set! injected? false true)) "
                       "(apply original opts " (pr-str missing-verification) " (rest argv)) "
                       (when recovery-fails?
                         (str "(= [\"jj\" \"op\" \"restore\"] (vec (take 3 argv))) "
                              "(apply original opts " (pr-str missing-recovery) " (rest argv)) "))
                       ":else (apply original opts argv)))))\n"
                       "(scripts.jj-split-patch/main *command-line-args*)\n"))
              result (run-mounted repo env (str runner) (str patch) "-m" "selected" "@")
              commands (map #(json/parse-string % true)
                            (str/split-lines (slurp (str commands-file))))
              op (slurp (str captured-operation))
              recovery (filter #(= ["jj" "op" "restore"] (take 3 (:argv %))) commands)]
          (is (= 3 (:exit result)) (:err result))
          (is (str/includes? (:err result) missing-verification))
          (is (not (str/includes? (:err result) missing-recovery)))
          (is (= 1 (count recovery)))
          (is (= {:dir (str repo)} (:opts (first recovery))))
          (is (= ["jj" "op" "restore" op] (:argv (first recovery))))
          (is (not-any? #(= ["jj" "--agent-split"] (take 2 (:argv %))) commands))
          (is (empty? (fs/list-dir helper-temp)))
          (if recovery-fails?
            (is (str/includes? (:err result) (str "jj op restore " op " to recover")))
            (do
              (is (str/includes? (:err result) (str "restored operation " op)))
              (is (= (slurp (str captured-commit))
                     (:out (shell! repo "jj" "log" "--ignore-working-copy" "-r" "@"
                                   "--no-graph" "-T" "commit_id"))))
              (is (= "one\nTWO\nthree\nfour\nfive\nsix\nseven\neight\nnine\nTEN\n"
                     (:out (shell! repo "jj" "file" "show" "--ignore-working-copy"
                                   "-r" "@" "note.txt")))))))))))
