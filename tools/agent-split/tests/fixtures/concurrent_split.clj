;; Test driver: inject a real writer at a deterministic CLI boundary.
(require '[babashka.fs :as fs]
         '[babashka.process :as process])

(let [[script phase mutation & args] *command-line-args*]
  (load-file script)
  (alter-var-root (ns-resolve 'scripts.jj-split-patch 'script-dir)
                  (constantly (fn [] (fs/parent script))))
  (let [split-var (ns-resolve 'scripts.jj-split-patch 'run-split!)
        original @split-var
        split-completed? (atom false)
        mutate! (fn []
                  (case mutation
                    "unrelated" (do (spit "other.txt" "another writer's edit\n")
                                    (spit "note.txt" "one\nTWO\nthree\nfour\nfive\nsix\nseven\neight\nnine\nNEW TEN\n"))
                    "selected" (spit "note.txt" "one\nDIFFERENT TWO\nthree\nfour\nfive\nsix\nseven\neight\nnine\nTEN\n"))
                  (let [result (process/shell {:out :string :err :string :continue true} "jj" "status")]
                    (when-not (zero? (:exit result))
                      (throw (ex-info "injected writer could not snapshot" result)))))]
    (when (#{"before-failure" "verify-failure" "during-verify-failure"} phase)
      (alter-var-root (ns-resolve 'scripts.jj-split-patch 'verify!)
                      (constantly (fn [& _]
                                    (when (= phase "during-verify-failure") (mutate!))
                                    "remainder mismatch: injected loss"))))
    (when (= phase "before-read-failure")
      (let [v (ns-resolve 'scripts.jj-split-patch 'run-jj-read)
            read! @v]
        (alter-var-root v (constantly (fn [& argv]
                                       (if @split-completed?
                                         (throw (java.io.IOException. "injected discovery read failure"))
                                         (apply read! argv)))))))
    (alter-var-root split-var
                    (constantly
                     (fn [& argv]
                       (when (#{"before" "before-failure" "before-read-failure"} phase) (mutate!))
                       (let [result (apply original argv)]
                         (reset! split-completed? true)
                         (when (= phase "after") (mutate!))
                         result))))
    ((ns-resolve 'scripts.jj-split-patch 'main) args)))
