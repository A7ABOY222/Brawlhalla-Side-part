import os
import json
import asyncio
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True  # required for role assignment

bot = commands.Bot(command_prefix="!", intents=intents)

# ── Weapon config ──────────────────────────────────────────────────────────────
# Each entry: emoji_id → role name
WEAPON_ROLES = {
    1524877970680971406: "Sword",
    1524878111798460560: "Hammer",
    1524877985897779445: "Spear",
    1524878047378145411: "Katar",
    1524878222259519679: "Bow",
    1524878272477794324: "Axe",
    1524878002393972908: "Scythe",
    1524878016822640660: "Rocket Lance",
    1524878032446161016: "Orb",
    1524878237442773053: "Blasters",
    1524877956684579036: "Gauntlets",
    1524878204442116116: "Cannon",
    1524878082664694002: "Greatsword",
    1524878253616267436: "Battle Boots",
    1524878128357445752: "Chakram",
}

# Ordered display list for the embed  (emoji_string, role_name)
WEAPON_LIST = [
    ("<:emoji_11:1524877970680971406>", "Sword"),
    ("<:emoji_20:1524878111798460560>", "Hammer"),
    ("<:emoji_12:1524877985897779445>", "Spear"),
    ("<:emoji_16:1524878047378145411>", "Katar"),
    ("<:emoji_23:1524878222259519679>", "Bow"),
    ("<:emoji_26:1524878272477794324>", "Axe"),
    ("<:emoji_13:1524878002393972908>", "Scythe"),
    ("<:emoji_14:1524878016822640660>", "Rocket Lance"),
    ("<:emoji_16:1524878032446161016>", "Orb"),
    ("<:emoji_23:1524878237442773053>", "Blasters"),
    ("<:emoji_11:1524877956684579036>", "Gauntlets"),
    ("<:emoji_22:1524878204442116116>", "Cannon"),
    ("<:emoji_19:1524878082664694002>", "Greatsword"),
    ("<:emoji_24:1524878253616267436>", "Battle Boots"),
    ("<:emoji_21:1524878128357445752>", "Chakram"),
]

# Normalised name lookup for !weapon command
WEAPON_NAMES = {name.lower(): name for _, name in WEAPON_LIST}

# ── Persistence (stores the reaction-role message ID per guild) ────────────────
DATA_FILE = "reaction_message.json"

def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {}

def save_data(data: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

# ── Helpers ────────────────────────────────────────────────────────────────────

async def get_or_create_role(guild: discord.Guild, name: str) -> discord.Role:
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        role = await guild.create_role(name=name, reason="Weapon reaction role auto-created")
    return role


async def _safe_disconnect(vc: discord.VoiceClient):
    try:
        await vc.disconnect(force=True)
    except Exception:
        pass
    await asyncio.sleep(1)

# ── Events ─────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.event
async def on_voice_state_update(member, before, after):
    if member == bot.user:
        return
    vc = member.guild.voice_client
    if vc and len(vc.channel.members) == 1:
        await _safe_disconnect(vc)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return

    data = load_data()
    guild_entry = data.get(str(payload.guild_id))
    if not guild_entry or guild_entry.get("message_id") != payload.message_id:
        return

    role_name = WEAPON_ROLES.get(payload.emoji.id)
    if not role_name:
        return

    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)
    if not member:
        return

    role = await get_or_create_role(guild, role_name)
    await member.add_roles(role, reason="Weapon reaction role")


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return

    data = load_data()
    guild_entry = data.get(str(payload.guild_id))
    if not guild_entry or guild_entry.get("message_id") != payload.message_id:
        return

    role_name = WEAPON_ROLES.get(payload.emoji.id)
    if not role_name:
        return

    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)
    if not member:
        return

    role = discord.utils.get(guild.roles, name=role_name)
    if role and role in member.roles:
        await member.remove_roles(role, reason="Weapon reaction role removed")

# ── Commands ───────────────────────────────────────────────────────────────────

