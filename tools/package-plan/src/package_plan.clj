(ns package-plan
  (:require [babashka.fs :as fs]
            [babashka.process :as process]
            [clojure.edn :as edn]
            [clojure.set :as set]
            [clojure.string :as str]
            [sci.core :as sci]))

(def root (-> *file* fs/absolutize fs/parent fs/parent fs/parent fs/parent str))
(def policy-path (str root "/install/packages.clj"))
(def bootstrap-path (str root "/install/bootstrap.edn"))
(def targets [:debian :ubuntu :fedora :arch :alpine :chimera :macos-arm64])
(def managers #{:apt :dnf :pacman :apk :brew})
(def resources #{:ubuntu-universe :powershell-repository :vscode-deb :git-ppa
                 :onepassword-fedora :rpmfusion-codecs})
(def package-name-pattern #"^[@A-Za-z0-9][A-Za-z0-9+_.@/-]*$")

(defn fail! [message]
  (throw (ex-info message {:type :user-error})))

(def allowed-policy-symbols
  '[let let* fn fn* if do quote
    assoc conj contains? disj filter get hash-set into keyword map mapcat merge
    name remove set str update vec vector])

(defn read-one-form [source description]
  (with-open [reader (java.io.PushbackReader. (java.io.StringReader. source))]
    (let [value (edn/read {:eof ::eof} reader)
          trailing (edn/read {:eof ::eof} reader)]
      (when (= value ::eof) (fail! (str description " is empty")))
      (when-not (= trailing ::eof)
        (fail! (str description " contains multiple values")))
      value)))

(defn evaluate-policy-source [source]
  (let [form (read-one-form source "package policy")
        context (sci/init {:allow allowed-policy-symbols})]
    (sci/eval-form context form)))

(defn read-policy []
  (evaluate-policy-source (slurp policy-path)))

(defn read-one-edn [path]
  (with-open [reader (java.io.PushbackReader. (java.io.FileReader. path))]
    (let [value (edn/read {:eof ::eof} reader)
          trailing (edn/read {:eof ::eof} reader)]
      (when (or (= value ::eof) (not= trailing ::eof))
        (fail! (str path " must contain exactly one EDN value")))
      value)))

(defn sha256 [path]
  (let [digest (java.security.MessageDigest/getInstance "SHA-256")]
    (with-open [input (java.io.BufferedInputStream. (java.io.FileInputStream. (str path)))]
      (let [buffer (byte-array 65536)]
        (loop []
          (let [count (.read input buffer)]
            (when (pos? count)
              (.update digest buffer 0 count)
              (recur))))))
    (format "%064x" (java.math.BigInteger. 1 (.digest digest)))))

(defn download! [url destination]
  (with-open [input (.openStream (.toURL (java.net.URI. url)))]
    (java.nio.file.Files/copy input (fs/path destination)
                              (into-array java.nio.file.CopyOption
                                          [java.nio.file.StandardCopyOption/REPLACE_EXISTING]))))

