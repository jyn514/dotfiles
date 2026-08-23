#!/usr/bin/env bb

(ns agent-permissions.render
  (:require [cheshire.core :as json]
            [clojure.string :as str]
            [sci.core :as sci]))

(def targets #{:codex :claude})
(def option-keys #{:match :reason :targets})
(def token-pattern #"[A-Za-z0-9_./:=+@%,-]+")
(def max-policy-bytes (* 64 1024))
(def evaluation-timeout-nanos (* 500 1000 1000))

(defn one-of [& values]
  {:one-of (vec values)})

(defn rule [decision pattern options]
  (let [unknown-options (remove option-keys (keys options))]
    (when (seq unknown-options)
      (throw (ex-info "unknown policy options" {:options (vec unknown-options)})))
    {:decision decision
     :match (or (:match options) :prefix)
     :pattern pattern
     :reason (:reason options)
     :targets (set (or (:targets options) targets))}))

(defn allow [pattern & {:as options}]
  (rule :allow pattern options))

(defn deny [pattern & {:as options}]
  (rule :deny pattern options))

(defn policy [& rules]
  (vec rules))

(defn sci-options [deadline]
  {:allow '[let let* policy allow deny one-of]
   :interrupt-fn #(when (> (System/nanoTime) deadline)
                    (throw (ex-info "policy evaluation exceeded 500ms" {})))
   :namespaces {'agent-permissions.render
                {'policy policy
                 'allow allow
                 'deny deny
                 'one-of one-of}}})

(defn load-policy [source]
  (when (> (count (.getBytes source "UTF-8")) max-policy-bytes)
    (throw (ex-info "policy source exceeds 64 KiB" {})))
  (sci/eval-string source
                   (sci-options (+ (System/nanoTime) evaluation-timeout-nanos))))

(defn valid-component? [component]
  (or (and (string? component) (re-matches token-pattern component))
      (and (map? component)
           (= #{:one-of} (set (keys component)))
           (seq (:one-of component))
           (every? #(and (string? %) (re-matches token-pattern %))
                   (:one-of component)))))

(defn validate-rule! [{:keys [decision match pattern reason targets] :as rule}]
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
