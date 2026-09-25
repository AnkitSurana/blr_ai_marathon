"""Category matcher using BM25 semantic token ranking and Character n-gram similarity.

Deterministic, fast, zero external dependencies.

Features:
- BM25 term weighting: rewards high-relevance domain keywords
- Token Dice + Char Tri-gram Dice: handles slight misspellings and partial word forms
- Morphological Stemmer: protects invariant words ending in 's' (e.g. lens, bus, status)
"""
import math
import re

STOP_WORDS = set("""
how many orders order were was there for in of the did we get number count total what show me
during placed sales are is a an our by to on and or with please tell list
""".split())

NORMALIZE_WORDS = {
    "clothes": "clothing"
}

INVARIANT_S_WORDS = {
    "lens", "bus", "gas", "plus", "canvas", "status", "focus", "basis", 
    "series", "species", "fitness", "business", "compass"
}


def stem(word: str) -> str:
    """Normalize and reduce English words to their base form safely."""
    word = NORMALIZE_WORDS.get(word, word)
    if word in INVARIANT_S_WORDS:
        return word
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("sses"):
        return word[:-2]  # e.g. dresses -> dress, glasses -> glass
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def clean_tokens(text: str) -> list[str]:
    """Extract clean, stemmed content tokens from text, removing punctuation and stop words."""
    cleaned = text.lower().replace("&", " and ").replace("'", "").replace("_", " ")
    raw_words = re.findall(r"[a-z0-9]+", cleaned)
    return [stem(w) for w in raw_words if w not in STOP_WORDS]


# Alias for backwards compatibility
toks = clean_tokens


def is_one_edit_distance(word_a: str, word_b: str) -> bool:
    """Return True if Levenshtein edit distance between word_a and word_b is at most 1."""
    if word_a == word_b:
        return True
    if abs(len(word_a) - len(word_b)) > 1:
        return False
    if len(word_a) > len(word_b):
        word_a, word_b = word_b, word_a
    i = j = diff_count = 0
    while i < len(word_a) and j < len(word_b):
        if word_a[i] == word_b[j]:
            i += 1
            j += 1
        else:
            diff_count += 1
            if diff_count > 1:
                return False
            if len(word_a) == len(word_b):
                i += 1
            j += 1
    return diff_count + (len(word_b) - j) + (len(word_a) - i) <= 1


lev1 = is_one_edit_distance


def tokens_match(token_a: str, token_b: str) -> bool:
    """Match exact tokens or allow 1-edit typo on words of length >= 5."""
    return token_a == token_b or (len(token_a) >= 5 and len(token_b) >= 5 and is_one_edit_distance(token_a, token_b))


tok_match = tokens_match


def count_token_hits(phrase_tokens: list[str], target_tokens: list[str]) -> int:
    """Count unique token matches between query tokens and target vocabulary tokens."""
    used_indices = set()
    hits = 0
    for query_token in phrase_tokens:
        for index, target_token in enumerate(target_tokens):
            if index not in used_indices and tokens_match(query_token, target_token):
                used_indices.add(index)
                hits += 1
                break
    return hits


token_hits = count_token_hits


def find_fuzzy_pairs(phrase_tokens: list[str], target_tokens: list[str]) -> list[tuple[str, str]]:
    """Return pairs of words that matched only via the 1-edit typo rule."""
    used_indices = set()
    fuzzy = []
    for query_token in phrase_tokens:
        for index, target_token in enumerate(target_tokens):
            if index not in used_indices and tokens_match(query_token, target_token):
                used_indices.add(index)
                if query_token != target_token:
                    fuzzy.append((query_token, target_token))
                break
    return fuzzy


fuzzy_pairs = find_fuzzy_pairs


def calculate_token_dice(phrase_tokens: list[str], target_tokens: list[str]) -> float:
    """Calculate Token Dice similarity coefficient (0.0 to 1.0)."""
    if not phrase_tokens or not target_tokens:
        return 0.0
    hits = count_token_hits(phrase_tokens, target_tokens)
    return 2.0 * hits / (len(phrase_tokens) + len(target_tokens))


token_dice = calculate_token_dice


def get_character_trigrams(token_list: list[str]) -> set[str]:
    """Extract character tri-grams with boundary padding."""
    text = " " + " ".join(token_list) + " "
    return {text[i:i + 3] for i in range(len(text) - 2)}


grams = get_character_trigrams


def calculate_char_dice(phrase_tokens: list[str], target_tokens: list[str]) -> float:
    """Calculate Character Trigram Dice similarity coefficient (0.0 to 1.0)."""
    trigrams_a = get_character_trigrams(phrase_tokens)
    trigrams_b = get_character_trigrams(target_tokens)
    if not trigrams_a or not trigrams_b:
        return 0.0
    shared = trigrams_a & trigrams_b
    return 2.0 * len(shared) / (len(trigrams_a) + len(trigrams_b))