(defn bootstrap-key [{:keys [target arch]}]
  (let [architecture (if (contains? #{"aarch64" "arm64"} arch) "arm64" "x64")]
    (if (= target :macos-arm64)
      :macos-arm64
      (keyword (str "linux-" architecture "-"
                    (if (#{:alpine :chimera} target) "musl" "glibc"))))))

(defn ensure-mise! [host]
  (if-let [mise (System/getenv "PACKAGE_PLAN_MISE")]
    mise
    (let [manifest (read-one-edn bootstrap-path)
          _ (when-not (= 1 (:schema manifest))
              (fail! "unsupported bootstrap manifest schema"))
          version (get-in manifest [:mise :version])
          artifact (get-in manifest [:mise :artifacts (bootstrap-key host)])
          url (:url artifact)
          expected-sha256 (:sha256 artifact)
          _ (when-not (and (string? version)
                           (re-matches #"https://github\.com/.+" (or url ""))
                           (re-matches #"[0-9a-f]{64}" (or expected-sha256 "")))
              (fail! (str "invalid mise bootstrap artifact for " (bootstrap-key host))))
          cache-root (or (System/getenv "XDG_CACHE_HOME")
                         (some-> (System/getenv "HOME") (str "/.cache"))
                         (str (System/getProperty "user.home") "/.cache"))
          destination (fs/path cache-root "dotfiles" "package-plan" "mise" version "mise")]
      (if (fs/executable? destination)
        (str destination)
        (let [parent (fs/parent destination)
              _ (fs/create-dirs parent)
              temporary (fs/create-temp-dir {:dir parent :prefix ".mise-"})
              archive (fs/path temporary "mise.tar.gz")]
          (try
            (download! url archive)
            (when-not (= expected-sha256 (sha256 archive))
              (fail! "mise checksum mismatch"))
            (let [result @(process/process
                           ["tar" "-xzf" (str archive) "-C" (str temporary)]
                           {:inherit true})
                  extracted (fs/path temporary "mise" "bin" "mise")]
              (when-not (zero? (:exit result)) (fail! "could not extract mise"))
              (when-not (fs/executable? extracted)
                (fail! "mise archive did not contain executable mise"))
              (java.nio.file.Files/move
               extracted destination
               (into-array java.nio.file.CopyOption
                           [java.nio.file.StandardCopyOption/ATOMIC_MOVE
                            java.nio.file.StandardCopyOption/REPLACE_EXISTING])))
            (str destination)
            (finally (fs/delete-tree temporary))))))))

(defn logical-packages [policy]
  (-> (set (:common policy))
      (into (mapcat val (:additions policy)))
      (into (keys (:fallbacks policy)))))

(defn disposition [policy target package]
  (let [target-policy (get-in policy [:targets-policy target])
        fallback (get-in policy [:fallbacks package])]
    (cond
      (some #{target} (:targets fallback))
      {:kind :fallback :manager (:manager fallback) :packages (:packages fallback)
       :reason (:reason fallback)}

      (contains? (:skip target-policy) package)
      {:kind :skip :reason (get-in target-policy [:skip package])}

      :else
      {:kind :native :manager (:manager target-policy)
       :packages (get-in target-policy [:rename package] [package])})))

(defn valid-package-name? [package]
  (and (or (keyword? package) (string? package))
       (re-matches package-name-pattern (name package))))

(defn validate-policy [policy]
  (when-not (= 1 (:schema policy)) (fail! "unsupported package policy schema"))
  (when-not (= (set targets) (set (:targets policy)))
    (fail! "package policy target set does not match the supported targets"))
  (when-not (= (set targets) (set (keys (:targets-policy policy))))
    (fail! "every target must have one target policy"))
  (doseq [target targets]
    (when-not (managers (get-in policy [:targets-policy target :manager]))
      (fail! (str "unknown manager for " (name target)))))
  (let [logical (logical-packages policy)]
    (doseq [target targets
            field [:rename :skip]
            package (keys (get-in policy [:targets-policy target field]))]
      (when-not (logical package)
        (fail! (str "unknown package in " (name field) " for " (name target)
                    ": " (name package))))))
  (when-not (= resources (set (:resources policy)))
    (fail! "package policy resource set is incomplete or unknown"))
  (doseq [[package fallback] (:fallbacks policy)]
    (when-not (= :brew (:manager fallback))
      (fail! (str "unsupported fallback provider for " (name package))))
    (when-not (set/subset? (set (:targets fallback))
                           #{:debian :ubuntu :fedora})
      (fail! (str "unsupported Brew fallback target for " (name package)))))
  (doseq [package (logical-packages policy)
          target targets]
    (let [{:keys [kind packages reason]} (disposition policy target package)]
      (when-not (#{:native :fallback :skip} kind)
        (fail! (str "missing disposition for " package " on " target)))
      (if (= :skip kind)
        (when (str/blank? reason) (fail! (str "skip lacks reason: " package)))
        (when (or (empty? packages) (not-every? valid-package-name? packages))
          (fail! (str "invalid package vector for " package " on " target))))))
  (doseq [target targets]
    (reduce
     (fn [owners package]
       (let [{:keys [kind manager packages]} (disposition policy target package)]
         (if (= kind :skip)
           owners
           (reduce
            (fn [owners physical]
              (let [key [manager (name physical)]]
                (when-let [owner (get owners key)]
                  (fail! (str "physical package " (second key) " on " (name target)
                              " is owned by both " (name owner) " and " (name package))))
                (assoc owners key package)))
            owners packages))))
     {} (logical-packages policy)))
  policy)

(defn parse-os-release [path]
  (when (fs/exists? path)
    (into {}
          (for [line (str/split-lines (slurp path))
                :when (str/includes? line "=")
                :let [[key value] (str/split line #"=" 2)]]
            [(keyword (str/lower-case key))
             (str/replace value #"^\"|\"$" "")]))))

(defn command-exists? [command]
  (zero? (:exit (process/shell {:out :string :err :string :continue true}
                               "sh" "-c" "command -v \"$1\" >/dev/null 2>&1"
                               "package-plan" command))))

(defn detect-host []
  (if-let [override (System/getenv "PACKAGE_PLAN_TARGET")]
    {:target (keyword override)
     :release (or (System/getenv "PACKAGE_PLAN_RELEASE") "test")
     :arch (or (System/getenv "PACKAGE_PLAN_ARCH") "x86_64")
     :wsl (= "1" (System/getenv "PACKAGE_PLAN_WSL"))}
    (let [os (System/getProperty "os.name")
          arch (System/getProperty "os.arch")]
      (if (= os "Mac OS X")
        (do
          (when-not (contains? #{"aarch64" "arm64"} arch)
            (fail! "Intel macOS is unsupported"))
          {:target :macos-arm64 :release "macos" :arch arch :wsl false})
        (let [release (parse-os-release "/etc/os-release")
              id (:id release)
              target ({"debian" :debian "ubuntu" :ubuntu "fedora" :fedora
                       "arch" :arch "alpine" :alpine "chimera" :chimera} id)]
          (when-not target (fail! (str "unsupported Linux distribution: " id)))
          {:target target :release (:version-id release) :arch arch
           :wsl (or (str/includes? (str/lower-case
                                    (or (System/getProperty "os.version") ""))
                                   "microsoft")
                    (some? (System/getenv "WSL_INTEROP")))})))))

(defn selected-packages [policy {:keys [target wsl]}]
  (cond-> (vec (:common policy))
    (seq (get-in policy [:additions target]))
    (into (get-in policy [:additions target]))
    wsl (into (get-in policy [:additions :wsl]))
    (#{:debian :ubuntu :fedora :macos-arm64} target)
    (into (get-in policy [:additions :brew-fallback]))
    (and (#{:debian :ubuntu} target) (not (command-exists? "pwsh")))
    (conj :powershell)
    (= :fedora target)
    (conj :onepassword)))

(defn root? []
  (= "0" (or (System/getenv "PACKAGE_PLAN_UID")
             (str/trim (:out (process/shell {:out :string} "id" "-u"))))))

(defn planned-sudo-prefix []
  (if (root?) [] ["sudo"]))

(defn require-elevation! [host]
  (when-not (root?)
    (let [target (:target host)]
      (cond
        (= target :chimera)
        (do (when-not (command-exists? "doas")
              (fail! "Chimera package setup requires opendoas in PATH"))
            (when-not (fs/executable? (fs/path root "vendor" "doas-sudo-shim" "sudo"))
              (fail! "vendored Chimera sudo shim is missing or not executable")))
        (command-exists? "sudo") nil
        :else (fail! (case target
                       :alpine "Alpine package setup requires sudo or doas-sudo-shim in PATH"
                       :macos-arm64 "macOS package setup requires the base-system sudo in PATH"
                       (str (str/capitalize (name target))
                            " package setup requires sudo in PATH")))))))

(defn old-git? []
  (when (command-exists? "git")
    (let [[_ major minor]
          (re-find #"git version (\d+)\.(\d+)"
                   (:out (process/shell {:out :string :continue true}
                                        "git" "--version")))]
      (when major
        (let [major (parse-long major)
              minor (parse-long minor)]
          (or (< major 2) (and (= major 2) (< minor 35))))))))

(defn universe-enabled? []
  (and (command-exists? "apt-cache")
       (str/includes? (:out (process/shell {:out :string :continue true}
                                           "apt-cache" "policy"))
                      "l=Ubuntu,c=universe")))

(defn resource-operations [{:keys [target release wsl]} sudo]
  (let [cache (str (or (System/getenv "XDG_CACHE_HOME")
                       (some-> (System/getenv "HOME") (str "/.cache"))
                       (str (System/getProperty "user.home") "/.cache"))
                   "/dotfiles/package-plan")]
    (vec
     (concat
      (when (and (= target :ubuntu) (not (universe-enabled?)))
        [{:kind :repository :name :ubuntu-universe
          :argv (into sudo ["add-apt-repository" "-y" "universe"])}])
      (when (and (#{:debian :ubuntu} target) (not (command-exists? "pwsh")))
        (let [deb (str cache "/packages-microsoft-prod.deb")
              distro (name target)]
          [{:kind :download :name :powershell-repository
            :destination deb
            :argv ["curl" "--fail" "--location" "--output" deb
                   (str "https://packages.microsoft.com/config/" distro "/" release
                        "/packages-microsoft-prod.deb")]}
           {:kind :repository :name :powershell-repository
            :argv (into sudo ["dpkg" "--install" deb])}]))
      (when (and (#{:debian :ubuntu} target) (not wsl)
                 (not (command-exists? "code")))
        (let [deb (str cache "/code.deb")]
          [{:kind :download :name :vscode-deb
            :destination deb
            :argv ["curl" "--fail" "--location" "--output" deb
                   "https://go.microsoft.com/fwlink/?LinkID=760868"]}
           {:kind :package-file :name :vscode-deb
            :argv (into sudo ["apt-get" "install" "-y" deb])}]))
      (when (and (= target :ubuntu) (old-git?))
        [{:kind :repository :name :git-ppa
          :argv (into sudo ["add-apt-repository" "-y" "ppa:git-core/ppa"])}])
      (when (= target :fedora)
        [{:kind :repository :name :onepassword-fedora-key
          :argv (into sudo ["rpm" "--import"
                            "https://downloads.1password.com/linux/keys/1password.asc"])}
         {:kind :repository :name :onepassword-fedora
          :argv (into sudo ["install" "-m" "0644"
                            (str root "/install/1password.repo")
                            "/etc/yum.repos.d/1password.repo"])}
         {:kind :repository :name :rpmfusion
          :argv (into sudo ["dnf" "install" "-y"
                            (str "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-" release ".noarch.rpm")
                            (str "https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-" release ".noarch.rpm")])}
         {:kind :packages :name :rpmfusion-codecs
          :argv (into sudo ["dnf" "install" "-y" "libavcodec-freeworld"
                            "h264enc" "x264" "x265" "openh264" "--allow-erasing"])}])))))

(defn package-operations [policy host sudo mise]
  (let [target (:target host)
        selected (selected-packages policy host)
        dispositions (map #(assoc (disposition policy target %) :logical %) selected)
        skipped (filter #(= :skip (:kind %)) dispositions)
        grouped (group-by :manager (remove #(= :skip (:kind %)) dispositions))]
    {:skipped (mapv #(select-keys % [:logical :reason]) skipped)
     :operations
     (vec
      (for [[manager entries] (sort-by (comp name key) grouped)
            :let [packages (->> entries (mapcat :packages) (map name) distinct sort vec)]]
        (if (= manager :pacman)
          {:kind :packages :manager manager
           :argv (into (vec sudo)
                       (concat ["pacman" "--sync" "--refresh" "--sysupgrade"
                                "--needed" "--"] packages))}
          {:kind :packages :manager manager
           :argv (into [mise "bootstrap" "packages" "apply"]
                       (concat (when (= manager :apt) ["--update"])
                               ["--yes"]
                               (map #(str (name manager) ":" %) packages)))})))}))

(defn build-plan [policy host mise]
  (let [sudo (planned-sudo-prefix)
        packages (package-operations policy host sudo mise)]
    {:host host
     :skipped (:skipped packages)
     :operations (into (resource-operations host sudo) (:operations packages))}))

(defn printable-plan [plan]
  (doseq [{:keys [kind manager argv] operation-name :name} (:operations plan)]
    (println (str (name kind)
                  (when (or operation-name manager)
                    (str " " (name (or operation-name manager))))
                  ": " (str/join " " (map pr-str argv)))))
  (doseq [{:keys [logical reason]} (:skipped plan)]
    (println "skip" (name logical) "-" reason)))

(defn execute! [plan dry-run? yes?]
  (printable-plan plan)
  (when-not dry-run?
    (require-elevation! (:host plan))
    (when-not yes?
      (print "Apply this package plan? [y/N] ")
      (flush)
      (when-not (= "y" (some-> (read-line) str/lower-case))
        (fail! "package plan declined")))
    (doseq [{:keys [argv kind manager destination]} (:operations plan)]
      (when destination (fs/create-dirs (fs/parent destination)))
      (let [options (cond-> {:inherit true}
                      (and (= :chimera (get-in plan [:host :target]))
                           (= :packages kind)
                           (= :apk manager))
                      (assoc :extra-env {"PATH" (str root "/vendor/doas-sudo-shim:"
                                                     (System/getenv "PATH"))}))
            result @(process/process argv options)]
        (when-not (zero? (:exit result))
          (fail! (str "operation failed with status " (:exit result))))))))

(defn matrix [policy]
  (doseq [package (sort-by name (logical-packages policy))]
    (let [cells (for [target targets
                      :let [{:keys [kind manager packages reason]}
                            (disposition policy target package)]]
                  (if (= kind :skip)
                    (str "skip:" reason)
                    (str (name kind) ":" (name manager) ":"
                         (str/join "," (map name packages)))))]
      (println (str (name package) "\t" (str/join "\t" cells))))))

(defn explain [policy package]
  (when-not (and package ((logical-packages policy) package))
    (fail! (str "unknown logical package: " (or (some-> package name) "<missing>"))))
  (doseq [target targets]
    (println (name target) (pr-str (disposition policy target package)))))

(defn run [arguments]
  (let [policy (validate-policy (read-policy))
        command (first arguments)
        flags (set (rest arguments))]
    (when (#{"show" "apply"} command)
      (when-let [unknown (first (remove #{"--dry-run" "--yes"} flags))]
        (fail! (str "unknown option: " unknown))))
    (case command
      "validate" (println "package policy is valid")
      "matrix" (matrix policy)
      "explain" (explain policy (some-> (second arguments) keyword))
      ("show" "apply")
      (let [host (detect-host)
            mise (ensure-mise! host)
            plan (build-plan policy host mise)]
        (if (= "show" command)
          (printable-plan plan)
          (execute! plan (contains? flags "--dry-run")
                    (contains? flags "--yes"))))
      (fail! "usage: package-plan {validate|show|matrix|explain PACKAGE|apply [--dry-run] [--yes]}"))))

(defn -main [& arguments]
  (try
    (run arguments)
    (catch clojure.lang.ExceptionInfo error
      (binding [*out* *err*] (println "package-plan:" (ex-message error)))
      (System/exit 1))
    (catch Exception error
      (binding [*out* *err*] (println "package-plan:" (ex-message error)))
      (System/exit 1))))
