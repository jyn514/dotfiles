(ns flower.jj-split-patch-test
  (:require [babashka.fs :as fs]
            [babashka.process :as process]
            [clojure.string :as str]
            [clojure.test :refer [deftest is testing]]))

(def script (str (fs/canonicalize "src/scripts/jj_split_patch.clj")))

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
  (run repo "jj" "file" "track" "note.txt")
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
        repo (fs/file root "repo")
        artifacts (fs/file root "artifacts")]
    (try
      (fs/create-dirs artifacts)
      (init-repo! repo)
      (f {:root root
          :repo repo
          :artifacts artifacts})
      (finally
        (fs/delete-tree root)))))

(defn- run-wrapper [{:keys [repo artifacts]} patch-content]
  (let [patch (fs/file artifacts "selected.patch")]
    (write-file! patch patch-content)
    (run repo "bb" script (str patch) "-m" "selected")))

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

(deftest jj-split-patch-names-failing-step-before-changing-history
  (testing "preflight rejects stale selected content"
    (with-repo*
      (fn [{:keys [repo] :as ctx}]
        (let [{:keys [exit err]} (run-wrapper ctx stale-patch)]
          (is (not (zero? exit)))
          (is (str/includes? err "preflight:"))
          (is (str/includes? (:out (shell! repo "jj" "diff" "--git" "-r" "@"))
                             "+TEN"))))))
  (testing "snapshot safety rejects repository-local patch files"
    (with-repo*
      (fn [{:keys [repo]}]
        (let [patch (fs/file repo "selected.patch")]
          (write-file! patch selected-patch)
          (let [{:keys [exit err]} (run repo "bb" script (str patch) "-m" "selected")]
            (is (not (zero? exit)))
            (is (str/includes? err "snapshot safety:"))))))))
