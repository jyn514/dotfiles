(ns scripts.agent-split-native-boundary-test
  (:require [babashka.fs :as fs]
            [babashka.process :as process]
            [cheshire.core :as json]
            [clojure.edn :as edn]
            [clojure.string :as str]
            [clojure.test :refer [deftest is testing use-fixtures]]))

(load-file "tools/agent-split/tests/fixtures/repo.clj")
(require '[scripts.agent-split-test-repo :as fixture])

(def script (str (fs/canonicalize "tools/agent-split/src/scripts/agent-split.clj")))
(def scratch (System/getProperty "java.io.tmpdir"))
(def containment-cases
  (edn/read-string (slurp "tools/agent-split/tests/fixtures/containment-cases.edn")))

(defn- representative-cases [kind labels]
  (mapv (fn [label]
          (let [matches (filter #(= label (first %)) (get containment-cases kind))]
            (when-not (= 1 (count matches))
              (throw (ex-info "native representative must exist exactly once"
                              {:kind kind :label label :matches (count matches)})))
            (first matches)))
        labels))

(defn- run [repo & args]
  (apply process/shell {:dir (str repo) :out :string :err :string
                        :continue true :shutdown nil} args))

(defn- checked [repo & args]
  (let [result (apply run repo args)]
    ;; A broken fixture/oracle must be an error, not a misleading product failure.
    (when-not (zero? (:exit result))
      (throw (ex-info "native test command failed" {:args args :result result})))
    (:out result)))

(defn- put! [repo path content]
  (let [file (fs/file repo path)]
    (fs/create-dirs (fs/parent file))
    (if (string? content)
      (spit file content)
      (java.nio.file.Files/write (fs/path file) (byte-array content)
                                 (make-array java.nio.file.OpenOption 0)))))

(defn- executable! [repo path value]
  (when-not (.setExecutable (fs/file repo path) value false)
    (throw (ex-info "cannot set fixture executable bit" {:path path :value value}))))

(defn- bytes [path]
  (vec (java.nio.file.Files/readAllBytes (fs/path path))))

(defn- text-entry [text & [executable?]]
  {:type "file" :executable? (boolean executable?)
   :bytes (vec (.getBytes text "UTF-8"))})

(defn- link-entry [target]
  {:type "symlink" :executable? false :bytes (vec (.getBytes target "UTF-8"))})

(declare commit-id)

(defn- read-blobs [repo objects]
  (if (empty? objects)
    {}
    (let [result (process/shell {:dir (str repo) :in (str (str/join "\n" objects) "\n")
                                 :out :bytes :err :string :continue true :shutdown nil}
                                "git" "cat-file" "--batch")]
      (when-not (zero? (:exit result))
        (throw (ex-info "cannot read revision blobs" {:result result})))
      (with-open [input (java.io.ByteArrayInputStream. (:out result))]
        (let [blobs
              (reduce
               (fn [blobs object]
                 (let [header (loop [chars []]
                                (let [b (.read input)]
                                  (cond
                                    (= -1 b) (throw (ex-info "truncated blob header" {:object object}))
                                    (= 10 b) (apply str chars)
                                    :else (recur (conj chars (char b))))))
                       [_ actual size] (re-matches #"([0-9a-f]+) blob ([0-9]+)" header)]
                   (when-not (= object actual)
                     (throw (ex-info "unexpected blob header" {:object object :header header})))
                   ;; Only headers are text. Git frames arbitrary bytes by their byte count.
                   (let [size (Integer/parseInt size)
                         content (.readNBytes input size)]
                     (when-not (and (= size (alength content)) (= 10 (.read input)))
                       (throw (ex-info "truncated blob contents" {:object object :size size})))
                     (assoc blobs object (vec content)))))
               {} objects)]
          (when-not (= -1 (.read input))
            (throw (ex-info "unexpected trailing blob data" {})))
          blobs)))))

(defn- revision-tree [repo revision]
  ;; Keep the independent Git oracle, but read all blobs in one native process.
  ;; Entries retain separate paths/modes even when their contents share an object ID.
  (let [inventory (checked repo "git" "ls-tree" "-r" "-z" "--full-tree"
                           (commit-id repo revision))
        entries (mapv (fn [entry]
                        (let [[_ mode object path] (re-matches #"([0-9]+) blob ([0-9a-f]+)\t(.*)" entry)]
                          (when-not (#{"100644" "100755" "120000"} mode)
                            (throw (ex-info "unsupported oracle entry" {:entry entry})))
                          {:mode mode :object object :path path}))
                      (remove str/blank? (str/split inventory #"\u0000")))
        blobs (read-blobs repo (map :object entries))]
    (into (sorted-map)
          (for [{:keys [mode object path]} entries]
            [path {:type (if (= "120000" mode) "symlink" "file")
                   :executable? (= "100755" mode)
                   :bytes (get blobs object)}]))))

(defn- working-tree [repo]
  (let [entries (atom (sorted-map))]
    ;; Never follow symlinks, including dangling links and file-kind transitions.
    (fs/walk-file-tree repo
      {:pre-visit-dir (fn [dir _]
                        (if (and (not= (fs/path repo) dir)
                                 (#{".git" ".jj" "target"} (str (fs/relativize repo dir))))
                          :skip-subtree :continue))
       :visit-file (fn [file _]
                     (let [path (str (fs/relativize repo file))
                           link? (fs/sym-link? file)]
                       (swap! entries assoc path
                              (if link?
                                (link-entry (str (fs/read-link file)))
                                {:type "file" :executable? (fs/executable? file)
                                 :bytes (bytes file)})))
                     :continue)})
    @entries))

(defn- commit-id [repo revision]
  (checked repo "jj" "log" "--ignore-working-copy" "-r" revision
           "--no-graph" "-T" "commit_id"))

(defn- operation-id [repo]
  (checked repo "jj" "op" "log" "--ignore-working-copy" "--limit" "1"
           "--no-graph" "-T" "id"))

(def ^:dynamic *copy-base!* nil)

(defn- with-repo
  ([f] (with-repo :empty f))
  ([base f]
   (fs/create-dirs scratch)
   (let [root (fs/create-temp-dir {:dir scratch :prefix "repo-"})]
     (try
       (*copy-base!* base root)
       (f root)
       (finally (fs/delete-tree root))))))

(defn- split! [repo patch revision]
  (let [path (fs/file repo "target" "jj-split" "selection.patch")]
    (put! repo "target/jj-split/selection.patch" patch)
    (let [result (run repo "env" "-u" "SANDBOX_PROXY_DIR"
                      "SANDBOX_PROXY_DEFAULT_DIR=/nonexistent"
                      "bb" script "--json" (str path) "-m" "selected boundary" revision)]
      (is (= patch (slurp path)) "ignored supplied patch is not rewritten or deleted")
      (select-keys result [:exit :out :err]))))

(defn- patch-for [repo revision & paths]
  (apply checked repo "jj" "diff" "--ignore-working-copy" "--git" "-r" revision "--" paths))

(defn- rich-base! [repo]
  (checked repo "jj" "git" "init" "--colocate")
  (put! repo ".gitignore" "target/\n")
  (doseq [[path content] {"alpha.txt" "old\nmiddle\nlast"
                        "run.sh" "#!/bin/sh\necho before\n"
                        "down.sh" "#!/bin/sh\necho stable\n"
                        "removed.txt" "remove me\n"
                        "shape" "regular before\n"
                        "nested/.sentinel" "unchanged\r\n"}]
    (put! repo path content))
  (put! repo "binary.dat" [0 1 -1 10])
  (executable! repo "down.sh" true)
  (fs/create-sym-link (fs/file repo "link") "old-target")
  (fs/create-sym-link (fs/file repo "dangling") "never-created")
  (checked repo "jj" "commit" "-m" "base"))

(use-fixtures :once
  (fn [f]
    (fixture/with-templates
      {:empty (fn [repo]
                (checked repo "jj" "git" "init" "--colocate")
                (put! repo ".gitignore" "target/\n"))
       :rich rich-base!}
      (fn [copy!]
        (binding [*copy-base!* copy!] (f))))))

(defn- rich-fixture! [repo]
  (let [base (revision-tree repo "@-")]
    (put! repo "alpha.txt" "new\nmiddle\nlast")
    (put! repo "run.sh" "#!/bin/sh\necho after\n")
    (executable! repo "run.sh" true)
    (executable! repo "down.sh" false)
    (fs/delete (fs/file repo "removed.txt"))
    (put! repo "added.txt" "unrelated addition\n")
    (put! repo "binary.dat" [0 2 -128 13 10])
    (checked repo "jj" "status")
    base))

(defn- assert-split! [repo patch revision expected-selected]
  (let [before (revision-tree repo revision)
        before-wc (working-tree repo)
        parent (commit-id repo (str "(" revision ")-"))
        result (split! repo patch revision)]
    (is (= 0 (:exit result)) (pr-str result))
    (when (zero? (:exit result))
      (let [{:keys [selected remaining]} (json/parse-string (:out result) true)]
        (is (= expected-selected (revision-tree repo selected)) "exact full selected tree")
        (is (= before (revision-tree repo remaining)) "complete pre-split tree retained")
        (is (= parent (commit-id repo (str "parents(" selected ")"))))
        (is (= (commit-id repo selected)
               (commit-id repo (str "parents(" remaining ")"))))))
    (is (= before-wc (working-tree repo)) "all workspace bytes, kinds and modes unchanged")))

(deftest ^:needs/git ^:needs/jj native-tree-oracle-preserves-generated-bytes-with-constant-process-count
  ;; Git is the producer; independent filesystem bytes/kinds/modes are the oracle.
  ;; Increasing file count must not add a native process for each blob.
  (with-repo
    (fn [repo]
      (put! repo "empty" [])
      (checked repo "jj" "commit" "-m" "small tree")
      (let [measure (fn []
                      (let [calls (atom 0)
                            original process/shell
                            tree (with-redefs [process/shell
                                               (fn [& args]
                                                 (swap! calls inc)
                                                 (apply original args))]
                                   (revision-tree repo "@-"))]
                        (is (= (working-tree repo) tree))
                        @calls))
            small-count (measure)
            random (java.util.Random. 1621)]
        (doseq [size [1 2 7 31 64 257]]
          (put! repo (str "generated-" size)
                (vec (repeatedly size #(- (.nextInt random 256) 128)))))
        (put! repo "all bytes" (vec (range -128 128)))
        (put! repo "same-a" [0 -1 10])
        (put! repo "same-b" [0 -1 10])
        (executable! repo "same-b" true)
        (fs/create-sym-link (fs/file repo "link") " target with spaces\n")
        (checked repo "jj" "commit" "-m" "larger binary tree")
        (is (= small-count (measure)) "native process count is independent of blob count")))))

(deftest ^:needs/git ^:needs/jj native-tree-oracle-rejects-missing-blobs
  (with-repo
    (fn [repo]
      (is (thrown-with-msg? clojure.lang.ExceptionInfo #"unexpected blob header"
                           (read-blobs repo [(apply str (repeat 40 "0"))]))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj native-split-checks-complete-trees-and-filesystem-metadata
  (doseq [selection [:text :content-without-mode :mode-without-content :mode-down
                    :addition :rename :symlink :symlink-addition :symlink-deletion
                    :unselected-symlink-deletion :deletion]]
    (testing (name selection)
      (with-repo :rich
        (fn [repo]
          (let [base (rich-fixture! repo)
                _ (case selection
                    :symlink (do (fs/delete (fs/file repo "link"))
                                 (fs/create-sym-link (fs/file repo "link") "new-target"))
                    :symlink-addition (fs/create-sym-link (fs/file repo "new-link") " target with spaces\n")
                    :symlink-deletion (fs/delete (fs/file repo "link"))
                    :unselected-symlink-deletion (fs/delete (fs/file repo "link"))
                    :rename (put! repo "renamed.txt" "remove me\n")
                    nil)
                _ (checked repo "jj" "status")
                [patch expected]
                (case selection
                  :text [(patch-for repo "@" "alpha.txt")
                         (assoc base "alpha.txt" (text-entry "new\nmiddle\nlast"))]
                  :content-without-mode [(-> (patch-for repo "@" "run.sh")
                                            (str/replace "old mode 100644\nnew mode 100755\n" ""))
                                         (assoc base "run.sh" (text-entry "#!/bin/sh\necho after\n"))]
                  :mode-without-content [(str "diff --git a/run.sh b/run.sh\n"
                                             "old mode 100644\nnew mode 100755\n")
                                        (assoc-in base ["run.sh" :executable?] true)]
                  :mode-down [(patch-for repo "@" "down.sh")
                              (assoc-in base ["down.sh" :executable?] false)]
                  :addition [(patch-for repo "@" "added.txt")
                             (assoc base "added.txt" (text-entry "unrelated addition\n"))]
                  :rename [(patch-for repo "@" "removed.txt" "renamed.txt")
                           (-> base (dissoc "removed.txt")
                               (assoc "renamed.txt" (text-entry "remove me\n")))]
                  :symlink [(patch-for repo "@" "link")
                            (assoc base "link" (link-entry "new-target"))]
                  :symlink-addition [(patch-for repo "@" "new-link")
                                     (assoc base "new-link" (link-entry " target with spaces\n"))]
                  :symlink-deletion [(patch-for repo "@" "link") (dissoc base "link")]
                  :unselected-symlink-deletion [(patch-for repo "@" "alpha.txt")
                                                (assoc base "alpha.txt" (text-entry "new\nmiddle\nlast"))]
                  :deletion [(patch-for repo "@" "removed.txt")
                             (dissoc base "removed.txt")])]
            (assert-split! repo patch "@" expected)))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj native-split-ancestor-does-not-select-working-copy-changes
  (with-repo :rich
    (fn [repo]
      (let [base (rich-fixture! repo)
            expected (assoc base "alpha.txt" (text-entry "new\nmiddle\nlast"))]
        (checked repo "jj" "commit" "-m" "revision to split")
        (let [revision (commit-id repo "@-")
              patch (patch-for repo revision "alpha.txt")]
          (put! repo "alpha.txt" "descendant workspace edit\n")
          (put! repo "workspace-only.txt" [0 -1 3])
          (executable! repo "workspace-only.txt" true)
          (checked repo "jj" "status")
          (let [wc-before (revision-tree repo "@")]
            (assert-split! repo patch revision expected)
            (is (= wc-before (revision-tree repo "@")) "rebased descendant retains its entire tree")))))))

(defn- assert-rejected! [repo patch revision]
  ;; Snapshot first: rejection may legitimately perform the documented initial
  ;; snapshot, but must not mutate an already-snapshotted operation/history.
  (checked repo "jj" "status")
  (let [before-tree (revision-tree repo revision)
        before-wc (working-tree repo)
        before-commit (commit-id repo revision)
        before-op (operation-id repo)
        result (split! repo patch revision)]
    (is (= 1 (:exit result)) (pr-str result))
    (is (= before-tree (revision-tree repo revision)) "rejected selection keeps revision tree")
    (is (= before-commit (commit-id repo revision)) "rejected selection keeps commit identity")
    (is (= before-op (operation-id repo)) "preflight rejection never splits history")
    (is (= before-wc (working-tree repo)) "rejected selection keeps filesystem bytes/kinds/modes")
    result))

(deftest ^:needs/bb ^:needs/git ^:needs/jj native-preflight-explains-zero-context-without-relaxing-rejection
  ;; Removing the diagnostic loses the reported recovery action; guessing from
  ;; hunk headers falsely labels stale patches. Normal contextual edits stay valid.
  (doseq [selection [:zero-context :stale-zero-context :wrong-context :with-context]]
    (testing (name selection)
      (with-repo
        (fn [repo]
          (put! repo "note.txt" "one\ntwo\nthree\nfour\nfive\n")
          (put! repo "other.txt" "unselected base\n")
          (checked repo "jj" "commit" "-m" "base")
          (let [base (revision-tree repo "@-")
                zero-context (str "diff --git a/note.txt b/note.txt\n"
                                  "--- a/note.txt\n+++ b/note.txt\n"
                                  "@@ -2 +2 @@\n-two\n+TWO\n")
                contextual (str "diff --git a/note.txt b/note.txt\n"
                                "--- a/note.txt\n+++ b/note.txt\n"
                                "@@ -1,3 +1,3 @@\n one\n-two\n+TWO\n three\n")
                patch (case selection
                        :zero-context zero-context
                        :stale-zero-context (str/replace zero-context "-two\n" "-not-in-base\n")
                        :wrong-context (str/replace contextual " one\n" " wrong\n")
                        :with-context contextual)]
            (put! repo "note.txt" "one\nTWO\nthree\nfour\nfive\n")
            (put! repo "other.txt" "unselected change\n")
            (checked repo "jj" "status")
            (if (= selection :with-context)
              (assert-split! repo patch "@"
                             (assoc base "note.txt" (text-entry "one\nTWO\nthree\nfour\nfive\n")))
              (let [result (assert-rejected! repo patch "@")
                    error (:err result)]
                (is (str/blank? (:out result)) "failure leaves JSON result output empty")
                (is (str/includes? error "patch dry-run failed"))
                (is (= (= selection :zero-context)
                       (str/includes? error "Git accepts this patch only with --unidiff-zero")))
                (is (str/includes? error "jj diff --git -r <revision>"))
                (is (str/includes? error "unchanged context from the revision's parent"))
                (is (str/includes? error "No split was run."))))))))))

(def duplicate-base "first\nold\nmiddle\nold\nlast\n")
(def wrong-occurrence-patch
  (str "diff --git a/note.txt b/note.txt\n--- a/note.txt\n+++ b/note.txt\n"
       "@@ -3,3 +3,3 @@\n middle\n-old\n+new\n last\n"))
(def extra-occurrence-patch
  (str "diff --git a/note.txt b/note.txt\n--- a/note.txt\n+++ b/note.txt\n"
       "@@ -1,5 +1,5 @@\n first\n-old\n+new\n middle\n-old\n+new\n last\n"))

(deftest ^:needs/bb ^:needs/git ^:needs/jj native-selects-either-legitimate-duplicate-occurrence-exactly
  ;; Positive controls for occurrence-sensitive containment: fixing the negative
  ;; cases must not prohibit selecting just one of two identical real edits.
  (doseq [[patch selected-text]
          [[(str "diff --git a/note.txt b/note.txt\n--- a/note.txt\n+++ b/note.txt\n"
                 "@@ -1,4 +1,4 @@\n first\n-old\n+new\n middle\n old\n")
            "first\nnew\nmiddle\nold\nlast\n"]
           [wrong-occurrence-patch "first\nold\nmiddle\nnew\nlast\n"]]]
    (with-repo
      (fn [repo]
        (put! repo "note.txt" duplicate-base)
        (put! repo "other.txt" "unselected base\n")
        (checked repo "jj" "commit" "-m" "base")
        (let [base (revision-tree repo "@-")]
          (put! repo "note.txt" "first\nnew\nmiddle\nnew\nlast\n")
          (put! repo "other.txt" "unselected change\n")
          (checked repo "jj" "status")
          (assert-split! repo patch "@" (assoc base "note.txt" (text-entry selected-text))))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj native-rejects-edits-at-unchanged-duplicate-occurrences
  (doseq [patch [wrong-occurrence-patch extra-occurrence-patch]]
    (with-repo
      (fn [repo]
        (put! repo "note.txt" duplicate-base)
        (checked repo "jj" "commit" "-m" "base")
        ;; Only the first occurrence belongs to this revision. The identical
        ;; second occurrence is unchanged, not permission to invent another edit.
        (put! repo "note.txt" "first\nnew\nmiddle\nold\nlast\n")
        (assert-rejected! repo patch "@")))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj native-rejects-invented-terminal-newline
  (with-repo
    (fn [repo]
      (put! repo "note.txt" "before")
      (checked repo "jj" "commit" "-m" "base without newline")
      (put! repo "note.txt" "after")
      (put! repo "other.txt" "remaining\n")
      ;; The added text is real, but the final newline is not. Containment must
      ;; include newline markers, not only sets of +/- lines.
      (assert-rejected! repo
                        (str "diff --git a/note.txt b/note.txt\n"
                             "--- a/note.txt\n+++ b/note.txt\n@@ -1 +1 @@\n"
                             "-before\n\\ No newline at end of file\n+after\n")
                        "@"))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj native-rejects-working-copy-content-not-in-targeted-ancestor
  (with-repo
    (fn [repo]
      (put! repo "note.txt" "before\n")
      (checked repo "jj" "commit" "-m" "base")
      (put! repo "note.txt" "ancestor change\n")
      (put! repo "other.txt" "unselected ancestor change\n")
      (checked repo "jj" "commit" "-m" "ancestor")
      (let [revision (commit-id repo "@-")
            patch (str/replace (patch-for repo revision "note.txt")
                               "+ancestor change" "+workspace only")]
        (put! repo "note.txt" "workspace only\n")
        (assert-rejected! repo patch revision)))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj native-rejects-stale-and-out-of-revision-selections
  (doseq [invalid [:invented-content :invented-mode :unchanged-path :nonapplying-context :wrong-revision]]
    (testing (name invalid)
      (with-repo :rich
        (fn [repo]
          (rich-fixture! repo)
          (let [patch (case invalid
                        :invented-content (str/replace (patch-for repo "@" "alpha.txt") "+new" "+invented")
                        :invented-mode (str "diff --git a/alpha.txt b/alpha.txt\n"
                                            "old mode 100644\nnew mode 100755\n")
                        :unchanged-path (str "diff --git a/dangling b/dangling\n"
                                             "deleted file mode 120000\n--- a/dangling\n+++ /dev/null\n"
                                             "@@ -1 +0,0 @@\n-never-created\n\\ No newline at end of file\n")
                        :nonapplying-context (str/replace (patch-for repo "@" "alpha.txt") " middle" " nonexistent")
                        :wrong-revision (patch-for repo "@" "alpha.txt"))
                revision (if (= invalid :wrong-revision)
                           (do
                             (checked repo "jj" "commit" "-m" "earlier change")
                             (put! repo "added.txt" "different revision\n")
                             "@")
                           "@")]
            (assert-rejected! repo patch revision)))))))

(defn- model-patch! [repo path base selected]
  ;; Separate filesystem models produce native Git input, not a candidate parser
  ;; or JJ materializer. nil means absence; contents may be text or raw bytes.
  (doseq [side ["a" "b"]] (fs/create-dirs (fs/file repo "target/models" side)))
  (when (some? base) (put! repo (str "target/models/a/" path) base))
  (when (some? selected) (put! repo (str "target/models/b/" path) selected))
  (let [result (run (fs/file repo "target/models") "git" "diff" "--no-index"
                    "--binary" "--no-renames" "--" "a" "b")]
    (when-not (= 1 (:exit result))
      (throw (ex-info "model patch must be nonempty" result)))
    (-> (:out result)
        (str/replace #"(?m)^diff --git a/[ab]/(.+) b/[ab]/(.+)$" "diff --git a/$1 b/$2")
        (str/replace #"(?m)^--- a/[ab]/" "--- a/")
        (str/replace #"(?m)^\+\+\+ b/[ab]/" "+++ b/"))))

(defn- text-patch! [repo base selected]
  (model-patch! repo "note.txt" base selected))

(deftest ^:needs/bb ^:needs/git ^:needs/jj native-base-coordinate-and-multiplicity-decision-table
  ;; Representative CLI/publication boundaries; containment-test runs every
  ;; authored case in-process with real Git-produced canonical diffs.
  (doseq [[label base original attempt valid?]
          (representative-cases :text [:non-prefix-addition :cross-paired :earlier-insertion
                                       :whole-replacement-tail :partial-unequal-cross-paired
                                       :whole-replacement-invented-addition
                                       :section-deletion-blank-alignment
                                       :blank-boundary-addition-cross-pair
                                       :blank-boundary-unrelated-occurrence
                                       :rotation-insertion-left
                                       :rotation-blank-insertion-left
                                       :rotation-deletion-left
                                       :rotation-crlf-insertion
                                       :rotation-no-final-newline
                                       :rotation-multiple-independent
                                       :rotation-extra-duplicate
                                       :rotation-and-cross-paired-replacement])]
    (testing (name label)
      (with-repo
        (fn [repo]
          (put! repo "note.txt" base)
          (put! repo "sentinel" "unchanged\n")
          (checked repo "jj" "commit" "-m" "base")
          (let [base-tree (revision-tree repo "@-")
                patch (text-patch! repo base attempt)]
            (put! repo "note.txt" original)
            (put! repo "other.txt" "unselected\n")
            (checked repo "jj" "status")
            (if valid?
              (assert-split! repo patch "@" (assoc base-tree "note.txt" (text-entry attempt)))
              (assert-rejected! repo patch "@"))))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj native-jj-kind-conversion-encoding-rejects-without-publication
  ;; Compatibility boundary, not a requirements decision: these JJ encodings
  ;; are rejected by Git apply. Do not turn this into a success expectation or
  ;; invent an alternate parser merely to make the fixture pass.
  (doseq [direction [:file-to-link :link-to-file]]
    (testing (name direction)
      (with-repo
        (fn [repo]
          (if (= direction :file-to-link)
            (put! repo "shape" "regular before\n")
            (fs/create-sym-link (fs/file repo "shape") "absent-before"))
          (checked repo "jj" "commit" "-m" "base")
          (fs/delete (fs/file repo "shape"))
          (if (= direction :file-to-link)
            (fs/create-sym-link (fs/file repo "shape") "absent-after")
            (put! repo "shape" "regular after\n"))
          (put! repo "other.txt" "unselected\n")
          (checked repo "jj" "status")
          (let [patch (patch-for repo "@" "shape")
                result (assert-rejected! repo patch "@")]
            (is (str/includes? patch "old mode ") "JJ emitted its conversion encoding")
            (is (str/includes? patch "new mode "))
            (is (str/includes? (:err result) "patch dry-run failed"))
            (is (str/includes? (:err result) "does not match old mode"))))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj native-whole-binary-selections-require-canonical-blob-equality
  (doseq [[label base original attempt valid?]
          (representative-cases :binary [:modification :invented-modification])]
    (testing (name label)
      (with-repo
        (fn [repo]
          (put! repo "note.txt" "base\n")
          (when (some? base) (put! repo "binary" base))
          (checked repo "jj" "commit" "-m" "base")
          (let [base-tree (revision-tree repo "@-")
                patch (model-patch! repo "binary" base attempt)]
            (put! repo "note.txt" "unselected real edit\n")
            (if (some? original)
              (put! repo "binary" original)
              (when (fs/exists? (fs/file repo "binary")) (fs/delete (fs/file repo "binary"))))
            (checked repo "jj" "status")
            (is (str/includes? patch "GIT binary patch"))
            (if valid?
              (assert-split! repo patch "@"
                             (if (nil? attempt)
                               (dissoc base-tree "binary")
                               (assoc base-tree "binary"
                                      {:type "file" :executable? false :bytes attempt})))
              (assert-rejected! repo patch "@"))))))))

(deftest ^:needs/bb ^:needs/git ^:needs/jj native-malformed-utf8-cannot-alias-a-replacement-character
  (with-repo
    (fn [repo]
      (put! repo "note.txt" "old\n")
      (checked repo "jj" "commit" "-m" "base")
      (let [patch (text-patch! repo "old\n" "�new\n")]
        ;; No NUL: Git emits a text diff, so a lossy :out :string decoder used
        ;; to authorize U+FFFD bytes that never existed in the revision.
        (put! repo "note.txt" [-1 110 101 119 10])
        (put! repo "other" "unselected\n")
        (checked repo "jj" "status")
        (is (= [-1 110 101 119 10] (get-in (revision-tree repo "@") ["note.txt" :bytes])))
        (let [result (assert-rejected! repo patch "@")]
          (is (str/includes? (:err result) "canonical diff contains non-UTF-8 text")))))))

(deftest ^:needs/git ^:needs/jj copied-repositories-own-working-copies-history-and-config
  ;; A tempting hard-link/clone/workspace shortcut can share mutable state.
  ;; Derive expectations from a sibling, not template filenames or JJ internals;
  ;; distinct valid edits must both work and never leak into siblings/future cases.
  (with-repo :rich
    (fn [first]
      (with-repo :rich
        (fn [sibling]
          (let [tree (working-tree sibling)
                commit (commit-id sibling "@")
                operation (operation-id sibling)
                config (checked sibling "jj" "config" "get" "user.name")]
            (is (= (str (fs/canonicalize first))
                   (str/trim (checked first "jj" "root"))))
            (is (= (str (fs/canonicalize first))
                   (str/trim (checked first "jj" "workspace" "list" "-T" "root"))))
            (is (= (str (fs/canonicalize (fs/file first ".git")))
                   (str/trim (checked first "jj" "git" "root"))
                   (str/trim (checked first "git" "rev-parse" "--absolute-git-dir"))))
            (checked first "jj" "config" "set" "--repo" "user.name" "Independent fixture")
            (checked first "git" "config" "--local" "fixture.marker" "first-only")
            (doseq [content ["independent edit\n" "a different valid edit\n"]]
              (put! first "alpha.txt" content)
              (checked first "jj" "commit" "-m" content))
            (put! first "binary.dat" [-128 0 7])
            (executable! first "down.sh" false)
            (fs/delete (fs/file first "dangling"))
            (fs/create-sym-link (fs/file first "dangling") "different-missing-target")
            (checked first "jj" "bookmark" "create" "first-only" "-r" "@-")
            (checked first "jj" "status")
            (is (not= commit (commit-id first "@")))
            (is (= "a different valid edit\n"
                   (checked first "jj" "file" "show" "-r" "@-" "alpha.txt")))
            (is (str/blank? (checked sibling "jj" "bookmark" "list")))
            (is (= 1 (:exit (run sibling "git" "config" "--local" "--get" "fixture.marker"))))
            (is (= tree (working-tree sibling)))
            (is (= commit (commit-id sibling "@")))
            (is (= operation (operation-id sibling)))
            (is (= config (checked sibling "jj" "config" "get" "user.name")))
            (with-repo :rich
              (fn [fresh]
                (is (= tree (working-tree fresh)) "published base survives case mutations")
                (is (= commit (commit-id fresh "@")))
                (is (= operation (operation-id fresh)))
                (is (= config (checked fresh "jj" "config" "get" "user.name")))
                (is (= 1 (:exit (run fresh "git" "config" "--local" "--get" "fixture.marker"))))))))))))
