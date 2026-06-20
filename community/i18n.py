"""
Project Glimi — 다국어 지원 (i18n)

사용:
  from community.i18n import t
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
_current_lang: str = "en"  # UI language (wizard + dashboard)
_agent_lang: str = "en"    # Agent language (per-server, from registry.toml)


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
    """UI 언어 설정 (위저드 + 대시보드)"""
    global _current_lang
    _current_lang = lang
    _load_lang(lang)


def get_language() -> str:
    """현재 UI 언어"""
    return _current_lang


def set_agent_language(lang: str):
    """에이전트 언어 설정 (서버별)"""
    global _agent_lang
    _agent_lang = lang


def get_agent_language() -> str:
    """현재 에이전트 언어"""
    return _agent_lang


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


def _load_ui_lang_from_config():
    """글로벌 UI 언어 설정 로드"""
    config_path = _PROJECT_ROOT / ".glimi.toml"
    if config_path.exists():
        try:
            if hasattr(__builtins__, '__import__'):
                import tomllib
            else:
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib
            with open(config_path, "rb") as f:
                cfg = tomllib.load(f)
            return cfg.get("ui_language", "en")
        except Exception:
            pass
    return None


def save_ui_language(lang: str):
    """글로벌 UI 언어 설정 저장"""
    config_path = _PROJECT_ROOT / ".glimi.toml"
    # 기존 설정 읽기
    content = ""
    if config_path.exists():
        content = config_path.read_text()

    # ui_language 업데이트
    import re
    if re.search(r'^ui_language\s*=', content, re.MULTILINE):
        content = re.sub(r'^ui_language\s*=.*$', f'ui_language = "{lang}"', content, flags=re.MULTILINE)
    else:
        content = f'ui_language = "{lang}"\n' + content

    config_path.write_text(content)
    set_language(lang)


# 초기화: .glimi.toml → 환경변수 → 기본값
_saved = _load_ui_lang_from_config()
if _saved:
    set_language(_saved)
_env_lang = os.environ.get("GLIMI_LANGUAGE", "")
if _env_lang:
    set_language(_env_lang)
