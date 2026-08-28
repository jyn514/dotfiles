#!/usr/bin/env python3
"""Evaluate a hand-authored Lapwing write-out decoder.

This deliberately contains no learned stroke mappings. The tables are direct
transcriptions/generalizations of Lapwing chapters 5-15 and Appendix D.
"""

from __future__ import annotations

import argparse
import json
import re
from functools import lru_cache
from itertools import product
from pathlib import Path

WORD_RE = re.compile(r"^[A-Za-z]+(?:[-'][A-Za-z]+)*$")
VOWEL_KEYS = set("AOEU")
FINGER_SPELLING_OUTLINES = dict(zip(
    "abcdefghijklmnopqrstuvwxyz",
    ("A*", "PW*", "KR*", "TK*", "E*", "TP*", "TKPW*", "H*", "EU*",
     "SKWR*", "K*", "HR*", "PH*", "TPH*", "O*", "P*", "KW*", "R*",
     "S*", "T*", "U*", "SR*", "W*", "KP*", "KWH*", "STKPW*"),
))
FINGER_SPELLING_LETTERS = {
    outline: letter for letter, outline in FINGER_SPELLING_OUTLINES.items()
}

INITIAL_TOKENS = {
    "TKPWHR": ("gl",), "STKPW": ("z",), "TKPWR": ("gr",),
    "TKPW": ("g", "gh"), "PWHR": ("bl",),
    "SKWR": ("j", "g"),
    "SPW": ("ent", "int"), "KPH": ("com",), "KPR": ("compr",),
    "STK": ("des", "dis"), "TKW": ("div",),
    "TPH": ("n", "kn", "gn"), "KWH": ("y",),
    "STR": ("str",), "SKR": ("scr", "skr"), "SPH": ("sm",),
    "SPR": ("spr",), "TKR": ("dr",), "TPR": ("fr",),
    "PWR": ("br",),
    "TK": ("d",), "PW": ("b",), "HR": ("l",),
    "TP": ("f", "ph"), "KW": ("qu", "q"), "PH": ("m",),
    "SR": ("v",), "SH": ("sh",), "KH": ("ch", "c", "k"),
    "TH": ("th",), "TW": ("tw", "chw"), "KP": ("x",),
    "KR": ("cr", "c", "kr"),
    "WR": ("wr", "r"), "WH": ("wh", "w"),
    "ST": ("st",), "SK": ("sk", "sc"), "SP": ("sp",),
    "TR": ("tr",), "PR": ("pr",),
    "S": ("s", "c"), "T": ("t",), "K": ("k", "c", "ch"),
    "P": ("p",), "W": ("w",), "H": ("h",), "R": ("r",),
}

STAR_INITIALS = {
    "TP": ("ph",),
}

VOWELS = {
    "": ("",),
    "A": ("a", "ea"), "E": ("e", "ea"),
    "EU": ("i", "y", "ie"),
    "O": ("o",), "U": ("u", "oo", "ou"),
    "OE": ("o", "oa", "oe", "ow"),
    "OU": ("ow", "ou"),
    "OEU": ("oi", "oy"),
    "AEU": ("a", "ai", "ay", "ei", "e"),
    "AOU": ("u", "ue", "ew", "iew", "oo", "ou"),
    "AOE": ("e", "ee", "ea", "ie", "y"),
    "AOEU": ("i", "igh", "y", "ie"),
    "AU": ("au", "aw", "o", "ough"),
    "AO": ("oo",),
    "AE": ("ai", "ei", "a", "ea", "ee", "ie", "e"),
}

