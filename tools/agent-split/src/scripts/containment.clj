(ns scripts.containment
  (:require [clojure.string :as str]
            [clojure.set :as set]))

(defn decode-utf8
  "Return text only when decoding is lossless. A replacement character may be
   legitimate UTF-8, but malformed bytes must never alias that character."
  [bytes]
  (let [text (String. bytes "UTF-8")]
    (when (= (vec bytes) (vec (.getBytes text "UTF-8"))) text)))

(defn change-index
  "Index canonical tree diffs by base-coordinate edit regions. Counts and right
   coordinates do not identify an occurrence: earlier unselected edits shift them.
   Newline state belongs to each line; additions remain ordered and retain repeats."
  [text]
  (let [index (atom {})
        file (atom nil)
        cursor (atom nil)
        region (atom nil)
        last-side (atom nil)
        binary? (atom false)
        flush! (fn []
                 (when @region
                   (swap! index update-in [@file :edits] (fnil conj []) @region)
                   (reset! region nil)))]
    (doseq [line (str/split text #"\n")]
      (cond
        (str/starts-with? line "diff --git ")
        (do (flush!)
            (reset! file (second (re-matches #"diff --git a/.+ b/(.+)" line)))
            (reset! cursor nil)
            (reset! binary? false)
            (swap! index assoc @file {:modes #{} :edits [] :binary [] :context {}}))

        (or @binary? (= line "GIT binary patch")
            (str/starts-with? line "Binary files "))
        (do (reset! binary? true)
            (swap! index update-in [@file :binary] conj line))

        (str/starts-with? line "@@ ")
        (do (flush!)
            (reset! cursor
                    (some-> (re-find #"^@@ -([0-9]+)" line) second parse-long (max 1))))

        (and @cursor (= line "\\ No newline at end of file"))
        (if (= @last-side :context)
          (swap! index assoc-in [@file :context (dec @cursor) :newline?] false)
          (when (and @region @last-side)
            (swap! region update @last-side
                   #(update % (dec (count %)) assoc :newline? false))))

        (and @cursor (or (str/starts-with? line "-")
                         (str/starts-with? line "+")))
        (let [side (if (str/starts-with? line "-") :removed :added)]
          (when-not @region
            (reset! region {:start @cursor :removed [] :added []}))
          (swap! region update side conj
                 (cond-> {:text (subs line 1) :newline? true}
                   (= side :removed) (assoc :position @cursor)))
          (reset! last-side side)
          (when (= side :removed) (swap! cursor inc)))

        (and @cursor (str/starts-with? line " "))
        (do (flush!)
            (swap! index assoc-in [@file :context @cursor]
                   {:text (subs line 1) :newline? true :position @cursor})
            (swap! cursor inc)
            (reset! last-side :context))

        (some #(str/starts-with? line %)
              ["old mode " "new mode " "deleted file mode " "new file mode "])
        (swap! index update-in [@file :modes] conj line)))
    (flush!)
    @index))

(defn- subsequence? [selected original]
  (loop [s (seq selected) o (seq original)]
    (cond (nil? s) true
          (nil? o) false
          (= (first s) (first o)) (recur (next s) (next o))
          :else (recur s (next o)))))

(defn- lines [index side]
  (mapcat (fn [{:keys [start] :as region}]
            (if (= side :removed)
              (:removed region)
              ;; Pure insertions share one base gap: any ordered subset is valid.
              ;; Replacements retain ordinal correspondence, allowing adjacent
              ;; one-for-one edits without borrowing another removal's addition.
              (map-indexed #(assoc %2 :position
                                   (if (empty? (:removed region)) start (+ start %1)))
                           (:added region))))
          (:edits index)))

(defn- within-region? [original selected]
  (<= (:start original)
      (:start selected)
      (+ (:start selected) (count (:removed selected)))
      (+ (:start original) (count (:removed original)))))

(defn- binary-section [index]
  ;; A section before another file has a trailing separator; split at EOF may
  ;; omit it. Remove only framing newlines, preserving all canonical payload.
  (str/replace (str/join "\n" (:binary index)) #"\n+$" ""))

(defn- deletion-fragments
  "Account for alternate blank-line alignment only for pure deletions of whole
   replacement regions. Git can retain an empty boundary as context while a
   section deletion removes it; the unselected replacement retains that boundary.
   Never move additions across these boundaries or discard arbitrary whitespace."
  [original selected]
  (let [edits (:edits original)
        removed (:removed selected)
        selected-lines (set removed)
        touched (filter #(some selected-lines (:removed %)) edits)
        whole? (every? #(every? selected-lines (:removed %)) touched)
        boundaries (set (mapcat (fn [region]
                                 (when (seq (:added region))
                                   [(dec (:start region))
                                    (+ (:start region) (count (:removed region)))]))
                               touched))
        authorized-removals (set (mapcat :removed touched))
        boundary? (fn [line]
                    (and (contains? boundaries (:position line))
                         ;; CR is part of a CRLF empty line, not ignorable space.
                         (or (= "" (:text line))
                             (and (= "\r" (:text line)) (:newline? line)))
                         (= line (get (:context original) (:position line)))))]
    (if (and (empty? (:added selected)) (seq removed) (seq touched) whole?
             (= (count removed) (count selected-lines))
             (every? #(or (contains? authorized-removals %) (boundary? %)) removed))
      ;; Split deletions back by their original owners. This is not a merged
      ;; allowance: the normal pooled occurrence check still owns each region.
      (mapv #(assoc % :added []) touched)
      [selected])))

(defn- region-location [{:keys [start removed]}]
  (case (count removed)
    0 (str "base gap before line " start)
    1 (str "base line " start)
    (str "base lines " start "-" (+ start (dec (count removed))))))

(defn rejection-reason
  "Return nil for a contained selection, otherwise identify the rejected edit
   using parent/base coordinates. This is the sole containment decision path."
  [original selected]
  (let [regions (mapcat (fn [region]
                          (if (some #(within-region? % region) (:edits original))
                            [region]
                            (deletion-fragments original region)))
                        (:edits selected))
        groups (group-by (fn [region]
                          (first (keep-indexed
                                  #(when (within-region? %2 region) %1)
                                  (:edits original))))
                        regions)]
    (cond
      (nil? original)
      (str (when-let [region (first (:edits selected))]
             (str "selected " (region-location region) ": "))
           "selected path has no change in the original diff")
      (not (or (seq (:modes selected)) (seq (:edits selected)) (seq (:binary selected))))
      "selected diff has no edits"
      ;; Whole binary blobs are selected by canonical equality, not mode lines
      ;; or payload parsing. Binary and mode failures have no text coordinates.
      (and (seq (:binary selected))
           (not= (binary-section original) (binary-section selected)))
      "selected binary patch differs from the original binary change"
      (not (set/subset? (:modes selected) (:modes original)))
      "selected file-mode change is absent from the original diff"
      (contains? groups nil)
      (str "selected " (region-location (first (get groups nil)))
           " does not fit an original edit region; crosses unchanged context or lies outside the original edits")
      :else
      ;; Pool fragments to prevent reused allowances, and inspect original
      ;; regions in source order so the first diagnostic is deterministic.
      (some (fn [[ordinal regions]]
              (let [region (nth (:edits original) ordinal)
                    original-region {:edits [region]}
                    selected-regions {:edits regions}
                    location (str "selected " (str/join ", " (map region-location regions))
                                  "; original edit at " (region-location region) ": ")]
                (cond
                  (not (subsequence? (lines selected-regions :removed)
                                     (lines original-region :removed)))
                  (str location "removed lines differ in occurrence, count, order, or newline state")
                  (not (subsequence? (lines selected-regions :added)
                                     (lines original-region :added)))
                  (str location "added lines differ in content, count, order, replacement position, or newline state"))))
            (sort-by key groups)))))
