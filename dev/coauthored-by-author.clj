#!/usr/bin/env bb

(ns dev.coauthored-by-author
  (:require
   [babashka.process :as process]
   [clojure.string :as str]))

(def default-match #"(?i)^Claude\b")

(defn shell
  [& args]
  (if (map? (first args))
    (apply process/shell (merge {:shutdown nil} (first args)) (rest args))
    (apply process/shell {:shutdown nil} args)))

(defn usage []
  (println "Usage: bb dev/coauthored-by-author.clj [--apply] [--keep-trailer] [--refs REF ...] [--match REGEX]")
  (println)
  (println "Find commits with a matching Co-Authored-By trailer and rewrite their")
  (println "primary author to the trailer identity using git-filter-repo. The matching")
  (println "trailer is removed unless --keep-trailer is passed.")
  (println)
  (println "Defaults:")
  (println "  --match '(?i)^Claude\\b'")
  (println "  --refs  HEAD")
  (println)
  (println "Without --apply, prints the commits that would be rewritten."))

(defn sh
  [& args]
  (let [result (apply shell
                      {:out :string
                       :err :string
                       :continue true}
                      args)]
    (if (zero? (:exit result))
      (:out result)
      (throw (ex-info (str "Command failed: " (str/join " " args)
                           (when (seq (:err result))
                             (str "\n" (:err result))))
                      {:args args
                       :exit (:exit result)})))))

(defn git
  [& args]
  (apply sh "git" args))

(defn parse-args
  [args]
  (loop [args args
         opts {:apply? false
               :keep-trailer? false
               :refs []
               :match default-match}]
    (case (first args)
      nil (update opts :refs #(if (seq %) % ["HEAD"]))
      "--help" (assoc opts :help? true)
      "-h" (assoc opts :help? true)
      "--apply" (recur (rest args) (assoc opts :apply? true))
      "--keep-trailer" (recur (rest args) (assoc opts :keep-trailer? true))
      "--refs" (let [refs (take-while #(not (str/starts-with? % "--")) (rest args))]
                 (when-not (seq refs)
                   (throw (ex-info "--refs requires at least one ref" {})))
                 (recur (drop (inc (count refs)) args)
                        (update opts :refs into refs)))
      "--match" (let [pattern (second args)]
                  (when-not pattern
                    (throw (ex-info "--match requires a regex" {})))
                  (recur (nnext args) (assoc opts :match (re-pattern pattern))))
      (throw (ex-info (str "Unknown argument: " (first args)) {})))))

(defn commit-records
  [refs]
  (->> (apply git "log" "--reverse" "--format=%H%x00%an%x00%ae%x00%B%x1e" refs)
       (#(str/split % #"\u001e"))
       (keep (fn [record]
               (let [record (str/trim-newline record)]
                 (when-not (str/blank? record)
                   (let [[commit author-name author-email message] (str/split record #"\u0000" 4)]
                     {:commit commit
                      :author {:name author-name
                               :email author-email}
                      :message message})))))))

(defn parsed-trailers
  [message]
  (->> (shell {:in message
               :out :string
               :err :string
               :continue true}
              "git"
              "interpret-trailers"
              "--parse")
       ((fn [{:keys [exit out err]}]
          (if (zero? exit)
            out
            (throw (ex-info (str "git interpret-trailers failed\n" err)
                            {:exit exit})))))
       str/split-lines
       (keep (fn [line]
               (when-let [[_ token value] (re-matches #"([^:]+):[ \t]*(.*)" line)]
                 [(str/lower-case token) value])))))

(defn parse-person
  [value]
  (when-let [[_ name email] (re-matches #"\s*(.*?)\s*<([^<>]+)>\s*" value)]
    {:name name
     :email email}))

(defn matching-coauthor
  [match-re message]
  (->> (parsed-trailers message)
       (filter (fn [[token _]] (= "co-authored-by" token)))
       (keep (fn [[_ value]]
               (when-let [person (parse-person value)]
                 (when (re-find match-re (:name person))
                   person))))
       first))

(defn candidates
  [{:keys [refs match]}]
  (->> (commit-records refs)
       (filter (fn [{:keys [message]}] (str/includes? message "Co-Authored-By:")))
       (keep (fn [{:keys [commit author message]}]
               (when-let [person (matching-coauthor match message)]
                 (when (not= author person)
                   {:commit commit
                    :author author
                    :new-author person}))))))

(defn print-candidate
  [{:keys [commit author new-author]}]
  (println (format "%s  %s <%s>  ->  %s <%s>"
                   commit
                   (:name author)
                   (:email author)
                   (:name new-author)
                   (:email new-author))))

(defn callback-source
  [{:keys [keep-trailer?]} candidates]
  (letfn [(py-string [s] (pr-str s))
          (entry [{:keys [commit new-author]}]
            (str "    " (py-string (str/trim commit)) ": "
                 "{'name': " (py-string (:name new-author))
                 ", 'email': " (py-string (:email new-author)) "}"))]
    (str "authors = {\n"
         (str/join ",\n" (map entry candidates))
         "\n}\n"
         "commit_id = commit.original_id.decode('ascii')\n"
         "author = authors.get(commit_id)\n"
         "if author:\n"
         "    commit.author_name = author['name'].encode('utf-8')\n"
         "    commit.author_email = author['email'].encode('utf-8')\n"
         (when-not keep-trailer?
           (str "    import re\n"
                "    trailer_value = ('%s <%s>' % (author['name'], author['email'])).encode('utf-8')\n"
                "    commit.message = re.sub(rb'(?im)^Co-Authored-By:[ \\t]*' + re.escape(trailer_value) + rb'[ \\t]*\\n?', b'', commit.message)\n"
                "    commit.message = re.sub(rb'\\n{3,}$', b'\\n\\n', commit.message)\n")))))

(defn temp-callback-path []
  (let [root (or (System/getenv "TMPDIR") (System/getProperty "java.io.tmpdir"))]
    (str (java.nio.file.Files/createTempFile
          (.toPath (java.io.File. root))
          "coauthored-by-author-"
          ".py"
          (make-array java.nio.file.attribute.FileAttribute 0)))))

(defn clean-worktree? []
  (str/blank? (git "status" "--porcelain=v1")))

(defn apply-rewrite!
  [opts candidates]
  (when-not (seq candidates)
    (println "Nothing to rewrite.")
    (System/exit 0))
  (when-not (clean-worktree?)
    (throw (ex-info "Refusing to rewrite history with a dirty Git worktree." {})))
  (let [callback (temp-callback-path)]
    (spit callback (callback-source opts candidates))
    (apply sh
           "git"
           "filter-repo"
           "--refs"
           (concat (:refs opts)
                   ["--commit-callback"
                    (str "exec(open(" (pr-str callback) ").read())")]))))

(defn -main
  [& args]
  (let [opts (parse-args args)]
    (if (:help? opts)
      (usage)
      (let [candidates (vec (candidates opts))]
        (if (seq candidates)
          (run! print-candidate candidates)
          (println "No matching Co-Authored-By trailers found."))
        (when (:apply? opts)
          (apply-rewrite! opts candidates))))))

(try
  (apply -main *command-line-args*)
  (catch Exception e
    (binding [*out* *err*]
      (println (.getMessage e)))
    (System/exit 1)))