FINAL_TOKENS = {
    "FRPBLG": ("nch",), "FRPB": ("rch", "nch"),
    "PBLG": ("j", "dge", "ge"),
    "FRB": ("rv",), "PBG": ("ng", "nj"),
    "RBS": ("cious", "tious", "shous"),
    "RBL": ("cial", "tial", "shal"),
    "BGS": ("x", "ction"), "BGT": ("ct", "kt"),
    "PLT": ("ment",),
    "BLT": ("bility", "ability", "ibility"),
    "PBD": ("nd",), "PBS": ("ns", "nce", "ness"),
    "PBT": ("nt",), "FL": ("fl", "ful", "val", "vel"),
    "FT": ("ft", "st"), "FR": ("fer", "ver", "fr"),
    "FP": ("ch", "tch", "sp"),
    "RB": ("sh", "rb", "ti", "ci"),
    "RP": ("rp",), "RL": ("rl", "ral"), "RT": ("rt",),
    "RD": ("rd",), "PT": ("pt",), "LD": ("ld",),
    "GS": ("tion", "sion", "cian"),
    "PL": ("m", "mb"), "BG": ("k", "ck", "c", "ch", "que"),
    "PB": ("n", "gn"),
    "LG": ("lj", "lch", "lk"), "GT": ("xt",),
    "BL": ("bl", "ble", "able", "ible"), "LT": ("lt", "let"),
    "F": ("f", "v", "s", "ph", "gh"), "R": ("r",),
    "P": ("p",),
    "B": ("b",), "L": ("l",), "G": ("g",), "T": ("t",),
    "S": ("s", "se", "ce"), "D": ("d",),
    "Z": ("z", "s", "se"),
}

STAR_FINALS = {
    "PL": ("mp",), "T": ("th", "t"), "LG": ("lk",),
    "FRB": ("rf",), "PBG": ("nk",), "BGS": ("ction",),
    "S": ("st", "s"), "F": ("f", "v"),
}

PREFIXES = {
    "A": ("a",), "KOE": ("co",), "TKAOE": ("de",),
    "TKE": ("de",), "TPOR": ("for",), "EUPB": ("in",),
    "PHEUS": ("mis",), "TPHOPB": ("non",),
    "PROE": ("pro",), "PRO": ("pro",), "PRE": ("pre",),
    "PRAOE": ("pre",), "RAOE": ("re",), "RE": ("re",),
    "EURPBT": ("inter",), "URPBD": ("under",),
    "PHULT": ("multi",), "PHEUPB": ("mini",),
    "PAEUR": ("para",), "PA*R": ("para",),
    "TPOR": ("for", "fore"), "EU": ("im", "in", "il"),
    "TKEU": ("dis",), "SAOURP": ("super",),
    "PHAOEURBG": ("micro",), "HAOEURP": ("hyper",),
    "KPRA": ("extra",), "PHO*PB": ("mono",),
    "OEUT": ("auto",), "SPHEU": ("semi",),
    "KOURPBT": ("counter",), "URLT": ("ultra",),
    "SUB": ("sub",),
}

