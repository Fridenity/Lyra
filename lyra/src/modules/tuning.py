import typing as t

import hikari as hk
import tanjun as tj
import alluka as al
import lavasnek_rs as lv

from ..lib.musicutils import init_component
from ..lib.extras import Option
from ..lib.utils import (
    say,
    err_say,
    with_message_command_group_template,
)
from ..lib.errors import NotConnected
from ..lib.compose import (
    DJ_PERMS,
    Checks,
    with_cmd_composer,
)
from ..lib.lavautils import Bands, access_equalizer


tuning = init_component(__name__)


# ~


def to_preset(value: str, /):
    if value.casefold() not in valid_presets.values():
        valid_presets_fmt = ', '.join(
            ('\"%s\" (%s)' % (j, i) for i, j in valid_presets.items())
        )
        raise ValueError(
            f"Invalid preset given. Must be one of the following:\n> {valid_presets_fmt}"
        )
    return value


async def set_mute(
    ctx: tj.abc.Context,
    lvc: lv.Lavalink,
    /,
    *,
    mute: Option[bool],
    respond: bool = False,
) -> None:
    assert not (ctx.cache is None or ctx.guild_id is None)
    me = ctx.cache.get_me()
    assert me is not None

    async with access_equalizer(ctx, lvc) as eq:
        if mute is None:
            mute = not eq.is_muted
        if mute and eq.is_muted:
            await err_say(ctx, content="❗ Already muted")
            return
        if not (mute or eq.is_muted):
            await err_say(ctx, content="❗ Already unmuted")
            return

        if mute:
            await ctx.rest.edit_member(ctx.guild_id, me, mute=True)
            msg = "🔇 Muted"
        else:
            await ctx.rest.edit_member(ctx.guild_id, me, mute=False)
            msg = "🔊 Unmuted"

        eq.is_muted = mute
        if respond:
            await say(ctx, content=msg)


with_common_cmd_check = with_cmd_composer(checks=Checks.CONN, perms=DJ_PERMS)
with_stage_cmd_check = with_cmd_composer(
    checks=Checks.CONN | Checks.SPEAK, perms=DJ_PERMS
)


@tuning.with_listener(hk.VoiceStateUpdateEvent)
async def on_voice_state_update(
    event: hk.VoiceStateUpdateEvent, lvc: al.Injected[lv.Lavalink]
):
    try:
        async with access_equalizer(event.guild_id, lvc) as eq:
            eq.is_muted = event.state.is_guild_muted
    except NotConnected:
        return


# Volume


volume_g_s = tuning.with_slash_command(
    tj.slash_command_group('volume', "Manages the volume of this guild's player")
)


@tj.as_message_command_group('volume', 'v', 'vol', strict=True)
@with_message_command_group_template
async def volume_g_m(_: tj.abc.MessageContext):
    """Manages the volume of this guild's player"""
    ...


## Volume Set


@volume_g_s.with_command
@with_stage_cmd_check
@tj.with_int_slash_option(
    'scale',
    "The volume scale? [Need to be between 0 and 10]",
    choices={str(i): i for i in range(10, -1, -1)},
)
@tj.as_slash_command('set', "Set the volume of the bot from 0-10")
#
@volume_g_m.with_command
@with_stage_cmd_check
@tj.with_argument('scale', converters=int, min_value=0, max_value=10)
@tj.with_parser
@tj.as_message_command('set', '=', '.')
async def volume_set_(
    ctx: tj.abc.Context,
    scale: int,
    lvc: al.Injected[lv.Lavalink],
):
    """
    Set the volume of the bot from 0-10
    """
    assert ctx.guild_id

    async with access_equalizer(ctx, lvc) as eq:
        eq.volume = scale
        await lvc.volume(ctx.guild_id, scale * 10)
        await say(ctx, content=f"🎚️ Volume set to **`{scale}`**")


## Volume Up


@volume_g_s.with_command
@with_stage_cmd_check
@tj.with_int_slash_option(
    'amount', "Increase by how much (If not given, by 1)", default=1
)
@tj.as_slash_command('up', "Increase the bot's volume")
#
@volume_g_m.with_command
@with_stage_cmd_check
@tj.with_argument('amount', converters=int, default=1)
@tj.with_parser
@tj.as_message_command('up', 'u', '+', '^')
async def volume_up_(
    ctx: tj.abc.Context,
    amount: int,
    lvc: al.Injected[lv.Lavalink],
):
    """
    Increase the bot's volume
    """
    assert ctx.guild_id

    async with access_equalizer(ctx, lvc) as eq:
        old = eq.volume
        if old == 10:
            await err_say(ctx, content=f"❗ Already maxed out the volume")
            return
        eq.up(amount)
        new = eq.volume
        await lvc.volume(ctx.guild_id, new * 10)

    await say(ctx, content=f"🔈**`＋`** ~~`{old}`~~ ➜ **`{new}`**")
    if not 0 <= amount <= 10 - old:
        await say(
            ctx,
            hidden=True,
            content=f"❕ *The given amount was too large; **Maxed out** the volume*",
        )


