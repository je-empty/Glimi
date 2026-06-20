"""English 'demo-en' community mockup seed — mirrors the 5-layer memory model.

Run: python3 scripts/seed_demo_mockup_en.py

Contents:
- owner + 7 personas (friends / colleagues / partners only, no family)
- assorted channels (DM, internal-dm, internal-group, group, mgr)
- rich conversations (50+ messages per channel avg)
- L1 / L2 / L3 episodic memory + importance · is_pinned · related_entities · mem_type
- agent_facts (Layer 3 Semantic) — structured per-entity knowledge
- relationship_history (Layer 4) — intimacy / dynamics inflection log
- varied emotional states (1-10 intensity)

Purpose: web dashboard showcase (English README) — http://localhost:8765/?community=demo-en

NOTE: This is the English counterpart of scripts/seed_demo_mockup.py.
Structure / logic / DB calls are 100% identical; only COMMUNITY_ID and the
user-visible content strings differ (translated to natural English). agent_id
values are intentionally unchanged (code depends on them).

import-safe: all side effects live inside `seed()`. Importing this module does
nothing.
"""
import json
import os
import random
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _copy_seed_avatars(dest_dir: Path) -> None:
    """Copy avatars into the demo profile-images dir (best-effort, never crash).

    Source priority:
      1) communities/private/profile_images  (dev machine only — gitignored)
      2) committed fallback: assets/sample_profile_images, assets/profile_images
    If none exist, skip (serve_avatar falls back to a placeholder SVG). Must not
    break on a fresh clone (no communities/ or data/).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in dest_dir.glob("*.png"):
        try:
            f.unlink()
        except OSError:
            pass

    candidates = [
        ROOT / "communities" / "private" / "profile_images",
        ROOT / "assets" / "sample_profile_images",
        ROOT / "assets" / "profile_images",
    ]
    src_dir = next((c for c in candidates if c.exists()), None)
    if src_dir is None:
        return
    for src in src_dir.glob("*.png"):
        try:
            shutil.copy(src, dest_dir / community.name)
        except OSError:
            pass


def seed(community_id: str = "demo-en") -> None:
    """Seed the English demo mockup into community_id (DB, env, avatars, chats).

    Idempotent: the DB is reset each run, so a re-call overwrites with the same
    result. Callers (ensure_demo_seeded) guard re-seeding via directory presence.
    """
    from community import community
    from community import db

    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    community.set_community(community_id)

    # ── 0. directory + DB reset ─────────────────────────────────
    demo_dir = ROOT / "communities" / community_id
    demo_dir.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-shm", "-wal"):
        p = demo_dir / f"community.db{suffix}"
        if p.exists():
            p.unlink()

    # copy profile images (private first, else committed assets fallback)
    demo_profile_images = demo_dir / "profile_images"
    _copy_seed_avatars(demo_profile_images)

    # logs + env
    logs_dir = demo_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "system.log").write_text("[seed] demo-en mockup (5-layer memory) loaded\n")
    env_path = demo_dir / ".env"
    if not env_path.exists():
        env_path.write_text("DISCORD_BOT_TOKEN=mockup-no-token\n")

    # DB init (init_db calls _migrate_schema to ensure latest columns/tables)
    db.init_db()
    conn = db.get_conn()

    # ── 1. owner (user) ────────────────────────────────────────
    OWNER_NAME = "You"
    conn.execute("""
        INSERT INTO users (id, name, age, mbti, personality)
        VALUES (?, ?, ?, ?, ?)
    """, ("owner", OWNER_NAME, 27, "INTJ",
          json.dumps({"gender": "male", "nickname": OWNER_NAME}, ensure_ascii=False)))
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('active_user_id', 'owner')")


    # ── 2. agent insert helper ────────────────────────────────
    def insert_agent(aid, atype, name, age, gender, mbti, background,
                     current_emotion="calm", intensity=5):
        conn.execute("""
            INSERT INTO agents (id, type, name, status, current_emotion, emotion_intensity,
                                birth_year, age, gender, mbti, background,
                                profile_image_filename, version, created_at)
            VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (aid, atype, name, current_emotion, intensity,
              2026 - age, age, gender, mbti, background,
              f"{aid}.png", datetime.now().isoformat()))


    insert_agent("agent-mgr-001", "mgr", "Yuna", 24, "female", "ENFJ",
                 "Glimi community manager. Friendly, organized, the big-sister type.")
    insert_agent("agent-creator-001", "creator", "Hana", 22, "female", "INFP",
                 "New-member tutorial guide + persona designer. Warm and creative.")


    # ── 3. 7 personas (friends only — no romance / coworkers-as-family) ─────────
    personas = [
        {
            "id": "agent-persona-001", "name": "Mia", "age": 24, "gender": "female",
            "mbti": "INFJ", "enneagram": "2",
            "bg": "A friend from a book club. Loves reading and writing. Quiet, prefers deep conversations.",
            "emotion": "serene", "intensity": 6,
            "traits": ["quiet", "kind", "thoughtful", "deeply empathetic"],
            "likes": ["books", "cafes on rainy days", "long walks", "indie bookstores"],
            "dislikes": ["noisy places", "dishonesty"],
            "rel_owner": "friend", "duration": "3 years", "pet_name": "You",
            "occupation": "Editor at a publishing house",
            "routine": "morning at the bookstore → afternoon work → evening cafe with friends",
        },
        {
            "id": "agent-persona-002", "name": "Chloe", "age": 27, "gender": "female",
            "mbti": "ESTP", "enneagram": "7",
            "bg": "Friends since elementary school. Lives one neighborhood over so they hang out often. Totally casual, can even swear around each other.",
            "emotion": "lively", "intensity": 8,
            "traits": ["energetic", "blunt", "loyal", "honest"],
            "likes": ["running", "craft beer", "traveling", "board games"],
            "dislikes": ["hypocrisy", "overcomplicated explanations"],
            "rel_owner": "childhood friend", "duration": "20-year friends", "pet_name": "hey",
            "occupation": "Backend developer",
            "routine": "morning work → evening run or friends → weekend trips",
        },
        {
            "id": "agent-persona-003", "name": "Emma", "age": 22, "gender": "female",
            "mbti": "ESFP", "enneagram": "7",
            "bg": "A college junior met at a department event. Bubbly and bright. The life of any gathering.",
            "emotion": "excited", "intensity": 9,
            "traits": ["bright", "charming", "high-energy", "spontaneous"],
            "likes": ["desserts", "K-POP", "shopping", "photography"],
            "dislikes": ["gloomy moods"],
            "rel_owner": "friend", "duration": "3 years", "pet_name": "You",
            "occupation": "College student (senior)",
            "routine": "classes → studying at a cafe → out with friends",
        },
        {
            "id": "agent-persona-004", "name": "Sophie", "age": 24, "gender": "female",
            "mbti": "ENFP", "enneagram": "4",
            "bg": "A friend met through Mia. Freelance illustrator. Held her first solo show last year. Sentimental and chatty.",
            "emotion": "happy", "intensity": 7,
            "traits": ["energetic", "artistic", "honest", "sentimental"],
            "likes": ["drawing", "exhibitions", "walks", "watercolors"],
            "dislikes": ["rigid rules"],
            "rel_owner": "friend", "duration": "3 years", "pet_name": "You",
            "occupation": "Freelance illustrator",
            "routine": "morning work → afternoon cafe/exhibitions → occasional evenings with Mia",
        },
        {
            "id": "agent-persona-005", "name": "Lily", "age": 20, "gender": "female",
            "mbti": "INFP", "enneagram": "9",
            "bg": "A younger friend met in a college club. Studying composition. Quiet but deep. Close with Emma.",
            "emotion": "calm", "intensity": 5,
            "traits": ["quiet", "sentimental", "considerate", "deep"],
            "likes": ["music", "photography", "cats", "night walks"],
            "dislikes": ["being pressured"],
            "rel_owner": "friend", "duration": "2 years", "pet_name": "You",
            "occupation": "College student (junior)",
            "routine": "classes → composition practice → frequent calls with Emma",
        },
        {
            "id": "agent-persona-006", "name": "Grace", "age": 30, "gender": "female",
            "mbti": "ENTJ", "enneagram": "8",
            "bg": "An older friend met at a gym/pilates group. Demanding but full of good advice. A lot to learn from her.",
            "emotion": "focused", "intensity": 7,
            "traits": ["organized", "a natural leader", "insightful", "honest"],
            "likes": ["coffee", "pilates", "reading", "camping"],
            "dislikes": ["unprepared meetups", "all talk no action"],
            "rel_owner": "friend", "duration": "2 years", "pet_name": "You",
            "occupation": "Pilates instructor",
            "routine": "6am pilates → evening reading / planning camping trips",
        },
        {
            "id": "agent-persona-007", "name": "Zoe", "age": 26, "gender": "female",
            "mbti": "ISFJ", "enneagram": "6",
            "bg": "A friend met at a brunch group. Meticulous and attentive. Loves cooking and baking; they go on restaurant hunts together a lot.",
            "emotion": "serene", "intensity": 6,
            "traits": ["diligent", "devoted", "warm", "careful"],
            "likes": ["cooking", "flowers", "reading", "brunch"],
            "dislikes": ["rushed decisions"],
            "rel_owner": "friend", "duration": "1 year", "pet_name": "You",
            "occupation": "Runs a neighborhood bakery",
            "routine": "early-morning baking → afternoon at the shop → evenings with friends",
        },
    ]

    for p in personas:
        insert_agent(p["id"], "persona", p["name"], p["age"], p["gender"],
                     p["mbti"], p["bg"], p["emotion"], p["intensity"])
        # profile satellite tables (JSON blob)
        conn.execute("INSERT INTO agent_personality (agent_id, data) VALUES (?, ?)",
                     (p["id"], json.dumps({
                         "traits": p["traits"],
                         "likes": p["likes"],
                         "dislikes": p["dislikes"],
                         "values": "relationships and sincerity",
                         "enneagram": p["enneagram"],
                     }, ensure_ascii=False)))
        conn.execute("INSERT INTO agent_appearance (agent_id, data) VALUES (?, ?)",
                     (p["id"], json.dumps({
                         "summary": f"{p['age']}-year-old {p['gender']}, a {p['traits'][0]} impression",
                         "height": f"{160 + (hash(p['id']) % 15)}cm",
                         "hair": "shoulder-length black hair" if p["gender"] == "female" else "neat short hair",
                         "fashion_style": "casual + clean",
                     }, ensure_ascii=False)))
        conn.execute("INSERT INTO agent_daily_life (agent_id, data) VALUES (?, ?)",
                     (p["id"], json.dumps({
                         "occupation": p["occupation"],
                         "routine": p["routine"],
                         "habits": ["a cup of coffee every day", "asleep by 11pm"],
                     }, ensure_ascii=False)))
        conn.execute("INSERT INTO agent_speech (agent_id, data) VALUES (?, ?)",
                     (p["id"], json.dumps({
                         "style_description": f"{p['traits'][0]} tone, casual",
                         "honorific": "casual" if p["age"] < 28 else "mixed",
                         "signature_expressions": ["haha", "omg", "right?"],
                         "emoji_pattern": "occasional lol + emoji",
                     }, ensure_ascii=False)))
        conn.execute("""INSERT INTO agent_relationship_templates
                        (agent_id, target_id, rel_type, duration, dynamics, pet_name, is_owner_relationship)
                        VALUES (?, 'owner', ?, ?, ?, ?, 1)""",
                     (p["id"], p["rel_owner"], p["duration"],
                      f"{p['rel_owner']}, {p['duration']} — a {p['traits'][0]} bond",
                      p["pet_name"]))

    # ── 4. inter-agent relationships (no family) ────────────────────────
    rel_pairs = [
        # (a, b, type, intimacy, dynamics) — all friendship-tier only
        ("agent-persona-001", "agent-persona-004", "best friends", 95, "college classmates, talk every day"),
        ("agent-persona-001", "agent-persona-002", "friends", 72, "met through You. Chloe's bluntness is occasionally a lot for Mia"),
        ("agent-persona-002", "agent-persona-006", "friends", 68, "got close at the running/pilates group. mutual respect"),
        ("agent-persona-003", "agent-persona-005", "best friends", 92, "club seniors/juniors, on the phone nearly every day"),
        ("agent-persona-004", "agent-persona-005", "friends", 60, "met through Mia. Sophie loves Lily's work"),
        ("agent-persona-006", "agent-persona-007", "friends", 82, "go to the brunch/pilates groups together"),
        ("agent-persona-001", "agent-persona-003", "acquaintances", 45, "a few times at You's gatherings — Emma's vibe is slightly much for Mia"),
        ("agent-persona-002", "agent-persona-003", "acquaintances", 50, "met at You's gatherings. Emma thinks Chloe is hilarious"),
        ("agent-persona-001", "agent-persona-007", "acquaintances", 55, "met at You's gatherings. both quiet types, they click"),
        ("agent-mgr-001", "agent-creator-001", "friends", 88, "Glimi manager & creator, lean on each other"),
    ]
    for a, b, rt, intim, dyn in rel_pairs:
        conn.execute("""INSERT INTO relationships
                        (agent_a, agent_b, type, intimacy_score, dynamics)
                        VALUES (?, ?, ?, ?, ?)""", (a, b, rt, intim, dyn))


    # ── 5. channels ─────────────────────────────────────────────
    def add_channel(name, participants, status='idle', max_turns=0):
        conn.execute("""INSERT INTO channels
                        (channel, participants, status, max_turns, created_at)
                        VALUES (?, ?, ?, ?, ?)""",
                     (name, json.dumps(participants, ensure_ascii=False),
                      status, max_turns, datetime.now().isoformat()))


    # DM (owner ↔ agent). Keyed by agent_id — the web chat (_list_postable_channels)
    # synthesizes dm-<agent_id> and the WS write path stores under the same key, so
    # the DM channel key MUST be dm-<agent_id> for history to resolve.
    for p in personas:
        add_channel(f"dm-{p['id']}", [p["id"]])
    # Manager / Creator DMs (these surface in the web chat as DMs too).
    add_channel("dm-agent-mgr-001", ["agent-mgr-001"])
    add_channel("dm-agent-creator-001", ["agent-creator-001"])
    add_channel("mgr-system-log", ["agent-mgr-001"])
    # Group (owner included)
    add_channel("group-friends", ["agent-persona-001", "agent-persona-002", "agent-persona-004"])
    add_channel("group-brunch", ["agent-persona-006", "agent-persona-007"])
    # Internal (between agents, owner read-only)
    add_channel("internal-dm-Mia-Sophie", ["agent-persona-001", "agent-persona-004"])
    add_channel("internal-dm-Emma-Lily", ["agent-persona-003", "agent-persona-005"])
    add_channel("internal-dm-Grace-Zoe", ["agent-persona-006", "agent-persona-007"])
    add_channel("internal-group-the-girls",
                ["agent-persona-001", "agent-persona-003", "agent-persona-004", "agent-persona-005"])


    # ── 6. conversation scripts (kept rich) ────────────────────
    def msg(channel, speaker, content, ago_min=0, emotion=None):
        ts = (datetime.now() - timedelta(minutes=ago_min)).isoformat()
        conn.execute("""INSERT INTO conversations
                        (channel, speaker, message, timestamp, context_emotion)
                        VALUES (?, ?, ?, ?, ?)""",
                     (channel, speaker, content, ts, emotion or 'calm'))


    # DM — channel key is dm-<agent_id> (web chat looks up dm-<agent_id> → must match).
    DM_SCRIPTS = {
        # Mia (partner, steady · lately worried You is busy)
        "dm-agent-persona-001": [
            ("agent-persona-001", "how was your day?"),
            ("owner", "honestly... kinda hectic lol"),
            ("agent-persona-001", "is the thing you mentioned last time still not sorted?"),
            ("owner", "nah I finally got it sorted yesterday"),
            ("agent-persona-001", "oh thank god haha"),
            ("agent-persona-001", "you coming over tonight?"),
            ("owner", "yeah probably around 8"),
            ("agent-persona-001", "I'll make pasta. I've got the white wine out too"),
            ("owner", "perfect ♥"),
            ("agent-persona-001", "don't push yourself too hard these days"),
            ("owner", "yeah just gotta get through this week"),
            ("agent-persona-001", "next week we rest, properly. promise"),
        ],
        # Chloe (20-year childhood friend)
        "dm-agent-persona-002": [
            ("agent-persona-002", "what are you up to this weekend"),
            ("owner", "why"),
            ("agent-persona-002", "the old crew's getting drinks"),
            ("agent-persona-002", "saturday night"),
            ("owner", "I've got dinner plans with Mia though..."),
            ("agent-persona-002", "lol go ask Mia for permission"),
            ("owner", "alright I'll ask"),
            ("agent-persona-002", "oh and I started running lately, you should come with me"),
            ("owner", "oh out of nowhere?"),
            ("agent-persona-002", "the river course is so good. morning runs are amazing, you feel so fresh"),
            ("owner", "hmm I could do a weekend morning"),
            ("agent-persona-002", "deal, I'll come pick you up sunday morning"),
            ("owner", "ok haha"),
        ],
        # Emma (college junior)
        "dm-agent-persona-003": [
            ("agent-persona-003", "heyyy lol"),
            ("owner", "what's up"),
            ("agent-persona-003", "you're coming to the club homecoming next week right?"),
            ("owner", "hmm gotta check my schedule"),
            ("agent-persona-003", "pleaseee come, everyone's gonna be there"),
            ("agent-persona-003", "also could you look over my presentation? pretty please ㅠㅠ"),
            ("owner", "what's the presentation about"),
            ("agent-persona-003", "career plans — graduation's coming up you know"),
            ("owner", "send it over"),
            ("agent-persona-003", "hehe thank you"),
            ("agent-persona-003", "btw Lily and I have been hitting up malatang spots lately, wanna come?"),
            ("owner", "haha maybe sometime"),
        ],
        # Sophie (friend, illustrator)
        "dm-agent-persona-004": [
            ("owner", "Sophie how's the exhibition coming along?"),
            ("agent-persona-004", "hey! it's basically done haha"),
            ("agent-persona-004", "opening's the 15th next month"),
            ("owner", "I'll come with Mia"),
            ("agent-persona-004", "you have to! there's a piece I think Mia's gonna love lol"),
            ("owner", "haha what, don't spoil it"),
            ("agent-persona-004", "it's a secret, just look forward to it"),
        ],
        # Lily (younger friend, composition)
        "dm-agent-persona-005": [
            ("agent-persona-005", "hi!"),
            ("owner", "hey Lily, doing okay?"),
            ("agent-persona-005", "yeah I've got a ton of composition assignments lately so I'm swamped haha"),
            ("agent-persona-005", "oh by the way I listened to that playlist you mentioned"),
            ("owner", "how was it?"),
            ("agent-persona-005", "I loved the Rachmaninoff. it actually inspired my next piece"),
            ("owner", "haha that's great"),
            ("agent-persona-005", "come by the club room sometime. Emma wants to see you too"),
            ("owner", "I'll make time next week"),
        ],
        # Grace (older pilates-group friend, demanding but looks out for you)
        "dm-agent-persona-006": [
            ("agent-persona-006", "hey, you haven't been working out lately have you"),
            ("owner", "lol how did you know"),
            ("agent-persona-006", "I can just tell. come to a class this weekend"),
            ("owner", "saturday's tough... how about sunday?"),
            ("agent-persona-006", "sunday morning's open. 11, let's go"),
            ("owner", "okay I'll be there"),
            ("agent-persona-006", "and your posture's not great. that text neck is bad"),
            ("owner", "ugh my neck really has been hurting lately"),
            ("agent-persona-006", "that's why you need to come. I'll start you on some stretches"),
            ("owner", "honestly don't know what I'd do without you haha"),
            ("agent-persona-006", "we're going camping next week too, wanna come? Zoe's coming"),
            ("owner", "oh nice"),
        ],
        # Zoe (brunch-group friend, runs a neighborhood bakery)
        "dm-agent-persona-007": [
            ("agent-persona-007", "I baked scones today, want me to bring you some?"),
            ("owner", "omg yes please"),
            ("agent-persona-007", "swing by the shop later. I'll give them to you while they're warm"),
            ("owner", "ok I'll come by around 7"),
            ("agent-persona-007", "oh and I booked that pasta place I mentioned"),
            ("owner", "oh I've been wanting to go there"),
            ("agent-persona-007", "saturday at 1? Grace is coming too"),
            ("owner", "sounds great haha"),
            ("agent-persona-007", "you'll love it, that place is the real deal"),
        ],
    }
    for ch, lines in DM_SCRIPTS.items():
        for i, (sp, content) in enumerate(lines):
            msg(ch, sp, content, ago_min=(len(lines) - i) * 4)

    # Manager DM (Yuna) — friend-news briefing
    MGR_LINES = [
        (90, "agent-mgr-001", "Hi! I'm Yuna, your manager :)"),
        (88, "owner", "hello!"),
        (85, "agent-mgr-001", "Emma brought up the homecoming next week. Let me know once you decide whether you're going~"),
        (82, "agent-mgr-001", "Also, Mia's been really worried about your health (based on your recent chats)"),
        (75, "owner", "haha thanks"),
        (30, "agent-mgr-001", "fyi, Mia and Sophie are discussing your birthday gift right now 🤫"),
        (15, "agent-mgr-001", "If you need to edit a profile or make a new friend, just tell Hana!"),
    ]
    for ago, sp, content in MGR_LINES:
        msg("dm-agent-mgr-001", sp, content, ago_min=ago)

    # Creator DM (Hana)
    msg("dm-agent-creator-001", "agent-creator-001", "Hi! What brings you by today?", 200)
    msg("dm-agent-creator-001", "owner", "I think the friends I have now are plenty for the moment", 195)
    msg("dm-agent-creator-001", "agent-creator-001", "Sounds good! Just call on me whenever you need 🌸", 190)

    # group channels
    msg("group-friends", "owner", "yo, drinks this weekend?", 60, "fun")
    msg("group-friends", "agent-persona-002", "I'm in!!!", 59, "excited")
    msg("group-friends", "agent-persona-001", "I'm free saturday afternoon onward", 58, "calm")
    msg("group-friends", "agent-persona-004", "saturday works for me too!", 57, "happy")
    msg("group-friends", "agent-persona-002", "saturday 7pm, Gangnam, let's go", 56, "lively")
    msg("group-friends", "agent-persona-001", "where should we go", 55, "calm")
    msg("group-friends", "agent-persona-002", "that izakaya from last time was solid", 54, "excited")
    msg("group-friends", "agent-persona-004", "I love that place!!", 53, "happy")
    msg("group-friends", "agent-persona-002", "I'll book it", 52, "motivated")
    msg("group-friends", "owner", "nice lol", 50, "fun")

    msg("group-brunch", "agent-persona-007", "where should we do brunch this weekend?", 20, "serene")
    msg("group-brunch", "agent-persona-006", "how about that place in Yeonnam-dong. their salad's great", 18, "calm")
    msg("group-brunch", "agent-persona-007", "oh nice! should we invite You too?", 17, "serene")
    msg("group-brunch", "owner", "haha if you're inviting me I'm there", 15, "fun")
    msg("group-brunch", "agent-persona-006", "deal. sunday at 12, let's go", 10, "calm")

    # Dummy thread + reactions (to demo the chat UI's thread/reaction affordances)
    def _msg_id(channel, speaker, content, ago_min=0, emotion=None):
        ts = (datetime.now() - timedelta(minutes=ago_min)).isoformat()
        cur = conn.execute("""INSERT INTO conversations
                        (channel, speaker, message, timestamp, context_emotion)
                        VALUES (?, ?, ?, ?, ?)""",
                     (channel, speaker, content, ts, emotion or 'calm'))
        return cur.lastrowid

    def _reply(channel, speaker, content, root_id, ago_min=0, emotion=None):
        ts = (datetime.now() - timedelta(minutes=ago_min)).isoformat()
        conn.execute("""INSERT INTO conversations
                        (channel, speaker, message, timestamp, context_emotion, reply_to, thread_root)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                     (channel, speaker, content, ts, emotion or 'calm', root_id, root_id))

    def _react(message_id, actor_id, emoji):
        ts = datetime.now().isoformat()
        conn.execute("""INSERT OR IGNORE INTO reactions (message_id, actor_id, emoji, created_at)
                        VALUES (?, ?, ?, ?)""", (message_id, actor_id, emoji, ts))

    _root = _msg_id("group-friends", "agent-persona-002", "yesterday's run 📸 6k along the river", 40, "excited")
    _reply("group-friends", "agent-persona-001", "oh nice ㅋㅋ", _root, 39, "calm")
    _reply("group-friends", "owner", "let's go together next time", _root, 38, "fun")
    _reply("group-friends", "agent-persona-004", "great shot ㅎㅎ", _root, 37, "happy")
    _react(_root, "owner", "❤️")
    _react(_root, "agent-persona-001", "🔥")
    _react(_root, "agent-persona-004", "👍")
    # A reaction in a DM too (Mia's DM)
    _dm_msg = _msg_id("dm-agent-persona-001", "agent-persona-001", "wanna hit the bookshop tomorrow?", 30, "serene")
    _react(_dm_msg, "owner", "👍")

    # Internal — Mia·Sophie (worried about You + birthday prep)
    INTERNAL_JIWOO_YERIN = [
        ("agent-persona-001", "Sophie, You's been looking so busy lately and I'm worried", 180),
        ("agent-persona-004", "haha you're in worry-mode again. You's pretty healthy you know", 178),
        ("agent-persona-001", "still, he hasn't been sleeping well and he's stressed", 176),
        ("agent-persona-004", "well he's got you by his side so he'll be fine"),
        ("agent-persona-001", "haha thanks Sophie"),
        ("agent-persona-004", "oh but his birthday's next month right?", 90),
        ("agent-persona-001", "yeah, trying to figure out what to do for him", 88),
        ("agent-persona-004", "what if I draw him something?"),
        ("agent-persona-001", "ooh that's so nice. what should I get then"),
        ("agent-persona-004", "get him that whisky he likes", 85),
        ("agent-persona-001", "oh that's good. wanna go shopping together?"),
        ("agent-persona-004", "next saturday? I'm free"),
        ("agent-persona-001", "deal!"),
        ("agent-persona-004", "and not a word to You okay lol"),
        ("agent-persona-001", "obviously haha"),
    ]
    for i, entry in enumerate(INTERNAL_JIWOO_YERIN):
        sp, content = entry[0], entry[1]
        ago = entry[2] if len(entry) > 2 else (len(INTERNAL_JIWOO_YERIN) - i) * 8
        msg("internal-dm-Mia-Sophie", sp, content, ago_min=ago,
            emotion="serene" if sp == "agent-persona-001" else "happy")

    # Internal — Emma·Lily (malatang + the crush)
    INTERNAL_SEOA_HARIN = [
        ("agent-persona-003", "what should we eat for dinner", 45),
        ("agent-persona-005", "hmm... malatang??", 44),
        ("agent-persona-003", "lol malatang again", 43),
        ("agent-persona-005", "I'm so stressed lately I'm craving spicy haha"),
        ("agent-persona-003", "ok the place we went to last time?"),
        ("agent-persona-005", "yeah that place is really good"),
        ("agent-persona-003", "btw I DMed You and the reply was kinda lukewarm"),
        ("agent-persona-005", "lol you message him way too much"),
        ("agent-persona-003", "what, when do I"),
        ("agent-persona-005", "Emma it's so obvious you actually like him lol"),
        ("agent-persona-003", "... am I that obvious"),
        ("agent-persona-005", "everyone already knows haha"),
        ("agent-persona-005", "but he's got Mia you know"),
        ("agent-persona-003", "I know lol. it's just feelings, that's all"),
        ("agent-persona-003", "anyway, 6 today!"),
        ("agent-persona-005", "ok let's meet at Gangnam station"),
    ]
    for i, entry in enumerate(INTERNAL_SEOA_HARIN):
        sp, content = entry[0], entry[1]
        ago = entry[2] if len(entry) > 2 else (len(INTERNAL_SEOA_HARIN) - i) * 3
        msg("internal-dm-Emma-Lily", sp, content, ago_min=ago,
            emotion="excited" if sp == "agent-persona-003" else "calm")

    # Internal — Grace·Zoe (looking after You + birthday prep)
    INTERNAL_JIHO_SUJIN = [
        ("agent-persona-006", "Zoe, doesn't You look kind of tired lately?", 30),
        ("agent-persona-007", "yeah, he's looking really run down..."),
        ("agent-persona-006", "it's because he doesn't work out. I'm gonna drag him out this weekend"),
        ("agent-persona-007", "haha I'll at least bring him some bread"),
        ("agent-persona-006", "yeah let's look after him a bit"),
        ("agent-persona-007", "oh and You's birthday is coming up. thinking about what to get him", 18),
        ("agent-persona-006", "oh right. should we do something together?"),
        ("agent-persona-007", "yes let's!"),
    ]
    for i, entry in enumerate(INTERNAL_JIHO_SUJIN):
        sp, content = entry[0], entry[1]
        ago = entry[2] if len(entry) > 2 else (len(INTERNAL_JIHO_SUJIN) - i) * 4
        msg("internal-dm-Grace-Zoe", sp, content, ago_min=ago, emotion="calm")

    # Internal group — the girls (Mia, Emma, Sophie, Lily)
    INTERNAL_GIRLS = [
        ("agent-persona-004", "hey, brunch this weekend?", 120),
        ("agent-persona-001", "sure, where?"),
        ("agent-persona-003", "Yeonnam-dong!!"),
        ("agent-persona-005", "I can come too haha"),
        ("agent-persona-004", "how about saturday 11?"),
        ("agent-persona-001", "saturday I have plans with You... sunday?"),
        ("agent-persona-003", "sunday works"),
        ("agent-persona-005", "sunday for me too"),
        ("agent-persona-004", "sunday 11 it is!"),
    ]
    for i, entry in enumerate(INTERNAL_GIRLS):
        sp, content = entry[0], entry[1]
        ago = entry[2] if len(entry) > 2 else (len(INTERNAL_GIRLS) - i) * 10
        msg("internal-group-the-girls", sp, content, ago_min=ago, emotion="happy")


    # ── 7. 5-layer memory ─────────────────────────────────────
    # for each agent's main channels: several L1 + L2 summary + (optional) L3 + pinned
    def insert_memory(aid, channel, content, mem_type, importance,
                      related_entities, knows=None, is_pinned=False, ago_days=0,
                      level=1):
        ts = (datetime.now() - timedelta(days=ago_days,
                                         hours=random.randint(0, 12))).isoformat()
        conn.execute("""INSERT INTO memories
            (agent_id, channel, level, content, mem_type,
             related_entities, knows, importance, is_pinned,
             msg_count, created_at, last_accessed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 5, ?, ?)""",
            (aid, channel, level, content, mem_type,
             json.dumps(related_entities, ensure_ascii=False) if related_entities else None,
             json.dumps(knows, ensure_ascii=False) if knows else None,
             importance, 1 if is_pinned else 0, ts, ts))


    # Mia (agent-persona-001) — book-cafe friend, daily life / taste focused (no private/work info)
    JIWOO_MEMS = [
        # Current channel L1s
        (1, "dm-You", "- had a long chat about the short-story collection You recently read\n- planning to recommend a sci-fi novel next time\n- You says he likes the way I underline passages",
         "event", 6, ["You"], 0),
        (1, "dm-You", "- You went to a cat cafe for the first time recently → liked it more than expected\n- suggested we go together next time\n- You is secretly an animal person",
         "event", 5, ["You"], 1),
        (1, "dm-You", "- You's been collecting LPs lately (jazz / 70s-80s rock)\n- told him to bring some to the cafe next time\n- thinking of buying a turntable myself",
         "event", 5, ["You"], 2),
        # L2 chronicle
        (2, "dm-You", "- was a regular since he started his part-time job → grew into friendship\n- similar taste in books / coffee / music makes conversation easy\n- text 3-4x a week, meet up occasionally on weekends",
         "relationship", 8, ["You"], 10),
        # Cross-channel
        (1, "internal-dm-Mia-Sophie", "- birthday gift ideas for You with Sophie\n- Sophie: draw an illustration / Mia: an LP You had his eye on\n- shopping together next week",
         "event", 7, ["Sophie", "You"], 2),
        # Pinned — for sharing worry
        (1, "dm-You", "- You hasn't been sleeping well lately so he takes early-morning walks\n- shared his route along the river\n- talked about sometimes going together",
         "fact", 7, ["You"], 3),
        (1, "dm-You", "- visited the indie bookstore 'The Loft' that You recommended → loved the atmosphere\n- decided to go again together\n- he bragged about a photo book he picked up there",
         "event", 5, ["You"], 4),
    ]
    for i, (lvl, ch, content, mt, imp, ents, ago) in enumerate(JIWOO_MEMS):
        # pinned: only the 'early-morning walk' item (index 5)
        pinned = (i == 5)
        insert_memory("agent-persona-001", ch, content, mt, imp,
                      ents, knows=["Mia", "owner"] if "You" in ents else None,
                      is_pinned=pinned, ago_days=ago, level=lvl)

    # Chloe — running / meetup memories
    insert_memory("agent-persona-002", "dm-You",
                  "- talked You into running together\n- sunday morning river course (Chloe picks him up)\n- teased him for never working out",
                  "event", 6, ["You"], ["Chloe", "owner"], ago_days=0)
    insert_memory("agent-persona-002", "dm-You",
                  "- You only has time on weekends lately (so busy)\n- old crew meetup saturday 7pm — confirming whether You will join\n- joked he needs Mia's permission",
                  "event", 5, ["You"], ["Chloe", "owner"], ago_days=1)
    insert_memory("agent-persona-002", "dm-You",
                  "- 20-year friends who trade opinions on every big life decision\n- the relationship where we tell each other the bluntest truths\n- I was the first to give advice when You started dating",
                  "relationship", 9, ["You"], ["Chloe", "owner"], ago_days=14)

    # Emma — has feelings for You (internal only)
    insert_memory("agent-persona-003", "dm-You",
                  "- asked You to come to the homecoming\n- asked him to review my presentation → he said send it\n- floated going for malatang together (didn't get a no)",
                  "event", 5, ["You"], ["Emma", "owner"], ago_days=0)
    # internal-dm-Emma-Lily — crush on You (owner not in knows → disclosure marker applies)
    insert_memory("agent-persona-003", "internal-dm-Emma-Lily",
                  "- Lily caught on that I like You\n- You has Mia → decided to just keep the feelings to myself",
                  "emotion", 8, ["You", "Lily", "Mia"],
                  ["Emma", "Lily"],  # no owner — private conversation
                  ago_days=1)

    # Sophie — You's birthday plan (internal)
    insert_memory("agent-persona-004", "internal-dm-Mia-Sophie",
                  "- discussed You's birthday gift with Mia\n- Sophie = draw him something by hand\n- Mia = planning to buy whisky\n- shopping together next saturday",
                  "event", 9, ["Mia", "You"],
                  ["Sophie", "Mia"],  # no owner
                  ago_days=2)
    insert_memory("agent-persona-004", "dm-You",
                  "- solo show opening the 15th next month\n- You + Mia promised to come\n- preparing 'a piece Mia will love' (secret)",
                  "event", 7, ["You", "Mia"], ["Sophie", "owner"], ago_days=0)

    # Lily — quiet depth
    insert_memory("agent-persona-005", "dm-You",
                  "- used the Rachmaninoff playlist as inspiration for composing\n- invited him to drop by the club room next week",
                  "fact", 5, ["You"], ["Lily", "owner"], ago_days=0)

    # Grace — working out / looking after You
    insert_memory("agent-persona-006", "dm-You",
                  "- called out You's text neck / bad posture\n- told him to come to sunday morning pilates class\n- also going camping together next week",
                  "event", 6, ["You"], ["Grace", "owner"], ago_days=0)
    insert_memory("agent-persona-006", "internal-dm-Grace-Zoe",
                  "- You's been looking tired → decided to look after him with Zoe\n- planning to drag him out to exercise this weekend\n- preparing a birthday gift together too",
                  "fact", 6, ["You", "Zoe"], ["Grace", "Zoe"],  # owner doesn't know
                  ago_days=0)

    # Zoe — baking + plans
    insert_memory("agent-persona-007", "dm-You",
                  "- baked scones to share at the shop\n- booked the pasta place for saturday (Grace coming too)",
                  "event", 5, ["You", "Grace"], ["Zoe", "owner"], ago_days=0)


    # ── 8. agent_facts (Layer 3 Semantic) ──────────────────
    # facts each agent knows about key people
    def add_fact(aid, subject, predicate, obj, importance=5):
        conn.execute("""INSERT INTO agent_facts
            (agent_id, subject, predicate, object, importance, confidence)
            VALUES (?, ?, ?, ?, ?, 1.0)""",
            (aid, subject, predicate, obj, importance))


    # what Mia knows about You — taste/daily-life focused (no work/private info)
    add_fact("agent-persona-001", "You", "music_taste", "jazz · 70s-80s rock · collects LPs", 7)
    add_fact("agent-persona-001", "You", "book_taste", "contemporary literary fiction · short stories · sci-fi", 6)
    add_fact("agent-persona-001", "You", "cafe_preference", "quiet spots · strong americano", 6)
    add_fact("agent-persona-001", "You", "hobby", "indie bookstore hopping · copying out passages by hand", 5)
    add_fact("agent-persona-001", "You", "animals", "likes cats (doesn't have one yet)", 5)
    add_fact("agent-persona-001", "You", "weekend_routine", "riverside walks · reading at cafes", 6)
    add_fact("agent-persona-001", "You", "drink_preference", "whisky neat", 5)
    add_fact("agent-persona-001", "You", "favorite_food", "pasta · light, simple dishes", 5)
    add_fact("agent-persona-001", "You", "recent_worry", "lack of sleep · early-morning walks", 8)
    add_fact("agent-persona-001", "You", "birthday", "early next month", 7)
    add_fact("agent-persona-001", "Sophie", "role", "close friend · college classmate", 6)

    # what Chloe knows about You
    add_fact("agent-persona-002", "You", "exercise", "recently started running (with Chloe)", 5)
    add_fact("agent-persona-002", "You", "disposition", "INTJ, analytical", 5)
    add_fact("agent-persona-002", "You", "drink_preference", "whisky > beer", 7)
    add_fact("agent-persona-002", "You", "relationship", "5 years with Mia", 8)
    add_fact("agent-persona-002", "You", "football_club", "Liverpool fan", 4)

    # what Emma knows about You
    add_fact("agent-persona-003", "You", "role", "college senior", 6)
    add_fact("agent-persona-003", "You", "MBTI", "INTJ", 5)
    add_fact("agent-persona-003", "You", "club_activity", "former president of the film-appreciation club", 6)
    add_fact("agent-persona-003", "Mia", "role", "You's girlfriend", 6)
    add_fact("agent-persona-003", "Lily", "role", "club batchmate", 5)

    # what Sophie knows about Mia
    add_fact("agent-persona-004", "Mia", "occupation", "editor at a publishing house", 7)
    add_fact("agent-persona-004", "Mia", "likes", "indie bookstores, rainy days", 6)
    add_fact("agent-persona-004", "Mia", "worry", "You's health", 9)
    add_fact("agent-persona-004", "You", "gift_preference", "practical + a drink he likes", 7)

    # what Grace knows about You/Zoe
    add_fact("agent-persona-006", "You", "exercise", "barely works out (target of her nagging)", 6)
    add_fact("agent-persona-006", "You", "health", "text neck · lack of sleep", 7)
    add_fact("agent-persona-006", "You", "personality", "follows along when you look out for him", 5)
    add_fact("agent-persona-006", "Zoe", "specialty", "baking · restaurant hunting", 6)
    add_fact("agent-persona-006", "Zoe", "occupation", "runs a neighborhood bakery", 6)

    # what Zoe knows about Grace/You
    add_fact("agent-persona-007", "Grace", "occupation", "pilates instructor", 6)
    add_fact("agent-persona-007", "You", "taste", "light, simple food · warm desserts", 5)
    add_fact("agent-persona-007", "You", "personality", "a careful INTJ", 5)


    # ── 9. relationship_history (Layer 4 inflection points) ────────────
    def add_rel_delta(a, b, dtype, from_s, to_s, reason, ago_days=0):
        ts = (datetime.now() - timedelta(days=ago_days)).isoformat()
        conn.execute("""INSERT INTO relationship_history
            (agent_a, agent_b, delta_type, from_state, to_state, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (a, b, dtype, from_s, to_s, reason, ts))


    add_rel_delta("agent-persona-001", "agent-persona-004", "intimacy", "90", "95",
                  "Sophie prepared a piece for Mia's solo show with Mia in mind", 5)
    add_rel_delta("agent-persona-002", "agent-persona-006", "dynamics",
                  "formal", "comfortable peers", "got close going to the running/pilates groups together", 14)
    add_rel_delta("agent-persona-003", "agent-persona-005", "intimacy", "88", "92",
                  "talking daily lately + hunting malatang spots together", 7)
    add_rel_delta("agent-persona-001", "agent-persona-003", "dynamics",
                  "easy with the junior", "slightly guarded", "Mia has mixed feelings seeing how often Emma dotes on You", 10)


    # ── 10. thinking sim ──────────────────────────────────────
    thinking_path = demo_dir / "logs" / "thinking.log"
    thinking_path.write_text("[agent-persona-002] start\n")


    # ── 11. live channels status='running' ───────────────────
    for ch in ("group-friends", "internal-dm-Emma-Lily", "dm-agent-persona-003"):
        conn.execute("UPDATE channels SET status='running' WHERE channel=?", (ch,))


    # ── 12. events ─────────────────────────────────────────────
    events = [
        ("relationship_strengthened", ["agent-persona-003", "agent-persona-005"],
         "Emma & Lily intimacy +4 after a club meetup", "positive"),
        ("emotional_shift", ["agent-persona-001", "agent-persona-003"],
         "Mia starting to feel a little wary of Emma and You's closeness", "caution"),
        ("anniversary_approaching", ["owner", "agent-persona-001"],
         "You's birthday next month — Mia & Sophie preparing a joint gift", "positive"),
        ("weekend_plan", ["agent-persona-006", "agent-persona-007", "owner"],
         "brunch + a river picnic with Grace & Zoe next week", "positive"),
        ("work_milestone", ["agent-persona-004"],
         "Sophie's solo show is ready. opening the 15th next month", "positive"),
    ]
    for et, parts, desc, impact in events:
        ts = (datetime.now() - timedelta(days=random.randint(0, 5))).isoformat()
        conn.execute("""INSERT INTO events
            (event_type, participants, description, impact, timestamp)
            VALUES (?, ?, ?, ?, ?)""",
            (et, json.dumps(parts, ensure_ascii=False), desc, impact, ts))


    conn.commit()
    conn.close()


    # ── 13. meta + achievements — tutorial complete + daily-life progress ─────
    db.set_meta("tutorial_phase", "complete")
    db.set_meta("yuna_greeted", "1")

    _DONE_ACH = [
        "tutorial_done", "first_friend_chat", "three_friends", "group_chat",
        "peek_internal", "agent_auto_chat", "late_night", "chatter",
        "secret_keeper", "many_friends",
    ]
    _UNLOCKED_ACH = ["long_relationship", "matchmaker", "room_master"]
    # keep unearned: meta_breach / first_conflict / reconciliation / confession

    for k in _DONE_ACH:
        db.upsert_achievement("owner", k, state="done", mark_unlocked=True, mark_completed=True)
    for k in _UNLOCKED_ACH:
        db.upsert_achievement("owner", k, state="unlocked", mark_unlocked=True)


    print("✅ demo-en mockup seed complete (5-layer memory reflected)")
    print(f"   ├─ owner: {OWNER_NAME}")
    print(f"   ├─ 9 agents: Yuna(mgr) / Hana(creator) / 7 personas (friends·colleagues·partners)")
    print(f"   ├─ channels: {len(DM_SCRIPTS) + 8} (DM + internal + group + mgr)")
    print(f"   ├─ conversations: 100+ messages, 3 live channels")
    print(f"   ├─ memories: mixed L1/L2/L3 ~15 + 1 pinned")
    print(f"   ├─ agent_facts: ~30 (structured per entity)")
    print(f"   ├─ relationship_history: 4 inflection points")
    print(f"   └─ events: {len(events)}")
    print(f"\n   View: http://localhost:8765/?community=demo-en")


if __name__ == "__main__":
    seed()
