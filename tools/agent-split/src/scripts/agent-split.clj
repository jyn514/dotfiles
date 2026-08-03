#!/usr/bin/env bb
(ns scripts.jj-split-patch
  (:require [babashka.fs :as fs]
            [babashka.process :as process]
            [clojure.set :as set]
            [clojure.string :as str]))

(defn- script-file []
  (if (not-empty *file*)
    *file*
    "tools/agent-split/src/scripts/agent-split.clj"))

(load-file (str (fs/file (fs/parent (fs/canonicalize (script-file)))
                         "temp.clj")))

(def temp-root (ns-resolve 'scripts.temp 'temp-root))

(defn ^:dynamic *exit!* [status]
  (System/exit status))

(defn- failure-text [step message]
  (str step ": " message))

(defn- fail! [step message]
  (binding [*out* *err*]
    (println (failure-text step message)))
  (*exit!* 1))

(defn- run
  [step & args]
  (let [opts (merge {:out :string
                     :err :string
                     :shutdown nil
                     :continue true}
                    (when (map? (first args))
                      (first args)))
        argv (if (map? (first args)) (rest args) args)
        result (apply process/shell opts argv)]
    (when-not (zero? (:exit result))
      (fail! step (str "command failed: " (str/join " " argv)
                       (when (seq (:err result))
                         (str "\n" (:err result))))))
    result))

(defn- usage! []
  (fail! "Usage" "bb agent-split <patch-file> -m <message> [revision]"))

(defn- print-help! []
  (println "Usage: bb agent-split <patch-file> -m <message> [revision]")
  (println "Splits the selected Git-style patch from a Jujutsu revision; revision defaults to @.")
  (println "The patch paths and hunks define the fileset to select and must be contained in the revision's diff.")
  (println "The patch and helper artifacts must be outside the visible workspace or under ignored target/jj-split/.")
  (println "Runs jj split with the repository's non-interactive jj-agent-split-editor, then verifies both resulting revisions.")
  (println "The split changes workspace history; preflight failures return before invoking jj split or the editor.")
  (println "Use -- to stop recognizing wrapper options; arguments after -- are validated as operands."))

