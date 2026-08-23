#!/usr/bin/env bb

(ns agent-permissions.render
  (:require [cheshire.core :as json]
            [clojure.set]
            [clojure.string :as str]
            [clojure.walk]
            [sci.core :as sci]))

(def targets #{:codex :claude})
(def rule-keys #{:decision :match :pattern :reason :targets})
(def token-pattern #"[A-Za-z0-9_./:=+@%,-]+")

(def sci-options
  {:classes {}
   :deny '[clojure.core/load-file
           clojure.core/print
           clojure.core/printf
           clojure.core/println
           clojure.core/prn
           clojure.core/read
           clojure.core/read-line
           clojure.core/slurp
           clojure.core/spit
           clojure.core/tap>
           clojure.core/use]
   :load-fn (fn [{:keys [namespace]}]
              (throw (ex-info "namespace unavailable in policy planner"
                              {:namespace namespace})))
   :namespaces {'clojure.set
                (sci/copy-ns clojure.set (sci/create-ns 'clojure.set))
                'clojure.string
                (sci/copy-ns clojure.string (sci/create-ns 'clojure.string))
                'clojure.walk
                (sci/copy-ns clojure.walk (sci/create-ns 'clojure.walk))}})

(defn load-policy [source]
  (sci/eval-string source sci-options))

(defn valid-component? [component]
  (or (and (string? component) (re-matches token-pattern component))
      (and (map? component)
           (= #{:one-of} (set (keys component)))
           (seq (:one-of component))
           (every? #(and (string? %) (re-matches token-pattern %))
                   (:one-of component)))))

(defn validate-rule! [{:keys [decision match pattern reason targets] :as rule}]
  (when-not (= rule-keys (set (keys rule)))
    (throw (ex-info "rules must contain exactly the supported fields" {:rule rule})))
  (when-not (contains? #{:allow :deny} decision)
    (throw (ex-info "invalid policy decision" {:rule rule})))
  (when-not (contains? #{:prefix :descendants :exact} match)
    (throw (ex-info "match must be :prefix, :descendants, or :exact" {:rule rule})))
  (when (and (contains? targets :codex) (not= :prefix match))
    (throw (ex-info "Codex rules support only prefix matching" {:rule rule})))
  (when-not (and (vector? pattern) (seq pattern)
                 (every? valid-component? pattern))
    (throw (ex-info "patterns must be nonempty vectors of command tokens or one-of forms"
                    {:rule rule})))
  (when-not (and (set? targets) (seq targets)
                 (every? agent-permissions.render/targets targets))
    (throw (ex-info "targets must contain only :codex or :claude" {:rule rule})))
  (when (and (= :allow decision) (some? reason))
    (throw (ex-info "allow rules cannot have reasons" {:rule rule})))
  (when (and (= :deny decision) (not (string? reason)))
    (throw (ex-info "deny rules require a reason" {:rule rule})))
  rule)

(defn validate-policy! [rules]
  (when-not (vector? rules)
    (throw (ex-info "policy must return a vector of rules" {:value rules})))
  (mapv validate-rule! rules))

(defn starlark-component [component]
  (if (string? component)
    (json/generate-string component)
    (str "[" (str/join ", " (map json/generate-string (:one-of component))) "]")))

(defn render-codex-rule [{:keys [decision pattern reason]}]
  (str (name decision) "(["
       (str/join ", " (map starlark-component pattern))
       "]"
       (when (= :deny decision)
         (str ", " (json/generate-string reason)))
       ")"))

(defn render-codex [rules]
  (str "def allow(pattern):\n"
       "    prefix_rule(pattern=pattern, decision=\"allow\")\n"
       "def deny(pattern, reason):\n"
       "    prefix_rule(pattern=pattern, decision=\"forbidden\", justification=reason)\n\n"
       (str/join "\n" (map render-codex-rule
                            (filter #(contains? (:targets %) :codex) rules)))
       "\n"))

(defn expand-pattern [pattern]
  (reduce (fn [prefixes component]
            (for [prefix prefixes
                  token (if (string? component) [component] (:one-of component))]
              (conj prefix token)))
          [[]]
          pattern))

(defn bash-rules [rules decision]
  (->> rules
       (filter #(and (= decision (:decision %))
                     (contains? (:targets %) :claude)))
       (mapcat (fn [{:keys [match pattern]}]
                 (for [tokens (expand-pattern pattern)
                       suffix (case match
                                :exact [""]
                                :descendants [" *"]
                                :prefix ["" " *"])]
                   (str "Bash(" (str/join " " tokens) suffix ")"))))
       distinct
       vec))

(defn base-bash-rules [base]
  (for [decision ["allow" "deny"]
        entry (get-in base ["permissions" decision] [])
        :when (str/starts-with? entry "Bash(")]
    [decision entry]))

(defn assert-no-base-bash-rules! [base]
  (when-let [entries (seq (base-bash-rules base))]
    (throw (ex-info "base Claude settings still contain Bash rules; migrate them to the shared policy"
                    {:rules (vec entries)})))
  base)

(defn append-rules [existing generated]
  (into (vec (or existing [])) generated))

(defn merge-claude-settings [base rules]
  (-> base
      assert-no-base-bash-rules!
      (update-in ["permissions" "allow"] append-rules
                 (bash-rules rules :allow))
      (update-in ["permissions" "deny"] append-rules
                 (bash-rules rules :deny))))

(defn read-policy [path]
  (-> path slurp load-policy validate-policy!))

(defn usage! []
  (binding [*out* *err*]
    (println "usage: render.clj codex POLICY | render.clj claude POLICY BASE-SETTINGS"))
  (System/exit 2))

(defn -main [& args]
  (case [(first args) (count args)]
    ["codex" 2]
    (print (render-codex (read-policy (second args))))

    ["claude" 3]
    (let [base (json/parse-string (slurp (nth args 2)))]
      (println (json/generate-string
                (merge-claude-settings base (read-policy (second args)))
                {:pretty true})))

    (usage!)))

(when (= *file* (System/getProperty "babashka.file"))
  (apply -main *command-line-args*))
