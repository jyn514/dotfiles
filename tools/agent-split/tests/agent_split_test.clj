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

(deftest jj-split-patch-snapshots-before-ignoring-the-working-copy
  (let [run-command (ns-resolve (quote scripts.jj-split-patch) (quote run))
        run-jj-read (ns-resolve (quote scripts.jj-split-patch) (quote run-jj-read))
        snapshot-workspace! (ns-resolve (quote scripts.jj-split-patch) (quote snapshot-workspace!))
        calls (atom [])]
    (with-redefs-fn {run-command (fn [& args]
                                   (swap! calls conj args)
                                   {:out ""})}
      (fn []
        (snapshot-workspace!)
        (run-jj-read "preflight" "log" "-r" "@")
        (run-jj-read "preflight" {:out "tree.txt"} "file" "show" "-r" "@-" "note.txt")))
    (is (= '(("snapshot safety" "jj" "status" "--no-pager")
             ("preflight" "jj" "log" "--ignore-working-copy" "-r" "@")
             ("preflight" {:out "tree.txt"} "jj" "file" "--ignore-working-copy"
              "show" "-r" "@-" "note.txt"))
           @calls))))

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

(deftest jj-split-patch-joins-message-paragraphs
  (let [parse-args (ns-resolve 'scripts.jj-split-patch 'parse-args)]
    (doseq [revision [nil "change-id"]]
      (let [args (cond-> ["selected.patch" "-m" "Subject"
                         "-m" "First paragraph" "-m" "Second paragraph"]
                   revision (conj revision))
            result (parse-args args)]
        (is (= "Subject\n\nFirst paragraph\n\nSecond paragraph" (:message result)))
        (is (= (or revision "@") (:revision result)))))))

(deftest jj-split-patch-keeps-message-values-literal
  (let [result ((ns-resolve 'scripts.jj-split-patch 'parse-args)
                ["selected.patch" "-m" "--json" "-m" "--remaining-message"
                 "-m" "--" "-m" "--help"])]
    (is (= "--json\n\n--remaining-message\n\n--\n\n--help" (:message result)))
    (is (false? (:json? result)))
    (is (nil? (:remaining-message result)))))

(deftest jj-split-patch-rejects-incomplete-message-paragraphs
  (doseq [args [["selected.patch" "-m"]
               ["selected.patch" "-m" "Subject" "-m"]
               ["selected.patch" "-m" "Subject" "revision" "extra"]]]
    (let [{:keys [exit err]}
          (captured-failure #((ns-resolve 'scripts.jj-split-patch 'parse-args) args))]
      (is (= 1 exit))
      (is (str/includes? err "Usage:")))))

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
                                  (recover! {:backend "native" :workspace "/repo"} "operation-id" "tree mismatch")))))]
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

