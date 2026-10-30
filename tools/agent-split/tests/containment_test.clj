(ns scripts.agent-split-containment-test
  (:require [babashka.fs :as fs]
            [babashka.process :as process]
            [clojure.edn :as edn]
            [clojure.string :as str]
            [clojure.test :refer [deftest is testing]]))

(load-file "tools/agent-split/src/scripts/agent-split.clj")

(def containment-cases
  ;; Authored expectations migrated unchanged from the native decision tables.
  ;; Neither Git nor the candidate containment implementation supplies valid?.
  (edn/read-string (slurp "tools/agent-split/tests/fixtures/containment-cases.edn")))

(defn- production [name]
  (ns-resolve 'scripts.jj-split-patch name))

(defn- put! [tree path content]
  ;; nil is absence, including binary additions/deletions, not an empty file.
  (when (some? content)
    (let [file (fs/file tree path)]
      (fs/create-dirs (fs/parent file))
      (if (string? content)
        (spit file content)
        (java.nio.file.Files/write (fs/path file) (byte-array content)
                                   (make-array java.nio.file.OpenOption 0))))))

(defn- check-case! [kind [label base original attempt valid?] context unrelated?]
  (let [root (fs/create-temp-dir {:prefix "containment-"})]
    (try
      (let [[left right selected] (mapv #(fs/file root %) ["left" "right" "selected"])
            path (if (= kind :binary) "binary" "note.txt")
            extra (if (= kind :binary) "note.txt" "other.txt")]
        (doseq [[tree content] [[left base] [right original] [selected attempt]]]
          (fs/create-dirs tree)
          (put! tree path content))
        ;; Preserve multi-file producer framing and a genuinely partial selection.
        ;; In particular binary's canonical section precedes another file only
        ;; in original; selected's binary section ends at EOF.
        (when unrelated?
          (put! right extra "unselected real edit\n"))
        (let [shell process/shell
              diff (fn [tree]
                     ;; Exercise a valid producer change without a new API: Git's
                     ;; -U option changes hunk grouping, not authored semantics.
                     (with-redefs [process/shell
                                   (fn [opts & args]
                                     (apply shell opts
                                            (map #(if (str/starts-with? % "--unified=")
                                                    (str "--unified=" context) %) args)))]
                       ((production 'normalize-diff-paths)
                        ((production 'diff-output) left tree) left tree)))
              original-diff (diff right)
              selected-diff (diff selected)
              result ((production 'capture-failure)
                      #((production 'validate-contained!)
                        ((production 'diff-change-index) original-diff)
                        ((production 'diff-change-index) selected-diff)))]
          (is (not (str/blank? selected-diff)) "no selected fixture is silently skipped")
          (when unrelated?
            (is (str/includes? original-diff (str "b/" extra)) "original retains unselected file")
            (is (not (str/includes? selected-diff (str "b/" extra))) "selection remains partial"))
          (when (= kind :binary)
            (is (str/includes? selected-diff "GIT binary patch") "native binary payload, not mode-only input"))
          (is (= valid? (not (contains? result :status)))
              (pr-str {:kind kind :label label :context context :result result}))
          (when-not valid?
            (is (= 1 (:status result)))
            (let [error (or (:error result) "")
                  expected (get {:excess-insertion ["selected base gap before line 2" "added lines differ"]
                                 :cross-paired ["selected base line 2" "original edit at base line 2" "added lines differ"]
                                 :blank-boundary-unrelated-occurrence ["selected base line 5" "does not fit an original edit region"]
                                 :blank-boundary-addition-cross-pair ["selected base lines 2-4" "does not fit an original edit region"]
                                 :invented-addition ["selected binary patch differs"]
                                 :invented-modification ["selected binary patch differs"]
                                 :unchanged-deletion ["selected path has no change"]}
                                label)]
              (is (str/includes? error "not contained in original diff"))
              (doseq [fragment expected]
                (is (str/includes? error fragment) (str label ": " error)))
              (when (= kind :binary)
                (is (not (re-find #"base (?:line|gap)" error)) "binary failures must not invent text coordinates"))))
          original-diff))
      (finally (fs/delete-tree root)))))

(deftest ^:needs/git canonical-containment-decision-table
  ;; Realistic faults: collapsing repeated edits to sets, borrowing an addition
  ;; from another anchor, losing CR/newline state, or checking binary modes only.
  ;; Boundary rows distinguish deleting an old section across Git's retained
  ;; empty lines from deleting spaces, unrelated occurrences, excess blanks,
  ;; partial replacements, or moving replacement additions across anchors.
  ;; Valid changes: partial ordered insertions/deletions and shifted coordinates;
  ;; changing canonical Git context must preserve every independent expectation.
  (doseq [kind [:text :binary]]
    (is (seq (get containment-cases kind)) (str "nonempty " kind " fixture table")))
  (doseq [context [3 1]
          kind [:text :binary]
          row (get containment-cases kind)]
    (testing (str kind " " (first row) " context=" context)
      (check-case! kind row context true))))

(deftest ^:needs/git unchanged-original-has-no-allowance
  ;; Reuse the unchanged-blob deletion case without the unrelated file: Git
  ;; exits zero and emits no original diff. Do not filter this case as empty.
  (let [row (first (filter #(= :unchanged-deletion (first %)) (:binary containment-cases)))]
    (is (some? row))
    (is (= "" (check-case! :binary row 3 false)))))

(defn- note-index
  ([hunk] (note-index "" hunk))
  ([metadata hunk]
   (get ((production 'diff-change-index)
         (str "diff --git a/note.txt b/note.txt\n" metadata
              "--- a/note.txt\n+++ b/note.txt\n" hunk))
        "note.txt")))

(deftest rightward-equivalent-representations-use-the-public-checker
  ;; The real-Git mirror fixtures are already accepted without retry: Git picks
  ;; the same anchor in both comparisons. These valid alternate unified diffs
  ;; force the opposite direction without pretending Git emitted them. In each
  ;; pair, rotating the selected block right reconstructs the same selected file.
  (doseq [[label original selected neighbor]
          [[:insertion
            (note-index "@@ -1,3 +1,6 @@\n A\n TOKEN\n+mine\n+TOKEN\n+other\n B\n")
            (note-index "@@ -1,3 +1,5 @@\n A\n+TOKEN\n+mine\n TOKEN\n B\n")
            2]
           [:deletion
            (note-index "@@ -1,6 +1,3 @@\n A\n TOKEN\n-mine\n-TOKEN\n-other\n B\n")
            (note-index "@@ -1,6 +1,4 @@\n A\n-TOKEN\n-mine\n TOKEN\n other\n B\n")
            4]]]
    (testing (name label)
      (is (nil? (scripts.containment/rejection-reason original selected)))
      ;; Canonical context can be sparse. Unknown neighbors must not be inferred
      ;; from the full diff or matching text in some other occurrence.
      (is (string? (scripts.containment/rejection-reason
                     original (update selected :context dissoc neighbor)))))))

(deftest complete-candidate-validation-prevents-pooled-allowance-reuse
  ;; Explicitly fragment one insertion representation at its unchanged base gap.
  ;; Git normally coalesces it; splitting the block does not change selected
  ;; bytes. Each half fits independently, but together they spend the only
  ;; [mine TOKEN] allowance twice. This isolates the final pooled validation.
  (let [original (note-index "@@ -1,3 +1,5 @@\n A\n TOKEN\n+mine\n+TOKEN\n B\n")
        selected (note-index "@@ -1,3 +1,7 @@\n A\n TOKEN\n+mine\n+TOKEN\n+mine\n+TOKEN\n B\n")
        block (first (:edits selected))
        fragmented (assoc selected :edits
                          (mapv #(assoc block :added (vec %))
                                (partition 2 (:added block))))]
    (is (= 2 (count (:edits fragmented))))
    (doseq [edit (:edits fragmented)]
      (is (nil? (scripts.containment/rejection-reason original (assoc fragmented :edits [edit])))))
    (is (string? (scripts.containment/rejection-reason original fragmented)))))

(deftest multi-step-rotations-in-both-directions
  ;; Two shifts are needed in every row: one-step acceptance cannot establish
  ;; the run walk, especially the consumed/freed base context of deletions.
  (doseq [[label full selected]
          [[:insert-left
            "@@ -1,4 +1,8 @@\n A\n+other\n+TOKEN\n+TOKEN\n+mine\n TOKEN\n TOKEN\n B\n"
            "@@ -1,4 +1,7 @@\n A\n TOKEN\n TOKEN\n+mine\n+TOKEN\n+TOKEN\n B\n"]
           [:insert-right
            "@@ -1,4 +1,8 @@\n A\n TOKEN\n TOKEN\n+mine\n+TOKEN\n+TOKEN\n+other\n B\n"
            "@@ -1,4 +1,7 @@\n A\n+TOKEN\n+TOKEN\n+mine\n TOKEN\n TOKEN\n B\n"]
           [:delete-left
            "@@ -1,8 +1,4 @@\n A\n-other\n-TOKEN\n-TOKEN\n-mine\n TOKEN\n TOKEN\n B\n"
            "@@ -1,8 +1,5 @@\n A\n other\n TOKEN\n TOKEN\n-mine\n-TOKEN\n-TOKEN\n B\n"]
           [:delete-right
            "@@ -1,8 +1,4 @@\n A\n TOKEN\n TOKEN\n-mine\n-TOKEN\n-TOKEN\n-other\n B\n"
            "@@ -1,8 +1,5 @@\n A\n-TOKEN\n-TOKEN\n-mine\n TOKEN\n TOKEN\n other\n B\n"]]]
    (testing (name label)
      (is (nil? (scripts.containment/rejection-reason (note-index full) (note-index selected)))))))

(deftest nonregular-metadata-does-not-enable-text-rotation-retry
  (let [full "@@ -1,3 +1,6 @@\n A\n TOKEN\n+mine\n+TOKEN\n+other\n B\n"
        selected "@@ -1,3 +1,5 @@\n A\n+TOKEN\n+mine\n TOKEN\n B\n"]
    (is (nil? (scripts.containment/rejection-reason (note-index full) (note-index selected))))
    (doseq [mode ["120000" "160000"]
            header [(str "index 1111111..2222222 " mode "\n")
                    (str "old mode 100644\nnew mode " mode "\n")]]
      (testing (pr-str [mode header])
        ;; Header policy is independent from the identical text placement. Both
        ;; mode sets are equal, so a mode-subset failure cannot mask this guard.
        (is (string? (scripts.containment/rejection-reason
                       (note-index header full) (note-index header selected))))))
    (doseq [side [:original :selected]]
      (testing (str "index metadata only on " side)
        ;; Existing-kind index headers do not add a mode change. Check each side
        ;; independently so guarding only one producer would be caught.
        (let [header "index 1111111..2222222 120000\n"]
          (is (string? (scripts.containment/rejection-reason
                         (note-index (if (= side :original) header "") full)
                         (note-index (if (= side :selected) header "") selected)))))))))
