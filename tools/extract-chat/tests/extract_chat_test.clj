(ns tools.extract-chat-test
  (:require [babashka.fs :as fs]
            [cheshire.core :as json]
            [clojure.java.io :as io]
            [clojure.java.shell :as shell]
            [clojure.string :as str]
            [clojure.test :refer [deftest is run-tests testing]]))

(load-file "tools/extract-chat/extract-chat")
(alias 'extract-chat 'tools.extract-chat)

(deftest extract-chat-default-root-prefers-codex-home
  (is (= "/tmp/custom-codex/sessions"
         (extract-chat/default-root {"CODEX_HOME" "/tmp/custom-codex"})))
  (is (= "/tmp/custom-codex/archived_sessions"
         (extract-chat/default-root {"CODEX_HOME" "/tmp/custom-codex"} true)))
  (is (= (str (System/getProperty "user.home") "/.codex/sessions")
         (extract-chat/default-root {}))))

(deftest extract-chat-extract-dir-writes-markdown-files
  (let [root (fs/create-temp-dir {:prefix "flower-extract-chat"})
        session-file (fs/file root "session.jsonl")
        extract-dir (fs/file root "markdown")
        event (fn [payload] (json/generate-string {:type "event_msg"
                                             :payload payload}))]
    (spit session-file
          (str (event {:type "user_message"
                       :message "Make tea."})
               "\n"
               (event {:type "agent_message"
                       :phase "final_answer"
                       :message "Tea is ready."})
               "\n"))
    (let [stdout (java.io.StringWriter.)
          exit (binding [*out* stdout]
                 (extract-chat/main ["--extract-dir" (str extract-dir) (str session-file)]))
          markdown-files (->> (file-seq (fs/file extract-dir))
                              (filter #(.isFile %))
                              (map fs/file-name)
                              sort)
          markdown (slurp (fs/file extract-dir "session.md"))]
      (is (nil? exit))
      (is (= "" (str stdout)))
      (is (= ["session.md"] markdown-files))
      (is (= (str "# " session-file "\n\n"
                  "## User\n\n"
                  "Make tea.\n\n"
                  "## Assistant\n\n"
                  "Tea is ready.\n\n")
             markdown)))))

(deftest extract-chat-empty-input-reports-sources-without-changing-success-status
  (let [root (fs/create-temp-dir {:prefix "flower-extract-empty"})
        empty-dir (fs/file root "empty sessions")
        missing-dir (fs/file root "missing sessions")
        extract-dir (fs/file root "exports")]
    (try
      (fs/create-dirs empty-dir)
      (spit (fs/file empty-dir "not-a-session.txt") "Ignored")
      (doseq [options [[] ["--native"] ["--extract-dir" (str extract-dir)]
                      ["--extract-dir" (str extract-dir) "--native"]]]
        (let [{:keys [exit out err]}
              (apply shell/sh "bb" "tools/extract-chat/extract-chat"
                     (concat options [(str empty-dir) (str missing-dir)]))]
          (is (= 0 exit))
          (is (= "" out))
          (is (= (str "extract-chat: No session files found in: " empty-dir ", " missing-dir "\n")
                 err))
          (is (not (fs/exists? extract-dir)))))
      (finally (fs/delete-tree root)))))

(deftest extract-chat-empty-default-root-reports-the-selected-root
  (let [root (fs/create-temp-dir {:prefix "flower-extract-empty-default"})
        extract-dir (fs/file root "exports")
        stdout (java.io.StringWriter.)
        stderr (java.io.StringWriter.)]
    (try
      (with-redefs [extract-chat/default-root (constantly (str root))]
        (binding [*out* stdout *err* stderr]
          (extract-chat/main ["--extract-dir" (str extract-dir)])))
      (is (= "" (str stdout)))
      (is (= (str "extract-chat: No session files found in: " root "\n") (str stderr)))
      (is (not (fs/exists? extract-dir)))
      (finally (fs/delete-tree root)))))

(deftest extract-chat-empty-first-root-does-not-warn-when-later-root-has-sessions
  (let [root (fs/create-temp-dir {:prefix "flower-extract-empty-first"})
        empty-dir (fs/file root "empty")
        populated-dir (fs/file root "populated")
        stdout (java.io.StringWriter.)
        stderr (java.io.StringWriter.)]
    (try
      (fs/create-dirs empty-dir)
      (fs/create-dirs populated-dir)
      (let [session-file (fs/file populated-dir "session.jsonl")]
        (spit session-file
              (str (json/generate-string {:type "message" :message {:role "user" :content "Make tea."}})
                   "\n"))
        (binding [*out* stdout *err* stderr]
          (extract-chat/main [(str empty-dir) (str populated-dir)]))
        (is (= (str "# " session-file "\n\n## User\n\nMake tea.\n\n") (str stdout)))
        (is (= "" (str stderr))))
      (finally (fs/delete-tree root)))))

(deftest extract-chat-extract-dir-deduplicates-resumed-codex-prefix
  (let [root (fs/create-temp-dir {:prefix "flower-extract-resumed-chat"})
        first-session (fs/file root "rollout-z-original.jsonl")
        resumed-session (fs/file root "rollout-a-resumed.jsonl")
        extract-dir (fs/file root "markdown")
        session-id "019abcde-1234-7000-8000-0123456789ab"
        event (fn [payload] (json/generate-string {:type "event_msg"
                                             :payload payload}))
        meta-event (fn [id timestamp]
                     (json/generate-string {:timestamp timestamp
                                      :type "session_meta"
                                      :payload {:id id
                                                :session_id session-id
                                                :timestamp timestamp}}))
        repeated-events [(event {:type "user_message"
                                 :message "Make tea."})
                         (event {:type "agent_message"
                                 :phase "final_answer"
                                 :message "Tea is ready."})]]
    (spit first-session
          (str (str/join "\n" (into [(meta-event session-id "2026-07-20T10:00:00Z")]
                                    repeated-events))
               "\n"))
    (spit resumed-session
          (str (str/join "\n" (into [(meta-event "019abcde-1234-7000-8000-111111111111"
                                                 "2026-07-20T11:00:00Z")]
                                    (concat repeated-events
                                            [(event {:type "user_message"
                                                     :message "Pour it."})
                                             (event {:type "agent_message"
                                                     :phase "final_answer"
                                                     :message "Tea is poured."})])))
               "\n"))
    (extract-chat/main ["--extract-dir" (str extract-dir) (str root)])
    (is (= (str "# " first-session "\n\n"
                "## User\n\nMake tea.\n\n"
                "## Assistant\n\nTea is ready.\n\n")
           (slurp (fs/file extract-dir "rollout-z-original.md"))))
    (is (= (str "# " resumed-session "\n\n"
                "## User\n\nPour it.\n\n"
                "## Assistant\n\nTea is poured.\n\n")
           (slurp (fs/file extract-dir "rollout-a-resumed.md"))))))

(deftest extract-chat-handles-claude-code-jsonl
  (let [root (fs/create-temp-dir {:prefix "flower-extract-claude"})
        session-file (fs/file root "claude-session.jsonl")]
    (spit session-file
          (str (json/generate-string {:type "user"
                                :message {:role "user"
                                          :content "Make tea."}})
               "\n"
               (json/generate-string {:type "permission-mode"
                                :mode "default"})
               "\n"
               (json/generate-string {:type "assistant"
                                :message {:role "assistant"
                                          :content [{:type "text"
                                                     :text "Tea is ready."}
                                                    {:type "tool_use"
                                                     :name "Write"
                                                     :input {:file_path "tea.txt"}}]}})
               "\n"
               (json/generate-string {:type "user"
                                :message {:role "user"
                                          :content [{:type "tool_result"
                                                     :content "wrote tea.txt"}]}})
               "\n"))
    (let [stdout (java.io.StringWriter.)
          exit (binding [*out* stdout]
                 (extract-chat/main [(str session-file)]))]
      (is (nil? exit))
      (is (= (str "# " session-file "\n\n"
                  "## User\n\n"
                  "Make tea.\n\n"
                  "## Assistant\n\n"
                  "Tea is ready.\n\n")
             (str stdout))))))

(deftest extract-chat-handles-pi-session-jsonl
  (let [root (fs/create-temp-dir {:prefix "flower-extract-pi"})
        session-file (fs/file root "session.jsonl")
        event (fn [role content]
                (json/generate-string
                 {:type "message"
                  :message {:role role :content content}}))]
    (spit session-file
          (str (json/generate-string {:type "session" :version 3
                                      :id "pi-session" :timestamp "2026-09-17T00:00:00Z"})
               "\n"
               (event "user" [{:type "text" :text "Make tea."}]) "\n"
               (event "assistant" [{:type "text" :text "Tea is ready."}
                                    {:type "toolCall" :name "shell"}]) "\n"))
    (let [stdout (java.io.StringWriter.)]
      (binding [*out* stdout]
        (extract-chat/main [(str session-file)]))
      (is (= (str "# " session-file "\n\n"
                  "## User\n\nMake tea.\n\n"
                  "## Assistant\n\nTea is ready.\n\n")
             (str stdout))))))

(deftest extract-chat-pi-goals-models-and-cancellations-keep-transcript-order
  (let [root (fs/create-temp-dir {:prefix "flower-extract-pi-events"})
        session-file (fs/file root "session.jsonl")
        extract-dir (fs/file root "markdown")
        goal (fn [status]
               {:type "custom" :customType "pi-codex-goal"
                :data {:version 1 :kind "set"
                       :goal {:objective "Make tea." :status status :tokenBudget 200}}})
        message (fn [value] {:type "message" :message value})]
    (try
      (spit session-file
            (str (str/join "\n" (map json/generate-string
                  [{:type "session" :version 3 :id "pi-events"}
                   {:type "message" :message {:role "user" :content "Start."}}
                   (goal "active")
                   {:type "model_change" :provider "openai-codex" :modelId "model-one"}
                   {:type "custom" :customType "pi-codex-goal"
                    :data {:version 1 :kind "usage" :usage {:tokensUsed 900}}}
                   {:type "custom_message" :customType "pi-codex-goal"
                    :content "Do not repeat this goal continuation."}
                   (message {:role "assistant" :content [{:type "text" :text "Heating water."}]
                             :stopReason "aborted" :errorMessage "Operation aborted"})
                   {:type "model_change" :provider "anthropic" :modelId "model-two"}
                   (goal "paused")
                   (message {:role "assistant" :content [] :stopReason "aborted"})
                   (message {:role "bashExecution" :command "boil-water"
                             :output "Tool output stays hidden" :cancelled true})
                   (message {:role "assistant" :content "Tea is ready." :stopReason "stop"
                             :provider "anthropic" :model "model-two"})
                   (goal "complete")])) "\n"))
      (let [expected (str "# " session-file "\n\n"
                          "## User\n\nStart.\n\n"
                          "## Goal (active)\n\nMake tea.\n\nToken budget: 200\n\n"
                          "## Model change\n\nopenai-codex/model-one\n\n"
                          "## Assistant\n\nHeating water.\n\n"
                          "## Cancellation\n\nOperation aborted\n\n"
                          "## Model change\n\nanthropic/model-two\n\n"
                          "## Goal (paused)\n\nMake tea.\n\nToken budget: 200\n\n"
                          "## Cancellation\n\nAssistant response cancelled.\n\n"
                          "## Cancellation\n\nShell command cancelled.\n\nCommand: boil-water\n\n"
                          "## Assistant\n\nTea is ready.\n\n"
                          "## Goal (complete)\n\nMake tea.\n\nToken budget: 200\n\n")]
        (is (= expected (with-out-str (extract-chat/main [(str session-file)]))))
        (extract-chat/main ["--final-only" "--extract-dir" (str extract-dir) (str session-file)])
        (is (= expected (slurp (fs/file extract-dir "session.md")))))
      (finally (fs/delete-tree root)))))

(deftest extract-chat-pi-event-only-sessions-produce-markdown
  (let [root (fs/create-temp-dir {:prefix "flower-extract-pi-event-only"})
        extract-dir (fs/file root "markdown")]
    (try
      (doseq [[name event expected]
              [["goal" {:type "custom" :customType "pi-codex-goal"
                        :data {:version 1 :kind "set" :source "command"
                               :goal {:objective "Make tea." :status "active" :tokenBudget nil}}}
                "## Goal (active)\n\nMake tea.\n\n"]
               ["model" {:type "model_change" :provider "openai-codex" :modelId "model-one"}
                "## Model change\n\nopenai-codex/model-one\n\n"]
               ["cancellation" {:type "message"
                                :message {:role "assistant" :content [{:type "thinking" :thinking "hidden"}]
                                          :stopReason "aborted"}}
                "## Cancellation\n\nAssistant response cancelled.\n\n"]]]
        (let [session-file (fs/file root (str name ".jsonl"))]
          (spit session-file (str (json/generate-string {:type "session" :version 3 :id name})
                                 "\n" (json/generate-string event) "\n"))
          (extract-chat/main ["--extract-dir" (str extract-dir) (str session-file)])
          (is (= (str "# " session-file "\n\n" expected)
                 (slurp (fs/file extract-dir (str name ".md")))))))
      (finally (fs/delete-tree root)))))

(deftest extract-chat-matches-session-id-filename-forms
  (let [root (fs/create-temp-dir {:prefix "flower-extract-session-names"})
        matcher (deref #'dotfiles.chat-history/session-file-name-matches?)]
    (doseq [[filename expected]
            [["01a0a66d-2c73-77d5-83a1-43ca8362dc92.jsonl" true]
             ["rollout-2026-09-15-01a0a66d-2c73-77d5-83a1-43ca8362dc92.jsonl" true]
             ["2026-09-15T18-56-07-795Z_01a0a66d-2c73-77d5-83a1-43ca8362dc92.jsonl" true]
             ["rollout-2026-09-15-01a0a66d-2c73-77d5-83a1-43ca8362dc92_01a13b22-1a3a-75c2-a8d2-3a3e381f9973.jsonl" true]
             ["rollout-2026-09-15-other_01a0a66d-2c73-77d5-83a1-43ca8362dc92_extra.jsonl" false]
             ["rollout-2026-09-15-other.jsonl" false]]]
      (let [file (fs/file root filename)]
        (spit file "{}")
        (is (= expected
               (matcher "01a0a66d-2c73-77d5-83a1-43ca8362dc92" (.toPath file))))))))

(deftest extract-chat-selects-newest-codex-rollout-by-session-id
  (let [root (fs/create-temp-dir {:prefix "flower-extract-rollouts"})
        session-id "01a13b22-06ae-7ad1-a2c5-bc418dcfe355"
        original (fs/file root (str "rollout-2026-10-14T17-57-28-" session-id ".jsonl"))
        later (fs/file root (str "rollout-2026-10-14T17-57-33-" session-id
                                 "_01a13b22-1a3a-75c2-a8d2-3a3e381f9973.jsonl"))
        last-file (fs/file root (str "rollout-2026-10-14T18-24-15-" session-id
                                     "_01a13b3a-8c7b-7e72-aa63-505f516f8d4e.jsonl"))]
    (try
      (spit original "{}\n")
      (doseq [[file text] [[later "Make tea."] [last-file "Pour tea."]
                           [(fs/file root "rollout-unrelated.jsonl") "Unrelated."]]]
        (spit file (str (json/generate-string
                         {:type "response_item"
                          :payload {:type "message" :role "user"
                                    :content [{:type "input_text" :text text}]}}) "\n")))
      (with-redefs [extract-chat/default-root (constantly (str root))
                    extract-chat/pi-root (constantly (str (fs/file root "pi")))]
        (is (= (str "# " last-file "\n\n## User\n\nPour tea.\n\n")
               (with-out-str (extract-chat/main ["--session" session-id])))))
      (finally (fs/delete-tree root)))))

(defn- write-paginated-rollout [file id base texts]
  (fs/create-dirs (fs/parent file))
  (let [start (or (:end_ordinal_exclusive base) 0)]
    (spit file
          (str (str/join "\n"
                         (map json/generate-string
                              (into [{:type "session_meta" :ordinal start
                                      :payload (cond-> {:id id :session_id id
                                                        :history_mode "paginated"}
                                                 base (assoc :history_base base))}]
                                    (map-indexed
                                     (fn [i text]
                                       (assoc (if (map? text)
                                                text
                                                {:type "response_item"
                                                 :payload {:type "message" :role "user"
                                                           :content [{:type "input_text" :text text}]}})
                                              :ordinal (+ start i 1)))
                                     texts)))) "\n"))))

(defn- history-position [file rollout-id record-count end-ordinal]
  {:thread_id rollout-id :end_ordinal_exclusive end-ordinal
   :end_byte_offset (alength (.getBytes
                             (str (str/join "\n" (take record-count (str/split-lines (slurp file)))) "\n")
                             "UTF-8"))})

(deftest extract-chat-reconstructs-fork-and-revert-history
  (let [root (fs/create-temp-dir {:prefix "flower-extract-lineage"})
        parent-id "01a13add-f050-7e93-88cc-a70f0bf1b3d3"
        parent-rollout "01a13b1f-1fb7-7e43-ac66-54cca4b4cdb8"
        child-id "01a13b22-06ae-7ad1-a2c5-bc418dcfe355"
        child-rollout "01a13b3a-8c7b-7e72-aa63-505f516f8d4e"
        parent (fs/file root "archived_sessions" (str "rollout-2026-10-14T16-43-05-" parent-id ".jsonl"))
        reverted-parent (fs/file root "archived_sessions"
                                 (str "rollout-2026-10-14T17-54-17-" parent-id "_" parent-rollout ".jsonl"))
        child (fs/file root "sessions" "2026" "10" "14"
                       (str "rollout-2026-10-14T17-57-28-" child-id ".jsonl"))
        latest (fs/file (fs/parent child)
                        (str "rollout-2026-10-14T18-24-15-" child-id "_" child-rollout ".jsonl"))
        unrelated-parent (fs/file root "archived_sessions"
                                  (str "rollout-2026-10-14T19-00-00-" parent-id
                                       "_01a13b3a-8c7b-7e72-aa63-505f516fffff.jsonl"))
        output-dir (fs/file root "markdown")]
    (try
      ;; Older inherited segments can use event_msg while the child uses response_item.
      (write-paginated-rollout parent parent-id nil
                              [{:type "event_msg" :payload {:type "user_message" :message "café"}}
                               "discarded parent turn"])
      (write-paginated-rollout reverted-parent parent-id
                              (history-position parent parent-id 2 2)
                              ["parent continuation" "after fork cutoff"])
      (write-paginated-rollout child child-id
                              (history-position reverted-parent parent-rollout 2 4)
                              ["discarded child turn"])
      ;; An empty intermediate segment still contributes its inherited history.
      (write-paginated-rollout latest child-id
                              (history-position child child-id 1 5)
                              ["current child turn"])
      (write-paginated-rollout unrelated-parent parent-id nil ["different parent branch"])
      (with-redefs [extract-chat/default-root
                    (fn
                      ([_] (str (fs/file root "sessions")))
                      ([_ archived?] (str (fs/file root (if archived? "archived_sessions" "sessions")))))
                    extract-chat/pi-root (constantly (str (fs/file root "pi")))]
        (let [expected (str "# " latest "\n\n## User\n\ncafé\n\n"
                            "## User\n\nparent continuation\n\n"
                            "## User\n\ncurrent child turn\n\n")]
          (is (= expected (with-out-str (extract-chat/main ["--session" child-id]))))
          (is (= expected (with-out-str (extract-chat/main [(str latest)]))))
          (is (= expected (with-out-str (extract-chat/main ["--final-only" "--session" child-id]))))
          (extract-chat/main ["--session" child-id "--extract-dir" (str output-dir)])
          (is (= expected (slurp (fs/file output-dir
                                         (str/replace (fs/file-name latest) #"\.jsonl$" ".md")))))))
      (finally (fs/delete-tree root)))))

(deftest extract-chat-rejects-incomplete-history-before-printing
  (let [root (fs/create-temp-dir {:prefix "flower-extract-invalid-lineage"})
        parent-id "01a13add-f050-7e93-88cc-a70f0bf1b3d3"
        child-id "01a13b22-06ae-7ad1-a2c5-bc418dcfe355"
        parent (fs/file root "sessions" (str "rollout-2026-10-14T16-43-05-" parent-id ".jsonl"))
        child (fs/file root "sessions" (str "rollout-2026-10-14T17-57-28-" child-id ".jsonl"))]
    (try
      (write-paginated-rollout parent parent-id nil ["inherited"])
      (let [valid (history-position parent parent-id 2 2)]
        (doseq [[base error]
                [[(assoc valid :thread_id "missing") #"missing or ambiguous source"]
                 [(assoc valid :end_byte_offset 999999) #"out-of-bounds"]
                 [(update valid :end_byte_offset dec) #"record boundary"]
                 [(assoc valid :end_ordinal_exclusive 1) #"cutoffs disagree"]
                 [(assoc valid :end_ordinal_exclusive 3) #"cutoffs disagree"]
                 [(assoc valid :thread_id child-id) #"reference cycle"]]]
          (write-paginated-rollout child child-id base ["child"])
          (let [stdout (java.io.StringWriter.)]
            (binding [*out* stdout]
              (is (thrown-with-msg? clojure.lang.ExceptionInfo error
                                   (extract-chat/main [(str child)]))))
            (is (= "" (str stdout))))))
      (finally (fs/delete-tree root)))))

(deftest extract-chat-keeps-materialized-legacy-forks-self-contained
  (let [root (fs/create-temp-dir {:prefix "flower-extract-legacy-fork"})
        file (fs/file root "legacy.jsonl")]
    (try
      (spit file (str (json/generate-string
                      {:type "session_meta" :payload {:id "legacy" :forked_from_id "unavailable"}})
                     "\n"
                     (json/generate-string
                      {:type "event_msg" :payload {:type "user_message" :message "Already copied."}})
                     "\n"))
      (is (= (str "# " file "\n\n## User\n\nAlready copied.\n\n")
             (with-out-str (extract-chat/main [(str file)]))))
      (finally (fs/delete-tree root)))))

(deftest extract-chat-prefers-codex-source-over-pi-import-with-the-same-id
  (let [root (fs/create-temp-dir {:prefix "flower-extract-source-priority"})
        codex-root (fs/file root "codex")
        pi-root (fs/file root "pi")
        session-id "019abcde-1234-7000-8000-0123456789ab"
        codex (fs/file codex-root (str "rollout-2026-07-15-" session-id ".jsonl"))
        pi (fs/file pi-root (str "timestamp_" session-id ".jsonl"))]
    (try
      (fs/create-dirs codex-root)
      (fs/create-dirs pi-root)
      (spit codex (str (json/generate-string
                        {:type "event_msg" :payload {:type "user_message" :message "Codex source"}}) "\n"))
      (spit pi (str (json/generate-string
                     {:type "message" :message {:role "user" :content "Pi import"}}) "\n"))
      (with-redefs [extract-chat/default-root (constantly (str codex-root))
                    extract-chat/pi-root (constantly (str pi-root))]
        (is (= (str "# " codex "\n\n## User\n\nCodex source\n\n")
               (with-out-str (extract-chat/main ["--session" session-id]))))
        (fs/delete codex)
        (is (= (str "# " pi "\n\n## User\n\nPi import\n\n")
               (with-out-str (extract-chat/main ["--session" session-id])))))
      (finally (fs/delete-tree root)))))

(deftest extract-chat-positional-session-ids-respect-flags-and-existing-paths
  (let [root (fs/create-temp-dir {:prefix "flower-extract-positional-id"})
        session-id "019abcde-1234-7000-8000-0123456789ab"
        active (fs/file root "active")
        archived (fs/file root "archived")
        local-path (fs/file root session-id)
        event (fn [text] (str (json/generate-string
                              {:type "event_msg" :payload {:type "user_message" :message text}}) "\n"))]
    (try
      (fs/create-dirs active)
      (fs/create-dirs archived)
      (spit (fs/file active (str "rollout-2026-07-15-" session-id ".jsonl")) (event "Active"))
      (spit (fs/file archived (str "rollout-2026-07-15-" session-id ".jsonl")) (event "Archived"))
      (fs/create-dirs local-path)
      (spit (fs/file local-path "local.jsonl") (event "Local path"))
      (with-redefs [extract-chat/default-root
                    (fn
                      ([_] (str active))
                      ([_ archived?] (str (if archived? archived active))))
                    extract-chat/pi-root (constantly (str (fs/file root "pi")))]
        (doseq [flags [[] ["--archived"] ["--final-only"]]]
          (is (= (with-out-str (extract-chat/main (into ["--session" session-id] flags)))
                 (with-out-str (extract-chat/main (into [session-id] flags))))))
        (let [output (with-out-str (extract-chat/main [session-id (str local-path)]))]
          (is (str/includes? output "Active"))
          (is (str/includes? output "Local path")))
        (let [output (with-out-str (extract-chat/main [(str local-path)]))]
          (is (str/includes? output "Local path"))
          (is (not (str/includes? output "Active"))))
        (is (thrown-with-msg? clojure.lang.ExceptionInfo #"No session found"
                             (extract-chat/main ["019abcde-1234-7000-8000-000000000000"]))))
      (let [{:keys [exit out err]}
            (shell/sh "bb" (str (fs/absolutize "tools/extract-chat/extract-chat")) session-id
                      :dir (str root))]
        (is (= 0 exit) err)
        (is (str/includes? out "Local path")))
      (finally (fs/delete-tree root)))))

(deftest extract-chat-finds-pi-session-by-id
  (let [root (fs/create-temp-dir {:prefix "flower-extract-pi-session"})
        session-id "01a0a66d-2c73-77d5-83a1-43ca8362dc92"
        session-file (fs/file root (str "2026-09-15T18-56-07-795Z_" session-id ".jsonl"))]
    (spit session-file
          (str (json/generate-string {:type "message"
                                      :message {:role "user" :content "Make tea."}})
               "\n"))
    (let [stdout (java.io.StringWriter.)]
      (with-redefs [extract-chat/pi-root (constantly (str root))]
        (binding [*out* stdout]
          (extract-chat/main ["--session" session-id])))
      (is (= (str "# " session-file "\n\n"
                  "## User\n\nMake tea.\n\n")
             (str stdout))))))

(deftest extract-chat-finds-archived-codex-session-by-id
  (let [root (fs/create-temp-dir {:prefix "flower-extract-archived-codex"})
        sessions-root (fs/file root "sessions")
        archived-root (fs/file root "archived_sessions")
        session-id "019abcde-1234-7000-8000-0123456789ab"
        archived-file (fs/file archived-root (str "rollout-2026-07-15-" session-id ".jsonl"))]
    (fs/create-dirs sessions-root)
    (fs/create-dirs archived-root)
    (spit archived-file
          (str (json/generate-string {:type "event_msg"
                                      :payload {:type "user_message"
                                                :message "Recover the tea."}})
               "\n"))
    (let [stdout (java.io.StringWriter.)]
      (with-redefs [extract-chat/default-root
                    (fn
                      ([_] (str sessions-root))
                      ([_ archived?] (str (if archived? archived-root sessions-root))))]
        (binding [*out* stdout]
          (extract-chat/main ["--archived" "--session" session-id])))
      (is (= (str "# " archived-file "\n\n"
                  "## User\n\nRecover the tea.\n\n")
             (str stdout))))))

(deftest extract-chat-finds-codex-session-by-id
  (let [root (fs/create-temp-dir {:prefix "flower-extract-codex"})
        session-id "019abcde-1234-7000-8000-0123456789ab"
        session-file (fs/file root "2026" "07" "15"
                              (str "rollout-2026-07-15T12-00-00-" session-id ".jsonl"))]
    (fs/create-dirs (fs/parent session-file))
    (spit session-file
          (str (json/generate-string {:type "event_msg"
                                :payload {:type "user_message"
                                          :message "Make tea."}})
               "\n"))
    (let [stdout (java.io.StringWriter.)]
      (with-redefs [extract-chat/default-root (constantly (str root))]
        (binding [*out* stdout]
          (extract-chat/main ["--session" session-id])))
      (is (= (str "# " session-file "\n\n"
                  "## User\n\n"
                  "Make tea.\n\n")
             (str stdout))))))

(deftest extract-chat-handles-current-codex-content-parts
  (let [root (fs/create-temp-dir {:prefix "flower-extract-current-codex"})
        session-file (fs/file root "session.jsonl")]
    (spit session-file
          (str (json/generate-string
                {:type "response_item"
                 :payload {:type "message"
                           :role "user"
                           :content [{:type "input_text" :text "Make tea."}]}})
               "\n"
               (json/generate-string
                {:type "response_item"
                 :payload {:type "message"
                           :role "assistant"
                           :phase "final_answer"
                           :content [{:type "output_text" :text "Tea is ready."}]}})
               "\n"))
    (let [stdout (java.io.StringWriter.)]
      (binding [*out* stdout]
        (extract-chat/main [(str session-file)]))
      (is (= (str "# " session-file "\n\n"
                  "## User\n\nMake tea.\n\n"
                  "## Assistant\n\nTea is ready.\n\n")
             (str stdout))))))

(deftest extract-chat-omits-synthetic-codex-user-messages
  (let [root (fs/create-temp-dir {:prefix "flower-extract-synthetic-codex"})
        session-file (fs/file root "session.jsonl")
        message (fn [text]
                  (json/generate-string
                   {:type "response_item"
                    :payload {:type "message" :role "user"
                              :content [{:type "input_text" :text text}]}}))]
    (spit session-file
          (str (str/join "\n" [(message "# AGENTS.md instructions for /src/work\n\nRules")
                                (message "<environment_context>\n  <cwd>/src/work</cwd>")
                                (message "Make tea.")])
               "\n"))
    (let [stdout (java.io.StringWriter.)]
      (binding [*out* stdout]
        (extract-chat/main [(str session-file)]))
      (is (= (str "# " session-file "\n\n## User\n\nMake tea.\n\n")
             (str stdout))))))

(deftest extract-chat-native-exports-pi-html-and-keeps-other-formats-markdown
  (let [root (fs/create-temp-dir {:prefix "flower-extract-native"})
        input-dir (fs/file root "sessions with spaces")
        extract-dir (fs/file root "exports with spaces")
        calls (atom [])]
    (try
      (fs/create-dirs input-dir)
      ;; A Pi session with only tool output still has a native export.
      (doseq [filename ["pi.jsonl" "tool-only.json"]]
        (spit (fs/file input-dir filename)
              (str (json/generate-string {:type "session" :version 3 :id filename})
                   "\n"
                   (json/generate-string
                    {:type "message" :message {:role "toolResult" :content "Tool output"}})
                   "\n")))
      (spit (fs/file input-dir "codex.jsonl")
            (str (json/generate-string
                  {:type "event_msg" :payload {:type "user_message" :message "Make tea."}})
                 "\n"))
      (spit (fs/file input-dir "claude.jsonl")
            (str (json/generate-string
                  {:type "user" :message {:role "user" :content "Pour tea."}})
                 "\n"))
      (with-redefs [shell/sh (fn [& args]
                              (swap! calls conj (vec args))
                              (spit (last args) "<html>Native Pi export</html>")
                              {:exit 0 :out (str (last args) "\n") :err ""})]
        (extract-chat/main ["--native" "--final-only" "--extract-dir"
                            (str extract-dir) (str input-dir)]))
      (is (= [["pi" "--export" (str (fs/file input-dir "pi.jsonl"))
               (str (fs/file extract-dir "pi.html"))]
              ["pi" "--export" (str (fs/file input-dir "tool-only.json"))
               (str (fs/file extract-dir "tool-only.html"))]]
             @calls))
      (is (= ["claude.md" "codex.md" "pi.html" "tool-only.html"]
             (sort (map fs/file-name (fs/list-dir extract-dir)))))
      (is (= "<html>Native Pi export</html>" (slurp (fs/file extract-dir "pi.html"))))
      (is (str/includes? (slurp (fs/file extract-dir "codex.md")) "Make tea."))
      (is (str/includes? (slurp (fs/file extract-dir "claude.md")) "Pour tea."))
      (finally (fs/delete-tree root)))))

;; Delegation compatibility only: Pi's unknown default destination remains held,
;; not certified source-safe by the known-destination preflight.
(deftest extract-chat-native-without-output-dir-uses-pi-default-output
  (let [root (fs/create-temp-dir {:prefix "flower-extract-native-default"})
        session-id "test-native-session"
        session-file (fs/file root (str "timestamp_" session-id ".jsonl"))
        calls (atom [])]
    (try
      (spit session-file (str (json/generate-string {:type "session" :version 3 :id session-id}) "\n"))
      (with-redefs [extract-chat/pi-root (constantly (str root))
                    shell/sh (fn [& args]
                               (swap! calls conj (vec args))
                               {:exit 0 :out "Exported to pi-session.html\n" :err ""})]
        (is (= "Exported to pi-session.html\n"
               (with-out-str (extract-chat/main ["--native" "--session" session-id])))))
      (is (= [["pi" "--export" (str session-file)]] @calls))
      (finally (fs/delete-tree root)))))

(deftest extract-chat-codex-native-failures-clean-up-and-stop
  (doseq [failure ["conversion" "export"]]
    (let [root (fs/create-temp-dir {:prefix "flower-extract-native-codex"})
          file (fs/file root "codex.jsonl")
          output (fs/file root "exports")
          converted (atom nil)
          calls (atom [])]
      (try
        (spit file (str (json/generate-string {:type "session_meta" :payload {:session_id "test"}}) "\n"))
        (with-redefs [shell/sh
                      (fn [& args]
                        (swap! calls conj (vec args))
                        (if (= "python3" (first args))
                          (do
                            (reset! converted (last args))
                            (is (some #{"--branches"} args))
                            (spit @converted "{}\n")
                            (if (= "conversion" failure)
                              {:exit 1 :out "" :err "conversion failed"}
                              {:exit 0 :out "temporary conversion output" :err ""}))
                          (do
                            (is (fs/exists? @converted))
                            {:exit 2 :out "" :err "export failed"})))]
          (is (thrown-with-msg? clojure.lang.ExceptionInfo #"failed"
                               (extract-chat/main ["--branches" "--native" "--extract-dir" (str output)
                                                   (str file)]))))
        (is (= (if (= "conversion" failure) 1 2) (count @calls)))
        (is (not (fs/exists? (fs/parent @converted))))
        (is (empty? (fs/glob root "**/*.html")))
        (finally (fs/delete-tree root))))))

(deftest extract-chat-native-export-failure-stops-without-markdown-fallback
  (let [root (fs/create-temp-dir {:prefix "flower-extract-native-failure"})
        session-file (fs/file root "pi.jsonl")
        extract-dir (fs/file root "exports")
        calls (atom [])]
    (try
      (spit session-file (str (json/generate-string {:type "session" :version 3 :id "pi"}) "\n"))
      (with-redefs [shell/sh (fn [& args]
                              (swap! calls conj (vec args))
                              {:exit 2 :out "" :err "Export refused"})]
        (is (thrown-with-msg? clojure.lang.ExceptionInfo #"Pi export failed.*Export refused"
                             (extract-chat/main ["--native" "--extract-dir" (str extract-dir)
                                                 (str session-file) (str session-file)]))))
      (is (= 1 (count @calls)))
      (is (empty? (fs/list-dir extract-dir)))
      (finally (fs/delete-tree root)))))

(defn- write-export-fixture [file text native?]
  (io/make-parents file)
  (spit file (str (when native?
                    (str (json/generate-string {:type "session" :version 3 :id (str file)}) "\n"))
                  (json/generate-string {:type "message" :message {:role "user" :content text}})
                  "\n")))

(defn- fixture-export-environment
  ([root] (fixture-export-environment root false))
  ([root include-source?]
    (let [bin (fs/file root "fixture-bin")
          exporter (fs/file bin "pi")
          converter (fs/file bin "python3")
          calls (fs/file root "pi-calls")]
      (fs/create-dirs bin)
      ;; Exercise the real CLI subprocess boundary, not a replacement allocation or
      ;; writer. The fixture implements only the intended explicit-output Pi API.
      (spit exporter (str "#!/bin/sh\nset -eu\n"
                         "printf '%s\\n' \"$@\" >> \"$EXTRACT_CHAT_PI_CALLS\"\n"
                         "[ \"$#\" -eq 3 ]\n[ \"$1\" = '--export' ]\n"
                         "printf '<html>fixture export</html>\\n' > \"$3\"\n"
                         (when include-source? "cat \"$2\" >> \"$3\"\n")))
      (.setExecutable exporter true)
      (fs/copy "tools/extract-chat/tests/fixtures/converter-spy.sh" converter)
      (.setExecutable converter true)
      (assoc (into {} (System/getenv))
             "PATH" (str bin ":" (System/getenv "PATH"))
             "EXTRACT_CHAT_PI_CALLS" (str calls)
             "EXTRACT_CHAT_CONVERTER_CALLS" (str (fs/file root "converter-calls"))
             "EXTRACT_CHAT_PYTHON" (str (fs/which "python3"))))))

(defn- run-export-cli [environment & args]
  (apply shell/sh "bb" (str (fs/absolutize "bin/extract-chat"))
         (concat (map str args) [:env environment]
                 (when-let [directory (get environment "EXTRACT_CHAT_CWD")]
                   [:dir directory]))))

(deftest extract-chat-cli-rejects-all-batch-collisions-before-any-writes
  (doseq [native? [false true]
          collision [:directories :extensions]]
    (let [root (fs/create-temp-dir {:prefix "extract-chat-collision"})
          output (fs/file root "exports")
          earlier (fs/file root "00-earlier.jsonl")
          first-source (fs/file root "a" (if (= collision :extensions) "same.json" "same.jsonl"))
          second-source (fs/file root (if (= collision :extensions) "a" "b") "same.jsonl")
          extension (if native? ".html" ".md")
          unchanged (fs/file output (str "00-earlier" extension))]
      (try
        (let [environment (fixture-export-environment root)]
          (doseq [file [earlier first-source second-source]]
            (write-export-fixture file (str file) native?))
          (fs/create-dirs output)
          (spit unchanged "Existing export must not change")
          (let [{:keys [exit out err]}
                (apply run-export-cli environment
                       (concat (when native? ["--native"])
                               ["--extract-dir" output earlier]
                               (if (= collision :directories)
                                 [(fs/parent first-source) (fs/parent second-source)]
                                 [first-source second-source])))]
            (is (not (zero? exit)))
            (is (= "" out))
            (is (str/includes? err "Export destination collision:"))
            (doseq [file [first-source second-source (fs/file output (str "same" extension))]]
              (is (str/includes? err (str file))))
            (is (= "Existing export must not change" (slurp unchanged)))
            (is (= [(str "00-earlier" extension)] (map fs/file-name (fs/list-dir output))))
            (is (not (fs/exists? (fs/file root "pi-calls"))))))
        (finally (fs/delete-tree root))))))

(deftest extract-chat-cli-preserves-successful-batch-names-and-single-source-reruns
  (let [root (fs/create-temp-dir {:prefix "extract-chat-rerun"})
        first-source (fs/file root "a" "first.jsonl")
        second-source (fs/file root "b" "second.json")
        output (fs/file root "exports")]
    (try
      (write-export-fixture first-source "First conversation" false)
      (write-export-fixture second-source "Second conversation" false)
      (let [environment (into {} (System/getenv))
            result (run-export-cli environment "--extract-dir" output
                                   (fs/parent first-source) (fs/parent second-source))]
        (is (= 0 (:exit result)) (:err result))
        (is (= ["first.md" "second.md"] (sort (map fs/file-name (fs/list-dir output)))))
        (is (= (str "# " first-source "\n\n## User\n\nFirst conversation\n\n")
               (slurp (fs/file output "first.md"))))
        (let [second-export (slurp (fs/file output "second.md"))]
          (write-export-fixture first-source "Updated conversation" false)
          (let [rerun (run-export-cli environment "--extract-dir" output first-source)]
            (is (= 0 (:exit rerun)) (:err rerun)))
          (is (= (str "# " first-source "\n\n## User\n\nUpdated conversation\n\n")
                 (slurp (fs/file output "first.md"))))
          (is (= second-export (slurp (fs/file output "second.md"))))))
      (finally (fs/delete-tree root)))))

(deftest extract-chat-cli-passes-allocated-paths-to-native-exporter
  (let [root (fs/create-temp-dir {:prefix "extract-chat-native-paths"})
        pi-source (fs/file root "a" "same.jsonl")
        markdown-source (fs/file root "b" "same.json")
        output (fs/file root "exports")]
    (try
      (let [environment (fixture-export-environment root)]
        (write-export-fixture pi-source "Native conversation" true)
        (write-export-fixture markdown-source "Markdown conversation" false)
        ;; Matching stems with different actual output extensions do not collide.
        (doseq [inputs [[pi-source markdown-source] [pi-source]]]
          (let [result (apply run-export-cli environment
                              (concat ["--native" "--extract-dir" output] inputs))]
            (is (= 0 (:exit result)) (:err result))))
        (is (= ["same.html" "same.md"] (sort (map fs/file-name (fs/list-dir output)))))
        (is (= "<html>fixture export</html>\n" (slurp (fs/file output "same.html"))))
        (is (str/includes? (slurp (fs/file output "same.md")) "Markdown conversation"))
        (is (= (vec (mapcat identity
                           (repeat 2 ["--export" (str pi-source) (str (fs/file output "same.html"))])))
               (str/split-lines (slurp (fs/file root "pi-calls"))))))
      (finally (fs/delete-tree root)))))

(defn- export-tree-state [root]
  (into (sorted-map)
        (for [file (fs/glob root "**" {:hidden true})]
          [(str (fs/relativize root file))
           (cond
             (fs/sym-link? file) [:symlink (str (fs/read-link file))
                                 (vec (java.nio.file.Files/readAllBytes (fs/path file)))]
             (fs/directory? file) [:directory]
             :else [:file (vec (java.nio.file.Files/readAllBytes (fs/path file)))])])))

(defn- preservation-source [inputs label index]
  (fs/file inputs (str "rollout-" label "-10000000-0000-4000-8000-"
                       (format "%012d" index) ".jsonl")))

(defn- write-preservation-source [route file index no-output?]
  (if (#{:codex-native :codex-default} route)
    (write-paginated-rollout file (str "10000000-0000-4000-8000-" (format "%012d" index))
                             nil [(str "Disposable source " index)])
    (if no-output?
      (spit file (str (json/generate-string {:type "session" :id "tool-only"}) "\n"
                      (json/generate-string {:type "message"
                                            :message {:role "toolResult" :content "No transcript"}})
                      "\n"))
      (write-export-fixture file (str "Disposable source " index) true))))

(defn- preservation-output [output source native?]
  (fs/file output (str (str/replace (str (fs/file-name source)) #"\.jsonl$" "")
                       (if native? ".html" ".md"))))

(defn- preservation-args [route output inputs]
  (concat (when (not= :markdown route) ["--native"])
          (when (#{:codex-native :codex-default} route) ["--branches"])
          (when (not= :codex-default route) ["--extract-dir" (str output)])
          [(str inputs)]))

(defn- create-preservation-link [kind output target]
  (case kind
    :symlink (fs/create-sym-link output target)
    :hardlink (java.nio.file.Files/createLink (fs/path output) (fs/path target))))

(deftest extract-chat-rejects-output-aliases-to-every-batch-input-before-effects
  ;; The independent early output makes late rejection observably insufficient.
  ;; The tool-only input intentionally has no Markdown destination of its own.
  (doseq [route [:markdown :pi-native :codex-native :codex-default]
          kind [:symlink :hardlink]
          victim (if (= :markdown route) [:self :other :other-no-output] [:self :other])]
    (testing (str route " " kind " " victim)
      (let [root (fs/create-temp-dir {:prefix "extract-chat-input-preservation"})]
        (try
          (let [inputs (fs/file root "inputs")
                output (fs/file root "output")
                early (preservation-source inputs "a-early" 1)
                source (preservation-source inputs "z-source" 2)
                other (preservation-source inputs "zz-other" 3)
                no-output? (= :other-no-output victim)
                native? (not= :markdown route)]
            (fs/create-dirs inputs)
            (fs/create-dirs output)
            (doseq [[file index] [[early 1] [source 2] [other 3]]]
              (write-preservation-source route file index (and (= file other) no-output?)))
            (spit (preservation-output output early native?) "Existing independent early output")
            (when-not no-output?
              (spit (preservation-output output other native?) "Existing other output"))
            (let [target (if (= :self victim) source other)
                  destination (preservation-output output source native?)
                  _ (create-preservation-link kind destination target)
                  environment (assoc (fixture-export-environment root)
                                     "EXTRACT_CHAT_CWD" (str output))
                  before (export-tree-state root)
                  {:keys [exit out err]} (apply run-export-cli environment
                                               (preservation-args route output inputs))]
              (is (not= 0 exit))
              (is (str/blank? out))
              (is (str/includes? err "Export destination overlaps input:"))
              (is (str/includes? err (if (= :codex-default route)
                                       (str "./" (fs/file-name destination))
                                       (str destination))))
              (is (str/includes? err (str target)))
              (is (= before (export-tree-state root)))
              (is (fs/same-file? destination target))
              (is (not (fs/exists? (get environment "EXTRACT_CHAT_PI_CALLS"))))
              (is (not (fs/exists? (get environment "EXTRACT_CHAT_CONVERTER_CALLS"))))))
          (finally
            (fs/delete-tree root)))))))

(deftest extract-chat-preserves-independent-overwrites-and-output-links
  ;; Output links remain links and retain their existing write-through behavior.
  (doseq [route [:markdown :pi-native :codex-native :codex-default]
          kind [:regular :symlink :hardlink]]
    (testing (str route " " kind)
      (let [root (fs/create-temp-dir {:prefix "extract-chat-independent-output"})]
        (try
          (let [inputs (fs/file root "inputs")
                output (fs/file root "output")
                source (preservation-source inputs "source" 1)
                native? (not= :markdown route)
                destination (preservation-output output source native?)
                backing (fs/file root "unrelated-backing")]
            (fs/create-dirs inputs)
            (fs/create-dirs output)
            (write-preservation-source route source 1 false)
            (spit backing "Old unrelated output")
            (if (= :regular kind)
              (spit destination "Old independent output")
              (create-preservation-link kind destination backing))
            (let [environment (assoc (fixture-export-environment root)
                                     "EXTRACT_CHAT_CWD" (str output))
                  before (slurp source)]
              (dotimes [_ 2]
                (let [{:keys [exit err]} (apply run-export-cli environment
                                              (preservation-args route output inputs))]
                  (is (zero? exit) err)
                  (is (= before (slurp source)))
                  (is (str/includes? (slurp destination)
                                     (if native? "fixture export" "Disposable source 1")))
                  (when (not= :regular kind)
                    (is (fs/same-file? destination backing))
                    (is (= (slurp destination) (slurp backing))))))
              (is (= (= :symlink kind) (fs/sym-link? destination)))
              (if native?
                (is (= 2 (count (filter #{"--export"}
                                       (str/split-lines
                                         (slurp (get environment "EXTRACT_CHAT_PI_CALLS")))))))
                (is (not (fs/exists? (get environment "EXTRACT_CHAT_PI_CALLS")))))
              (if (#{:codex-native :codex-default} route)
                (is (= ["convert" "convert"]
                       (str/split-lines (slurp (get environment "EXTRACT_CHAT_CONVERTER_CALLS")))))
                (is (not (fs/exists? (get environment "EXTRACT_CHAT_CONVERTER_CALLS")))))))
          (finally
            (fs/delete-tree root)))))))

(deftest extract-chat-rejects-cross-source-output-identities-before-effects
  (doseq [route [:markdown :pi-native :codex-native :codex-default]
          kind [:hardlink :symlink :independent :same-source]]
    (testing (str route " " kind)
      (let [root (fs/create-temp-dir {:prefix "extract-chat-output-preservation"})]
        (try
          (let [inputs (fs/file root "inputs")
                output (fs/file root "output")
                early (preservation-source inputs "a-early" 1)
                first-source (preservation-source inputs "b-first" 2)
                second-source (preservation-source inputs "c-second" 3)
                sources [early first-source second-source]
                native? (not= :markdown route)
                first-output (preservation-output output first-source native?)
                second-output (preservation-output output second-source native?)
                collision? (#{:hardlink :symlink} kind)]
            (fs/create-dirs inputs)
            (fs/create-dirs output)
            (doseq [[file index] (map vector sources (range 1 4))]
              (write-preservation-source route file index false))
            (spit (preservation-output output early native?) "Existing early output")
            (spit first-output "Existing first output")
            (if collision?
              (create-preservation-link kind second-output first-output)
              (spit second-output "Existing independent second output"))
            (let [environment (assoc (fixture-export-environment root true)
                                     "EXTRACT_CHAT_CWD" (str output))
                  before (export-tree-state root)
                  source-bytes (mapv slurp sources)
                  args (concat (preservation-args route output inputs)
                               (when (= :same-source kind) [(str first-source)]))
                  {:keys [exit out err]} (apply run-export-cli environment args)]
              (is (= source-bytes (mapv slurp sources)))
              (if collision?
                (do
                  (is (not= 0 exit))
                  (is (str/blank? out))
                  (is (str/includes? err "Export destination collision:"))
                  (doseq [file [first-source second-source first-output second-output]]
                    (is (str/includes? err (str (if (= :codex-default route)
                                                (fs/file-name file) file)))))
                  (is (= before (export-tree-state root)))
                  (is (fs/same-file? first-output second-output))
                  (is (not (fs/exists? (get environment "EXTRACT_CHAT_PI_CALLS"))))
                  (is (not (fs/exists? (get environment "EXTRACT_CHAT_CONVERTER_CALLS")))))
                (do
                  (is (zero? exit) err)
                  (is (not (fs/same-file? first-output second-output)))
                  (doseq [[index source] (map vector (range 1 4) sources)]
                    (is (str/includes? (slurp (preservation-output output source native?))
                                       (str "Disposable source " index))))
                  (is (= native? (fs/exists? (get environment "EXTRACT_CHAT_PI_CALLS"))))
                  (is (= (boolean (#{:codex-native :codex-default} route))
                         (fs/exists? (get environment "EXTRACT_CHAT_CONVERTER_CALLS"))))))))
          (finally
            (fs/delete-tree root)))))))

(deftest extract-chat-identity-preflight-handles-optional-and-colliding-file-keys
  ;; BasicFileAttributes keys are optional and are not themselves the identity
  ;; oracle. Cover absent keys in either comparison direction, plus key collisions.
  (doseq [key-mode [:none :inputs-only :outputs-only :colliding]
          policy [:inputs :outputs]
          collision? [false true]]
    (testing (str key-mode " " policy " collision=" collision?)
      (let [root (fs/create-temp-dir {:prefix "extract-chat-optional-keys"})]
        (try
          (let [inputs (fs/file root "inputs")
                output (fs/file root "output")
                first-source (fs/file inputs "first.jsonl")
                second-source (fs/file inputs "second.jsonl")
                first-output (fs/file output "first.md")
                second-output (fs/file output "second.md")
                original-reader fs/read-attributes]
            (write-export-fixture first-source "First independent result" false)
            (write-export-fixture second-source "Second independent result" false)
            (fs/create-dirs output)
            (spit second-output "Existing second output")
            (if collision?
              (create-preservation-link :hardlink first-output
                                        (if (= :inputs policy) second-source second-output))
              (spit first-output "Existing first output"))
            (let [before (export-tree-state root)
                  source-bytes (mapv slurp [first-source second-source])]
              (with-redefs [fs/read-attributes
                            (fn [file attributes]
                              (let [result (original-reader file attributes)
                                    input? (str/ends-with? (str file) ".jsonl")]
                                (assoc result :fileKey
                                       (case key-mode
                                         :none nil
                                         :inputs-only (when input? (:fileKey result))
                                         :outputs-only (when-not input? (:fileKey result))
                                         :colliding false))))]
                (binding [*out* (java.io.StringWriter.)]
                  (if collision?
                    (is (thrown-with-msg? clojure.lang.ExceptionInfo
                                         (if (= :inputs policy)
                                           #"Export destination overlaps input:"
                                           #"Export destination collision:")
                                         (extract-chat/main ["--extract-dir" (str output) (str inputs)])))
                    (extract-chat/main ["--extract-dir" (str output) (str inputs)]))))
              (is (= source-bytes (mapv slurp [first-source second-source])))
              (if collision?
                (is (= before (export-tree-state root)))
                (do
                  (is (str/includes? (slurp first-output) "First independent result"))
                  (is (str/includes? (slurp second-output) "Second independent result"))))))
          (finally
            (fs/delete-tree root)))))))

(let [{:keys [fail error]} (run-tests 'tools.extract-chat-test)]
  (when (pos? (+ fail error))
    (System/exit 1)))
