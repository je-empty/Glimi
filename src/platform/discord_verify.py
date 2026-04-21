"""Discord 봇 토큰 검증 — TUI wizard 의 `_discord_connect` 를 플랫폼용으로 이관.

토큰으로 실제 Discord 접속 → 봇 정보, 서버 목록, 권한 체크, 기존 `glimi-*` 채널 조회.
모든 검증 로직을 한 번에 수행해서 프론트에 JSON 으로 반환.
"""
import asyncio

import discord as discord_lib


async def verify_token(token: str, timeout: float = 15.0) -> dict:
    """토큰 → {ok, bot_name, bot_id, guilds[], missing_perms[]}

    guilds[i] = {id, name, member_count, glimi_channels[{name, id}]}
    """
    intents = discord_lib.Intents.default()
    intents.guilds = True
    client = discord_lib.Client(intents=intents)
    result: dict = {"ok": False}

    @client.event
    async def on_ready():
        guilds = []
        missing_perms: list[str] = []
        for g in client.guilds:
            me = g.me
            perms = me.guild_permissions if me else None
            if perms:
                if not perms.manage_channels:
                    missing_perms.append("채널 관리 (Manage Channels)")
                if not perms.manage_webhooks:
                    missing_perms.append("웹훅 관리 (Manage Webhooks)")
                if not perms.send_messages:
                    missing_perms.append("메시지 보내기 (Send Messages)")
                if not perms.read_messages:
                    missing_perms.append("메시지 읽기 (Read Messages)")
                if not perms.manage_messages:
                    missing_perms.append("메시지 관리 (Manage Messages)")

            glimi_cats = [c for c in g.categories if c.name.startswith("glimi")]
            glimi_channels = []
            for cat in glimi_cats:
                glimi_channels.extend(
                    {"name": ch.name, "id": ch.id}
                    for ch in cat.text_channels
                )
            guilds.append({
                "id": g.id,
                "name": g.name,
                "member_count": g.member_count,
                "glimi_channels": glimi_channels,
            })
        result.update(
            ok=True,
            bot_name=client.user.name,
            bot_id=client.user.id,
            guilds=guilds,
            missing_perms=sorted(set(missing_perms)),
        )
        await client.close()

    try:
        await asyncio.wait_for(client.start(token), timeout=timeout)
    except asyncio.TimeoutError:
        result["error"] = "연결 시간 초과"
        try:
            await client.close()
        except Exception:
            pass
    except discord_lib.LoginFailure:
        result["error"] = "유효하지 않은 토큰"
    except asyncio.CancelledError:
        pass
    except Exception as e:
        result["error"] = str(e)
        try:
            await client.close()
        except Exception:
            pass
    return result


def verify_token_sync(token: str, timeout: float = 15.0) -> dict:
    """동기 wrapper — FastAPI 라우터 스레드풀에서 호출용."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(verify_token(token, timeout=timeout))
    finally:
        try:
            loop.close()
        except Exception:
            pass


async def wipe_glimi_channels(token: str, timeout: float = 30.0) -> dict:
    """봇이 접속한 모든 길드에서 `glimi*` 카테고리 + 그 안의 채널을 전부 삭제.

    반환: {ok, deleted_channels: [..], deleted_categories: [..], errors: [..]}
    """
    intents = discord_lib.Intents.default()
    intents.guilds = True
    client = discord_lib.Client(intents=intents)
    result: dict = {
        "ok": False,
        "deleted_channels": [],
        "deleted_categories": [],
        "errors": [],
    }

    @client.event
    async def on_ready():
        try:
            for g in client.guilds:
                # 모든 glimi* 카테고리 수집
                glimi_cats = [c for c in g.categories if c.name.startswith("glimi")]
                for cat in glimi_cats:
                    # 먼저 카테고리 내 채널 삭제
                    for ch in list(cat.text_channels):
                        try:
                            await ch.delete(reason="Glimi new community — wipe existing")
                            result["deleted_channels"].append(f"{g.name}/#{ch.name}")
                        except Exception as e:
                            result["errors"].append(f"channel {ch.name}: {e}")
                    # 카테고리 삭제
                    try:
                        await cat.delete(reason="Glimi new community — wipe existing")
                        result["deleted_categories"].append(f"{g.name}/[{cat.name}]")
                    except Exception as e:
                        result["errors"].append(f"category {cat.name}: {e}")
                # orphan 채널 — glimi 카테고리 밖에 있지만 이름이 패턴 매칭
                orphan_patterns = ("mgr-", "dm-", "group-", "internal-")
                for ch in g.text_channels:
                    if not any(ch.name.startswith(p) for p in orphan_patterns):
                        continue
                    try:
                        await ch.delete(reason="Glimi new community — orphan cleanup")
                        result["deleted_channels"].append(f"{g.name}/#{ch.name} (orphan)")
                    except Exception as e:
                        result["errors"].append(f"orphan {ch.name}: {e}")
            result["ok"] = True
        finally:
            await client.close()

    try:
        await asyncio.wait_for(client.start(token), timeout=timeout)
    except asyncio.TimeoutError:
        result["errors"].append("연결 시간 초과")
        try:
            await client.close()
        except Exception:
            pass
    except discord_lib.LoginFailure:
        result["errors"].append("유효하지 않은 토큰")
    except Exception as e:
        result["errors"].append(str(e))
        try:
            await client.close()
        except Exception:
            pass
    return result


def wipe_glimi_channels_sync(token: str, timeout: float = 30.0) -> dict:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(wipe_glimi_channels(token, timeout=timeout))
    finally:
        try:
            loop.close()
        except Exception:
            pass
