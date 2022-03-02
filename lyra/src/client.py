import os
import json
import yaml

# import yuyo
# import miru
import typing as t
import logging
import pathlib as pl
import dotenv
import hikari as hk
import tanjun as tj
import lavasnek_rs as lv

from .lib import *


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


fn = next(inj_glob('./config.yml'))

with open(fn.resolve(), 'r') as f:
    _y = yaml.load(f, yaml.Loader)

    PREFIX: list[str] = _y['prefixes']

    _dev: bool = _y['dev_mode']
    TOKEN: str = os.environ['LYRA_DEV_TOKEN' if _dev else 'LYRA_TOKEN']

    decl_glob_cmds: list[int] | t.Literal[True] = _y['guilds'] if _dev else True


client = (
    tj.Client.from_gateway_bot(
        bot := hk.GatewayBot(token=TOKEN),
        declare_global_commands=(decl_glob_cmds),
        mention_prefix=True,
    )
    .add_prefix(PREFIX)
    .set_hooks(hooks)
    .load_modules(*(p for p in pl.Path('.').glob('./src/modules/*.py')))
)

activity = hk.Activity(name='/play', type=hk.ActivityType.LISTENING)


lavalink_client: lv.Lavalink


cfg_fetched: t.Any = cfg_ref.get()
guild_config = GuildConfig(cfg_fetched)
logger.info("Loaded guild_configs")

(
    client.set_type_dependency(GuildConfig, guild_config)
    # .set_type_dependency(yuyo.ComponentClient, yuyo_client)
)


@client.with_prefix_getter
async def prefix_getter(
    ctx: tj.abc.MessageContext, cfg: GuildConfig = tj.inject(type=GuildConfig)
) -> t.Iterable[str]:
    return (
        cfg.setdefault(str(ctx.guild_id), {}).setdefault('prefixes', [])
        if ctx.guild_id
        else []
    )


# @client.with_listener(hk.StartedEvent)
# async def on_started(event: hk.StartedEvent, client_: tj.Client = tj.inject(type=tj.Client)) -> None:
#     from src.lib.utils import get_client

#     get_client = tj.injecting.SelfInjectingCallback(client_, get_client)


@client.with_listener(hk.ShardReadyEvent)
async def on_shard_ready(
    event: hk.ShardReadyEvent,
    client_: tj.Client = tj.inject(type=tj.Client),
) -> None:
    """Event that triggers when the hikari gateway is ready."""
    host = (
        os.environ['LAVALINK_HOST']
        if os.environ.get('IN_DOCKER', False)
        else '127.0.0.1'
    )

    builder = (
        lv.LavalinkBuilder(event.my_user.id, TOKEN)
        .set_host(host)
        .set_password(os.environ['LAVALINK_PASSWORD'])
        .set_port(int(os.environ['LAVALINK_PORT']))
        .set_start_gateway(False)
    )

    lvc = await builder.build(EventHandler())

    global lavalink_client
    lavalink_client = lvc
    client_.set_type_dependency(lv.Lavalink, lvc)
    # app_id = 0
    # guild_ids = []
    # _L = len(guild_ids)
    # for i, g in enumerate(guild_ids, 1):
    #     # print(await bot.rest.fetch_guild(g))
    #     cmds = await bot.rest.fetch_application_commands(698222394548027492, g)
    #     L = len(cmds)
    #     for j, cmd in enumerate(cmds, 1):
    #         await cmd.delete()
    #         print(f"#{i}/{_L} {j}/{L} {g}", cmd)


@client.with_listener(hk.VoiceStateUpdateEvent)
async def on_voice_state_update(
    event: hk.VoiceStateUpdateEvent,
    lvc: lv.Lavalink = tj.inject(type=lv.Lavalink),
) -> None:
    """Passes voice state updates to lavalink."""

    new = event.state
    # old = event.old_state

    lvc.raw_handle_event_voice_state_update(
        new.guild_id,
        new.user_id,
        new.session_id,
        new.channel_id,
    )


@client.with_listener(hk.VoiceServerUpdateEvent)
async def on_voice_server_update(
    event: hk.VoiceServerUpdateEvent,
    lvc: lv.Lavalink = tj.inject(type=lv.Lavalink),
) -> None:
    """Passes voice server updates to lavalink."""
    if event.endpoint is not None:
        await lvc.raw_handle_event_voice_server_update(
            event.guild_id,
            event.endpoint,
            event.token,
        )


@client.with_listener(hk.StoppingEvent)
async def on_stopping(
    _: hk.StoppingEvent, cfg: GuildConfig = tj.inject(type=GuildConfig)
) -> None:
    cfg_ref.set(dict(cfg))
    logger.info("Saved to guild_configs")