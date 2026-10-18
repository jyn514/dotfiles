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
                                            (concat (take 2 args)
                                                    [(str "--unified=" context)]
                                                    (drop 2 args))))]
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
