#!/usr/bin/env python3
"""Prototype: infer per-stroke orthographic chunks from a Plover JSON dictionary."""
from __future__ import annotations
import argparse, collections, hashlib, json, math, pickle, re, time
from pathlib import Path

WORD_RE = re.compile(r"^[A-Za-z]+(?:[-'][A-Za-z]+)*$")

def stable_u64(s: str, seed: str) -> int:
    return int.from_bytes(hashlib.sha256((seed + "\0" + s).encode()).digest()[:8], "big")

def load_data(path, test_fraction, seed, max_words=0):
    raw = json.loads(Path(path).read_text(encoding="utf8"))
    grouped = collections.defaultdict(list)
    for outline, text in raw.items():
        if WORD_RE.fullmatch(text):
            grouped[text].append(tuple(outline.split("/")))
    words = sorted(grouped, key=lambda w: (stable_u64(w, seed), w))
    if max_words:
        words = words[:max_words]
    cutoff = int(test_fraction * (1 << 64))
    test_words = {w for w in words if stable_u64(w, seed + ":split") < cutoff}
    train = [(s, w) for w in words if w not in test_words for s in grouped[w]]
    test = [(s, w) for w in words if w in test_words for s in grouped[w]]
    return train, test, set(words), len(raw)

def balanced_parts(word, n):
    # Nonempty, deterministic initial alignment.
    cuts = [round(i * len(word) / n) for i in range(n + 1)]
    cuts[0], cuts[-1] = 0, len(word)
    for i in range(1, n): cuts[i] = max(cuts[i], cuts[i-1] + 1)
    for i in range(n-1, 0, -1): cuts[i] = min(cuts[i], cuts[i+1] - 1)
    return tuple(word[cuts[i]:cuts[i+1]] for i in range(n))

def viterbi(strokes, word, model, alpha=.1):
    n, m = len(strokes), len(word)
    if m < n: return None
    # dp[i][j] = (score, tuple chunks), deterministic lexical tie break.
    dp = {(0, 0): (0.0, ())}
    for i, stroke in enumerate(strokes):
        counts = model.get(stroke, {})
        total = sum(counts.values())
        denom = total + alpha * (len(counts) + 1)
        for j in range(i, m - (n-i) + 1):
            old = dp.get((i, j))
            if old is None: continue
            max_end = m - (n-i-1)
            for e in range(j+1, max_end+1):
                chunk = word[j:e]
                if chunk in counts:
                    emit = math.log((counts[chunk] + alpha) / denom)
                else:
                    emit = math.log(alpha / denom) - 3.0
                # Weak regularizer prevents absurd unseen chunks during early rounds.
                emit -= .08 * abs(len(chunk) - len(word)/n)
                cand = (old[0] + emit, old[1] + (chunk,))
                key = (i+1, e)
                if key not in dp or cand[0] > dp[key][0] + 1e-12 or (abs(cand[0]-dp[key][0]) <= 1e-12 and cand[1] < dp[key][1]):
                    dp[key] = cand
    return dp.get((n, m), (None, None))[1]

def learn(entries, iterations, alpha):
    usable = [(s,w) for s,w in entries if len(s) >= 2 and len(w) >= len(s)]
    align = [(s,w,balanced_parts(w,len(s))) for s,w in usable]
    model = {}
    for it in range(iterations):
        counts = collections.defaultdict(collections.Counter)
        for strokes, _, chunks in align:
            for s,c in zip(strokes,chunks): counts[s][c] += 1
        model = {s: dict(c) for s,c in counts.items()}
        align = [(s,w,viterbi(s,w,model,alpha)) for s,w,_ in align]
    # Count final alignment (rather than penultimate one).
    counts = collections.defaultdict(collections.Counter)
    for strokes, _, chunks in align:
        for s,c in zip(strokes,chunks): counts[s][c] += 1
    return {s: dict(sorted(c.items())) for s,c in sorted(counts.items())}, len(usable)

def options(model, stroke, per_stroke):
    c = model.get(stroke, {})
    total = sum(c.values()) or 1
    return [(x, math.log(v/total)) for x,v in sorted(c.items(), key=lambda z:(-z[1],z[0]))[:per_stroke]]