SUFFIXES = {
    "AES": ("'s",),
    "A*R": ("ar",), "O*R": ("or",), "*ER": ("er",),
    "-FL": ("ful",), "-PBS": ("ness",), "-PLT": ("ment",),
    "-BLT": ("ability", "ibility"), "-BL": ("able", "ible"),
    "-LT": ("let",), "KWRAL": ("al",),
    "KWRAPBT": ("ant", "ent"), "KWRAEUGS": ("ation",),
    "KWRAOEUZ": ("ize",), "KWROUT": ("out",),
    "KWREUF": ("ive",), "KWREUFPL": ("ism",),
    "KWREUFT": ("ist",), "KWREUPB": ("in",),
    "KWREUBG": ("ic",), "KWREPB": ("en",),
    "KWRAOEUDZ": ("ized",), "KWRAOEUGZ": ("izing",),
    "KWRAOEUSZ": ("izes",), "STKPWAEUGS": ("ization",),
    "TEU": ("ity",), "TEUZ": ("ities",),
    "TEUF": ("tive",), "TOER": ("atory",),
    "KWREUFL": ("ively",), "TEUFL": ("tively",),
    "SEU": ("cy",), "SEUS": ("sis",), "SEUF": ("sive",),
    "KWRAEUT": ("ate",), "KWRAEUTS": ("ates",),
    "KWRAEUGT": ("ating",),
    "KAEUT": ("cate",), "KAEUGS": ("cation",),
    "HRAEUT": ("late",), "HRAEUTS": ("lates",),
    "HRAEUGS": ("lation",), "HRAEUGT": ("lating",),
    "TPHAEUT": ("nate",), "TPHAEUGS": ("nation",),
    "TAEUGS": ("tation",), "RAEUGS": ("ration",),
    "KWRUS": ("ous",), "WUS": ("uous",),
    "KWRAER": ("ary",), "KWRALT": ("ality",),
    "KWRAPBLG": ("age",), "KWRAPB": ("ian", "an"),
    "KWRUPL": ("ium",), "KWREPBS": ("ence",),
    "EBL": ("bly",), "EFL": ("fully",),
    "KAL": ("cal", "cally", "ical"),
    "KAEL": ("cal", "cally", "ically"),
    "TEUBG": ("tic",), "TPHEUBG": ("nic",),
    "KHUR": ("ture",), "KHURZ": ("tures",),
    "SHAL": ("ial", "tial", "ential"),
    "SKWREU": ("ology",), "SKWREUFT": ("ologist",),
    "TPAOEU": ("ify",), "TPAOEUD": ("ified",),
    "TPAEUBGS": ("fication",), "TREU": ("try",),
    "KWRAR": ("iar",), "KWROR": ("ior",), "KWRER": ("ier",),
    "KWREFT": ("est",), "KWREU": ("y", "ly"),
    "HREU": ("ly", "ally"), "KWRAT": ("ate",),
    "KWROER": ("ory",), "KWRUR": ("ure", "ture"),
    "WAEUT": ("ate",), "WAURD": ("ward",),
    "-G": ("ing",), "-S": ("s",), "-D": ("ed",),
    "-Z": ("s",), "-LS": ("less",), "-LG": ("ling",),
    "-LD": ("led",), "-LZ": ("les",), "*ERZ": ("ers",),
    "TERZ": ("ters",), "-PLTS": ("ments",), "TEUFZ": ("tives",),
}

WHOLE_STROKES = {
    "TKPWRAF": ("graph",), "TKPWRAEF": ("graphy",),
    "TKPWRAFR": ("grapher",), "OLG": ("ology",),
    "KWRAL": ("al",), "WAL": ("ual",), "TWAL": ("tual",),
}


def parse_stroke(stroke: str) -> tuple[str, str, str, bool]:
    star = "*" in stroke
    clean = stroke.replace("*", "")
    if "-" in clean:
        left, right = clean.split("-", 1)
        return left, "", right, star
    vowel_positions = [i for i, character in enumerate(clean)
                       if character in VOWEL_KEYS]
    if vowel_positions:
        first, last = vowel_positions[0], vowel_positions[-1]
        return clean[:first], clean[first:last + 1], clean[last + 1:], star
    if star:
        star_position = stroke.index("*")
        return stroke[:star_position], "", stroke[star_position + 1:], True
    return clean, "", "", False


def segment(text: str, tokens: dict[str, tuple[str, ...]], limit: int = 512) -> list[tuple[str, ...]]:
    results: list[tuple[str, ...]] = []

    def visit(offset: int, pieces: tuple[str, ...]) -> None:
        if len(results) >= limit:
            return
        if offset == len(text):
            results.append(pieces)
            return
        matches = [token for token in tokens if text.startswith(token, offset)]
        for token in sorted(matches, key=lambda item: (-len(item), item)):
            for value in tokens[token]:
                visit(offset + len(token), pieces + (value,))

    visit(0, ())
    return results


