(ns flower.jj-agent-split-editor-test
  (:require [babashka.fs :as fs]
            [babashka.process :as process]
            [clojure.string :as str]
            [clojure.test :refer [deftest is testing]]))

(def script "tools/agent-split/src/scripts/agent-split-editor")

(defn- write-file! [path content]
  (fs/create-dirs (fs/parent path))
  (spit (str path) content))

(defn- executable! [path]
  (assert (.setExecutable (fs/file path) true false))
  path)

(defn- temp-trees []
  (let [root (fs/create-temp-dir {:prefix "flower-jj-agent-split"})
        left (fs/file root "left")
        right (fs/file root "right")
        patch (fs/file root "selected.patch")]
    (fs/create-dirs left)
    (fs/create-dirs right)
    {:root root
     :left left
     :right right
     :patch patch}))

(defn- run-editor
  ([trees patch-content] (run-editor trees patch-content {}))
  ([{:keys [left right patch]} patch-content {:keys [unset-patch?]}]
   (when patch-content
     (write-file! patch patch-content))
   (apply process/shell
          {:out :string
           :err :string
           :continue true
           :shutdown nil}
          (cond-> ["env"]
            unset-patch? (into ["-u" "JJ_AGENT_SPLIT_PATCH"])
            (not unset-patch?) (conj (str "JJ_AGENT_SPLIT_PATCH=" patch))
            true (into [script (str left) (str right)])))))

(defn- with-trees* [f]
  (let [{:keys [root] :as trees} (temp-trees)]
    (try
      (f trees)
      (finally
        (fs/delete-tree root)))))

(defn- assert-success [{:keys [exit out err]}]
  (is (zero? exit)
      (str "stdout:\n" out "\nstderr:\n" err)))

(defn- assert-failure [{:keys [exit err]} pattern]
  (is (not (zero? exit)))
  (is (re-find pattern err)
      (str "stderr:\n" err)))

(def multi-hunk-base
  (str "one\n"
       "two\n"
       "three\n"
       "four\n"
       "five\n"
       "six\n"
       "seven\n"
       "eight\n"
       "nine\n"
       "ten\n"
       "eleven\n"
       "twelve\n"))

(def multi-hunk-right
  (str "one\n"
       "TWO\n"
       "three\n"
       "four\n"
       "FIVE\n"
       "six\n"
       "seven\n"
       "eight\n"
       "nine\n"
       "TEN\n"
       "eleven\n"
       "twelve\n"))

(def multi-hunk-selected
  (str "one\n"
       "TWO\n"
       "three\n"
       "four\n"
       "five\n"
       "six\n"
       "seven\n"
       "eight\n"
       "nine\n"
       "TEN\n"
       "eleven\n"
       "twelve\n"))

(def multi-hunk-patch
  (str "diff --git a/note.txt b/note.txt\n"
       "--- a/note.txt\n"
       "+++ b/note.txt\n"
       "@@ -1,5 +1,5 @@\n"
       " one\n"
       "-two\n"
       "+TWO\n"
       " three\n"
       " four\n"
       " five\n"
       "@@ -7,6 +7,6 @@ six\n"
       " seven\n"
       " eight\n"
       " nine\n"
       "-ten\n"
       "+TEN\n"
       " eleven\n"
       " twelve\n"))

(deftest split-editor-replaces-right-with-selected-multi-hunk-tree
  (with-trees*
    (fn [{:keys [left right] :as trees}]
      (write-file! (fs/file left "note.txt") multi-hunk-base)
      (write-file! (fs/file right "note.txt") multi-hunk-right)
      (let [result (run-editor trees multi-hunk-patch)]
        (assert-success result)
        (is (str/includes? (:out result) "note.txt"))
        (is (= multi-hunk-selected (slurp (str (fs/file right "note.txt")))))))))

(deftest split-editor-recounts-edited-hunks
  (with-trees*
    (fn [{:keys [left right] :as trees}]
      (write-file! (fs/file left "note.txt") multi-hunk-base)
      (write-file! (fs/file right "note.txt") multi-hunk-right)
      (assert-success (run-editor trees
                                  (str/replace multi-hunk-patch "-1,5 +1,5" "-1,9 +1,2")))
      (is (= multi-hunk-selected (slurp (str (fs/file right "note.txt"))))))))

