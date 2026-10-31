;; Private library, loaded by the two bin/ entrypoints, not an independent CLI.
;; Callers own identity/trailer policy, refs, preview text, callback data lifetime,
;; and JJ synchronization. These helpers do not choose or synchronize refs.
(ns dotfiles.rewrite-history
  (:require [babashka.process :as process]
            [clojure.string :as str]))

(defn shell
  "Run a command without a shutdown hook; return the process result, including failures."
  [& args]
  (let [[opts args] (if (map? (first args))
                      [(first args) (rest args)]
                      [{} args])]
    (apply process/shell (merge {:shutdown nil} opts) args)))

(defn sh
  "Capture stdout; throw with command, stderr, and exit status on failure.
  An optional first options map supports stdin and per-process environment."
  [& args]
  (let [[opts args] (if (map? (first args))
                      [(first args) (rest args)]
                      [{} args])
        result (apply shell (merge {:out :string :err :string :continue true} opts) args)]
    (if (zero? (:exit result))
      (:out result)
      (throw (ex-info (str "Command failed: " (str/join " " args)
                           (when (seq (:err result)) (str "\n" (:err result))))
                      {:exit (:exit result) :args args})))))

(defn git [& args]
  (apply sh "git" args))

(defn require-clean-worktree!
  "Reject tracked or untracked Git worktree changes before a rewrite."
  []
  (when-not (str/blank? (git "status" "--porcelain=v1"))
    (throw (ex-info "Refusing to rewrite history with a dirty Git worktree." {}))))

(defn commit-records
  "Read Git log records using caller-supplied [key pretty-format] fields and order.
  Preserve the existing NUL-field/RS-record framing; the final field may contain NULs."
  [fields refs reverse?]
  (let [format (str "--format=" (str/join "%x00" (map second fields)) "%x1e")]
    (->> (apply git "log" (concat (when reverse? ["--reverse"]) [format] refs))
         (#(str/split % #"\u001e"))
         (keep (fn [record]
                 (let [record (str/trim-newline record)]
                   (when-not (str/blank? record)
                     (zipmap (map first fields)
                             (str/split record #"\u0000" (count fields))))))))))

(defn preview!
  "Print each selected commit, or the caller's no-match message."
  [matches print-candidate empty-message]
  (if (seq matches)
    (run! print-candidate matches)
    (println empty-message)))

(defn filter-repo!
  "Execute the caller's filter-repo command vector with explicit refs and callback.
  Options supplies process options, not rewrite policy; flags retains caller safety policy."
  [command options flags refs callback]
  (apply sh options (concat command flags ["--refs"] refs ["--commit-callback" callback])))

(defn run-main!
  "Run an entrypoint; report a thrown exception once on stderr and exit 1."
  [main args]
  (try
    (apply main args)
    (catch Exception error
      (binding [*out* *err*]
        (println (.getMessage error)))
      (System/exit 1))))
