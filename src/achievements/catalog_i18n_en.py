"""Achievement title/description — English translations.

Catalog 파일들(`catalog/<key>.py`)은 한국어를 정본으로 둔다. 영문 커뮤니티
(registry `language = "en"`)에서는 engine.dashboard_summary() 가 이 맵을 참조해
title/description 을 영어로 치환한다. 키가 없으면 한국어 원본으로 fallback.

키 = achievement.key (= catalog 파일명). 33개 전부 커버.
번역 톤: README 쇼케이스용, 짧고 임팩트 있는 제목 + 1문장 설명.
메타 용어(에이전트/봇) 금지 — friends/people 등 자연스러운 표현.
"""
from __future__ import annotations

ACHIEVEMENTS_EN: dict[str, dict[str, str]] = {
    "chatter": {
        "title": "Chatterbox",
        "description": "The community crossed 500 total messages.",
    },
    "mgr_love": {
        "title": "Beyond the Title 💝",
        "description": "The manager set the role aside and shared love with you, person to person.",
    },
    "first_conflict": {
        "title": "First Quarrel",
        "description": "The first conflict broke out among friends. The real relationship starts here.",
    },
    "new_universe": {
        "title": "Into Another World",
        "description": "You stepped into your first universe.",
    },
    "character_designer": {
        "title": "Character Designer",
        "description": "You created five or more friends yourself.",
    },
    "three_friends": {
        "title": "Three Friends",
        "description": "Talk with three different friends.",
    },
    "secret_keeper": {
        "title": "Peeping Audience 🎭",
        "description": "You peeked at 30 or more private conversations between friends.",
    },
    "reconciliation": {
        "title": "Patched Up",
        "description": "Friends who fought made up again.",
    },
    "room_master": {
        "title": "Room Master",
        "description": "Create five or more different group chats.",
    },
    "late_night": {
        "title": "Friend at Dawn",
        "description": "Talk 10+ times between midnight and 5am. Only the truly close get here.",
    },
    "confession": {
        "title": "Opening Up",
        "description": "Someone found the courage to confess their feelings.",
    },
    "daily_streak": {
        "title": "Steady Friend",
        "description": "Talk with the same friend seven days in a row.",
    },
    "mbti_collection": {
        "title": "MBTI Collection",
        "description": "Have four or more friends of different MBTI types.",
    },
    "matchmaker": {
        "title": "Matchmaker",
        "description": "Connect friends over DM ten times.",
    },
    "oshikatsu": {
        "title": "Oshikatsu",
        "description": "Reach a romantic relationship with one VTuber (推し活).",
    },
    "many_friends": {
        "title": "Life of the Party 🎈",
        "description": "Build a community where you talk with five or more friends.",
    },
    "song_buddy": {
        "title": "Music Buddy",
        "description": "Chat about songs, lyrics, or music ten or more times.",
    },
    "memory_keeper": {
        "title": "Memory Box",
        "description": "Have three or more pinned memories.",
    },
    "hakooshi": {
        "title": "Hakooshi",
        "description": "Reach a romantic relationship with five or more VTubers (箱推し).",
    },
    "persona_love": {
        "title": "Becoming Lovers 💑",
        "description": "You and a friend confirmed your feelings and became a couple.",
    },
    "meta_breach": {
        "title": "Breaking the Fourth Wall 🔨",
        "description": "You shattered a friend's illusion. That friend lost their memories and vanished.",
    },
    "tutorial_done": {
        "title": "Tutorial Complete",
        "description": "You finished your first meeting with the managers and made your first friend.",
    },
    "universe_collector": {
        "title": "Universe Collector",
        "description": "Have three or more friends from different universes.",
    },
    "long_relationship": {
        "title": "A Lasting Bond",
        "description": "A conversation with one friend that ran longer than three days.",
    },
    "true_self": {
        "title": "Unmasking",
        "description": "A moment a friend's emotions ran high (intensity 8+).",
    },
    "agent_auto_chat": {
        "title": "Social on Their Own",
        "description": "A moment friends started talking to each other on their own.",
    },
    "peek_internal": {
        "title": "The Joy of Peeking",
        "description": "A private conversation between friends (internal-*) ran 10+ turns.",
    },
    "group_chat": {
        "title": "Group Chat Debut",
        "description": "Exchange five or more messages in a group chat with friends.",
    },
    "first_friend_chat": {
        "title": "First Conversation",
        "description": "Talk three or more turns with a new friend in DM.",
    },
    "photographer": {
        "title": "Profile Camera",
        "description": "You chose a friend's profile picture yourself.",
    },
    "bestie": {
        "title": "Best Friends",
        "description": "Reach 90+ closeness with one friend.",
    },
    "reality_check": {
        "title": "Hallucination Blocked",
        "description": "A watcher blocked a hallucinated message (debug).",
    },
}
