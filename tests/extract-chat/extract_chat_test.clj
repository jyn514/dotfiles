(ns scripts.extract-chat-test
  (:require [babashka.fs :as fs]
            [cheshire.core :as json]
            [clojure.string :as str]
            [clojure.test :refer [deftest is]]))

(load-file "bin/extract-chat")
(alias 'extract-chat 'scripts.extract-chat)

(deftest extract-chat-default-root-prefers-codex-home
  (is (= "/tmp/custom-codex/sessions"
         (extract-chat/default-root {"CODEX_HOME" "/tmp/custom-codex"})))
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
