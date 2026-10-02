(ns tools.extract-chat-test
  (:require [babashka.fs :as fs]
            [cheshire.core :as json]
            [clojure.java.shell :as shell]
            [clojure.string :as str]
            [clojure.test :refer [deftest is run-tests]]))

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
        matcher (deref #'extract-chat/session-file-name-matches?)]
    (doseq [[filename expected]
            [["01a0a66d-2c73-77d5-83a1-43ca8362dc92.jsonl" true]
             ["rollout-2026-09-15-01a0a66d-2c73-77d5-83a1-43ca8362dc92.jsonl" true]
             ["2026-09-15T18-56-07-795Z_01a0a66d-2c73-77d5-83a1-43ca8362dc92.jsonl" true]
             ["rollout-2026-09-15-other.jsonl" false]]]
      (let [file (fs/file root filename)]
        (spit file "{}")
        (is (= expected
               (matcher "01a0a66d-2c73-77d5-83a1-43ca8362dc92" (.toPath file))))))))

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

(let [{:keys [fail error]} (run-tests 'tools.extract-chat-test)]
  (when (pos? (+ fail error))
    (System/exit 1)))
