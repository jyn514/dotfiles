(ns scripts.jj-split-patch-test
  (:require [babashka.fs :as fs]
            [clojure.string :as str]
            [clojure.test :refer [deftest is testing]]
            [scripts.temp :as scripts.temp]))

(def script (str (fs/canonicalize "tools/agent-split/src/scripts/agent-split.clj")))
(load-file script)

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

(defn- captured-failure [f]
  (let [err (java.io.StringWriter.)]
    (binding [*err* err]
      (try
        (with-redefs-fn {(ns-resolve (quote scripts.jj-split-patch) (quote *exit!*)) (fn [status]
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
      (is (= tmpdir-root ((ns-resolve (quote scripts.jj-split-patch) (quote git-tool-dir))))))
    (with-redefs [scripts.temp/tmpdir-env (constantly nil)
                  scripts.temp/java-tmpdir (constantly java-root)]
      (is (= java-root ((ns-resolve (quote scripts.jj-split-patch) (quote git-tool-dir))))))))

(deftest jj-split-patch-failure-text-names-step
  (is (= "preflight: stale selected content"
         ((ns-resolve (quote scripts.jj-split-patch) (quote failure-text)) "preflight" "stale selected content"))))

(deftest jj-split-patch-parses-json-output-mode
  (is (= {:patch "selected.patch"
          :message "Extract change"
          :revision "change-id"
          :json? true
          :remaining-message nil}
         ((ns-resolve (quote scripts.jj-split-patch) (quote parse-args))
          ["--json" "selected.patch" "-m" "Extract change" "change-id"]))))

(deftest jj-split-patch-parses-remaining-message
  (is (= "Keep other work"
         (:remaining-message
          ((ns-resolve (quote scripts.jj-split-patch) (quote parse-args))
           ["--remaining-message" "Keep other work"
            "selected.patch" "-m" "Extract change" "change-id"])))))

(deftest jj-split-patch-help-recognition-stops-at-double-dash
  (let [{:keys [exit err]}
        (captured-failure
         #((ns-resolve (quote scripts.jj-split-patch) (quote parse-args))
           ["--" "--help"]))]
    (is (= 1 exit))
    (is (str/includes? err "Usage:"))))

(deftest jj-split-patch-rejects-stale-selected-content-before-split
  (let [original ((ns-resolve (quote scripts.jj-split-patch) (quote diff-change-index))
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
        selected ((ns-resolve (quote scripts.jj-split-patch) (quote diff-change-index)) stale-patch)
        {:keys [exit err]} (captured-failure
                            #((ns-resolve (quote scripts.jj-split-patch) (quote validate-contained!)) original selected))]
    (is (= 1 exit))
    (is (str/includes? err "preflight:"))
    (is (str/includes? err "not contained in original diff"))))

(deftest jj-split-patch-verification-failures-use-distinct-status
  (let [{:keys [exit err]} (captured-failure
                            #((ns-resolve (quote scripts.jj-split-patch) (quote verify-fail!))
                              "tree mismatch"))]
    (is (= 3 exit))
    (is (str/includes? err "verify: tree mismatch"))))

(deftest jj-split-patch-restores-before-reporting-verification-failure
  (let [restore-operation! (ns-resolve (quote scripts.jj-split-patch) (quote restore-operation!))
        recover! (ns-resolve (quote scripts.jj-split-patch) (quote recover-verification-failure!))
        {:keys [exit err]} (captured-failure
                            (fn []
                              (with-redefs-fn {restore-operation! (constantly true)}
                                (fn []
                                  (recover! "operation-id" "tree mismatch")))))]
    (is (= 3 exit))
    (is (str/includes? err "restored operation operation-id"))))

(deftest jj-split-patch-selects-one-commit-from-a-divergent-change
  (let [matching-selected-commit (ns-resolve (quote scripts.jj-split-patch) (quote matching-selected-commit))
        revision-ids (ns-resolve (quote scripts.jj-split-patch) (quote revision-ids))
        revision-description (ns-resolve (quote scripts.jj-split-patch) (quote revision-description))
        parent-commit-ids (ns-resolve (quote scripts.jj-split-patch) (quote parent-commit-ids))
        matches-tree? (ns-resolve (quote scripts.jj-split-patch) (quote revision-matches-selected-tree?))
        result (with-redefs-fn {revision-ids (fn [& _] ["commit-a" "commit-b"])
                                revision-description (constantly "Selected work")
                                parent-commit-ids #(if (= "commit-a" %)
                                                     #{"original-parent"}
                                                     #{"other-parent"})
                                matches-tree? (fn [& _] true)}
                 (fn []
                   (matching-selected-commit {} "change-id" "Selected work"
                                             #{"original-parent"} "helper")))]
    (is (= "commit-a" result))))

(deftest jj-split-patch-verification-rejects-unexpected-selected-paths
  (let [root (fs/create-temp-dir {:prefix "agent-split-verify"})
        expected (fs/file root "expected")
        helper (fs/file root "helper")
        verify! (ns-resolve (quote scripts.jj-split-patch) (quote verify!))
        changed-paths (ns-resolve (quote scripts.jj-split-patch) (quote changed-paths))
        materialize! (ns-resolve (quote scripts.jj-split-patch) (quote materialize-patch-paths!))
        diff-output (ns-resolve (quote scripts.jj-split-patch) (quote diff-output))
        run-command (ns-resolve (quote scripts.jj-split-patch) (quote run))]
    (try
      (fs/create-dirs expected)
      (fs/create-dirs helper)
      (let [result (with-redefs-fn {changed-paths (constantly #{"expected.txt" "invented.txt"})
                                    materialize! (fn [& _])
                                    diff-output (fn [& _] "")
                                    run-command (fn [& _] {:out ""})}
                     (fn []
                       (verify! {:original-paths ["expected.txt"]
                                 :expected-selected-tree expected}
                                "original"
                                {:selected "selected-change"
                                 :remaining "remaining-change"
                                 :selected-revision "selected"
                                 :remaining-revision "remaining"}
                                helper)))]
        (is (str/includes? result "invented.txt")))
      (finally
        (fs/delete-tree root)))))

(deftest jj-split-patch-classifies-patch-artifact-safety
  (let [root (fs/path "/flower-jj-split-patch")
        repo (fs/file root "repo")
        artifact-root (fs/file repo "target" "jj-split")
        helper-root (fs/file artifact-root "helper")]
    (testing "allows target/jj-split artifacts"
      (let [patch (fs/file artifact-root "selected.patch")]
        (is (nil? ((ns-resolve (quote scripts.jj-split-patch) (quote check-snapshot-safety!)) repo artifact-root patch helper-root)))))
    (testing "rejects repository-local patch files"
      (let [patch (fs/file repo "selected.patch")
            {:keys [exit err]} (captured-failure
                                #((ns-resolve (quote scripts.jj-split-patch) (quote check-snapshot-safety!)) repo
                                                                                                             artifact-root
                                                                                                             patch
                                                                                                             helper-root))]
        (is (= 1 exit))
        (is (str/includes? err "snapshot safety:"))
        (is (str/includes? err "patch file is inside the Jujutsu workspace"))))))
