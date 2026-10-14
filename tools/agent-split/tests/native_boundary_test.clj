(ns scripts.agent-split-native-boundary-test
  (:require [babashka.fs :as fs]
            [babashka.process :as process]
            [cheshire.core :as json]
            [clojure.string :as str]
            [clojure.test :refer [deftest is testing]]))

(def script (str (fs/canonicalize "tools/agent-split/src/scripts/agent-split.clj")))
(def scratch (System/getProperty "java.io.tmpdir"))

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

(defn- revision-tree [repo revision]
  ;; Read the colocated Git object store, not production's JJ materialization or
  ;; diff parser. JJ file show does not return symlink targets on this JJ version.
  ;; NUL-delimited paths and raw blob bytes also preserve binary/non-UTF-8 data.
  (let [inventory (checked repo "git" "ls-tree" "-r" "-z" "--full-tree"
                           (commit-id repo revision))]
    (into (sorted-map)
          (for [entry (remove str/blank? (str/split inventory #"\u0000"))
                :let [[_ mode object path] (re-matches #"([0-9]+) blob ([0-9a-f]+)\t(.*)" entry)
                      _ (when-not (#{"100644" "100755" "120000"} mode)
                          (throw (ex-info "unsupported oracle entry" {:entry entry})))
                      result (process/shell {:dir (str repo) :out :bytes :err :string
                                             :continue true :shutdown nil}
                                            "git" "cat-file" "blob" object)]]
            (do
              (when-not (zero? (:exit result))
                (throw (ex-info "cannot read revision blob" {:path path :result result})))
              [path {:type (if (= "120000" mode) "symlink" "file")
                     :executable? (= "100755" mode)
                     :bytes (vec (:out result))}])))))

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

(defn- with-repo [f]
  (fs/create-dirs scratch)
  (let [root (fs/create-temp-dir {:dir scratch :prefix "repo-"})]
    (try
      (checked root "jj" "git" "init" "--colocate")
      (put! root ".gitignore" "target/\n")
      (f root)
      (finally (fs/delete-tree root)))))

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

(defn- rich-fixture! [repo]
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
  (checked repo "jj" "commit" "-m" "base")
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

(deftest ^:needs/bb ^:needs/git ^:needs/jj native-split-checks-complete-trees-and-filesystem-metadata
  (doseq [selection [:text :content-without-mode :mode-without-content :mode-down
                    :addition :rename :symlink :symlink-addition :symlink-deletion
                    :unselected-symlink-deletion :deletion]]
    (testing (name selection)
      (with-repo
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
  (with-repo
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
      (with-repo
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
  ;; Realistic regressions: line-string sets, bags without anchors, anchoring to
  ;; shifted right coordinates, unpaired additions, and trimming CR/newlines.
  ;; Valid changes allowed: independently selecting adjacent identical edits,
  ;; context/hunk regrouping by Git, and unrelated earlier insertions/deletions.
  (doseq [[label base original attempt valid?]
          [[:excess-insertion "start\nend\n" "start\nnew\nend\n" "start\nnew\nnew\nend\n" false]
           [:non-prefix-addition "start\nend\n" "start\nfirst\nsecond\nend\n"
            "start\nsecond\nend\n" true]
           [:non-adjacent-additions "start\nend\n" "start\nfirst\nsecond\nthird\nend\n"
            "start\nfirst\nthird\nend\n" true]
           [:non-prefix-addition-no-final-newline "start\n" "start\nfirst\nsecond"
            "start\nsecond" true]
           [:reordered-additions "start\nend\n" "start\nfirst\nsecond\nend\n"
            "start\nsecond\nfirst\nend\n" false]
           [:excess-non-prefix-addition "start\nend\n" "start\nfirst\nsecond\nend\n"
            "start\nsecond\nsecond\nend\n" false]
           [:non-prefix-deletion "start\nfirst\nsecond\nend\n" "start\nend\n"
            "start\nfirst\nend\n" true]
           [:fragmented-deletion "start\nfirst\nsecond\nthird\nend\n" "start\nend\n"
            "start\nsecond\nend\n" true]
           [:cross-paired "start\nalpha\nseparator\nbeta\nend\n"
            "start\nALPHA\nseparator\nBETA\nend\n" "start\nBETA\nseparator\nbeta\nend\n" false]
           [:adjacent-cross-paired "alpha\nbeta\nend\n" "ALPHA\nBETA\nend\n" "BETA\nbeta\nend\n" false]
           [:adjacent-first "old\nold\nend\n" "new\nnew\nend\n" "new\nold\nend\n" true]
           [:adjacent-second "old\nold\nend\n" "new\nnew\nend\n" "old\nnew\nend\n" true]
           [:earlier-insertion "head\nanchor\nold\nend\n" "extra\nhead\nanchor\nnew\nend\n"
            "head\nanchor\nnew\nend\n" true]
           [:earlier-deletion "head\nanchor\nold\nend\n" "anchor\nnew\nend\n"
            "head\nanchor\nnew\nend\n" true]
           [:long-insertion-cross-pair "alpha\ns1\ns2\ns3\ns4\nbeta\nend\n"
            "x\ny\nz\nw\nq\nBETA\ns1\ns2\ns3\ns4\nREAL\nend\n"
            "alpha\ns1\ns2\ns3\ns4\nBETA\nend\n" false]
           [:long-insertion-later-selection "alpha\ns1\ns2\ns3\ns4\nbeta\nend\n"
            "x\ny\nz\nw\nq\nBETA\ns1\ns2\ns3\ns4\nREAL\nend\n"
            "alpha\ns1\ns2\ns3\ns4\nREAL\nend\n" true]
           [:earlier-unequal-replacement "alpha\nseparator\nbeta\nend\n"
            "x\ny\nseparator\nBETA\nend\n" "alpha\nseparator\nBETA\nend\n" true]
           [:unequal-cross-paired "alpha\nseparator\nbeta\nend\n"
            "x\ny\nseparator\nBETA\nend\n" "BETA\nseparator\nbeta\nend\n" false]
           [:legitimate-replacement-character "old\nend\n" "�new\nend\n"
            "�new\nend\n" true]
           [:crlf "before\r\nend\r\n" "after\r\nend\r\n" "after\r\nend\r\n" true]
           [:invented-cr "before\r\nend\r\n" "after\r\nend\r\n" "after\nend\r\n" false]]]
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
          [[:addition nil [0 1 -1 10] [0 1 -1 10] true]
           [:deletion [0 1 -1 10] nil nil true]
           [:modification [0 1 -1 10] [0 2 -128 13 10] [0 2 -128 13 10] true]
           [:invented-addition nil [0 1 -1 10] [0 2 -1 10] false]
           [:invented-modification [0 1 -1 10] [0 2 -128 13 10] [0 3 -128 13 10] false]
           [:unchanged-deletion [0 1 -1 10] [0 1 -1 10] nil false]]]
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