(deftest split-route-checks-the-consumer-contract
  (let [check (ns-resolve 'scripts.jj-split-patch 'checked-route)
        valid {:backend "native" :workspace "/tmp/repo" :destination nil
               :command ["split"] :hooks true}]
    (is (= valid (check (cheshire.core/generate-string valid))))
    (doseq [route [(assoc valid :backend "fallback")
                   (assoc valid :workspace "relative")
                   (assoc valid :destination 3)
                   (assoc valid :command [3])
                   (assoc valid :hooks "true")
                   (dissoc valid :workspace)]]
      (is (= 1 (:exit (captured-failure #(check (cheshire.core/generate-string route)))))))
    (doseq [text ["not JSON" "" "   "
                  (str (cheshire.core/generate-string valid) "\n" (cheshire.core/generate-string valid))
                  (str (cheshire.core/generate-string valid) " trailing garbage")]]
      (is (= 1 (:exit (captured-failure #(check text))))))))

(deftest ordinary-host-split-does-not-need-the-sandbox-helper
  (with-redefs-fn {(ns-resolve 'scripts.jj-split-patch 'sandbox-proxy-dir) (constantly nil)
                  (ns-resolve 'scripts.jj-split-patch 'run) (fn [& _] (throw (Exception. "helper invoked")))}
    #(is (= "native" (:backend ((ns-resolve 'scripts.jj-split-patch 'split-route)))))))

(deftest split-and-recovery-use-the-resolved-backend-not-socket-presence
  (let [calls (atom [])
        shell (fn [opts & args] (swap! calls conj [opts (vec args)]) {:exit 0 :out "op-id"})
        run-read (ns-resolve 'scripts.jj-split-patch 'run-jj-read)
        capture (ns-resolve 'scripts.jj-split-patch 'current-operation-id)
        restore (ns-resolve 'scripts.jj-split-patch 'restore-operation!)
        split (ns-resolve 'scripts.jj-split-patch 'run-split!)
        native {:backend "native" :workspace "/tmp/independent"}
        proxy {:backend "proxy" :workspace "/src/protected"}]
    (with-redefs-fn {#'babashka.process/shell shell
                    run-read (fn [& args] (swap! calls conj args) {:out "op-id"})
                    (ns-resolve 'scripts.jj-split-patch 'sandbox-proxy-dir) (constantly "/mounted")}
      (fn []
        (is (= "op-id" (capture native)))
        (is (true? (restore native "op-id")))
        (split native "/patch" "message" "@")
        (is (nil? (capture proxy)))
        (is (nil? (restore proxy "op-id")))
        (split proxy "/opaque -R patch" "--message" "--revision")))
    (is (= {:dir "/tmp/independent"} (second (first @calls))))
    (is (= "/tmp/independent" (:dir (first (second @calls)))))
    (is (= ["jj" "op" "restore" "op-id"] (second (second @calls))))
    (is (= ["jj" "--agent-split" "/opaque -R patch" "--message" "--revision"]
           (second (last @calls))))))

(deftest recovery-launch-failure-preserves-the-original-diagnostic
  (let [route {:backend "native" :workspace "/tmp/repo"}
        result (with-redefs-fn {#'babashka.process/shell (fn [& _] (throw (Exception. "recovery launch failed")))}
                 #(captured-failure
                   (fn [] ((ns-resolve 'scripts.jj-split-patch 'recover-verification-failure!)
                           route "original-op" "original tree mismatch"))))]
    (is (= 3 (:exit result)))
    (is (str/includes? (:err result) "original tree mismatch"))
    (is (str/includes? (:err result) "jj op restore original-op"))))

(deftest unexpected-exceptions-are-captured-only-after-mutation
  (let [capture (ns-resolve 'scripts.jj-split-patch 'capture-failure)
        fail #(do (binding [*out* *err*] (println "verification dispatch"))
                  (throw (java.io.IOException. "unavailable verification executable")))
        result (capture fail true)]
    (is (= 3 (:status result)))
    (is (str/includes? (:error result) "verification dispatch"))
    (is (str/includes? (:error result) "java.io.IOException: unavailable verification executable"))
    (is (thrown? java.io.IOException (capture fail)))
    (is (str/includes? (:error (capture #(throw (ex-info "discovery failed" {})) true))
                       "discovery failed"))))

(deftest proxy-post-split-exceptions-never-attempt-local-operation-recovery
  (let [capture (ns-resolve 'scripts.jj-split-patch 'capture-failure)
        recover (ns-resolve 'scripts.jj-split-patch 'recover-verification-failure!)
        original (capture #(throw (java.io.IOException. "proxy verification launch failed")) true)
        calls (atom [])
        result (with-redefs-fn {#'babashka.process/shell (fn [& args]
                                                        (swap! calls conj args)
                                                        (throw (Exception. "native recovery forbidden")))}
                 #(captured-failure
                   (fn [] (recover {:backend "proxy" :workspace "/protected"}
                                   nil (:error original)))))]
    (is (= 3 (:exit result)))
    (is (str/includes? (:err result) "proxy verification launch failed"))
    (is (str/includes? (:err result) "automatic recovery was unavailable"))
    (is (empty? @calls))))
