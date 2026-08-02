(require '[clojure.test :as test])

(load-file "tools/agent-split/tests/agent_split_test.clj")
(load-file "tools/agent-split/tests/agent_split_editor_test.clj")
(load-file "tools/agent-split/tests/integration_test.clj")

(let [{:keys [fail error]}
      (test/run-tests 'scripts.jj-split-patch-test
                      'flower.jj-agent-split-editor-test
                      'scripts.jj-split-patch-integration-test)]
  (when (pos? (+ fail error))
    (System/exit 1)))
