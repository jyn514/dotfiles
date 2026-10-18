#!/usr/bin/env bb
(ns scripts.jj-split-patch
  (:require [babashka.fs :as fs]
            [babashka.process :as process]
            [cheshire.core :as json]
            [clojure.set :as set]
            [clojure.string :as str]))

(defn- script-file []
  (if (not-empty *file*)
    *file*
    "tools/agent-split/src/scripts/agent-split.clj"))

(load-file (str (fs/file (fs/parent (fs/canonicalize (script-file)))
                         "temp.clj")))

(def temp-root (ns-resolve 'scripts.temp 'temp-root))

(load-file (str (fs/file (fs/parent (fs/canonicalize (script-file)))
                         "containment.clj")))

(defn ^:dynamic *exit!* [status]
  (System/exit status))

(def ^:dynamic *preflight-revision* nil)
(def ^:dynamic *read-backend* "native")
(def ^:dynamic *split-result* nil)

(defn- split-result-text []
  (when-let [result (some-> *split-result* deref)]
    (str "\nSelected change: " (or (:selected result) "unavailable")
         "\nSelected commit: " (or (:selected-revision result) "unavailable")
         "\nRemaining change: " (or (:remaining result) "unavailable")
         "\nRemaining commit: " (or (:remaining-revision result) "unavailable")
         "\nSplit input commit: " (or (:input-revision result) "unavailable"))))

(defn- failure-text [step message]
  (str step ": " message
       (when (and (= step "preflight") *preflight-revision*)
         (str "\nPreflight target: " (:revision *preflight-revision*)
              "\nResolved commit: " (:commit *preflight-revision*)
              "\nResolved parents: " (str/join ", " (sort (:parents *preflight-revision*)))
              "\nNo split was run."))))

(defn- fail-with-status! [status step message]
  (binding [*out* *err*]
    (println (failure-text step message)))
  (*exit!* status))

(defn- fail! [step message]
  (fail-with-status! 1 step message))

(defn- verify-fail! [message]
  (fail-with-status! 3 "verify" message))

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

