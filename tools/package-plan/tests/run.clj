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
  (is (= [:perl-File-Which]
         (:packages (planner/disposition policy :fedora :perl-file-which))))
  (is (= [:sane-backends]
         (:packages (planner/disposition policy :fedora :sane))))
  (doseq [package [:fzy :markdown-oxide :signal-desktop]]
    (is (= :skip
           (:kind (planner/disposition policy :fedora package)))))
  (is (= :fallback
         (:kind (planner/disposition policy :debian :bacon))))
  (is (= :skip
         (:kind (planner/disposition policy :macos-arm64 :valgrind)))))

(deftest fedora-release-comes-from-os-release
  (with-redefs [planner/parse-os-release
                (constantly {:id "fedora" :version_id "42"})]
    (is (= "42" (:release (planner/detect-host))))))

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

(deftest portable-search-and-formatter-use-one-native-request-per-target
  (with-redefs [planner/command-exists? (constantly true)]
    (doseq [[target manager] {:debian :apt :ubuntu :apt :fedora :dnf
                             :arch :pacman :alpine :apk :chimera :apk
                             :macos-arm64 :brew}]
      (let [host {:target target :release "test" :arch "x86_64" :wsl false}
            operations (:operations (planner/package-operations policy host [] "/mise"))
            requests (mapcat (fn [{:keys [argv manager]}]
                               (if (= manager :pacman)
                                 (rest (drop-while #(not= "--" %) argv))
                                 (filter #(clojure.string/starts-with?
                                           % (str (name manager) ":")) argv)))
                             operations)]
        (is (= (count requests) (count (distinct requests))) (str target))
        (doseq [package [:ripgrep :shfmt]]
          (let [request (str (when-not (= manager :pacman) (str (name manager) ":"))
                             (name package))]
            (is (= {:kind :native :manager manager :packages [package]}
                   (planner/disposition policy target package))
                (str target " " package))
            (is (= 1 (get (frequencies requests) request 0))
                (str target " " package))))))))

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

(deftest fedora-codec-install-allows-erasing
  (let [operation (last (planner/resource-operations
                         {:target :fedora :release "42" :arch "x86_64" :wsl false}
                         ["sudo"]))]
    (is (= "--allowerasing" (last (:argv operation))))))

(deftest chimera-enables-user-and-refreshes-before-installing
  (with-redefs [planner/root? (constantly true)]
    (let [plan (planner/build-plan policy
                                   {:target :chimera :arch "x86_64" :wsl false}
                                   "/mise")
          operations (:operations plan)]
      (is (= [:chimera-user :chimera-user-index]
             (mapv :name (take 2 operations))))
      (is (= ["apk" "update"] (:argv (second operations))))
      (is (= :packages (:kind (nth operations 2 nil)))))))

(deftest chimera-repository-is-idempotent-and-dry-run-does-not-write
  (let [directory (fs/create-temp-dir {:prefix "chimera-repository-"})
        repositories (fs/path directory "repositories")
        original "# user repository is needed for developer commands\nhttps://repo.chimera-linux.org/current/main"
        plan {:host {:target :chimera} :skipped []
              :operations [(planner/chimera-user-operation [] repositories)]}]
    (try
      (spit (str repositories) original)
      (with-redefs [planner/root? (constantly true)]
        (planner/execute! plan true true)
        (is (= original (slurp (str repositories))))
        (planner/execute! plan false true)
        (let [enabled (slurp (str repositories))]
          (is (= (str original "\nhttps://repo.chimera-linux.org/current/user\n")
                 enabled))
          (planner/execute! plan false true)
          (is (= enabled (slurp (str repositories))))))
      (finally (fs/delete-tree directory)))))

(deftest chimera-repository-creates-a-missing-fragment
  (let [directory (fs/create-temp-dir {:prefix "chimera-new-repository-"})
        repositories (fs/path directory "repositories.d" "user.list")
        plan {:host {:target :chimera} :skipped []
              :operations [(planner/chimera-user-operation [] repositories)]}]
    (try
      (with-redefs [planner/root? (constantly true)]
        (planner/execute! plan true true)
        (is (not (fs/exists? (fs/parent repositories))))
        (planner/execute! plan false true)
        (let [enabled (slurp (str repositories))]
          (is (= "\nhttps://repo.chimera-linux.org/current/user\n" enabled))
          (planner/execute! plan false true)
          (is (= enabled (slurp (str repositories))))))
      (finally (fs/delete-tree directory)))))

(deftest failed-chimera-refresh-prevents-install-and-can-be-retried
  (let [directory (fs/create-temp-dir {:prefix "chimera-refresh-"})
        repositories (fs/path directory "repositories")
        installed (fs/path directory "installed")
        repository (planner/chimera-user-operation [] repositories)
        install {:kind :packages :manager :apk
                 :argv ["touch" (str installed)]}
        plan {:host {:target :chimera} :skipped []
              :operations [repository {:kind :repository :argv ["false"]} install]}]
    (try
      (spit (str repositories) "https://repo.chimera-linux.org/current/main\n")
      (with-redefs [planner/root? (constantly true)]
        (is (thrown-with-msg? clojure.lang.ExceptionInfo #"operation failed"
                              (planner/execute! plan false true)))
        (is (not (fs/exists? installed)))
        (let [enabled (slurp (str repositories))]
          (planner/execute! (assoc-in plan [:operations 1 :argv] ["true"]) false true)
          (is (fs/exists? installed))
          (is (= enabled (slurp (str repositories))))))
      (finally (fs/delete-tree directory)))))

(deftest chimera-repository-operations-use-the-doas-sudo-shim
  (let [options (atom [])
        plan {:host {:target :chimera} :skipped []
              :operations [(planner/chimera-user-operation ["sudo"] "/etc/apk/repositories")]}]
    (with-redefs [planner/require-elevation! (constantly nil)
                  babashka.process/process
                  (fn [_ opts]
                    (swap! options conj opts)
                    (delay {:exit 0}))]
      (planner/execute! plan false true))
    (is (clojure.string/starts-with? (get-in @options [0 :extra-env "PATH"])
                                   (str planner/root "/vendor/doas-sudo-shim:")))))

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