## Volume Down


@volume_g_s.with_command
@with_stage_cmd_check
@tj.with_int_slash_option(
    'amount', "Decrease by how much? (If not given, by 1)", default=1
)
@tj.as_slash_command('down', "Decrease the bot's volume")
#
@volume_g_m.with_command
@with_stage_cmd_check
@tj.with_argument('amount', converters=int, default=1)
@tj.with_parser
@tj.as_message_command('down', 'd', '-', 'v')
async def volume_down_(
    ctx: tj.abc.Context,
    amount: int,
    lvc: al.Injected[lv.Lavalink],
):
    """
    Decrease the bot's volume"
    """
    assert ctx.guild_id

    async with access_equalizer(ctx, lvc) as eq:
        old = eq.volume
        if old == 0:
            await err_say(ctx, content=f"❗ Already muted the volume")
            return
        eq.down(amount)
        new = eq.volume
        await lvc.volume(ctx.guild_id, new * 10)

    await say(ctx, content=f"🔈**`ー`** **`{new}`** ⟸ ~~`{old}`~~")
    if not 0 <= amount <= old:
        await say(
            ctx,
            hidden=True,
            content=f"❕ *The given amount was too large; **Muted** the volume*",
        )


# Mute


@with_common_cmd_check
@tj.as_slash_command('mute', 'Server mutes the bot')
#
@with_common_cmd_check
@tj.as_message_command('mute', 'm')
async def mute_(ctx: tj.abc.Context, lvc: al.Injected[lv.Lavalink]):
    """
    Server mutes the bot
    """
    await set_mute(ctx, lvc, mute=True, respond=True)


# Unmute


@with_common_cmd_check
@tj.as_slash_command('unmute', 'Server unmutes the bot')
#
@with_common_cmd_check
@tj.as_message_command('unmute', 'u', 'um')
async def unmute_(ctx: tj.abc.Context, lvc: al.Injected[lv.Lavalink]):
    """
    Server unmutes the bot
    """
    await set_mute(ctx, lvc, mute=False, respond=True)


# Mute-Unmute


@with_common_cmd_check
@tj.as_slash_command('mute-unmute', 'Toggles between server mute and unmuting the bot')
#
@with_common_cmd_check
@tj.as_message_command('mute-unmute', 'muteunmute', 'mm', 'mu', 'tm', 'togglemute')
async def mute_unmute_(ctx: tj.abc.Context, lvc: al.Injected[lv.Lavalink]):
    """
    Toggles between server mute and unmuting the bot
    """
    await set_mute(ctx, lvc, mute=None, respond=True)


# Equalizer


equalizer_g_s = tuning.with_slash_command(
    tj.slash_command_group('equalizer', "Manages the bot's equalizer")
)


@tj.as_message_command_group('equalizer', 'eq', strict=True)
@with_message_command_group_template
async def equalizer_g_m(_: tj.abc.MessageContext):
    """Manages the bot's equalizer"""
    ...


## Equalizer Rreset


valid_presets: t.Final[dict[str, str]] = {
    j['name']: i
    for i, j in Bands._load_bands().items()  # pyright: ignore [reportPrivateUsage, reportGeneralTypeIssues]
} | {'Flat': 'flat'}


@equalizer_g_s.with_command
@with_stage_cmd_check
@tj.with_str_slash_option(
    'preset',
    "Which present?",
    choices=valid_presets,
)
@tj.as_slash_command('preset', "Sets the bot's equalizer to a preset")
#
@equalizer_g_m.with_command
@with_stage_cmd_check
@tj.with_argument('preset', to_preset)
@tj.with_parser
@tj.as_message_command('preset', 'pre', '=')
async def equalizer_preset_(
    ctx: tj.abc.Context,
    preset: str,
    lvc: al.Injected[lv.Lavalink],
):
    """
    Sets the bot's equalizer to a preset
    """
    assert ctx.guild_id

    async with access_equalizer(ctx, lvc) as eq:
        bands = Bands.load(preset)
        await lvc.equalize_all(ctx.guild_id, [*bands])
        eq.bands = bands
    await say(ctx, content=f"🎛️ Equalizer set to preset: `{preset.capitalize()}`")


# -


loader = tuning.load_from_scope().make_loader()
