import os
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.command(name="join")
async def join(ctx):
    """Join the voice channel you're currently in."""
    if ctx.author.voice is None:
        await ctx.send("You need to be in a voice channel first!")
        return

    channel = ctx.author.voice.channel

    if ctx.voice_client is not None:
        await ctx.voice_client.move_to(channel)
        await ctx.send(f"Moved to **{channel.name}**.")
    else:
        await channel.connect()
        await ctx.send(f"Joined **{channel.name}**.")


@bot.command(name="leave")
async def leave(ctx):
    """Leave the current voice channel."""
    if ctx.voice_client is None:
        await ctx.send("I'm not in a voice channel.")
        return

    channel_name = ctx.voice_client.channel.name
    await ctx.voice_client.disconnect()
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