(defn- parse-args [args]
  (let [wrapper-args (take-while #(not= "--" %) args)
        operands (if (= "--" (nth args (count wrapper-args) nil))
                   (concat wrapper-args (drop (inc (count wrapper-args)) args))
                   args)
        [patch flag message revision & extra] operands]
    (when (some #{"-h" "--help"} wrapper-args)
      (print-help!)
      (System/exit 0))
    (when (or (nil? patch)
              (not= "-m" flag)
              (nil? message)
              (seq extra))
      (usage!))
    {:patch patch
     :message message
     :revision (or revision "@")}))

(defn- split-diff-paths [line]
  (when-let [[_ left right] (re-matches #"diff --git a/(.+) b/(.+)" line)]
    [left right]))

(defn- patch-file-paths [patch-text]
  (let [paths (atom [])
        saw-diff? (atom false)]
    (doseq [line (str/split-lines patch-text)]
      (cond
        (str/starts-with? line "diff --git ")
        (if-let [[left right] (split-diff-paths line)]
          (do
            (reset! saw-diff? true)
            (swap! paths into [left right]))
          (fail! "preflight" (str "malformed diff header: " line)))

        (or (str/starts-with? line "--- ")
            (str/starts-with? line "+++ "))
        (let [path (subs line 4)]
          (when-not (= "/dev/null" path)
            (if-let [[_ _prefix file] (re-matches #"([ab])/(.+)" path)]
              (swap! paths conj file)
              (fail! "preflight" (str "malformed patch path: " path)))))))
    (when-not @saw-diff?
      (fail! "preflight" "malformed patch: no diff --git header found"))
    (distinct @paths)))

(defn- unsafe-path? [path]
  (let [path (str path)]
    (or (str/blank? path)
        (str/starts-with? path "/")
        (some #{".."} (str/split path #"/")))))

(defn- validate-patch-paths! [patch-text]
  (doseq [path (patch-file-paths patch-text)]
    (when (unsafe-path? path)
      (fail! "preflight" (str "unsafe patch path: " path)))))

(defn- normalize-abs [path]
  (.normalize (.toAbsolutePath (fs/path path))))

(defn- git-tool-dir []
  (str (temp-root)))

(defn- path-inside? [root path]
  (let [root (normalize-abs root)
        path (normalize-abs path)
        root-prefix (str root java.io.File/separator)]
    (and (str/starts-with? (str path) root-prefix)
         (not= root path))))

(defn- artifact-path? [artifact-root path]
  (path-inside? artifact-root path))

(defn- check-artifact-root-ignored! [repo-root]
  (let [probe "target/jj-split/.jj-split-ignore-probe"
        result (process/shell {:dir repo-root
                               :out :string
                               :err :string
                               :shutdown nil
                               :continue true}
                              "git" "check-ignore" "-q" probe)]
    (when-not (zero? (:exit result))
      (fail! "snapshot safety"
             "target/jj-split is not ignored by version control"))))

(defn- check-snapshot-safety! [repo-root artifact-root patch helper-root]
  (doseq [[label path] {"patch file" patch
                        "helper artifact" helper-root}]
    (when (and (path-inside? repo-root path)
               (not (artifact-path? artifact-root path)))
      (fail! "snapshot safety"
             (str label " is inside the Jujutsu workspace outside target/jj-split: " path)))))

(defn- tree-entry-index [revision]
  (let [template "path ++ \"\\t\" ++ file_type ++ \"\\t\" ++ executable ++ \"\\n\""
        out (:out (run "preflight" "jj" "file" "list" "-r" revision "-T" template))]
    (into {}
          (keep (fn [line]
                  (let [[path type executable] (str/split line #"\t")]
                    (when (seq path)
                      [path {:type type
                             :executable? (= "true" executable)}]))))
          (str/split-lines out))))

(defn- write-file-from-revision! [revision path target executable?]
  (fs/create-dirs (fs/parent target))
  (let [result (process/shell {:out target
                               :err :string
                               :shutdown nil
                               :continue true}
                              "jj" "file" "show" "-r" revision path)]
    (when-not (zero? (:exit result))
      (fail! "preflight" (str "could not materialize " path "\n" (:err result)))))
  (when executable?
    (.setExecutable (fs/file target) true false)))

(defn- materialize-patch-paths! [revision paths target]
  (let [entries (tree-entry-index revision)]
    (doseq [path paths
            :let [{:keys [type executable?]} (get entries path)
                  target-path (fs/file target path)]]
      (case type
        nil nil
        "file" (write-file-from-revision! revision path target-path executable?)
        "symlink" (do
                    (fs/create-dirs (fs/parent target-path))
                    (fs/create-sym-link target-path
                                        (str/trim-newline
                                         (:out (run "preflight" "jj" "file" "show"
                                                    "-r" revision path)))))
        (fail! "preflight" (str "unsupported tree entry for " path ": " type))))))

(defn- deleted-symlink-paths [patch-text]
  (loop [[line & more] (str/split-lines patch-text)
         file nil
         paths []]
    (cond
      (nil? line) paths
      (str/starts-with? line "diff --git ")
      (recur more (some-> line split-diff-paths second) paths)
      (and file (= line "deleted file mode 120000"))
      (recur more file (conj paths file))
      :else
      (recur more file paths))))

(defn- without-deleted-symlink-sections [patch-text]
  (->> (str/split patch-text #"(?m)(?=^diff --git )")
       (remove (fn [section]
                 (some #{"deleted file mode 120000"}
                       (str/split-lines section))))
       (apply str)))

(defn- delete-selected-symlinks! [tree paths]
  (doseq [path paths
          :let [link (fs/file tree path)]]
    (if (fs/sym-link? link)
      (fs/delete link)
      (fail! "preflight" (str "expected deleted symlink at " path)))))

(defn- apply-patch! [tree patch]
  (let [check (process/shell {:dir (str tree)
                              :out :string
                              :err :string
                              :shutdown nil
                              :continue true}
                             "git" "apply" "--unsafe-paths" "--check"
                             (str patch))]
    (when-not (zero? (:exit check))
      (fail! "preflight" (str "patch dry-run failed\n" (:err check))))
    (run "preflight" {:dir (str tree)}
         "git" "apply" "--unsafe-paths" (str patch))))

(defn- diff-output [left right]
  (let [result (process/shell {:dir (git-tool-dir)
                               :out :string
                               :err :string
                               :shutdown nil
                               :continue true}
                              "git" "diff" "--no-index" "--binary" "--no-renames"
                              "--src-prefix=a/" "--dst-prefix=b/" (str left) (str right))]
    (when-not (#{0 1} (:exit result))
      (fail! "preflight" (str "could not diff temporary trees\n" (:err result))))
    (:out result)))

(defn- diff-path-prefixes [path]
  (let [absolute (normalize-abs path)
        relative (try
                   (fs/relativize (fs/cwd) absolute)
                   (catch Exception _ nil))]
    (->> [(str/replace (str absolute) #"^/" "")
          (some-> relative str)]
         (remove str/blank?)
         (map #(str % "/")))))

(defn- normalize-diff-paths [diff-text left right]
  (reduce (fn [text prefix]
            (str/replace text prefix ""))
          diff-text
          (concat (diff-path-prefixes left)
                  (diff-path-prefixes right))))

(defn- current-file [line]
  (some-> (split-diff-paths line) second))

(defn- diff-change-index [diff-text]
  (loop [[line & more] (str/split-lines diff-text)
         file nil
         in-hunk? false
         index {}]
    (cond
      (nil? line) index

      (str/starts-with? line "diff --git ")
      (recur more (current-file line) false (update index (current-file line) (fnil identity #{})))

      (nil? file)
      (recur more file in-hunk? index)

      (str/starts-with? line "@@ ")
      (recur more file true index)

      (or (str/starts-with? line "old mode ")
          (str/starts-with? line "new mode ")
          (str/starts-with? line "deleted file mode ")
          (str/starts-with? line "new file mode "))
      (recur more file in-hunk? (update index file (fnil conj #{}) line))

      (and in-hunk?
           (or (str/starts-with? line "+")
               (str/starts-with? line "-"))
           (not (str/starts-with? line "+++ "))
           (not (str/starts-with? line "--- ")))
      (recur more file in-hunk? (update index file (fnil conj #{}) line))

      :else
      (recur more file in-hunk? index))))

(defn- validate-contained! [original selected]
  (doseq [[file selected-changes] selected]
    (let [original-changes (get original file #{})]
      (when (empty? selected-changes)
        (fail! "preflight" (str "selected diff for " file " is empty or malformed")))
      (when-not (set/subset? selected-changes original-changes)
        (fail! "preflight"
               (str "selected change for " file " is not contained in original diff"))))))

(defn- preflight! [patch-text revision helper-root]
  (validate-patch-paths! patch-text)
  (let [paths (patch-file-paths patch-text)
        left-revision (format "(%s)-" revision)
        left (fs/file helper-root "left")
        selected (fs/file helper-root "selected")
        remaining-patch (fs/file helper-root "remaining.patch")
        original (diff-change-index
                  (:out (run "preflight" "jj" "diff" "--git" "-r" revision)))
        deleted-symlinks (deleted-symlink-paths patch-text)]
    (validate-contained! original
                         (select-keys (diff-change-index patch-text)
                                      deleted-symlinks))
    (fs/create-dirs left)
    (fs/create-dirs selected)
    (materialize-patch-paths! left-revision paths left)
    (materialize-patch-paths! left-revision paths selected)
    (delete-selected-symlinks! selected deleted-symlinks)
    (let [remaining-text (without-deleted-symlink-sections patch-text)]
      (when-not (str/blank? remaining-text)
        (spit (str remaining-patch) remaining-text)
        (apply-patch! selected remaining-patch)))
    (let [selected-index (merge-with
                          set/union
                          (diff-change-index
                           (normalize-diff-paths (diff-output left selected)
                                                 left
                                                 selected))
                          (select-keys (diff-change-index patch-text)
                                       deleted-symlinks))]
      (validate-contained! original selected-index)
      {:original-index original
       :selected-index selected-index})))

(defn- script-dir []
  (-> (if (and (not-empty *file*)
               (fs/regular-file? *file*))
        *file*
        "tools/agent-split/src/scripts/agent-split.clj")
      fs/canonicalize
      fs/parent))

(defn- split-tool-config [editor]
  [(str "merge-tools.agent-split.program=\"" editor "\"")
   "merge-tools.agent-split.edit-args=[\"$left\",\"$right\"]"])

(defn- run-split! [patch message revision]
  (let [editor (str (fs/file (script-dir) "agent-split-editor"))
        [program-config args-config] (split-tool-config editor)
        result (process/shell {:out :string
                               :err :string
                               :shutdown nil
                               :continue true}
                              "env" (str "JJ_AGENT_SPLIT_PATCH=" patch)
                              "jj" "split"
                              "--config" program-config
                              "--config" args-config
                              "--tool" "agent-split"
                              "-m" message
                              "-r" revision)]
    (when-not (zero? (:exit result))
      (fail! "split" (str "jj split failed\n" (:out result) (:err result))))
    (print (:out result))
    (binding [*out* *err*]
      (print (:err result)))
    (str (:out result) "\n" (:err result))))

(defn- split-output-revisions [output]
  (let [selected (some->> output
                          str/split-lines
                          (keep #(second (re-find #"Selected changes\s*:\s+([a-z]+)" %)))
                          first)
        remaining (some->> output
                           str/split-lines
                           (keep #(second (re-find #"Remaining changes:\s+([a-z]+)" %)))
                           first)]
    (when-not (and selected remaining)
      (fail! "verify" "could not identify selected and remaining revisions from jj split output"))
    {:selected selected
     :remaining remaining}))

(defn- index-difference [left right]
  (into {}
        (keep (fn [[file changes]]
                (let [remaining (set/difference changes (get right file #{}))]
                  (when (seq remaining)
                    [file remaining]))))
        left))

(defn- verify! [{:keys [original-index selected-index]} split-revisions]
  (let [{:keys [selected remaining]} split-revisions
        actual-selected (diff-change-index
                         (:out (run "verify" "jj" "diff" "--git" "-r" selected)))
        actual-remaining (diff-change-index
                          (:out (run "verify" "jj" "diff" "--git" "-r" remaining)))
        expected-remaining (index-difference original-index selected-index)]
    (when-not (= selected-index actual-selected)
      (fail! "verify"
             "selected commit does not match supplied patch; use jj op restore to recover"))
    (when-not (= expected-remaining actual-remaining)
      (fail! "verify"
             "remaining commit does not retain the unselected changes; use jj op restore to recover"))))

(defn- hunk-summary [patch-text]
  (loop [[line & more] (str/split-lines patch-text)
         file nil
         counts {}]
    (cond
      (nil? line) counts
      (str/starts-with? line "diff --git ")
      (recur more (current-file line) (update counts (current-file line) (fnil identity 0)))
      (and file (str/starts-with? line "@@ "))
      (recur more file (update counts file (fnil inc 0)))
      :else
      (recur more file counts))))

(defn- print-summary! [patch-text]
  (println "selected files:")
  (doseq [[file hunks] (sort (hunk-summary patch-text))]
    (println (str "  " file " (" hunks " hunk" (when-not (= 1 hunks) "s") ")"))))

(defn main [args]
  (let [{:keys [patch message revision]} (parse-args args)
        patch (fs/canonicalize patch)
        patch-text (if (fs/regular-file? patch)
                     (slurp (str patch))
                     (fail! "preflight" (str "patch file does not exist: " patch)))
        repo-root (str/trim-newline (:out (run "snapshot safety" "jj" "root")))
        artifact-root (fs/file repo-root "target" "jj-split")
        _ (fs/create-dirs artifact-root)
        helper-root (fs/create-temp-dir {:dir (temp-root)
                                         :prefix "jj-split-patch"})]
    (try
      (check-artifact-root-ignored! repo-root)
      (let [preflight (preflight! patch-text revision helper-root)]
        (check-snapshot-safety! repo-root artifact-root patch helper-root)
        (->> (run-split! patch message revision)
             split-output-revisions
             (verify! preflight))
        (print-summary! patch-text))
      (finally
        (fs/delete-tree helper-root)))))

(when (= *file* (System/getProperty "babashka.file"))
  (main *command-line-args*))