def candidates(strokes, model, vocabulary, k, per_stroke, beam):
    states = [(0.0, "")]
    for s in strokes:
        opts = options(model, s, per_stroke)
        if not opts: return []
        states = sorted(((sc+v, text+c) for sc,text in states for c,v in opts), key=lambda z:(-z[0],z[1]))[:beam]
    out=[]; seen=set()
    for _, word in states:
        if word in vocabulary and word not in seen:
            seen.add(word); out.append(word)
            if len(out) == k: break
    return out

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("dictionary", help="official lapwing-base.json")
    ap.add_argument("--test-fraction",type=float,default=.2)
    ap.add_argument("--seed",default="lapwing-rule-proto-v1")
    ap.add_argument("--iterations",type=int,default=4)
    ap.add_argument("--alpha",type=float,default=.1)
    ap.add_argument("--top-k",type=int,default=10)
    ap.add_argument("--chunks-per-stroke",type=int,default=12)
    ap.add_argument("--max-model-strokes",type=int,default=0,help="retain only the most frequent strokes; 0 means all")
    ap.add_argument("--beam",type=int,default=5000,help="maximum unfiltered compositions")
    ap.add_argument("--max-words",type=int,default=0,help="deterministic subset; 0 means all")
    ap.add_argument("--model-out",help="write learned model as JSON")
    ap.add_argument("--evaluation-words",type=Path,help="newline word list used for evaluation and candidate filtering")
    args=ap.parse_args(argv)
    if not 0 < args.test_fraction < 1 or min(args.iterations,args.top_k,args.chunks_per_stroke,args.beam)<1: ap.error("invalid numeric option")
    start=time.perf_counter()
    train,test,vocab,raw_n=load_data(args.dictionary,args.test_fraction,args.seed,args.max_words)
    loaded=time.perf_counter()
    if args.evaluation_words:
        evaluation_words = {word.strip().lower() for word in args.evaluation_words.read_text().splitlines() if word.strip()}
        test = [(strokes, word) for strokes, word in test if word.lower() in evaluation_words]
        vocab = {word for word in vocab if word.lower() in evaluation_words}
    model,learn_n=learn(train,args.iterations,args.alpha)
    if args.max_model_strokes:
        retained = sorted(model, key=lambda stroke: (-sum(model[stroke].values()), stroke))[:args.max_model_strokes]
        model = {stroke: model[stroke] for stroke in sorted(retained)}
    model = {stroke: dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:args.chunks_per_stroke])
             for stroke, counts in model.items()}
    learned=time.perf_counter()
    eligible=hit=top1=0
    for strokes,target in test:
        # The model is intentionally learned only from multi-stroke entries, but can
        # compose an outline of any length if every stroke was observed there.
        if not all(s in model for s in strokes): continue
        eligible += 1
        cs=candidates(strokes,model,vocab,args.top_k,args.chunks_per_stroke,args.beam)
        hit += target in cs
        top1 += bool(cs and cs[0]==target)
    done=time.perf_counter()
    compact=json.dumps(model,separators=(",",":"),ensure_ascii=False).encode()
    pkl=pickle.dumps(model,protocol=5)
    packed_estimate = sum(
        4 + sum(2 + (len(chunk) * 5 + 7) // 8 for chunk in counts)
        for counts in model.values()
    )
    if args.model_out: Path(args.model_out).write_bytes(compact+b"\n")
    report={
      "raw_dictionary_entries":raw_n,"plain_vocabulary_words":len(vocab),
      "train_entries":len(train),"test_entries":len(test),"multi_stroke_training_entries":learn_n,
      "model_strokes":len(model),"model_mappings":sum(map(len,model.values())),
      "eligible_test_entries":eligible,"eligible_fraction":eligible/len(test) if test else 0.0,
      "candidate_recall_at_k":hit/eligible if eligible else 0.0,
      "overall_candidate_recall_at_k":hit/len(test) if test else 0.0,
      "top1_accuracy":top1/eligible if eligible else 0.0,
      "overall_top1_accuracy":top1/len(test) if test else 0.0,"top_k":args.top_k,
      "serialized_bytes":{"compact_json":len(compact),"pickle_protocol_5":len(pkl),
                          "packed_embedded_estimate":packed_estimate},
      "runtime_seconds":{"load_split":loaded-start,"learn":learned-loaded,"evaluate":done-learned,"total":done-start},
      "notes":"Metrics use test entries whose every stroke has a learned mapping; vocabulary filter includes all selected plain words."
    }
    print(json.dumps(report,indent=2,sort_keys=True))
if __name__ == "__main__": main()
