;; Run the public workflow with read-call recording, delegating every query to JJ.
(require '[babashka.fs :as fs]
         '[cheshire.core :as json])

(let [[script log & args] *command-line-args*]
  (load-file script)
  (alter-var-root (ns-resolve 'scripts.jj-split-patch 'script-dir)
                  (constantly (fn [] (fs/parent script))))
  (let [read-var (ns-resolve 'scripts.jj-split-patch 'run-jj-read)
        original @read-var]
    (alter-var-root read-var
                    (constantly (fn [step & argv]
                                  (spit log (str (json/generate-string (mapv str (remove map? argv))) "\n") :append true)
                                  (apply original step argv))))
    ((ns-resolve 'scripts.jj-split-patch 'main) args)))