def decode_stroke(stroke: str, limit: int = 2048) -> list[str]:
    direct = list(WHOLE_STROKES.get(stroke, ()))
    left, vowel, right, star = parse_stroke(stroke)
    initials = segment(left, INITIAL_TOKENS) if left else [()]
    finals = segment(right, FINAL_TOKENS) if right else [()]
    if star and left in STAR_INITIALS:
        initials = [(value,) for value in STAR_INITIALS[left]] + initials
    if star and right in STAR_FINALS:
        finals = [(value,) for value in STAR_FINALS[right]] + finals
    # Chapter 15: KWR may be a silent linker or an internal y/glide.
    if left == "KWR":
        initials = [(), ("y",), ("i",)] + initials
    vowels = VOWELS.get(vowel, ())
    silent_e_vowels = {"AEU", "AOEU", "OE", "AOU", "AOE"}
    for initial, nucleus, final in product(initials, vowels, finals):
        spelling = "".join(initial) + nucleus + "".join(final)
        direct.append(spelling)
        if (vowel in silent_e_vowels and final
                and spelling[-1:] not in "aeiouy"):
            direct.append(spelling + "e")
        if len(direct) >= limit:
            break
    return unique(direct)[:limit]


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def rebuild_stroke(left: str, vowel: str, right: str, star: bool) -> str:
    marker = "*" if star else ""
    if vowel:
        return left + vowel + marker + right
    if right:
        return left + marker + "-" + right
    return left + marker


def joins(root: str, addition: str, affix: bool) -> list[str]:
    values = [root + addition]
    if root and addition and not affix:
        values.append(root + "-" + addition)
    if root and addition and root[-1] == addition[0]:
        values.append(root + addition[1:])
    if not affix and addition == "l":
        values.append(root + "el")
    if affix and root.endswith("e") and addition[0:1] in "aeiouy":
        values.append(root[:-1] + addition)
    if affix and root.endswith("y") and addition not in ("y",):
        values.append(root[:-1] + "i" + addition)
    if affix and addition == "s":
        if root.endswith(("s", "x", "z", "ch", "sh")):
            values.append(root + "es")
        if root.endswith("y"):
            values.append(root[:-1] + "ies")
    if affix and addition == "ed":
        if root.endswith("e"):
            values.append(root + "d")
        if root.endswith("y"):
            values.append(root[:-1] + "ied")
    if affix and addition == "ing" and root.endswith("e"):
        values.append(root[:-1] + "ing")
    if affix and addition in ("ing", "ed") and len(root) >= 3:
        vowels = "aeiou"
        if root[-1] not in vowels + "wxy" and root[-2] in vowels and root[-3] not in vowels:
            values.append(root + root[-1] + addition)
    return unique(values)


@lru_cache(maxsize=512)
def decode_stroke_analyses(stroke: str, final_position: bool) -> tuple[str, ...]:
    analyses = decode_stroke(stroke)
    left, vowel, right, star = parse_stroke(stroke)
    folded_suffixes = {"G": "ing", "D": "ed", "Z": "s", "S": "s"}
    for marker, suffix in folded_suffixes.items():
        if not right.endswith(marker):
            continue
        base_right = right[:-1]
        if not (left or vowel or base_right):
            continue
        base_stroke = rebuild_stroke(left, vowel, base_right, star)
        for root in decode_stroke(base_stroke, limit=512):
            analyses.extend(joins(root, suffix, True))

    # Chapter 17 folding: a key can carry a following unstressed ending.
    fold_endings = {"L": ("ly", "al"), "T": ("ity", "ty")}
    if final_position:
        fold_endings["R"] = ("er", "or", "ar")
    for marker, endings in fold_endings.items():
        if not right.endswith(marker):
            continue
        base_stroke = rebuild_stroke(left, vowel, right[:-1], star)
        for root in decode_stroke(base_stroke, limit=256):
            for ending in endings:
                analyses.extend(joins(root, ending, True))
    if final_position and "E" in vowel:
        index = vowel.rfind("E")
        base_vowel = vowel[:index] + vowel[index + 1:]
        base_stroke = rebuild_stroke(left, base_vowel, right, star)
        for root in decode_stroke(base_stroke, limit=256):
            analyses.extend(joins(root, "y", True))
    return tuple(unique(analyses))


