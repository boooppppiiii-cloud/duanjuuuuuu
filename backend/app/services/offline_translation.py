"""Local comment translation backed by installed Argos Translate models.

Translation never sends comment text to an external service. Model packages are
downloaded once, stored under backend/data, and reused by later app runs.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path

from ftfy import fix_text
from langdetect import DetectorFactory, LangDetectException, detect_langs

from ..config import get_settings

settings = get_settings()
model_dir = settings.offline_translation_model_dir.resolve()
model_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("ARGOS_PACKAGES_DIR", str(model_dir))
os.environ.setdefault("ARGOS_DEVICE_TYPE", "cpu")

from argostranslate import package, translate  # noqa: E402

logger = logging.getLogger(__name__)
DetectorFactory.seed = 0

_lock = threading.RLock()
_ready_pairs: set[tuple[str, str]] = set()
_state = {"preparing": False, "ready": False, "last_error": ""}
_protected_pattern = re.compile(r"https?://\S+|www\.\S+|@[\w.-]+", re.IGNORECASE)
_chinese_pattern = re.compile(r"[\u3400-\u9fff]")
_auto_languages = {"en", "fr", "es", "pt", "id", "vi", "th", "ja", "ko", "de", "it", "nl", "ru"}


def translation_status() -> dict[str, object]:
    return {
        **_state,
        "enabled": settings.offline_translation_enabled,
        "languages": settings.offline_translation_language_list,
        "target": settings.offline_translation_target,
        "model_dir": str(model_dir),
    }


def _installed_pairs() -> set[tuple[str, str]]:
    return {(item.from_code, item.to_code) for item in package.get_installed_packages()}


def _ensure_pair(source: str, target: str, allow_download: bool = True) -> bool:
    pair = (source, target)
    if pair in _ready_pairs:
        return True
    with _lock:
        installed = _installed_pairs()
        if pair in installed:
            _ready_pairs.add(pair)
            return True
        if not allow_download or not settings.offline_translation_auto_install:
            return False
        package.update_package_index()
        candidate = next(
            (item for item in package.get_available_packages() if item.from_code == source and item.to_code == target),
            None,
        )
        if candidate is None:
            logger.warning("No Argos translation package is available for %s -> %s", source, target)
            return False
        logger.info("Downloading offline translation package %s -> %s", source, target)
        download_path = candidate.download()
        package.install_from_path(download_path)
        _ready_pairs.add(pair)
        logger.info("Installed offline translation package %s -> %s", source, target)
        return True


def prepare_translation_models() -> bool:
    if not settings.offline_translation_enabled:
        return False
    with _lock:
        if _state["ready"]:
            return True
        _state.update(preparing=True, last_error="")
        try:
            target = settings.offline_translation_target
            sources = settings.offline_translation_language_list
            if "auto" in sources:
                sources = ["en"]
            outcomes = [_ensure_route(source, target) for source in sources if source != target]
            _state["ready"] = bool(outcomes) and all(outcomes)
            return bool(_state["ready"])
        except Exception as exc:
            _state["last_error"] = str(exc)
            logger.exception("Failed to prepare offline translation models")
            return False
        finally:
            _state["preparing"] = False


def detect_language(text: str) -> str:
    if _chinese_pattern.search(text):
        return "zh"
    sample = _protected_pattern.sub(" ", text).strip()
    if not sample:
        return ""
    try:
        candidate = detect_langs(sample)[0]
        code = candidate.lang.lower() if candidate.prob >= 0.8 else ""
    except LangDetectException:
        code = "en" if re.search(r"[a-zA-Z]", sample) else ""
    code = {"zh-cn": "zh", "zh-tw": "zh", "iw": "he"}.get(code, code)
    if code != "en":
        words = set(re.findall(r"[a-z]+", sample.casefold()))
        common_english = {
            "beautiful", "bullying", "cute", "episode", "full", "handsome", "hotdog",
            "kidnapping", "looks", "love", "manners", "movie", "nice", "pretty", "story",
            "stupid", "wait", "watch", "where",
        }
        if words & common_english:
            return "en"
    return code


def _ensure_route(source: str, target: str, allow_download: bool = True) -> bool:
    if source == target:
        return True
    if source == "en" or target != "zh":
        return _ensure_pair(source, target, allow_download=allow_download)
    return _ensure_pair(source, "en", allow_download=allow_download) and _ensure_pair(
        "en", target, allow_download=allow_download
    )


def _protect_text(text: str) -> tuple[str, dict[str, str]]:
    values: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        token = f"ARGOSTOKEN{len(values)}"
        values[token] = match.group(0)
        return token

    return _protected_pattern.sub(replace, text), values


def _restore_text(text: str, values: dict[str, str]) -> str:
    restored = text
    for token, value in values.items():
        restored = re.sub(re.escape(token), lambda _: value, restored, flags=re.IGNORECASE)
    return restored


def translate_to_chinese(text: str, *, allow_download: bool = True) -> str:
    """Translate one comment locally, returning an empty string when unsupported."""
    clean = fix_text(text.strip())
    if not clean or not settings.offline_translation_enabled:
        return ""
    source = detect_language(clean)
    target = settings.offline_translation_target
    if source == target:
        return clean
    configured_languages = settings.offline_translation_language_list
    if "auto" not in configured_languages and source not in configured_languages:
        return ""
    if "auto" in configured_languages and source not in _auto_languages:
        return ""
    latin_languages = {"fr", "es", "pt", "id", "vi", "de", "it", "nl"}
    if source in latin_languages and len(re.findall(r"[a-zA-ZÀ-ÖØ-öø-ÿ]+", clean)) < 4:
        return ""
    try:
        if not _ensure_route(source, target, allow_download=allow_download):
            return ""
        protected, values = _protect_text(clean)
        with _lock:
            if source == "en" or target != "zh":
                result = translate.translate(protected, source, target)
            else:
                result = translate.translate(protected, source, "en")
                result = translate.translate(result, "en", target)
        return _restore_text(result.strip(), values)
    except Exception:
        logger.exception("Offline translation failed for detected language %s", source)
        return ""


def backfill_missing_translations(limit: int = 2000) -> int:
    """Fill existing untranslated rows after the model is ready."""
    from sqlmodel import Session, select

    from ..database import engine
    from ..models import SocialComment

    translated = 0
    with Session(engine) as session:
        rows = session.exec(
            select(SocialComment)
            .where(SocialComment.text_zh == "")
            .order_by(SocialComment.id.desc())
            .limit(limit)
        ).all()
        for item in rows:
            text_zh = translate_to_chinese(item.text_original, allow_download=True)
            if text_zh:
                item.text_zh = text_zh
                session.add(item)
                translated += 1
        session.commit()
    logger.info("Offline-translated %s existing comments", translated)
    return translated


def prepare_and_backfill() -> None:
    if prepare_translation_models():
        backfill_missing_translations()


def start_translation_worker() -> None:
    if not settings.offline_translation_enabled or _state["preparing"]:
        return
    threading.Thread(target=prepare_and_backfill, name="comment-translation", daemon=True).start()
