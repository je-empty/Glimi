"""
Project Glimi — 다국어 지원 (i18n)

사용:
  from src.i18n import t
  t("wizard.new_community")  →  "새 커뮤니티 생성" (ko)
  t("wizard.new_community")  →  "New Community" (en)

언어 설정:
  community.toml의 language 필드 또는 GLIMI_LANGUAGE 환경변수
"""
import json
import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_I18N_DIR = _PROJECT_ROOT / "i18n"
_cache: dict[str, dict] = {}
_current_lang: str = "en"


def _load_lang(lang: str) -> dict:
    if lang in _cache:
        return _cache[lang]
    path = _I18N_DIR / f"{lang}.json"
    if not path.exists():
        path = _I18N_DIR / "en.json"  # 폴백
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _cache[lang] = data
        return data
    except Exception:
        return {}


def set_language(lang: str):
    """언어 설정"""
    global _current_lang
    _current_lang = lang
    _load_lang(lang)


def get_language() -> str:
    return _current_lang


def t(key: str, **kwargs) -> str:
    """번역 키로 문자열 가져오기. dot notation 지원.
    예: t("wizard.new_community") → "새 커뮤니티 생성"
    kwargs로 포맷 변수 지원: t("msg", name="유나") → "유나가 왔어요"
    """
    data = _load_lang(_current_lang)
    parts = key.split(".")
    val = data
    for p in parts:
        if isinstance(val, dict):
            val = val.get(p)
        else:
            val = None
            break

    if val is None:
        # 영어 폴백
        data = _load_lang("en")
        val = data
        for p in parts:
            if isinstance(val, dict):
                val = val.get(p)
            else:
                val = None
                break

    if val is None:
        return key  # 키 자체 반환

    if isinstance(val, str) and kwargs:
        try:
            return val.format(**kwargs)
        except (KeyError, IndexError):
            return val
    return val if isinstance(val, str) else key


# 초기화: 환경변수 또는 기본값
_env_lang = os.environ.get("GLIMI_LANGUAGE", "")
if _env_lang:
    set_language(_env_lang)