char_dice = calculate_char_dice


def calculate_bm25_similarity(phrase_tokens: list[str], target_tokens: list[str], avg_len: float = 3.0) -> float:
    """Calculate lightweight BM25 term relevance score normalized to [0.0, 1.0]."""
    if not phrase_tokens or not target_tokens:
        return 0.0
    k1 = 1.5
    b = 0.75
    doc_len = len(target_tokens)
    score = 0.0
    for q_tok in phrase_tokens:
        # Term frequency in target
        tf = sum(1 for t in target_tokens if tokens_match(q_tok, t))
        if tf > 0:
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * (doc_len / max(1.0, avg_len)))
            score += numerator / max(1e-5, denominator)
    # Normalize score by query length
    return min(1.0, score / max(1, len(phrase_tokens)))


def compare(phrase_tokens: list[str], target_tokens: list[str]) -> tuple[float, float]:
    """Compare query tokens against target tokens.

    Returns:
        (similarity_score 0.0..1.0, coverage_ratio 0.0..1.0)
    """
    if phrase_tokens == target_tokens:
        return 1.0, 1.0
    if not phrase_tokens:
        return 0.0, 0.0

    coverage = count_token_hits(phrase_tokens, target_tokens) / len(phrase_tokens)

    from .config import CONFIG
    t_dice = calculate_token_dice(phrase_tokens, target_tokens)
    c_dice = calculate_char_dice(phrase_tokens, target_tokens)
    bm25 = calculate_bm25_similarity(phrase_tokens, target_tokens)

    # Hybrid blend: Token Dice + Char Dice + BM25 Lexical Weighting
    blended_score = (
        CONFIG.matcher.token_dice_weight * max(t_dice, bm25)
        + CONFIG.matcher.char_dice_weight * c_dice
    )
    return blended_score, coverage


def score_all(phrase_tokens: list[str], vocabulary: dict) -> list[tuple[str, float, str, float]]:
    """Rank all vocabulary categories by match similarity to phrase_tokens.

    Returns:
        List of (category_name, best_score, matched_phrase, coverage) sorted descending.
    """
    results = []
    for category_name, category_data in vocabulary.items():
        best_score = 0.0
        best_via = ""
        best_coverage = 0.0
        
        # Check canonical category name plus all defined aliases
        candidate_texts = [category_name] + category_data.get("aliases", [])
        for candidate_text in candidate_texts:
            candidate_tokens = clean_tokens(candidate_text)
            score, coverage = compare(phrase_tokens, candidate_tokens)
            if score > best_score:
                best_score = score
                best_via = candidate_text
                best_coverage = coverage
                
        results.append((category_name, best_score, best_via, best_coverage))

    results.sort(key=lambda item: -item[1])
    return results


def parse(question: str) -> tuple[str | None, list[str]]:
    """Extract 4-digit year and clean content tokens from question."""
    year_match = re.search(r"\b(20\d{2})\b", question)
    year = year_match.group(1) if year_match else None
    cleaned_question = re.sub(r"\b20\d{2}\b", " ", question)
    phrase_tokens = clean_tokens(cleaned_question)
    return year, phrase_tokens


def interpret(question: str, vocabulary: dict, threshold: float | None = None, margin: float | None = None) -> dict:
    """Interpret question and make routing decision: answer, clarify, confirm, or refuse."""
    from .config import CONFIG
    if threshold is None:
        threshold = CONFIG.matcher.interpret_threshold
    if margin is None:
        margin = CONFIG.matcher.ambiguity_margin

    year, phrase_tokens = parse(question)
    ranked = score_all(phrase_tokens, vocabulary)
    
    (cat1, score1, via1, cov1), (cat2, score2, _, _) = ranked[0], ranked[1]
    base_result = {
        "year": year,
        "phrase": " ".join(phrase_tokens),
        "tokens": phrase_tokens,
        "best": cat1,
        "score": round(score1, 3),
        "via": via1,
        "coverage": round(cov1, 3),
        "runner": cat2,
        "runner_score": round(score2, 3),
    }

    if not phrase_tokens or score1 < threshold or cov1 < CONFIG.matcher.coverage_floor:
        return {**base_result, "action": "refuse"}

    close_candidates = [cat for cat, sc, _, _ in ranked if score1 - sc < margin]
    if len(close_candidates) > 1:
        return {**base_result, "action": "clarify", "candidates": close_candidates[:5]}

    fuzzy = find_fuzzy_pairs(phrase_tokens, clean_tokens(via1))
    if fuzzy:
        return {**base_result, "action": "confirm", "fuzzy": fuzzy}

    return {**base_result, "action": "answer"}
