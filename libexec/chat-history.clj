;; Shared read-only session loading for extract-chat and codex-to-pi.
;; Library API: files-under lists JSON/JSONL inputs; find-session selects a path within explicit search roots;
;; history-segments returns event sequences, oldest ancestor first, omitting injected skill instructions.
;; Direct invocation: bb chat-history.clj MODE SOURCE CODEX-HOME.
;; MODE is file, session, or archived-session. Success writes one JSON object:
;; {"file": "selected path", "segments": [[exportable source events], ...]}.
;; Failure writes a diagnostic to stderr, exits 1, and emits no JSON.
(ns dotfiles.chat-history
  (:require [cheshire.core :as json]
            [clojure.java.io :as io]
            [clojure.string :as str])
  (:import (java.nio.file Files Path)))

(defn- path [s]
  (.toPath (io/file s)))

(defn- regular-file? [^Path p]
  (Files/isRegularFile p (make-array java.nio.file.LinkOption 0)))

(defn- directory? [^Path p]
  (Files/isDirectory p (make-array java.nio.file.LinkOption 0)))

(defn- session-file? [^Path p]
  (let [s (str p)]
    (and (regular-file? p)
         (or (str/ends-with? s ".json")
             (str/ends-with? s ".jsonl")))))

(defn files-under [^Path p]
  (if (directory? p)
    (with-open [stream (Files/walk p (make-array java.nio.file.FileVisitOption 0))]
      (->> (iterator-seq (.iterator stream))
           (filter session-file?)
           (sort-by str)
           doall))
    (when (session-file? p) [p])))

