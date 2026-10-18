(ns scripts.agent-split-test-repo
  (:require [babashka.fs :as fs]))

(defn with-templates [builders f]
  (let [root (fs/create-temp-dir {:prefix "agent-split-bases-"})]
    (try
      (let [templates (into {}
                            (for [[name build!] builders]
                              (let [repo (fs/file root (clojure.core/name name))]
                                (fs/create-dirs repo)
                                (build! repo)
                                [name repo])))]
        ;; Published templates are only read by copy-tree, never opened by JJ.
        ;; Copy attributes and symlinks, not hard links or shared JJ workspaces:
        ;; every case owns its complete mutable Git/JJ metadata and working tree.
        (f (fn [name destination]
             (fs/copy-tree (get templates name) destination
                           {:copy-attributes true :nofollow-links true}))))
      (finally (fs/delete-tree root)))))
