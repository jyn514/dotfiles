;; Run in a disposable Chimera container after bootstrapping Babashka.
;; Exercise only this migration's package slice, not a whole system upgrade.
(require '[package-plan :as p])
(let [policy (assoc (p/read-policy) :common [:ripgrep :shfmt] :additions {})
      host (p/detect-host)
      _ (assert (= :chimera (:target host)))
      plan (p/build-plan policy host (p/ensure-mise! host))
      repositories "/etc/apk/repositories.d/90-package-plan-user.list"
      before (.exists (java.io.File. repositories))]
  (p/execute! plan true true)
  (assert (= before (.exists (java.io.File. repositories))) "dry run changed repositories")
  (p/execute! plan false true)
  (let [after (slurp repositories)]
    (p/execute! plan false true)
    (assert (= after (slurp repositories)) "repeat changed repositories")))
