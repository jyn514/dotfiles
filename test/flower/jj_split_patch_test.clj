(ns flower.jj-split-patch-test
  (:require [babashka.fs :as fs]
            [babashka.process :as process]
            [clojure.string :as str]
            [clojure.test :refer [deftest is testing]]
            [scripts.temp :as scripts.temp]))

(def script (str (fs/canonicalize "src/scripts/jj_split_patch.clj")))
(load-file script)

(def git-tool-dir (ns-resolve 'scripts.jj-split-patch 'git-tool-dir))
(def exit!* (ns-resolve 'scripts.jj-split-patch '*exit!*))
(def failure-text (ns-resolve 'scripts.jj-split-patch 'failure-text))
(def diff-change-index (ns-resolve 'scripts.jj-split-patch 'diff-change-index))
(def validate-contained! (ns-resolve 'scripts.jj-split-patch 'validate-contained!))
(def check-snapshot-safety! (ns-resolve 'scripts.jj-split-patch 'check-snapshot-safety!))

(defn- shell!
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

(defn- run
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

(def stale-patch
  (str "diff --git a/note.txt b/note.txt\n"
       "--- a/note.txt\n"
       "+++ b/note.txt\n"
       "@@ -1,5 +1,5 @@\n"
       " one\n"
       "-two\n"
       "+invented\n"
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

(defn- run-wrapper [{:keys [repo]} patch-content]
  (let [patch (fs/file repo "target" "jj-split" "selected.patch")]
    (write-file! patch patch-content)
    (run repo "bb" script (str patch) "-m" "selected")))

(defn- captured-failure [f]
  (let [err (java.io.StringWriter.)]
    (binding [*err* err]
      (try
        (with-redefs-fn {exit!* (fn [status]
                                  (throw (ex-info "script exited"
                                                  {:exit status})))}
          f)
        nil
        (catch clojure.lang.ExceptionInfo ex
          {:exit (:exit (ex-data ex))
           :err (str err)})))))

(deftest jj-split-patch-git-tool-dir-uses-shared-temp-root
  (let [tmpdir-root (str (fs/file (scripts.temp/temp-root)
                                  (str "flower-jj-split-tmpdir-" (random-uuid))))
        java-root (str (fs/file (scripts.temp/temp-root)
                                (str "flower-jj-split-java-" (random-uuid))))]
    (with-redefs [scripts.temp/tmpdir-env (constantly tmpdir-root)
                  scripts.temp/java-tmpdir (constantly java-root)]
      (is (= tmpdir-root (git-tool-dir))))
    (with-redefs [scripts.temp/tmpdir-env (constantly nil)
                  scripts.temp/java-tmpdir (constantly java-root)]
      (is (= java-root (git-tool-dir))))))

(deftest jj-split-patch-splits-selected-hunk-and-verifies-remainder
  (with-repo*
    (fn [{:keys [repo] :as ctx}]
      (let [{:keys [exit out err]} (run-wrapper ctx selected-patch)]
        (is (zero? exit)
            (str "stdout:\n" out "\nstderr:\n" err))
        (is (str/includes? out "note.txt (1 hunk)"))
        (is (str/includes? (:out (shell! repo "jj" "diff" "--git" "-r" "@-"))
                           "+TWO"))
        (is (not (str/includes? (:out (shell! repo "jj" "diff" "--git" "-r" "@-"))
                                "+TEN")))
        (is (str/includes? (:out (shell! repo "jj" "diff" "--git" "-r" "@"))
                           "+TEN"))))))

(deftest jj-split-patch-failure-text-names-step
  (is (= "preflight: stale selected content"
         (failure-text "preflight" "stale selected content"))))

(deftest jj-split-patch-rejects-stale-selected-content-before-split
  (let [original (diff-change-index
                  (str "diff --git a/note.txt b/note.txt\n"
                       "--- a/note.txt\n"
                       "+++ b/note.txt\n"
                       "@@ -1,5 +1,5 @@\n"
                       " one\n"
                       "-two\n"
                       "+TWO\n"
                       " three\n"
                       "@@ -8,3 +8,3 @@\n"
                       " eight\n"
                       "-ten\n"
                       "+TEN\n"))
        selected (diff-change-index stale-patch)
        {:keys [exit err]} (captured-failure
                            #(validate-contained! original selected))]
    (is (= 1 exit))
    (is (str/includes? err "preflight:"))
    (is (str/includes? err "not contained in original diff"))))

(deftest jj-split-patch-classifies-patch-artifact-safety
  (let [root (temp-root)
        repo (fs/file root "repo")
        artifact-root (fs/file repo "target" "jj-split")
        helper-root (fs/file artifact-root "helper")]
    (try
      (testing "allows target/jj-split artifacts"
        (let [patch (fs/file artifact-root "selected.patch")]
          (is (nil? (check-snapshot-safety! repo artifact-root patch helper-root)))))
      (testing "rejects repository-local patch files"
        (let [patch (fs/file repo "selected.patch")
              {:keys [exit err]} (captured-failure
                                  #(check-snapshot-safety! repo
                                                           artifact-root
                                                           patch
                                                           helper-root))]
          (is (= 1 exit))
          (is (str/includes? err "snapshot safety:"))
          (is (str/includes? err "patch file is inside the Jujutsu workspace"))))
      (finally
        (fs/delete-tree root)))))
