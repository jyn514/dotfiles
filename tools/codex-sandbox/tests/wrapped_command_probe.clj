(require '[babashka.fs :as fs]
         '[babashka.process :as process]
         '[clojure.string :as str])

(def wrapped-commands ["bb" "docker" "java" "jj" "podman" "rg"])

(doseq [command wrapped-commands]
  (let [wrapper-directory (if (#{"docker" "podman"} command)
                           "/libexec/sandbox-wrappers"
                           "/libexec/agent-wrappers")
        wrapper (fs/canonicalize (fs/path wrapper-directory command))
        selected (fs/which command)
        alternate (fs/path "/opt/agent-tools/bin" command)]
    (doseq [candidate [selected alternate]]
      (when-not (= wrapper (fs/canonicalize candidate))
        (throw (ex-info "public command does not resolve to its wrapper"
                        {:command command :candidate candidate}))))))

(defn run [extra-env & command]
  (apply process/shell {:continue true :out :string :err :string
                        :extra-env extra-env}
         command))

(doseq [[command expected-prefix]
        [["bb" "babashka v"]
         ["rg" "ripgrep "]]]
  (let [result (run {} (str "/opt/agent-tools/bin/" command) "--version")]
    (when-not (and (zero? (:exit result))
                   (str/starts-with? (:out result) expected-prefix))
      (throw (ex-info "public alias did not reach the real executable"
                      {:command command :result result})))))

(doseq [[command environment]
        [["bb" {"BB_REAL" "/bin/false"}]
         ["java" {"JAVA_REAL" "/bin/false"}]
         ["jj" {"JJ_REAL" "/bin/false"}]
         ["docker" {"CONTAINER_CLI_REAL_DIR" "/nonexistent"}]
         ["podman" {"CONTAINER_CLI_REAL_DIR" "/nonexistent"}]]]
  (when (zero? (:exit (run environment command "--version")))
    (throw (ex-info "nested process bypassed its wrapper" {:command command}))))

(let [result (run {"RIPGREP_CONFIG_PATH" "/nonexistent"}
                  "rg" "--pre" "true" "needle")]
  (when-not (and (= 2 (:exit result))
                 (str/includes? (:err result) "rg wrapper: --pre is not permitted"))
    (throw (ex-info "nested rg bypassed its wrapper" result))))

(println "wrapped-command-probe-ok")
