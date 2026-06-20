"""community/bot/formatting.py 단위 테스트.

실행: python -m tests.unit.test_formatting (또는 pytest)
"""
from community.bot.formatting import format_for_discord


class _MockCh:
    def __init__(self, name, id):
        self.name = name
        self.id = id


class _MockGuild:
    text_channels = [
        _MockCh("mgr-creator", 1111),
        _MockCh("mgr-dashboard", 2222),
        _MockCh("dm-서유나", 3333),
        _MockCh("internal-dm-서유나-한유진", 4444),
    ]


def _run():
    guild = _MockGuild()
    cases = [
        # (input, expected)
        ("#mgr-creator 가서 얘기해봐", "<#1111> 가서 얘기해봐"),
        ("#dm-서유나 가자", "<#3333> 가자"),
        ("#internal-dm-서유나-한유진 여기서", "<#4444> 여기서"),
        ("#없는채널", "#없는채널"),
        ("단어중간말#mgr-creator", "단어중간말#mgr-creator"),
        ("띄어쓰기 #mgr-creator!", "띄어쓰기 <#1111>!"),
        ("코드 `#mgr-creator` 는 그대로", "코드 `<#1111>` 는 그대로"),
        ("#1번채널", "#1번채널"),
        ("", ""),
        ("nothing", "nothing"),
        # Multi-channel in one message
        ("#mgr-creator 랑 #mgr-dashboard 둘 다", "<#1111> 랑 <#2222> 둘 다"),
    ]
    failures = []
    for inp, want in cases:
        got = format_for_discord(inp, guild=guild)
        if got != want:
            failures.append((inp, want, got))

    if failures:
        print(f"FAIL — {len(failures)}/{len(cases)}")
        for inp, want, got in failures:
            print(f"  input:    {inp!r}")
            print(f"  expected: {want!r}")
            print(f"  got:      {got!r}")
        raise SystemExit(1)
    print(f"✓ {len(cases)}/{len(cases)} passed")


def test_no_guild_passes_through():
    """guild 없거나 매칭 실패면 `#name` 평문 유지 (포터빌리티)."""
    out = format_for_discord("#mgr-creator 가자", guild=None)
    assert out == "#mgr-creator 가자", out


def test_empty_is_noop():
    assert format_for_discord("", guild=_MockGuild()) == ""
    assert format_for_discord("nothing here", guild=_MockGuild()) == "nothing here"


if __name__ == "__main__":
    _run()
    test_no_guild_passes_through()
    test_empty_is_noop()
    print("all tests passed")
