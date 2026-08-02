(require '[clojure.test :as test])

(load-file "tools/agent-split/tests/agent_split_test.clj")
(load-file "tools/agent-split/tests/agent_split_editor_test.clj")

(let [{:keys [fail error]}
      (test/run-tests 'scripts.jj-split-patch-test
                      'flower.jj-agent-split-editor-test)]
  (when (pos? (+ fail error))
    (System/exit 1)))
