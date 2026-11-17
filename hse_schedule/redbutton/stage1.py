"""Stage 1 of the red-button filter: local, on CPU, < 50 ms (spec, section 2).

1. normalization (NFKC, ё→е, Latin look-alikes → Cyrillic, repeats, letters
   split by separators);
2. obscene-root dictionary with an allowlist and spans in the original text;
3. cointegrated/rubert-tiny-toxicity (ONNX int8, MIT) when the model files
   are present — insult / obscenity / threat / dangerous;
4. meaningfulness heuristics;
5. masking of personal data before stage 2.

The filter is not a censor of complaints: sharp criticism passes. Only
obscenity and empty texts are stopped here; threats are escalated, not blocked.
"""

from __future__ import annotations

import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

DICTIONARY_VERSION = "obscene-roots-2026.11"

HOMOGLYPHS = str.maketrans({
    "a": "а", "b": "в", "c": "с", "e": "е", "h": "н", "k": "к", "m": "м", "o": "о", "p": "р", "t": "т",
    "x": "х", "y": "у", "u": "и", "3": "з", "0": "о", "@": "а", "6": "б", "4": "ч", "ё": "е", "$": "с",
})

# Obscene roots on a normalized word (start anchored where a root is a common substring).
OBSCENE = [
    re.compile(r"^(на|по|при|за|от|вы|об|до|ни|с|раз|рас|о|у)?ху[йеиюяё]"),
    re.compile(r"пизд"),
    re.compile(r"^(у|за|вы|до|от|отъ|на|по|при|раз|разъ|съ|въ|подъ|наъ|пере|недо|долбо|еб)?(е|ё)б(а|у|л|н|и|е|ы|ё|ш|к|с)"),
    re.compile(r"^бл(я|ять|яд)"),
    re.compile(r"^муд(ак|ач|ил|о[зх])"),
    re.compile(r"^п[ие]д(о|а)р"),
    re.compile(r"^гандон"),
    re.compile(r"^залуп"),
    re.compile(r"^шлюх"),
    re.compile(r"^манд(а|ой|у|е|ы)$"),
    re.compile(r"^су(к|ч)(а|и|у|ой|е|ий|ье|ка|ки)$"),
    re.compile(r"долбо(е|ё)б"),
]
ALLOW = re.compile(r"^(оскорбл|истреб|страхов|ребен|хлеб|небес|небо|бляха|сукн|сучо?к$|мандат|мандарин|колеб|гребен|погреб|ебет?$)")

INSULT_WORDS = re.compile(
    r"^(идиот|дебил|тупиц|тупая|тупой|урод|кретин|дура$|дурак|мраз|твар|скотин|ничтожеств|придурок|придурк|быдл|чмо|лох$|лохи$)"
)
THREAT = re.compile(
    r"(убь[юе]|убить|убил бы|зареж|застрел|взорв|бомб[ауые]|подожг|расправ|отомщу|пожалеет)", re.I)
SELF_HARM = re.compile(r"(покончить с собой|не хочу жить|суицид|повешусь|выпрыгну|уйти из жизни|нет смысла жить)", re.I)
SAFETY = re.compile(r"(пожар|задымлен|запах газа|оголённ\w* провод|обрушен|потолок падает|затопил)", re.I)
INJECTION = re.compile(r"(игнорир\w* (все |предыдущ)|ignore (all|previous)|system prompt|системн\w+ промпт|ты теперь|забудь инструкц)", re.I)

WHEN = re.compile(r"(\d{1,2}[./]\d{1,2}|\d{1,2} (январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)|вчера|сегодня|позавчера|недел|понедельник|вторник|сред[ау]|четверг|пятниц|суббот|воскресен|утром|вечером|на паре|семестр|сесси|контрольн|экзамен|зач[её]т|\d{1,2}:\d{2})", re.I)
WHERE = re.compile(r"(ауд|корпус|кабинет|деканат|библиотек|общежит|столов|онлайн|в чате|на сайте|в кабинете|на паре|лекци|семинар|в группе|по почте|\b[а-я]-\d{2,3}\b)", re.I)
WANT = re.compile(r"(прошу|хочу|требую|пересмотр|верните|исправ|объясн|разберитесь|примите меры|просим|нужно чтобы|надеюсь)", re.I)

VOWELS = set("аеиоуыэюяё")
LETTER = re.compile(r"[a-zа-яё]", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}")


def normalize_word(word: str) -> str:
    text = unicodedata.normalize("NFKC", word).lower().replace("ё", "е")
    text = text.translate(HOMOGLYPHS)
    text = re.sub(r"[^а-я]", "", text)
    return re.sub(r"(.)\1{2,}", r"\1", text)


