(require '[cheshire.core :as json])

(let [home (System/getenv "HOME")
      property-home (System/getProperty "user.home")]
  ;; A failing isolation test must never write into the real home.
  (when-not (= home property-home)
    (throw (ex-info "user.home escaped the private HOME" {:home home :user.home property-home})))
  (spit (str home "/bb-home-probe") "private test state")
  (println (json/generate-string {:home home :property-home property-home
                                  :preload-home (System/getProperty "test.preload.home")})))
