(ns sample-policy
  (:require [clojure.string :as str]))

(def targets #{:codex :claude})

(defn one-of [& values]
  {:one-of (vec values)})

(defn rule [decision pattern {:keys [match reason targets]}]
  {:decision decision
   :match (or match :prefix)
   :pattern pattern
   :reason reason
   :targets (set (or targets sample-policy/targets))})

(defn allow [pattern & {:as options}]
  (rule :allow pattern options))

(defn deny [pattern & {:as options}]
  (rule :deny pattern options))

(defn policy [& rules]
  (vec rules))

(defn allow-subcommands [program & commands]
  (allow [(str/lower-case program) (apply one-of commands)]))

(policy
  (allow-subcommands "jj" "status" "diff")
  (allow ["git" "fetch"] :targets [:codex])
  (allow ["command" "-v"] :targets [:claude])
  (deny ["sed"] :reason "use structured tools"))
