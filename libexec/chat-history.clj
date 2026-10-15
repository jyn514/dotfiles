;; Shared read-only session loading for extract-chat and codex-to-pi.
;; Library API: files-under lists JSON/JSONL inputs; find-session searches explicit roots in priority order;
;; history-segments returns event sequences, oldest ancestor first, omitting injected skill instructions.
;; history-ranges retains physical rollout identities for graph consumers.
;; Direct invocation: bb chat-history.clj MODE SOURCE CODEX-HOME [--branches].
;; MODE is file, session, or archived-session. Success writes one JSON object:
;; {"file": "selected path", "segments": [[exportable source events], ...]}.
;; --branches adds all related paginated rollouts as branches, each with file,
;; thread_id, rollout_id, selected, and ranges [{file, rollout_id, events}].
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
  (let [matches (some (fn [root]
                        (seq (->> (files-under (path root))
                                  (filter #(session-file-name-matches? session %))
                                  distinct
                                  (sort-by str))))
                      (remove nil? roots))]
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

(defn- physical-rollout-id [file]
  (second (re-find #"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl?$"
                   (str file))))

(defn history-ranges [file codex-roots]
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
              segments (conj segments {:file (str identity)
                                       :rollout_id (physical-rollout-id file)
                                       :events events})]
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
            (mapv #(update % :events (fn [events] (vec (remove skill-instruction-message? events))))
                  segments)))))))

(defn history-segments [file codex-roots]
  (mapv :events (history-ranges file codex-roots)))

(defn- session-header [file]
  ;; Family discovery needs only metadata, not every unrelated conversation.
  (try
    (with-open [reader (io/reader (.toFile ^Path file))]
      (let [event (some #(when-not (str/blank? %) (json/parse-string % true)) (line-seq reader))]
        (when (= "session_meta" (:type event)) (:payload event))))
    (catch Exception _ nil)))

(defn branch-histories [file codex-roots]
  (let [selected (.toRealPath ^Path file (make-array java.nio.file.LinkOption 0))
        selected-meta (session-header selected)
        entries (->> (history-search-roots selected codex-roots)
                     (mapcat #(files-under (path %)))
                     (cons selected)
                     (map #(.toRealPath ^Path % (make-array java.nio.file.LinkOption 0)))
                     distinct
                     (keep (fn [file]
                             (when-let [meta (session-header file)]
                               (when (or (= (:id meta) (:id selected-meta))
                                         (nil? (:parent_thread_id meta)))
                                 {:file file :meta meta :rollout_id (physical-rollout-id file)}))))
                     (sort-by (comp str :file))
                     vec)
        by-rollout (group-by :rollout_id entries)
        links (fn [{:keys [meta]}]
                (remove nil? [(:id meta) (:forked_from_id meta)
                              (when-let [base-id (get-in meta [:history_base :thread_id])]
                                (-> by-rollout (get base-id) first :meta :id))]))
        family (loop [ids #{(:id selected-meta)}]
                 (let [expanded (reduce (fn [ids entry]
                                          (let [neighbors (links entry)]
                                            (if (some ids neighbors) (into ids neighbors) ids)))
                                        ids entries)]
                   (if (= ids expanded) ids (recur expanded))))]
    (when-not (and (:id selected-meta) (= "paginated" (:history_mode selected-meta)))
      (throw (history-error file "--branches requires paginated Codex history")))
    (mapv (fn [{:keys [file meta rollout_id]}]
            (when-not (and rollout_id (= "paginated" (:history_mode meta)))
              (throw (history-error file "cannot join a related legacy or noncanonical rollout")))
            {:file (str file) :thread_id (:id meta) :rollout_id rollout_id
             :selected (= selected file) :ranges (history-ranges file codex-roots)})
          (filter #(contains? family (get-in % [:meta :id])) entries))))

(defn- main [[mode source codex-home branches :as args]]
  (try
    (when-not (and (or (= 3 (count args))
                       (and (= 4 (count args)) (= "--branches" branches)))
                   (#{"file" "session" "archived-session"} mode))
      (throw (ex-info "Expected MODE SOURCE CODEX-HOME [--branches]" {})))
    (let [roots (map #(str (io/file codex-home %)) ["sessions" "archived_sessions"])
          file (if (= "file" mode)
                 (path source)
                 (find-session source [(if (= "archived-session" mode)
                                         (second roots) (first roots))]))]
      (println (json/generate-string
                (cond-> {:file (str file) :segments (history-segments file roots)}
                  branches (assoc :branches (branch-histories file roots))))))
    (catch Exception error
      (binding [*out* *err*]
        (println (str "chat-history: " (ex-message error))))
      (System/exit 1))))

(when (= *file* (System/getProperty "babashka.file"))
  (main *command-line-args*))
