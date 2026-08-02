(ns scripts.temp
  (:require [babashka.fs :as fs]))

(defn tmpdir-env []
  (System/getenv "TMPDIR"))

(defn java-tmpdir []
  (System/getProperty "java.io.tmpdir"))

(defn temp-root []
  (fs/path (or (tmpdir-env)
               (java-tmpdir))))

(defn with-default-temp-parent
  "Default unrooted babashka.fs create-temp-* calls to $TMPDIR when it is set.
   Caller-supplied :dir/:path wins; without $TMPDIR, args pass through unchanged."
  [args]
  (if (tmpdir-env)
    (let [opts (if (map? (first args)) (first args) {})]
      [(cond-> opts
         (not (or (:dir opts) (:path opts)))
         (assoc :dir (str (temp-root))))])
    args))
