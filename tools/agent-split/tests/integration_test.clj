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