(defn- session-file-name-matches? [session ^Path file]
  (let [file-name (str (.getFileName file))
        stem (str/replace file-name #"\.jsonl?$" "")
        ;; Reverts keep the thread ID but append a new physical rollout ID.
        stem (if (str/starts-with? stem "rollout-")
               (str/replace stem #"_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$" "")
               stem)]
    (or (= session stem)
        (str/ends-with? stem (str "-" session))
        (str/ends-with? stem (str "_" session)))))

(defn find-session [session roots]
  (let [matches (->> roots
                     (remove nil?)
                     (mapcat #(files-under (path %)))
                     (filter #(session-file-name-matches? session %))
                     distinct
                     (sort-by str))]
    (cond
      (empty? matches)
      (throw (ex-info (str "No session found for " session)
                      {:session session :roots roots}))

      (= 1 (count matches)) (first matches)

      ;; Match Codex's offline filename fallback: timestamp, then rollout UUID.
      (every? #(str/starts-with? (str (.getFileName ^Path %)) "rollout-") matches)
      (last (sort-by #(str (.getFileName ^Path %)) matches))

      :else
      (throw (ex-info (str "Multiple sessions found for " session)
                      {:session session :matches matches})))))

(defn- read-json-lines [file]
  (with-open [r (io/reader (.toFile file))]
    (doall
     (for [line (line-seq r)
           :let [line (str/trim line)]
           :when (seq line)]
       (json/parse-string line true)))))

(defn- read-json-file [file]
  (let [value (json/parse-string (slurp (.toFile file)) true)]
    (cond
      (sequential? value) value
      (map? value) [value]
      :else [])))

(defn- read-events [file]
  (if (str/ends-with? (str file) ".jsonl")
    (read-json-lines file)
    (try
      (read-json-file file)
      (catch Exception _
        ;; Some exported session files are JSONL even when named .json.
        (read-json-lines file)))))

(defn- history-search-roots [^Path file codex-roots]
  (let [parent (.getParent (.toAbsolutePath file))
        managed-root (some #(when (#{"sessions" "archived_sessions"}
                                    (str (.getFileName ^Path %))) %)
                           (take-while some? (iterate #(.getParent ^Path %) parent)))]
    (if managed-root
      (map #(str (.resolve (.getParent ^Path managed-root) ^String %))
           ["sessions" "archived_sessions"])
      (distinct (cons (str parent) codex-roots)))))

(defn- history-error [file detail]
  (ex-info (str "Invalid Codex history for " file ": " detail) {:file (str file)}))

(defn- read-history-prefix [^Path file {:keys [end_byte_offset end_ordinal_exclusive]}]
  (when-not (and (integer? end_byte_offset) (pos? end_byte_offset)
                 (<= end_byte_offset (Files/size file))
                 (integer? end_ordinal_exclusive) (pos? end_ordinal_exclusive))
    (throw (history-error file "invalid or out-of-bounds history cutoff")))
  (with-open [input (io/input-stream (.toFile file))]
    (let [bytes (.readNBytes input (Math/toIntExact (long end_byte_offset)))]
      (when-not (and (= end_byte_offset (alength bytes))
                     (= 10 (aget bytes (dec (alength bytes)))))
        (throw (history-error file "history byte cutoff is not a JSONL record boundary")))
      (let [events (mapv #(json/parse-string % true)
                         (remove str/blank? (str/split-lines (String. bytes "UTF-8"))))]
        (when-not (and (seq events)
                       (every? #(and (integer? (:ordinal %))
                                     (< (:ordinal %) end_ordinal_exclusive)) events)
                       (= end_ordinal_exclusive (inc (:ordinal (last events)))))
          (throw (history-error file "history byte and ordinal cutoffs disagree")))
        events))))

(defn- skill-instruction-message? [{:keys [type payload message]}]
  (let [content (case type
                  "event_msg" (when (= "user_message" (:type payload)) (:message payload))
                  "response_item" (when (and (= "message" (:type payload))
                                             (= "user" (:role payload))) (:content payload))
                  "message" (when (= "user" (:role message)) (:content message))
                  "user" (:content message)
                  nil)
        text (cond
               (string? content) content
               (map? content) (:text content)
               (sequential? content) (str/join "\n" (keep :text content))
               :else "")]
    ;; Match the complete injected wrapper, preserving invocations and discussion of skills.
    (boolean (re-matches #"(?s)<skill>\s*<name>[^<]+</name>\s*<path>[^<]+</path>.*</skill>"
                         (str/trim (or text ""))))))

(defn history-segments [file codex-roots]
  ;; history_base.thread_id is a physical rollout ID, not the logical fork parent.
  ;; Resolve it by the filename's final UUID, without selecting that parent's latest revert.
  (let [candidates (delay (->> (history-search-roots file codex-roots)
                               (mapcat #(files-under (path %)))
                               (map #(.toRealPath ^Path % (make-array java.nio.file.LinkOption 0)))
                               distinct
                               doall))]
    (loop [file file, cutoff nil, seen #{}, segments ()]
      (let [identity (.toRealPath ^Path file (make-array java.nio.file.LinkOption 0))]
        (when (contains? seen identity)
          (throw (history-error file "history reference cycle")))
        (let [events (if cutoff (read-history-prefix file cutoff) (read-events file))
              meta (when (= "session_meta" (:type (first events))) (:payload (first events)))
              base (:history_base meta)
              segments (conj segments events)]
          (when (and cutoff (not= "paginated" (:history_mode meta)))
            (throw (history-error file "source rollout is not paginated")))
          (if base
            (let [id (:thread_id base)
                  matches (when (string? id)
                            (filter #(let [stem (str/replace (str (.getFileName ^Path %))
                                                             #"\.jsonl?$" "")]
                                       (or (str/ends-with? stem (str "-" id))
                                           (str/ends-with? stem (str "_" id)))) @candidates))]
              (when-not (= 1 (count matches))
                (throw (history-error file (str "missing or ambiguous source rollout " id))))
              (recur (first matches) base (conj seen identity) segments))
            ;; Keep source ordinals and byte offsets intact until all cutoffs are checked.
            (mapv #(vec (remove skill-instruction-message? %)) segments)))))))

(defn- main [[mode source codex-home :as args]]
  (try
    (when-not (and (= 3 (count args)) (#{"file" "session" "archived-session"} mode))
      (throw (ex-info "Expected MODE SOURCE CODEX-HOME" {})))
    (let [roots (map #(str (io/file codex-home %)) ["sessions" "archived_sessions"])
          file (if (= "file" mode)
                 (path source)
                 (find-session source [(if (= "archived-session" mode)
                                         (second roots) (first roots))]))]
      (println (json/generate-string
                {:file (str file) :segments (history-segments file roots)})))
    (catch Exception error
      (binding [*out* *err*]
        (println (str "chat-history: " (ex-message error))))
      (System/exit 1))))

(when (= *file* (System/getProperty "babashka.file"))
  (main *command-line-args*))