(defn- run-jj-read
  [step & args]
  (let [opts (when (map? (first args)) (first args))
        [subcommand & subcommand-args] (if opts (rest args) args)]
    (if (= "proxy" *read-backend*)
      ;; The proxy forbids caller security-sensitive flags in both modes; its
      ;; trusted inspect executor adds --ignore-working-copy after validation.
      (apply run step (update (or opts {}) :extra-env
                              #(assoc (or % {}) "JJ_PROXY_INSPECT" "1"))
             "jj" subcommand subcommand-args)
      (if opts
        (apply run step opts "jj" subcommand "--ignore-working-copy" subcommand-args)
        (apply run step "jj" subcommand "--ignore-working-copy" subcommand-args)))))

(defn- snapshot-workspace! []
  (run "snapshot safety" "jj" "status" "--no-pager")
  nil)

(defn- usage! []
  (fail! "Usage" "bb agent-split [--json] [--remaining-message <message>] <patch-file> -m <message> [-m <message> ...] [revision]"))

(defn- print-help! []
  (println "Usage: bb agent-split [--json] [--remaining-message <message>] <patch-file> -m <message> [-m <message> ...] [revision]")
  (println "Splits the selected Git-style patch from a Jujutsu revision; revision defaults to @.")
  (println "The patch paths and hunks define the fileset to select and must be contained in the revision's diff.")
  (println "The patch and helper artifacts must be outside the visible workspace or under ignored target/jj-split/.")
  (println "Runs jj split with the repository's non-interactive jj-agent-split-editor, then verifies both resulting revisions.")
  (println "The split changes workspace history; preflight failures return before invoking jj split or the editor.")
  (println "Exit status 1 means preflight failure, 2 means jj split failure, and 3 means post-split verification failure.")
  (println "Verification failures leave the split intact and report all known resulting revision IDs.")
  (println "--json suppresses human progress output and prints full selected and remaining change IDs as JSON.")
  (println "--remaining-message describes the remaining commit before verification completes.")
  (println "Repeat -m to join message paragraphs with a blank line; each value is literal text.")
  (println "Use -- to stop recognizing wrapper options; arguments after -- are validated as operands."))

(defn- parse-wrapper-options [args]
  (loop [remaining args
         options {:json? false :remaining-message nil :help? false}
         operands []]
    (let [[arg & more] remaining]
      (cond
        (nil? arg) [options operands]
        (= "--" arg) [options (into operands more)]
        (#{"-h" "--help"} arg) (recur more (assoc options :help? true) operands)
        (= "--json" arg) (recur more (assoc options :json? true) operands)
        (= "--remaining-message" arg)
        (if-let [message (first more)]
          (recur (rest more) (assoc options :remaining-message message) operands)
          (usage!))
        (= "-m" arg)
        (if-let [message (first more)]
          (recur (rest more) options (into operands [arg message]))
          (usage!))
        :else (recur more options (conj operands arg))))))

(defn- parse-args [args]
  (let [[options operands] (parse-wrapper-options args)
        [patch & tail] operands]
    (when (:help? options)
      (print-help!)
      (System/exit 0))
    (when (nil? patch)
      (usage!))
    (loop [[arg message & more :as remaining] tail
           messages []]
      (if (= "-m" arg)
        (if (some? message)
          (recur more (conj messages message))
          (usage!))
        (do
          (when (or (empty? messages) (> (count remaining) 1))
            (usage!))
          (merge (dissoc options :help?)
                 {:patch patch
                  :message (str/join "\n\n" messages)
                  :revision (or arg "@")}))))))

(defn- split-diff-paths [line]
  (when-let [[_ left right] (re-matches #"diff --git a/(.+) b/(.+)" line)]
    [left right]))

(defn- patch-file-paths [patch-text]
  (let [paths (atom [])
        saw-diff? (atom false)
        in-hunk? (atom false)]
    (doseq [line (str/split-lines patch-text)]
      (cond
        (str/starts-with? line "diff --git ")
        (if-let [[left right] (split-diff-paths line)]
          (do
            (reset! saw-diff? true)
            (reset! in-hunk? false)
            (swap! paths into [left right]))
          (fail! "preflight" (str "malformed diff header: " line)))

        (str/starts-with? line "@@ ")
        (reset! in-hunk? true)

        ;; Hunk content can itself begin with --- or +++; only parse file headers.
        @in-hunk? nil

        (some #(str/starts-with? line %)
              ["rename from " "rename to " "copy from " "copy to "])
        (let [[_ path] (re-matches #"(?:rename|copy) (?:from|to) (.+)" line)]
          (swap! paths conj path))

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
        out (:out (run-jj-read "preflight" "file" "list" "-r" revision "-T" template))]
    (into {}
          (keep (fn [line]
                  (let [[path type executable] (str/split line #"\t")]
                    (when (seq path)
                      [path {:type type
                             :executable? (= "true" executable)}]))))
          (str/split-lines out))))

(defn- write-file-from-revision! [revision path target executable?]
  (fs/create-dirs (fs/parent target))
  (let [result (run-jj-read "preflight"
                            {:out target}
                            "file" "show" "-r" revision path)]
    (when-not (zero? (:exit result))
      (fail! "preflight" (str "could not materialize " path "\n" (:err result)))))
  (when executable?
    (.setExecutable (fs/file target) true false)))

(defn- symlink-target [git-dir commit path]
  ;; JJ file show intentionally excludes symlinks. Read the Git blob verbatim.
  (:out (run "preflight" "git" (str "--git-dir=" git-dir)
             "cat-file" "blob" (str commit ":" path))))

(defn- materialize-patch-paths! [revision paths target]
  (let [entries (tree-entry-index revision)
        ;; Resolve only if needed, once for this materialization, never across
        ;; preflight and post-split verification or between invocations.
        symlink-source (delay
                         [(str/trim-newline (:out (run-jj-read "preflight" "git" "root")))
                          (str/trim-newline
                           (:out (run-jj-read "preflight" "log" "-r" revision
                                             "--no-graph" "-T" "commit_id")))])]
    (doseq [path paths
            :let [{:keys [type executable?]} (get entries path)
                  target-path (fs/file target path)]]
      (case type
        nil nil
        "file" (write-file-from-revision! revision path target-path executable?)
        "symlink" (do
                    (fs/create-dirs (fs/parent target-path))
                    (let [[git-dir commit] @symlink-source]
                      (fs/create-sym-link target-path (symlink-target git-dir commit path))))
        (fail! "preflight" (str "unsupported tree entry for " path ": " type))))))

(defn- apply-patch! [tree patch]
  ;; Hand-selected hunks may retain old counts; application and containment still validate content.
  (let [check (process/shell {:dir (str tree)
                              :out :string
                              :err :string
                              :shutdown nil
                              :continue true}
                             "git" "apply" "--recount" "--unsafe-paths" "--check"
                             (str patch))]
    (when-not (zero? (:exit check))
      ;; Ask Git whether missing context explains the failure; never apply with
      ;; relaxed matching or infer the cause from patch headers alone.
      (let [zero-context-check (process/shell {:dir (str tree)
                                               :out :string
                                               :err :string
                                               :shutdown nil
                                               :continue true}
                                              "git" "apply" "--recount" "--unsafe-paths"
                                              "--unidiff-zero" "--check" (str patch))]
        (fail! "preflight"
               (str "patch dry-run failed\n" (:err check)
                    (when (zero? (:exit zero-context-check))
                      "\nGit accepts this patch only with --unidiff-zero; agent-split does not use that option.")
                    "\nRegenerate selected hunks from jj diff --git -r <revision>, retaining unchanged context from the revision's parent."))))
    (run "preflight" {:dir (str tree)}
         "git" "apply" "--recount" "--unsafe-paths" (str patch))))

(defn- diff-output [left right]
  (let [result (process/shell {:dir (git-tool-dir)
                               :out :bytes
                               :err :string
                               :shutdown nil
                               :continue true}
                              "git" "diff" "--no-index" "--binary" "--no-renames"
                              "--src-prefix=a/" "--dst-prefix=b/" (str left) (str right))]
    (when-not (#{0 1} (:exit result))
      (fail! "preflight" (str "could not diff temporary trees\n" (:err result))))
    (or ((ns-resolve 'scripts.containment 'decode-utf8) (:out result))
        (fail! "preflight" "canonical diff contains non-UTF-8 text; selection is unsupported"))))

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

(def diff-change-index (ns-resolve 'scripts.containment 'change-index))

(defn- validate-contained! [original selected]
  (doseq [[file selected-changes] selected]
    (let [original-changes (get original file)]
      (when-not (or (seq (:modes selected-changes)) (seq (:edits selected-changes))
                    (seq (:binary selected-changes)))
        (fail! "preflight" (str "selected diff for " file " is empty or malformed")))
      (when-let [reason ((ns-resolve 'scripts.containment 'rejection-reason)
                         original-changes selected-changes)]
        (fail! "preflight"
               (str "selected change for " file " is not contained in original diff\n" reason))))))

(defn- preflight! [patch-text revision helper-root]
  (validate-patch-paths! patch-text)
  (let [original-patch (:out (run-jj-read "preflight" "diff" "--git" "-r" revision))
        original-paths (patch-file-paths original-patch)
        left-revision (format "(%s)-" revision)
        left (fs/file helper-root "left")
        right (fs/file helper-root "right")
        selected (fs/file helper-root "selected")
        remaining-patch (fs/file helper-root "remaining.patch")]
    (doseq [tree [left right selected]] (fs/create-dirs tree))
    (materialize-patch-paths! left-revision original-paths left)
    (materialize-patch-paths! revision original-paths right)
    ;; Apply to an independent copy of the exact parent tree already read.
    ;; Archive copy preserves raw bytes, executable bits and dangling symlinks.
    (run "preflight" "cp" "-a" (str left "/.") (str selected))
    (spit (str remaining-patch) patch-text)
    (apply-patch! selected remaining-patch)
    (validate-contained!
     (diff-change-index (normalize-diff-paths (diff-output left right) left right))
     (diff-change-index (normalize-diff-paths (diff-output left selected) left selected)))
    {:original-paths original-paths
     :expected-selected-tree selected}))

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

(defn- sandbox-proxy-dir []
  (or (not-empty (System/getenv "SANDBOX_PROXY_DIR"))
      (let [directory (or (not-empty (System/getenv "SANDBOX_PROXY_DEFAULT_DIR"))
                          "/run/sandbox-proxies")]
        (when (fs/exists? (fs/file directory "jj" "socket"))
          directory))))

(defn- route-helper []
  (or (not-empty (System/getenv "JJ_ROUTE_HELPER"))
      (str (fs/file (-> (script-dir) fs/parent fs/parent fs/parent)
                    "jj-proxy" "route.py"))))

(defn- checked-route [text]
  (let [results (try (vec (json/parsed-seq (java.io.StringReader. text) true))
                     (catch Exception _
                       (fail! "routing" "helper returned invalid JSON")))
        route (if (= 1 (count results))
                (first results)
                (fail! "routing" "helper must return one JSON object"))
        nullable-path? #(or (nil? %) (and (string? %) (fs/absolute? %)))]
    (when-not (and (map? route)
                   (every? #(contains? route %) [:backend :workspace :destination :command :hooks])
                   (#{"native" "proxy"} (:backend route))
                   (nullable-path? (:workspace route))
                   (nullable-path? (:destination route))
                   (vector? (:command route))
                   (every? string? (:command route))
                   (boolean? (:hooks route)))
      (fail! "routing" "helper returned an invalid split route"))
    route))

(defn- split-route []
  ;; Ordinary hosts must not depend on the sandbox helper or Linux mount data.
  ;; Keep the caller environment intact, including stripped-env socket discovery.
  (if-let [proxy-dir (sandbox-proxy-dir)]
    (checked-route (:out (run "routing" {:extra-env {"SANDBOX_PROXY_DIR" proxy-dir}}
                             "python3" (route-helper) "--" "split")))
    {:backend "native" :workspace nil :destination nil :command ["split"] :hooks true}))

(defn- run-split! [route patch message revision]
  (let [editor (str (fs/file (script-dir) "agent-split-editor"))
        [program-config args-config] (split-tool-config editor)
        command (if (= "proxy" (:backend route))
                  ["jj" "--agent-split" (str patch) message revision]
                  ["env" (str "JJ_AGENT_SPLIT_PATCH=" patch)
                   "jj" "split"
                   "--config" program-config
                   "--config" args-config
                   "--tool" "agent-split"
                   "-m" message
                   "-r" revision])
        result (apply process/shell {:out :string
                                     :err :string
                                     :shutdown nil
                                     :continue true}
                      command)]
    (when-not (zero? (:exit result))
      (fail-with-status! 2 "split" (str "jj split failed\n" (:out result) (:err result))))
    nil))

(defn- current-operation-id [route]
  (when (= "native" (:backend route))
    (str/trim-newline
     (:out (run-jj-read "preflight" {:dir (:workspace route)}
                        "op" "log" "--limit" "1" "--no-graph"
                        "-T" "id.short()")))))

(def change-id-template "change_id.short(32) ++ \"\\n\"")
(def commit-id-template "commit_id.short(40) ++ \"\\n\"")

(defn- revision-change-id [revision]
  (str/trim-newline
   (:out (run-jj-read "preflight" "log" "-r" revision "--no-graph"
                      "-T" change-id-template))))

(defn- revision-commit-id [revision]
  (str/trim-newline
   (:out (run-jj-read "preflight" "log" "-r" revision "--no-graph"
                      "-T" commit-id-template))))

(defn- revision-description [revision]
  (str/trim-newline
   (:out (run-jj-read "preflight" "log" "-r" revision "--no-graph"
                      "-T" "description"))))

(defn- revision-ids [revset template]
  (->> (:out (run-jj-read "preflight" "log" "-r" revset "--no-graph" "-T" template))
       str/split-lines
       (remove str/blank?)
       vec))

(defn- revision-children [revision]
  (revision-ids (str "children(" revision ")") change-id-template))

(defn- parent-commit-ids [revision]
  (set (revision-ids (str "parents(" revision ")") commit-id-template)))

(declare revision-matches-selected-tree?)

(defn- matching-selected-commit [preflight change-id message original-parents helper-root]
  (let [candidates (filter #(and (= message (revision-description %))
                                 (= original-parents (parent-commit-ids %)))
                           (revision-ids change-id commit-id-template))
        ;; Identify before verifying: even a mismatched selected tree must leave
        ;; the caller with the commit IDs needed to inspect the completed split.
        matches (if (= 1 (count candidates))
                  candidates
                  (filter #(revision-matches-selected-tree? preflight % helper-root)
                          candidates))]
    (when-not (= 1 (count matches))
      (verify-fail!
       (str "expected one selected commit for change " change-id
            ", found " (count matches))))
    (first matches)))

(defn- record-split-result! [result]
  (when *split-result* (swap! *split-result* merge result))
  result)

(defn- evolution-entries [revision limit]
  (let [result (apply run-jj-read "verify" "evolog" "-r" revision "--no-graph"
                      "-T" (str "json({\"commit\" => commit.commit_id(), "
                                 "\"operation\" => operation.id(), "
                                 "\"predecessors\" => predecessors.map(|c| c.commit_id())}) ++ \"\\n\"")
                      (when limit ["--limit" (str limit)]))]
    (vec (json/parsed-seq (java.io.StringReader. (:out result)) true))))

(defn- split-evolution [selected-commit]
  ;; JJ records the exact input as the selected commit's predecessor, and both
  ;; split outputs belong to the same operation. Follow those immutable entries
  ;; instead of accepting a later working-copy snapshot as the split remainder.
  (let [entry (first (evolution-entries selected-commit 1))]
    (when-not (and (= selected-commit (:commit entry))
                   (= 1 (count (:predecessors entry))))
      (verify-fail! "expected one split input predecessor"))
    entry))

(defn- discover-split-revisions [preflight change-id message original-parents helper-root]
  (let [selected-commit (matching-selected-commit preflight change-id message
                                                   original-parents helper-root)
        _ (record-split-result! {:selected-revision selected-commit})
        remaining-commits (revision-ids (str "children(" selected-commit ")")
                                        commit-id-template)]
    (when-not (= 1 (count remaining-commits))
      (verify-fail!
       (str "expected one remaining child of commit " selected-commit
            ", found " (count remaining-commits))))
    (let [current-remaining (first remaining-commits)
          _ (record-split-result! {:remaining (revision-change-id current-remaining)
                                   :remaining-revision current-remaining})
          entry (split-evolution selected-commit)
          input (first (:predecessors entry))
          _ (record-split-result! {:input-revision input})
          versions (filter #(= (:operation entry) (:operation %))
                           (evolution-entries current-remaining nil))]
      (when-not (= 1 (count versions))
        (verify-fail! (str "expected one remaining commit from the split operation, found " (count versions))))
      (record-split-result!
       {:selected (revision-change-id selected-commit)
        :remaining (revision-change-id current-remaining)
        :selected-revision selected-commit
        :remaining-revision (:commit (first versions))
        :current-remaining-revision current-remaining
        :input-revision input}))))

(defn- describe-revision! [revision message]
  (run "verify" "jj" "describe" "-r" revision "-m" message))

(defn- revision-matches-selected-tree?
  [{:keys [original-paths expected-selected-tree]} revision helper-root]
  (let [actual-tree (fs/file helper-root "already-selected")]
    (when (fs/exists? actual-tree)
      (fs/delete-tree actual-tree))
    (fs/create-dirs actual-tree)
    (materialize-patch-paths! revision original-paths actual-tree)
    (str/blank?
     (normalize-diff-paths (diff-output expected-selected-tree actual-tree)
                           expected-selected-tree
                           actual-tree))))

(defn- reject-already-applied! [preflight revision message helper-root]
  (when (and (= message (revision-description revision))
             (revision-matches-selected-tree? preflight revision helper-root))
    (let [children (revision-children revision)
          continuation (when (= 1 (count children)) (first children))]
      (fail! "preflight"
             (str "patch and message already describe revision " revision
                  (when continuation
                    (str "; continue with child " continuation)))))))

(defn- changed-paths [revision]
  (->> (:out (run-jj-read "verify" "diff" "-r" revision "--name-only"))
       str/split-lines
       (remove str/blank?)
       set))

(defn- verify! [{:keys [original-paths expected-selected-tree]}
                original-commit split-revisions helper-root]
  (let [{:keys [selected-revision remaining-revision]} split-revisions
        expected-paths (set original-paths)
        actual-paths (changed-paths selected-revision)
        unexpected-paths (set/difference actual-paths expected-paths)
        actual-selected-tree (fs/file helper-root "verify-selected")
        _ (fs/create-dirs actual-selected-tree)
        _ (materialize-patch-paths! selected-revision original-paths actual-selected-tree)
        selected-diff (normalize-diff-paths
                       (diff-output expected-selected-tree actual-selected-tree)
                       expected-selected-tree
                       actual-selected-tree)
        remaining-diff (:out (run-jj-read "verify" "diff" "--from" original-commit
                                          "--to" remaining-revision "--name-only"))]
    (cond
      (seq unexpected-paths)
      (str "selected commit changed unexpected paths: "
           (str/join ", " (sort unexpected-paths)))

      (not (str/blank? selected-diff))
      "selected patch mismatch: selected commit does not match supplied patch"

      (not (str/blank? remaining-diff))
      "remainder mismatch: remaining tree differs from the actual split input"

      :else nil)))

(defn- capture-failure
  ([f] (capture-failure f false))
  ([f post-split?]
   (let [err (java.io.StringWriter.)]
     (binding [*err* err
               *exit!* (fn [status]
                         (throw (ex-info "captured exit" {:status status})))]
       (try
         (let [value (f)] {:value value :stderr (str err)})
         (catch Exception ex
           (if-let [status (:status (ex-data ex))]
             {:status status
              :error (str/trim (str err))}
             (if post-split?
               ;; Once split succeeds, launch/discovery exceptions need the same
               ;; failure status and result diagnostics as a tree mismatch.
               {:status 3
                :error (str/join "\n"
                                 (remove str/blank?
                                         [(str/trim (str err))
                                          (failure-text "verify" (str ex))]))}
               (throw ex)))))))))

(defn- report-verification-failure! [operation-id message]
  ;; An operation-wide restore can erase another writer's work, even if our
  ;; last inspection saw no concurrent edits. Failed splits remain inspectable.
  (verify-fail!
   (str message
        (when (some-> *split-result* deref :concurrent-edits?)
          "; concurrent edits observed")
        "; split left intact; no automatic recovery attempted"
        (when operation-id (str "\nPreflight operation: " operation-id))
        (split-result-text))))

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

(defn- execute-main [args]
  (let [{:keys [patch message revision json? remaining-message]} (parse-args args)
        patch (fs/canonicalize patch)
        patch-text (if (fs/regular-file? patch)
                     (slurp (str patch))
                     (fail! "preflight" (str "patch file does not exist: " patch)))
        route (split-route)]
    ;; Resolve once, including workspace-root queries. Inspection mode is scoped
    ;; to each read child, not snapshots, structured splits or descriptions.
    (binding [*read-backend* (:backend route)]
      (let [;; Establish one authoritative preflight snapshot.
        _ (snapshot-workspace!)
        repo-root (or (:workspace route)
                      (str/trim-newline (:out (run-jj-read "snapshot safety" "workspace" "root"))))
        route (assoc route :workspace repo-root)
        artifact-root (fs/file repo-root "target" "jj-split")
        _ (fs/create-dirs artifact-root)
        helper-root (fs/create-temp-dir {:dir (temp-root)
                                         :prefix "jj-split-patch"})]
    (try
      (check-artifact-root-ignored! repo-root)
      (let [original-commit (revision-commit-id revision)
            selected-change-id (revision-change-id original-commit)
            original-parents (parent-commit-ids original-commit)
            preflight (binding [*preflight-revision* {:revision revision
                                                     :commit original-commit
                                                     :parents original-parents}]
                        (let [preflight (preflight! patch-text original-commit helper-root)]
                          (check-snapshot-safety! repo-root artifact-root patch helper-root)
                          (reject-already-applied! preflight original-commit message helper-root)
                          preflight))]
        (let [operation-id (current-operation-id route)
              _ (run-split! route patch message revision)]
          (binding [*split-result* (atom {:selected selected-change-id})]
            (let [post-split
                  (capture-failure
                   #(let [split-revisions (discover-split-revisions preflight
                                                                    selected-change-id message
                                                                    original-parents helper-root)
                          input-commit (:input-revision split-revisions)
                          _ (record-split-result! {:input-revision input-commit})
                          changed (when-not (= original-commit input-commit)
                                    (:out (run-jj-read "verify" "diff" "--from" original-commit
                                                       "--to" input-commit "--name-only")))
                          _ (when-not (str/blank? changed)
                              (record-split-result! {:concurrent-edits? true}))
                          later-edits (when-not (= (:remaining-revision split-revisions)
                                                    (:current-remaining-revision split-revisions))
                                        (:out (run-jj-read "verify" "diff"
                                                           "--from" (:remaining-revision split-revisions)
                                                           "--to" (:current-remaining-revision split-revisions)
                                                           "--name-only")))
                          _ (record-split-result!
                             {:concurrent-edits? (or (not (str/blank? changed))
                                                     (not (str/blank? later-edits)))})
                          ;; Native editors validate at split time. Revalidate
                          ;; here too for the protected editor, whose interface
                          ;; only applies a patch and cannot return a receipt.
                          recheck (when-not (str/blank? changed)
                                    (capture-failure
                                     (fn [] (preflight! patch-text input-commit
                                                        (fs/file helper-root "split-input")))))
                          _ (when (:status recheck)
                              (verify-fail!
                               (str "selected source changed since preflight: " (:error recheck))))
                          _ (when remaining-message
                              (describe-revision! (:current-remaining-revision split-revisions)
                                                  remaining-message))]
                      {:split-revisions split-revisions
                       :verification-error (verify! preflight input-commit
                                                    split-revisions helper-root)})
                   true)]
              (when-let [error (:error post-split)]
                (report-verification-failure! operation-id error))
              (let [{:keys [split-revisions verification-error]} (:value post-split)]
                (when verification-error
                  (report-verification-failure! operation-id verification-error))
                (when (:concurrent-edits? @*split-result*)
                  (binding [*out* *err*]
                    (println "concurrent edits observed; remainder verified against the actual split input")))
                (if json?
                  (println (json/generate-string (select-keys split-revisions [:selected :remaining])))
                  (do
                    (print-summary! patch-text)
                    (println (str "selected revision: " (:selected split-revisions)))
                    (println (str "remaining revision: " (:remaining split-revisions))))))))))
      (finally
        (fs/delete-tree helper-root)))))))

(defn main [args]
  ;; Defer process exit until execute-main's artifact cleanup has run.
  (let [result (capture-failure #(execute-main args))]
    (if-let [status (:status result)]
      (do
        (binding [*out* *err*] (println (:error result)))
        (*exit!* status))
      (when (seq (:stderr result))
        (binding [*out* *err*]
          (print (:stderr result))
          (flush))))))

(when (= *file* (System/getProperty "babashka.file"))
  (main *command-line-args*))