@bot.command(name="setupweapons")
@commands.has_permissions(manage_roles=True)
async def setup_weapons(ctx):
    """Post the weapon reaction-role embed in this channel. (Requires Manage Roles)"""
    lines = "\n".join(f"{emoji} — **{name}**" for emoji, name in WEAPON_LIST)
    embed = discord.Embed(
        title="⚔️ Choose Your Weapon",
        description=f"React to get your weapon role. Remove your reaction to drop it.\n\n{lines}",
        color=discord.Color.dark_gold(),
    )
    msg = await ctx.send(embed=embed)

    # Add all reactions upfront so users can just click
    for emoji_str, _ in WEAPON_LIST:
        try:
            await msg.add_reaction(emoji_str)
        except discord.HTTPException:
            pass  # emoji not in server — skip silently

    # Persist the message ID
    data = load_data()
    data[str(ctx.guild.id)] = {"message_id": msg.id, "channel_id": ctx.channel.id}
    save_data(data)

    await ctx.message.delete()


@bot.command(name="weapon")
async def weapon(ctx, *, name: str):
    """Get a weapon role by typing its name. Usage: !weapon Sword"""
    normalised = name.strip().lower()
    role_name = WEAPON_NAMES.get(normalised)

    if not role_name:
        close = [w for w in WEAPON_NAMES if normalised in w]
        hint = f" Did you mean: {', '.join(f'**{WEAPON_NAMES[w]}**' for w in close)}?" if close else ""
        await ctx.send(f"Unknown weapon `{name}`.{hint}\nAvailable: {', '.join(n for _, n in WEAPON_LIST)}")
        return

    role = await get_or_create_role(ctx.guild, role_name)
    if role in ctx.author.roles:
        await ctx.author.remove_roles(role)
        await ctx.send(f"Removed **{role_name}** role.", delete_after=5)
    else:
        await ctx.author.add_roles(role)
        await ctx.send(f"Gave you the **{role_name}** role.", delete_after=5)

    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass


@bot.command(name="join")
async def join(ctx):
    """Join the voice channel you're currently in."""
    if ctx.author.voice is None:
        await ctx.send("You need to be in a voice channel first!")
        return

    target = ctx.author.voice.channel

    if ctx.voice_client is not None:
        if ctx.voice_client.channel == target:
            await ctx.send(f"Already in **{target.name}**.")
            return
        await _safe_disconnect(ctx.voice_client)

    try:
        await target.connect(timeout=15.0, reconnect=False, self_deaf=True)
        await ctx.send(f"Joined **{target.name}**.")
    except discord.errors.ConnectionClosed as e:
        await ctx.send(f"Voice connection closed unexpectedly (code {e.code}). Try again.")
    except asyncio.TimeoutError:
        await ctx.send("Timed out trying to join the voice channel.")
    except Exception as e:
        await ctx.send(f"Failed to join: {e}")


@bot.command(name="joinid")
async def joinid(ctx, channel_id: int):
    """Join a voice channel by its ID. Usage: !joinid <channel_id>"""
    channel = ctx.guild.get_channel(channel_id)

    if channel is None:
        await ctx.send(f"No channel found with ID `{channel_id}`.")
        return

    if not isinstance(channel, discord.VoiceChannel):
        await ctx.send(f"**{channel.name}** is not a voice channel.")
        return

    if ctx.voice_client is not None:
        if ctx.voice_client.channel == channel:
            await ctx.send(f"Already in **{channel.name}**.")
            return
        await _safe_disconnect(ctx.voice_client)

    try:
        await channel.connect(timeout=15.0, reconnect=False, self_deaf=True)
        await ctx.send(f"Joined **{channel.name}**.")
    except discord.errors.ConnectionClosed as e:
        await ctx.send(f"Voice connection closed unexpectedly (code {e.code}). Try again.")
    except asyncio.TimeoutError:
        await ctx.send("Timed out trying to join the voice channel.")
    except Exception as e:
        await ctx.send(f"Failed to join: {e}")


@bot.command(name="leave")
async def leave(ctx):
    """Leave the current voice channel."""
    if ctx.voice_client is None:
        await ctx.send("I'm not in a voice channel.")
        return

    channel_name = ctx.voice_client.channel.name
    await _safe_disconnect(ctx.voice_client)
    await ctx.send(f"Left **{channel_name}**.")


@bot.command(name="ping")
async def ping(ctx):
    """Check the bot's latency."""
    await ctx.send(f"Pong! Latency: {round(bot.latency * 1000)}ms")


if __name__ == "__main__":
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise ValueError("DISCORD_TOKEN environment variable is not set.")
    bot.run(token)