def orthographic_repairs(word: str) -> list[str]:
    """Return bounded one-edit repairs for common steno spelling omissions."""
    repairs: list[str] = []
    consonants = set("bcdfghjklmnpqrstvwxyz")
    for index, character in enumerate(word):
        if character in consonants:
            repairs.append(word[:index] + character + word[index:])
    for index in range(1, len(word)):
        for insertion in "aeiou'":
            repairs.append(word[:index] + insertion + word[index:])
    for index in range(len(word)):
        repairs.append(word[:index] + word[index + 1:])
    for index in range(len(word) - 1):
        if word[index] != word[index + 1]:
            repairs.append(word[:index] + word[index + 1] + word[index]
                           + word[index + 2:])
    substitutions = {
        "a": "eiou", "e": "aiou", "i": "aeou", "o": "aeiu", "u": "aeio",
        "c": "ks", "k": "c", "s": "c", "g": "j", "j": "g",
        "f": "v", "v": "f",
    }
    for index, character in enumerate(word):
        for replacement in substitutions.get(character, ""):
            repairs.append(word[:index] + replacement + word[index + 1:])
    # Lapwing's compressed SEL/PWRAEUGS family omits the unstressed vowel and
    # voices the initial consonant of "celebr-".
    if "selbr" in word:
        repairs.append(word.replace("selbr", "celebr", 1))
    # Folded liquid and broad-vowel strokes regularly collapse these spelling
    # sequences. Exact vocabulary membership decides which expansion is valid.
    repairs.extend(word[:index] + "al" + word[index + 1:]
                   for index, character in enumerate(word) if character == "o")
    repairs.extend(word[:index] + "l" + word[index + 2:]
                   for index in range(len(word) - 1)
                   if word[index:index + 2] == "hr")
    repairs.extend(word[:index] + "l" + word[index + 1:]
                   for index, character in enumerate(word) if character == "u")
    repairs.extend(word[:index] + "oll" + word[index + 2:]
                   for index in range(len(word) - 1)
                   if word[index:index + 2] == "hr")
    if word.endswith("f"):
        repairs.append(word[:-1] + "ve")
    if word.endswith("z"):
        repairs.append(word[:-1] + "es")
    repairs.extend(word[:index] + "ce" + word[index + 1:]
                   for index, character in enumerate(word) if character == "f")
    repairs.extend(word[:index] + "gh" + word[index:]
                   for index in range(1, len(word)))
    repairs.extend(word[:index] + "in" + word[index:]
                   for index in range(1, len(word)))
    # Regular spelling variants remain exact-vocabulary gated at runtime.
    repairs.extend(word[:index] + "our" + word[index + 2:]
                   for index in range(len(word) - 1)
                   if word[index:index + 2] == "or")
    repairs.extend(word[:index] + "is" + word[index + 2:]
                   for index in range(len(word) - 1)
                   if word[index:index + 2] == "iz")
    if word.endswith("er"):
        repairs.append(word[:-2] + "re")
    repairs.extend(word[:index] + "ll" + word[index + 1:]
                   for index in range(len(word) - 2)
                   if word[index] == "l"
                   and word[index + 1:].startswith(("ed", "ing")))
    return unique(repairs)