(deftest split-editor-treats-header-like-lines-as-content
  (doseq [replacement ["++ selected" "++ invented"]]
    (with-trees*
      (fn [{:keys [left right] :as trees}]
        (write-file! (fs/file left "note.txt") "-- comment\ncontext\n")
        (write-file! (fs/file right "note.txt") "++ selected\ncontext\n")
        (let [result (run-editor trees
                                 (str "diff --git a/note.txt b/note.txt\n"
                                      "--- a/note.txt\n+++ b/note.txt\n"
                                      "@@ -1,2 +1,2 @@\n--- comment\n+" replacement
                                      "\n context\n"))]
          (if (= replacement "++ selected")
            (assert-success result)
            (assert-failure result #"not contained|stale"))
          (is (= "++ selected\ncontext\n" (slurp (str (fs/file right "note.txt"))))))))))

(deftest split-editor-fails-clearly-for-missing-and-malformed-patches
  (testing "missing JJ_AGENT_SPLIT_PATCH"
    (with-trees*
      (fn [trees]
        (assert-failure (run-editor trees nil {:unset-patch? true})
                        #"JJ_AGENT_SPLIT_PATCH"))))
  (testing "malformed patch"
    (with-trees*
      (fn [{:keys [left right] :as trees}]
        (write-file! (fs/file left "note.txt") multi-hunk-base)
        (write-file! (fs/file right "note.txt") multi-hunk-right)
        (assert-failure (run-editor trees "not a unified diff\n")
                        #"malformed|apply")))))

(deftest split-editor-rejects-traversal-before-apply
  (testing "parent traversal"
    (with-trees*
      (fn [{:keys [left right] :as trees}]
        (write-file! (fs/file left "note.txt") "base\n")
        (write-file! (fs/file right "note.txt") "right\n")
        (let [patch (str "diff --git a/../outside.txt b/../outside.txt\n"
                         "--- a/../outside.txt\n"
                         "+++ b/../outside.txt\n"
                         "@@ -1 +1 @@\n"
                         "-base\n"
                         "+right\n")
              result (run-editor trees patch)]
          (assert-failure result #"unsafe patch path")
          (is (= "right\n" (slurp (str (fs/file right "note.txt")))))))))
  (testing "absolute path"
    (with-trees*
      (fn [{:keys [left right] :as trees}]
        (write-file! (fs/file left "note.txt") "base\n")
        (write-file! (fs/file right "note.txt") "right\n")
        (let [patch (str "diff --git a//tmp/outside.txt b//tmp/outside.txt\n"
                         "--- a//tmp/outside.txt\n"
                         "+++ b//tmp/outside.txt\n"
                         "@@ -1 +1 @@\n"
                         "-base\n"
                         "+right\n")
              result (run-editor trees patch)]
          (assert-failure result #"unsafe patch path")
          (is (= "right\n" (slurp (str (fs/file right "note.txt"))))))))))
  (testing "rename metadata traversal"
    (with-trees*
      (fn [{:keys [left right] :as trees}]
        (write-file! (fs/file left "old.txt") "same\n")
        (write-file! (fs/file right "new.txt") "same\n")
        (let [patch (str "diff --git a/old.txt b/new.txt\n"
                         "similarity index 100%\n"
                         "rename from old.txt\n"
                         "rename to ../outside.txt\n")]
          (assert-failure (run-editor trees patch) #"unsafe patch path")))))

(deftest split-editor-dry-run-rejects-patches-that-do-not-apply
  (with-trees*
    (fn [{:keys [left right] :as trees}]
      (write-file! (fs/file left "note.txt") "base\n")
      (write-file! (fs/file right "note.txt") "right\n")
      (let [patch (str "diff --git a/note.txt b/note.txt\n"
                       "--- a/note.txt\n"
                       "+++ b/note.txt\n"
                       "@@ -1 +1 @@\n"
                       "-not-base\n"
                       "+right\n")
            result (run-editor trees patch)]
        (assert-failure result #"dry-run failed|note.txt")
        (is (= "right\n" (slurp (str (fs/file right "note.txt")))))))))

(deftest split-editor-rejects-stale-and-out-of-revision-patches
  (testing "stale selected content"
    (with-trees*
      (fn [{:keys [left right] :as trees}]
        (write-file! (fs/file left "note.txt") "base\n")
        (write-file! (fs/file right "note.txt") "right\n")
        (let [patch (str "diff --git a/note.txt b/note.txt\n"
                         "--- a/note.txt\n"
                         "+++ b/note.txt\n"
                         "@@ -1 +1 @@\n"
                         "-base\n"
                         "+invented\n")]
          (assert-failure (run-editor trees patch) #"not contained|stale")))))
  (testing "path not changed by original revision"
    (with-trees*
      (fn [{:keys [left right] :as trees}]
        (write-file! (fs/file left "kept.txt") "same\n")
        (write-file! (fs/file right "kept.txt") "same\n")
        (let [patch (str "diff --git a/new.txt b/new.txt\n"
                         "new file mode 100644\n"
                         "--- /dev/null\n"
                         "+++ b/new.txt\n"
                         "@@ -0,0 +1 @@\n"
                         "+selected\n")]
          (assert-failure (run-editor trees patch) #"not contained|outside"))))))

(deftest split-editor-selects-pure-rename
  (with-trees*
    (fn [{:keys [left right] :as trees}]
      (write-file! (fs/file left "old.txt") "same\n")
      (write-file! (fs/file right "new.txt") "same\n")
      (let [patch (str "diff --git a/old.txt b/new.txt\n"
                       "similarity index 100%\n"
                       "rename from old.txt\n"
                       "rename to new.txt\n")
            result (run-editor trees patch)]
        (assert-success result)
        (is (not (fs/exists? (fs/file right "old.txt"))))
        (is (= "same\n" (slurp (str (fs/file right "new.txt")))))))))

(deftest split-editor-selects-rename-with-content-change
  (with-trees*
    (fn [{:keys [left right] :as trees}]
      (write-file! (fs/file left "old.txt") "before\n")
      (write-file! (fs/file right "new.txt") "after\n")
      (let [patch (str "diff --git a/old.txt b/new.txt\n"
                       "similarity index 50%\n"
                       "rename from old.txt\n"
                       "rename to new.txt\n"
                       "--- a/old.txt\n"
                       "+++ b/new.txt\n"
                       "@@ -1 +1 @@\n"
                       "-before\n"
                       "+after\n")
            result (run-editor trees patch)]
        (assert-success result)
        (is (not (fs/exists? (fs/file right "old.txt"))))
        (is (= "after\n" (slurp (str (fs/file right "new.txt")))))))))

(deftest split-editor-rejects-stale-rename-destination
  (with-trees*
    (fn [{:keys [left right] :as trees}]
      (write-file! (fs/file left "old.txt") "same\n")
      (write-file! (fs/file right "new.txt") "different\n")
      (let [patch (str "diff --git a/old.txt b/new.txt\n"
                       "similarity index 100%\n"
                       "rename from old.txt\n"
                       "rename to new.txt\n")]
        (assert-failure (run-editor trees patch) #"not contained|stale")))))

(deftest split-editor-preserves-executable-bit-selection
  (with-trees*
    (fn [{:keys [left right] :as trees}]
      (write-file! (fs/file left "run.sh") "#!/bin/sh\n")
      (write-file! (fs/file right "run.sh") "#!/bin/sh\n")
      (executable! (fs/file right "run.sh"))
      (let [patch (str "diff --git a/run.sh b/run.sh\n"
                       "old mode 100644\n"
                       "new mode 100755\n")
            result (run-editor trees patch)]
        (assert-success result)
        (is (fs/executable? (fs/file right "run.sh")))))))

(deftest split-editor-preserves-symlink-selection
  (with-trees*
    (fn [{:keys [left right] :as trees}]
      (fs/create-sym-link (fs/file left "link") "old-target")
      (fs/create-sym-link (fs/file right "link") "new-target")
      (let [patch (str "diff --git a/link b/link\n"
                       "index 7784f83..9cfbe09 120000\n"
                       "--- a/link\n"
                       "+++ b/link\n"
                       "@@ -1 +1 @@\n"
                       "-old-target\n"
                       "\\ No newline at end of file\n"
                       "+new-target\n"
                       "\\ No newline at end of file\n")
            result (run-editor trees patch)]
        (assert-success result)
        (is (fs/sym-link? (fs/file right "link")))
        (is (= "new-target" (str (fs/read-link (fs/file right "link")))))))))
