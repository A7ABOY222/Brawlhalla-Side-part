import os
import asyncio
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.event
async def on_voice_state_update(member, before, after):
    """Disconnect cleanly if the bot is left alone in a channel."""
    if member == bot.user:
        return

    vc = member.guild.voice_client
    if vc and len(vc.channel.members) == 1:
        await _safe_disconnect(vc)
        print(f"Left {vc.channel.name} — no users remaining.")


async def _safe_disconnect(vc: discord.VoiceClient):
    """Disconnect and wait for the session to fully close before continuing."""
    try:
        await vc.disconnect(force=True)
    except Exception:
        pass
    # Give Discord time to invalidate the old session server-side
    # so the next connect() doesn't collide with a stale 4017 session.
    await asyncio.sleep(1)


@bot.command(name="join")
async def join(ctx):
    """Join the voice channel you're currently in."""
    if ctx.author.voice is None:
        await ctx.send("You need to be in a voice channel first!")
        return

    target = ctx.author.voice.channel

    # Always clean up any existing voice client in this guild first.
    # Skipping this step is what causes the 4017 "session no longer valid" error:
    # discord.py tries to re-authenticate into a session that Discord has already closed.
    if ctx.voice_client is not None:
        if ctx.voice_client.channel == target:
            await ctx.send(f"Already in **{target.name}**.")
            return
        await _safe_disconnect(ctx.voice_client)

    try:
        # reconnect=False — let us handle reconnection explicitly so we don't
        # accidentally resume a dead session (which produces 4017).
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
    