def generate_outline(outline: str, beam: int,
                     prefixes: set[str] | None = None,
                     prune_final: bool = True) -> list[str]:
    strokes = outline.split("/")
    if strokes and strokes[0].startswith("#"):
        strokes[0] = strokes[0][1:]
    if strokes and all(stroke in FINGER_SPELLING_LETTERS for stroke in strokes):
        # Explicit fingerspelling is authoritative and may intentionally produce
        # a word absent from the compact vocabulary.
        return ["".join(FINGER_SPELLING_LETTERS[stroke] for stroke in strokes)]
    if (len(strokes) > 1 and strokes[-1] == "AES"
            and all(stroke in FINGER_SPELLING_LETTERS for stroke in strokes[:-1])):
        return ["".join(FINGER_SPELLING_LETTERS[stroke] for stroke in strokes[:-1]) + "'s"]
    states = [""]
    for index, stroke in enumerate(strokes):
        analyses: list[tuple[str, bool]] = []
        if index == 0:
            analyses.extend((value, True) for value in PREFIXES.get(stroke, ()))
        if index > 0:
            analyses.extend((value, True) for value in SUFFIXES.get(stroke, ()))
        analyses.extend((value, False) for value in decode_stroke_analyses(
            stroke, final_position=index == len(strokes) - 1
        ))
        analyses = list(dict.fromkeys(analyses))[:beam]
        next_states: list[str] = []
        for state in states:
            for value, affix in analyses:
                joined = [value] if not state else joins(state, value, affix)
                next_states.extend(candidate for candidate in joined
                                   if (prefixes is None
                                       or (not prune_final
                                           and index + 1 == len(strokes))
                                       or candidate in prefixes))
                if len(next_states) >= beam * 2:
                    break
            if len(next_states) >= beam * 2:
                break
        states = unique(next_states)[:beam]
        if not states:
            return []
    return states


def decode_outline(outline: str, vocabulary: set[str], beam: int, top_k: int) -> list[str]:
    return [candidate for candidate in generate_outline(outline, beam)
            if candidate.lower() in vocabulary][:top_k]


def packed_rule_size() -> int:
    tables = (INITIAL_TOKENS, STAR_INITIALS, VOWELS, FINAL_TOKENS,
              STAR_FINALS, PREFIXES, SUFFIXES, WHOLE_STROKES)
    # Conservative byte-oriented representation: NUL-terminated keys/values.
    return sum(len(key) + 1 + sum(len(value) + 1 for value in values)
               for table in tables for key, values in table.items())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dictionary", type=Path)
    parser.add_argument("--beam", type=int, default=5000)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--max-entries", type=int, default=0)
    parser.add_argument("--evaluation-words", type=Path)
    args = parser.parse_args()

    raw = json.loads(args.dictionary.read_text())
    entries = [(outline, translation.lower())
               for outline, translation in raw.items()
               if WORD_RE.fullmatch(translation)]
    vocabulary = {translation for _, translation in entries}
    if args.evaluation_words:
        evaluation_words = {word.strip().lower() for word in args.evaluation_words.read_text().splitlines() if word.strip()}
        entries = [(outline, translation) for outline, translation in entries
                   if translation in evaluation_words]
        vocabulary &= evaluation_words
    if args.max_entries:
        entries = entries[:args.max_entries]

    generated = hit = top1 = 0
    by_length: dict[int, list[int]] = {}
    for outline, target in entries:
        candidates = decode_outline(outline, vocabulary, args.beam, args.top_k)
        generated += bool(candidates)
        hit += target in candidates
        top1 += bool(candidates and candidates[0] == target)
        bucket = by_length.setdefault(outline.count("/") + 1, [0, 0, 0])
        bucket[0] += 1
        bucket[1] += target in candidates
        bucket[2] += bool(candidates and candidates[0] == target)

    count = len(entries)
    report = {
        "entries": count,
        "vocabulary_words": len(vocabulary),
        "rule_table_bytes": packed_rule_size(),
        "candidate_coverage": generated / count if count else 0,
        "recall_at_k": hit / count if count else 0,
        "top1_accuracy": top1 / count if count else 0,
        "top_k": args.top_k,
        "by_outline_length": {
            str(length): {
                "entries": values[0],
                "recall_at_k": values[1] / values[0],
                "top1_accuracy": values[2] / values[0],
            }
            for length, values in sorted(by_length.items())
        },
        "notes": "Hand-authored rules only; vocabulary is used solely to filter complete generated spellings.",
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