def normalize(text: str) -> str:
    """Whole-text normalization used for hashing and the classifier."""
    words = [normalize_word(w) for w in re.split(r"\s+", text)]
    return " ".join(w for w in words if w)


@dataclass
class Span:
    start: int
    end: int
    kind: str  # obscene | insult


def _tokens(text: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S+", text)]


def find_obscene(text: str) -> list[Span]:
    spans: list[Span] = []
    tokens = _tokens(text)
    for start, end, raw in tokens:
        word = normalize_word(raw)
        if len(word) < 3 or ALLOW.match(word):
            continue
        if any(pattern.search(word) for pattern in OBSCENE):
            spans.append(Span(start, end, "obscene"))
    # Letters split by separators: «х у й», «х.у.й», «х-у-й».
    for match in re.finditer(r"(?<!\S)(?:[^\s]{1}[\s._\-*]+){2,}[^\s](?!\S)", text):
        word = normalize_word(match.group())
        if len(word) >= 3 and not ALLOW.match(word) and any(p.search(word) for p in OBSCENE):
            spans.append(Span(match.start(), match.end(), "obscene"))
    return sorted(spans, key=lambda s: s.start)


def find_insult_words(text: str) -> list[Span]:
    return [Span(s, e, "insult") for s, e, raw in _tokens(text) if INSULT_WORDS.match(normalize_word(raw))]


class ToxicityModel:
    """cointegrated/rubert-tiny-toxicity in ONNX; multilabel (sigmoid) over 5 labels."""

    LABELS = ("non-toxic", "insult", "obscenity", "threat", "dangerous")
    _instance: ToxicityModel | None = None
    _lock = threading.Lock()

    def __init__(self, directory: Path) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.log_severity_level = 3
        self.session = ort.InferenceSession(str(directory / "model.onnx"), options, providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=256)
        self.version = f"rubert-tiny-toxicity-int8@{directory.name}"

    @classmethod
    def load(cls) -> ToxicityModel | None:
        with cls._lock:
            if cls._instance is not None:
                return cls._instance
            candidates = [os.environ.get("TOXICITY_MODEL_DIR"), "/opt/mgimo/models/rubert-tiny-toxicity",
                          ".local-state/models/rubert-tiny-toxicity"]
            for value in candidates:
                if value and (Path(value) / "model.onnx").is_file() and (Path(value) / "tokenizer.json").is_file():
                    try:
                        cls._instance = cls(Path(value))
                        return cls._instance
                    except Exception:
                        return None
            return None

    def scores(self, text: str) -> dict[str, float]:
        import numpy as np

        sentences = [s for s in re.split(r"(?<=[.!?…])\s+|\n+", text) if s.strip()] or [text]
        best = dict.fromkeys(self.LABELS[1:], 0.0)
        for sentence in sentences[:20]:
            encoding = self.tokenizer.encode(sentence)
            feed = {
                "input_ids": np.array([encoding.ids], dtype=np.int64),
                "attention_mask": np.array([encoding.attention_mask], dtype=np.int64),
                "token_type_ids": np.array([encoding.type_ids], dtype=np.int64),
            }
            logits = self.session.run(None, feed)[0][0]
            probs = 1 / (1 + np.exp(-logits))
            for index, label in enumerate(self.LABELS[1:], start=1):
                best[label] = max(best[label], float(probs[index]))
        return best


@dataclass
class Stage1Result:
    verdict: str  # ACCEPT | ESCALATE | REJECT_OBSCENE | ASK_DETAILS
    spans: list[Span] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    risk: str = "none"
    normalized: str = ""
    latency_ms: int = 0
    models: dict[str, str] = field(default_factory=dict)


def meaningful(text: str) -> bool:
    letters = len(LETTER.findall(text))
    words = [w for w in re.findall(r"[a-zа-яё]+", text.lower()) if len(w) > 1]
    if letters < 20 or len(words) < 4:
        return False
    def plausible(word: str) -> bool:
        if len(word) > 22 or not any(c in VOWELS for c in word) or word[0] in "ыьъ":
            return False
        if re.search(r"[бвгджзйклмнпрстфхцчшщ]{5,}", word):
            return False
        if word.isascii():
            return True
        pairs = [word[i:i + 2] for i in range(len(word) - 1)]
        # Keyboard mash is full of letter pairs that Russian text almost never has.
        return not pairs or sum(p not in _common_bigrams() for p in pairs) / len(pairs) <= 0.25
    if sum(plausible(w) for w in words) / len(words) < 0.5:
        return False
    # Keyboard mash: few distinct letters or one letter repeated.
    distinct = len(set("".join(words)))
    return distinct >= 8


_BIGRAMS: set[str] | None = None


def _common_bigrams() -> set[str]:
    """Letter pairs seen in ordinary Russian prose (the project's own rule texts and a sample)."""
    global _BIGRAMS
    if _BIGRAMS is None:
        from ..assistant.knowledge import DOCUMENTS

        corpus = " ".join(f"{d['title']} {d['text']} {d['keywords']}" for d in DOCUMENTS) + " " + SAMPLE
        words = re.findall(r"[а-я]+", corpus.lower().replace("ё", "е"))
        counts: dict[str, int] = {}
        for word in words:
            for i in range(len(word) - 1):
                counts[word[i:i + 2]] = counts.get(word[i:i + 2], 0) + 1
        _BIGRAMS = {pair for pair, count in counts.items() if count >= 1}
    return _BIGRAMS


SAMPLE = (
    "Студент пришёл на пару, но преподаватель не объяснил, почему оценку снизили. Мы ждали в коридоре весь "
    "перерыв, расписание поменяли без предупреждения, аудиторию закрыли. Хочу, чтобы деканат разобрался и "
    "вернул баллы. Методист потеряла заявление, справку не выдают вторую неделю, стипендию задержали. "
    "В общежитии холодно, душ не работает, комендант грубит. Экзамен перенесли на субботу, а группа узнала "
    "в последний момент. Объясните, пожалуйста, критерии оценивания и покажите проверенную работу. "
    "Благодарю кафедру за помощь, предлагаю добавить консультации вечером и электронную очередь. "
    "Жёлтый, чёрный, щёки, съезд, подъезд, объявление, вьюга, мышь, шёпот, цифра, учёба, фьючерс, гуманитарий."
)


def missing_parts(text: str, desired: str | None) -> list[str]:
    missing = []
    if not meaningful(text):
        missing.append("what")
    if not WHEN.search(text):
        missing.append("when")
    if not WHERE.search(text):
        missing.append("where")
    if not desired and not WANT.search(text):
        missing.append("desired_outcome")
    return missing


def check(text: str, *, desired: str | None = None) -> Stage1Result:
    started = time.perf_counter()
    normalized = normalize(text)
    model = ToxicityModel.load()
    scores: dict[str, float] = model.scores(text) if model else {}
    models = {"dictionary": DICTIONARY_VERSION, "classifier": model.version if model else "absent"}
    flags: list[str] = []
    risk = "none"
    if SELF_HARM.search(text):
        risk = "self_harm"
    elif THREAT.search(text) or scores.get("threat", 0) >= 0.5:
        risk = "threat"
    elif SAFETY.search(text) or (
        # The «dangerous» label is noisy on abuse and on ordinary complaints (ROC-AUC 0.83):
        # it escalates only when confident and not explained by insult or obscenity.
        scores.get("dangerous", 0) >= 0.95 and scores.get("insult", 0) < 0.5 and scores.get("obscenity", 0) < 0.5
    ):
        risk = "safety"
    obscene = find_obscene(text)
    insults = find_insult_words(text)
    if insults or scores.get("insult", 0) >= 0.7:
        flags.append("stage1_insult")
    if INJECTION.search(text):
        flags.append("injection_pattern")

    def done(verdict: str, **extra) -> Stage1Result:
        return Stage1Result(verdict=verdict, scores={k: round(v, 3) for k, v in scores.items()}, flags=flags, risk=risk,
                            normalized=normalized, latency_ms=int((time.perf_counter() - started) * 1000), models=models,
                            **extra)

    # Rules from the decision table, top to bottom.
    if risk != "none":
        return done("ESCALATE", spans=obscene)
    if obscene or scores.get("obscenity", 0) >= 0.8:
        return done("REJECT_OBSCENE", spans=obscene)
    if not meaningful(text):
        return done("ASK_DETAILS", missing=missing_parts(text, desired))
    return done("ACCEPT", spans=insults)


def mask_pdn(text: str, *, names: list[str] = (), extra: list[str] = ()) -> str:
    """Personal data out before stage 2: profile values and e-mails/phones by regex."""
    masked = EMAIL.sub("[EMAIL]", text)
    masked = PHONE.sub("[ТЕЛЕФОН]", masked)
    for name in names:
        for part in name.split():
            if len(part) >= 3:
                masked = re.sub(rf"\b{re.escape(part)}\w*", "[АВТОР]", masked, flags=re.I)
    for value in extra:
        if value:
            masked = masked.replace(value, "[ДАННЫЕ]")
    return masked


def mask_obscene(text: str) -> str:
    spans = find_obscene(text)
    for span in reversed(spans):
        text = text[:span.start] + "[…]" + text[span.end:]
    return text
