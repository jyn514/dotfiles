;; Native Babashka ignores JVM option environment variables.
;; Run before inherited preloads so test code sees the wrapper's private HOME.
(System/setProperty "user.home" (System/getenv "HOME"))
