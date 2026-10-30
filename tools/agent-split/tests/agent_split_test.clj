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

(deftest help-explains-numbered-discovery-and-patch-fallback
  (let [help (with-out-str ((ns-resolve 'scripts.jj-split-patch 'print-help!)))]
    (doseq [topic ["agent-split list" "Whole-hunk workflow:"
                   "full immutable source commit ID printed by list"
                   "without renumbering global hunk IDs"
                   "patch file for partial hunks"
                   "unsupported changes by path and kind"
                   "list prints the source commit and complete hunk catalog"
                   "split prints full selected and remaining change IDs"]]
      (is (str/includes? help topic) topic))))

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

(deftest verification-failures-leave-history-intact-even-when-concurrency-is-unknown
  (let [report! (ns-resolve 'scripts.jj-split-patch 'report-verification-failure!)
        result-var (ns-resolve 'scripts.jj-split-patch '*split-result*)]
    (doseq [concurrent? [nil false true]]
      (let [result (with-redefs-fn
                     {#'babashka.process/shell
                      (fn [& _] (throw (Exception. "failure reporting must not mutate history")))}
                     #(with-bindings {result-var (atom {:selected "selected-id"
                                                        :concurrent-edits? concurrent?})}
                        (captured-failure (fn [] (report! "original-op" "tree mismatch")))))]
        (is (= 3 (:exit result)))
        (is (str/includes? (:err result) "tree mismatch"))
        (is (str/includes? (:err result) "split left intact; no automatic recovery attempted"))
        (is (str/includes? (:err result) "Preflight operation: original-op"))
        (is (str/includes? (:err result) "Selected change: selected-id"))
        (is (str/includes? (:err result) "Remaining change: unavailable"))
        (is (= (true? concurrent?)
               (str/includes? (:err result) "concurrent edits observed")))))))

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
                       (verify! {:selected-paths ["expected.txt"]
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

(deftest verification-diagnostics-distinguish-selected-and-remainder-mismatches
  (let [root (fs/create-temp-dir {:prefix "agent-split-diagnostics"})
        expected (fs/file root "expected")
        verify! (ns-resolve 'scripts.jj-split-patch 'verify!)
        changed-paths (ns-resolve 'scripts.jj-split-patch 'changed-paths)
        materialize! (ns-resolve 'scripts.jj-split-patch 'materialize-patch-paths!)
        read! (ns-resolve 'scripts.jj-split-patch 'run-jj-read)]
    (try
      (fs/create-dirs expected)
      (spit (fs/file expected "note.txt") "wanted\n")
      (doseq [[kind diagnostic] [[:selected "selected patch mismatch"]
                                 [:remaining "remainder mismatch"]
                                 [:clean nil]]]
        (let [helper (fs/file root (name kind))
              _ (fs/create-dirs helper)
              result (with-redefs-fn
                       {changed-paths (constantly #{"note.txt"})
                        materialize! (fn [_ _ target]
                                       (spit (fs/file target "note.txt")
                                             (if (= kind :selected) "wrong\n" "wanted\n")))
                        read! (fn [& _] {:out (if (= kind :remaining) "note.txt\n" "")})}
                       #(verify! {:selected-paths ["note.txt"] :expected-selected-tree expected}
                                 "input" {:selected-revision "selected" :remaining-revision "remaining"}
                                 helper))]
          (if diagnostic
            (is (str/starts-with? result diagnostic))
            (is (nil? result)))))
      (finally (fs/delete-tree root)))))

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

(deftest split-and-operation-inspection-use-the-resolved-backend-not-socket-presence
  (let [calls (atom [])
        shell (fn [opts & args] (swap! calls conj [opts (vec args)]) {:exit 0 :out "op-id"})
        run-read (ns-resolve 'scripts.jj-split-patch 'run-jj-read)
        capture (ns-resolve 'scripts.jj-split-patch 'current-operation-id)
        split (ns-resolve 'scripts.jj-split-patch 'run-split!)
        native {:backend "native" :workspace "/tmp/independent"}
        proxy {:backend "proxy" :workspace "/src/protected"}]
    (with-redefs-fn {#'babashka.process/shell shell
                    run-read (fn [& args] (swap! calls conj args) {:out "op-id"})
                    (ns-resolve 'scripts.jj-split-patch 'sandbox-proxy-dir) (constantly "/mounted")}
      (fn []
        (is (= "op-id" (capture native)))
        (split native "/patch" "message" "@")
        (is (nil? (capture proxy)))
        (split proxy "/opaque -R patch" "--message" "--revision")))
    (is (= {:dir "/tmp/independent"} (second (first @calls))))
    (is (= ["jj" "--agent-split" "/opaque -R patch" "--message" "--revision"]
           (second (last @calls))))))

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

(deftest proxy-post-split-exceptions-retain-the-original-diagnostic
  (let [capture (ns-resolve 'scripts.jj-split-patch 'capture-failure)
        report! (ns-resolve 'scripts.jj-split-patch 'report-verification-failure!)
        original (capture #(throw (java.io.IOException. "proxy verification launch failed")) true)
        calls (atom [])
        result (with-redefs-fn {#'babashka.process/shell (fn [& args] (swap! calls conj args))}
                 #(captured-failure (fn [] (report! nil (:error original)))))]
    (is (= 3 (:exit result)))
    (is (str/includes? (:err result) "proxy verification launch failed"))
    (is (str/includes? (:err result) "no automatic recovery attempted"))
    (is (empty? @calls))))

(deftest revision-read-dispatch-keeps-inspection-scoped-to-proxy-queries
  (let [calls (atom [])
        run-command (ns-resolve 'scripts.jj-split-patch 'run)
        read-command (ns-resolve 'scripts.jj-split-patch 'run-jj-read)
        backend (ns-resolve 'scripts.jj-split-patch '*read-backend*)
        snapshot (ns-resolve 'scripts.jj-split-patch 'snapshot-workspace!)
        describe (ns-resolve 'scripts.jj-split-patch 'describe-revision!)]
    (with-redefs-fn {run-command (fn [& args] (swap! calls conj args) {:out ""})}
      (fn []
        (doseq [route ["native" "proxy"]]
          (with-bindings {backend route}
            (read-command "preflight" "log" "-r" "@")
            (read-command "preflight" {:out "tree" :extra-env {"MARKER" "kept"}}
                          "file" "show" "-r" "@-" "note.txt")))
        (with-bindings {backend "proxy"}
          (snapshot)
          (describe "remaining" "message"))))
    (is (= '("preflight" "jj" "log" "--ignore-working-copy" "-r" "@") (nth @calls 0)))
    (is (= '("preflight" {:out "tree" :extra-env {"MARKER" "kept"}}
                        "jj" "file" "--ignore-working-copy" "show" "-r" "@-" "note.txt")
           (nth @calls 1)))
    (is (= '("preflight" {:extra-env {"JJ_PROXY_INSPECT" "1"}}
                        "jj" "log" "-r" "@") (nth @calls 2)))
    (is (= '("preflight" {:out "tree" :extra-env {"MARKER" "kept" "JJ_PROXY_INSPECT" "1"}}
                        "jj" "file" "show" "-r" "@-" "note.txt") (nth @calls 3)))
    (is (= '("snapshot safety" "jj" "status" "--no-pager") (nth @calls 4)))
    (is (= '("verify" "jj" "describe" "-r" "remaining" "--message=message") (nth @calls 5)))))

(deftest ^:needs/git preflight-copies-the-parent-once-with-independent-bytes-modes-and-links
  (let [root (fs/create-temp-dir {:prefix "agent-split-parent-copy"})
        materialize! (ns-resolve 'scripts.jj-split-patch 'materialize-patch-paths!)
        preflight! (ns-resolve 'scripts.jj-split-patch 'preflight!)
        calls (atom [])
        patch (str "diff --git a/note.txt b/note.txt\n--- a/note.txt\n+++ b/note.txt\n"
                   "@@ -1 +1 @@\n-before\n+after\n")
        raw-bytes [0 -1 -128 13 10]
        link-target " target with spaces\n"]
    (try
      (with-redefs-fn
        {materialize! (fn [revision _ target]
                        ;; Negative control: the old third materialization fails.
                        (when (some #{revision} @calls)
                          (throw (ex-info "parent tree was redundantly read" {:revision revision})))
                        (swap! calls conj revision)
                        (fs/create-dirs (fs/file target "nested"))
                        (spit (fs/file target "note.txt")
                              (if (= revision "(revision)-") "before\n" "after\n"))
                        (java.nio.file.Files/write (fs/path target "binary") (byte-array raw-bytes)
                                                   (make-array java.nio.file.OpenOption 0))
                        (spit (fs/file target "nested/run.sh") "#!/bin/sh\n")
                        (is (.setExecutable (fs/file target "nested/run.sh") true false))
                        (fs/create-sym-link (fs/file target "link") link-target)
                        (fs/create-sym-link (fs/file target "dangling") "never-created"))}
        (fn []
          (let [result (preflight! patch "revision" root)
                selected (:expected-selected-tree result)
                left (fs/file root "left")]
            (is (= ["(revision)-" "revision"] @calls))
            (is (= "after\n" (slurp (fs/file selected "note.txt"))))
            (is (= "before\n" (slurp (fs/file left "note.txt"))) "patch application never changes the parent")
            (doseq [tree [left selected]]
              (is (= raw-bytes (vec (java.nio.file.Files/readAllBytes (fs/path tree "binary"))))))
            (is (= "#!/bin/sh\n" (slurp (fs/file selected "nested/run.sh"))))
            (is (fs/executable? (fs/file selected "nested/run.sh")))
            (is (fs/sym-link? (fs/file selected "link")))
            (is (= link-target (str (fs/read-link (fs/file selected "link")))))
            (is (fs/sym-link? (fs/file selected "dangling")))
            (is (= "never-created" (str (fs/read-link (fs/file selected "dangling")))))
            ;; Copies must not share mutable file storage (e.g. hard links).
            (spit (fs/file selected "binary") "changed independently")
            (is (= raw-bytes (vec (java.nio.file.Files/readAllBytes (fs/path left "binary"))))))))
      (finally (fs/delete-tree root)))))

(deftest symlink-source-lookups-are-lazy-and-local-to-each-materialization
  (let [root (fs/create-temp-dir {:prefix "agent-split-link-lookups"})
        materialize! (ns-resolve 'scripts.jj-split-patch 'materialize-patch-paths!)
        reads (atom [])
        blobs (atom [])
        targets {"first" " leading target\n" "second" "missing-target"}]
    (try
      (with-redefs-fn
        {(ns-resolve 'scripts.jj-split-patch 'tree-entry-index)
         (constantly {"first" {:type "symlink"} "second" {:type "symlink"}})
         (ns-resolve 'scripts.jj-split-patch 'run-jj-read)
         (fn [_ & args]
           (swap! reads conj (vec args))
           {:out (case (first args) "git" "/git-store\n" "log" "immutable-commit\n")})
         (ns-resolve 'scripts.jj-split-patch 'run)
         (fn [_ & args]
           (swap! blobs conj (vec args))
           {:out (get targets (subs (last args) (count "immutable-commit:")))})}
        (fn []
          (materialize! "revision" ["absent"] (fs/file root "empty"))
          (is (empty? @reads) "no Git-root or commit lookup without selected symlinks")
          (doseq [directory ["before" "verification"]]
            (materialize! "revision" ["first" "second"] (fs/file root directory))
            (doseq [[path target] targets]
              (is (= target (str (fs/read-link (fs/file root directory path)))))))
          (is (= [["git" "root"] ["log" "-r" "revision" "--no-graph" "-T" "commit_id"]
                  ["git" "root"] ["log" "-r" "revision" "--no-graph" "-T" "commit_id"]]
                 @reads)
              "two metadata queries per materialization, not per symlink or persistent across verification")
          (is (= 4 (count @blobs)))
          (is (every? #(= ["git" "--git-dir=/git-store" "cat-file" "blob"] (subvec % 0 4)) @blobs))))
      (finally (fs/delete-tree root)))))

(deftest numbered-selector-preserves-every-selected-payload-in-catalog-order
  ;; Exhaust every subset of a bounded catalog, reversing caller order. The
  ;; authored payloads include deletion/addition/context and newline framing.
  (let [select! (ns-resolve 'scripts.jj-split-patch 'select-hunks!)
        hunks (mapv (fn [id] {:id id :path (if (< id 4) "a" "b")
                              :text (str "@@ -" id ",1 +" id ",1 @@\n-old " id
                                         "\n+new " id "\n\\ No newline at end of file\n")})
                    (range 1 7))]
    (doseq [mask (range 1 64)]
      (let [selected (filterv #(bit-test mask (dec (:id %))) hunks)
            patch (select! {:hunks hunks} (str/join "," (reverse (map :id selected))))]
        (is (= (count (distinct (map :path selected)))
               (count (re-seq #"(?m)^diff --git " patch))))
        (doseq [hunk hunks]
          (is (= (contains? (set selected) hunk) (str/includes? patch (:text hunk)))))))))
