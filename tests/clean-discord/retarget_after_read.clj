;; Test-only preload: move the input symlink after the real read returns, before
;; the command cleans or publishes those bytes. No production timing hooks.
(require '[babashka.fs :as fs])

(let [link (System/getenv "CLEAN_DISCORD_TEST_LINK")
      original-target (System/getenv "CLEAN_DISCORD_TEST_ORIGINAL")
      next-target (System/getenv "CLEAN_DISCORD_TEST_NEXT")
      marker (System/getenv "CLEAN_DISCORD_TEST_MARKER")]
  (alter-var-root
   #'clojure.core/slurp
   (fn [read-original]
     (fn [source & options]
       (let [text (apply read-original source options)]
         (when (#{link original-target} (str source))
           (fs/delete link)
           (fs/create-sym-link link next-target)
           (spit marker "retargeted after read\n"))
         text)))))
