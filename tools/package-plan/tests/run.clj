(require '[babashka.fs :as fs]
         '[clojure.test :refer [deftest is run-tests testing]]
         '[package-plan :as planner])

(def policy (planner/validate-policy (planner/read-policy)))

(deftest policy-evaluation-allows-data-shaping-but-denies-effects
  (is (= {:common [:one :two]}
         (planner/evaluate-policy-source
          "(let [base [:one]] {:common (conj base :two)})")))
  (doseq [source ["(slurp \"/etc/passwd\")"
                  "(babashka.process/shell \"true\")"
                  "{} {}"]]
    (is (try
          (planner/evaluate-policy-source source)
          false
          (catch Exception _ true)) source)))

(deftest complete-matrix
  (is (= (set planner/targets) (set (:targets policy))))
  (doseq [package (planner/logical-packages policy)
          target planner/targets]
    (is (#{:native :fallback :skip}
         (:kind (planner/disposition policy target package)))
        (str package " on " target))))

(deftest representative-translations
  (is (= [:python3-lsp-server]
         (:packages (planner/disposition policy :fedora :python3-pylsp))))
  (is (= [:neovim]
         (:packages (planner/disposition policy :alpine :nvim))))
  (is (= :fallback
         (:kind (planner/disposition policy :debian :bacon))))
  (is (= :skip
         (:kind (planner/disposition policy :macos-arm64 :valgrind)))))

(deftest alpine-baseline-has-no-duplicate-requests
  (let [host {:target :alpine :release "test" :arch "x86_64" :wsl false}
        operations (:operations (planner/package-operations policy host [] "/mise"))
        packages (map #(clojure.string/replace % #"^apk:" "")
                      (mapcat #(drop 5 (:argv %)) operations))]
    (is (= (count packages) (count (distinct packages))))
    (is (every? (set packages) ["bash" "less" "libgcc" "shadow"
                                "cargo-audit" "difftastic"]))))

(deftest arch-performs-one-full-upgrade
  (let [host {:target :arch :release "test" :arch "x86_64" :wsl false}
        operation (-> (planner/package-operations policy host ["sudo"] "/mise")
                      :operations first)]
    (is (= ["sudo" "pacman" "--sync" "--refresh" "--sysupgrade"
            "--needed" "--"]
           (subvec (:argv operation) 0 7)))))

(deftest debian-does-not-select-ubuntu-resources
  (with-redefs [planner/command-exists? (constantly true)
                planner/old-git? (constantly true)]
    (is (not-any? #(#{:ubuntu-universe :git-ppa} (:name %))
                  (planner/resource-operations
                   {:target :debian :release "13" :arch "x86_64" :wsl false}
                   ["sudo"])))))

(deftest conditional-packages-follow-installed-state
  (let [debian {:target :debian :release "13" :arch "x86_64" :wsl false}]
    (with-redefs [planner/command-exists? (constantly false)]
      (is (some #{:powershell} (planner/selected-packages policy debian))))
    (with-redefs [planner/command-exists? (constantly true)]
      (is (not-any? #{:powershell} (planner/selected-packages policy debian)))))
  (let [fedora {:target :fedora :release "42" :arch "x86_64" :wsl false}
        operations (:operations
                    (planner/package-operations policy fedora ["sudo"] "/mise"))
        dnf (first (filter #(= :dnf (:manager %)) operations))]
    (is (some #{"dnf:1password"} (:argv dnf)))))

(deftest fedora-repositories-precede-package-groups
  (with-redefs [planner/command-exists? (constantly true)
                babashka.process/shell (fn [& _] {:out "0\n" :exit 0})]
    (let [host {:target :fedora :release "42" :arch "x86_64" :wsl false}
          plan (planner/build-plan policy host "/mise")
          kinds (map :kind (:operations plan))]
      (is (= [:repository :repository :repository :packages]
             (vec (take 4 kinds)))))))

(deftest dry-run-never-starts-a-process
  (let [started (atom [])
        plan {:host {:target :debian}
              :skipped []
              :operations [{:kind :packages :argv ["false"]}]}]
    (with-redefs [babashka.process/process
                  (fn [& arguments] (swap! started conj arguments))]
      (planner/execute! plan true false))
    (is (empty? @started))))

(deftest privilege-prerequisites-are-execution-errors
  (with-redefs [planner/root? (constantly false)
                planner/command-exists? (constantly false)]
    (is (= "Debian package setup requires sudo in PATH"
           (try
             (planner/require-elevation! {:target :debian})
             nil
             (catch clojure.lang.ExceptionInfo error (ex-message error))))))
  (with-redefs [planner/root? (constantly false)
                planner/command-exists? #(= % "doas")]
    (is (nil? (planner/require-elevation! {:target :chimera})))))

(deftest planning-and-dry-run-do-not-require-elevation
  (with-redefs [planner/root? (constantly false)
                planner/command-exists? (constantly false)]
    (let [host {:target :debian :release "13" :arch "x86_64" :wsl false}
          plan (planner/build-plan policy host "/mise")
          started (atom [])]
      (is (seq (:operations plan)))
      (is (some #(= "sudo" (first (:argv %))) (:operations plan)))
      (with-redefs [babashka.process/process
                    (fn [& arguments] (swap! started conj arguments))]
        (planner/execute! plan true true))
      (is (empty? @started)))))

(deftest execution-checks-elevation-before-mutation
  (let [started (atom [])
        plan {:host {:target :debian}
              :skipped []
              :operations [{:kind :packages :argv ["false"]}]}]
    (with-redefs [planner/root? (constantly false)
                  planner/command-exists? (constantly false)
                  babashka.process/process
                  (fn [& arguments] (swap! started conj arguments))]
      (is (thrown-with-msg? clojure.lang.ExceptionInfo
                            #"requires sudo"
                            (planner/execute! plan false true))))
    (is (empty? @started))))

(deftest bootstrap-manifest-is-complete
  (let [manifest (planner/read-one-edn planner/bootstrap-path)]
    (is (= 1 (:schema manifest)))
    (is (= #{:linux-x64 :linux-arm64 :macos-arm64}
           (set (keys (get-in manifest [:babashka :artifacts])))))
    (is (= #{:linux-x64-glibc :linux-arm64-glibc
             :linux-x64-musl :linux-arm64-musl :macos-arm64}
           (set (keys (get-in manifest [:mise :artifacts])))))
    (doseq [tool [:babashka :mise]
            [_ {:keys [url sha256]}] (get-in manifest [tool :artifacts])]
      (is (clojure.string/starts-with? url "https://github.com/"))
      (is (re-matches #"[0-9a-f]{64}" sha256)))))

(deftest vendored-shim-matches-recorded-digests
  (let [directory (fs/path planner/root "vendor" "doas-sudo-shim")]
    (doseq [line (clojure.string/split-lines (slurp (str (fs/path directory "SHA256"))))
            :let [[digest file] (clojure.string/split line #"  ")]]
      (is (= digest (planner/sha256 (fs/path directory file)))))))

(let [{:keys [fail error]} (run-tests)]
  (System/exit (if (zero? (+ fail error)) 0 1)))
