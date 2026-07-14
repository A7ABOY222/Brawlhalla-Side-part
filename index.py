import os
import json
import math
import random
import asyncio
import io
import time
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord.ext import commands
import aiohttp
from aiohttp import web
from PIL import Image, ImageDraw, ImageFont

# ── Config ─────────────────────────────────────────────────────────────────

GUILD_ID    = 1514385970684755980
CHANNEL_ID  = 1514388213547012197
DATA_FILE   = Path(__file__).parent / 'tournament_data.json'
PREFIX      = '!'
DEFAULT_ELO = 1000
K           = 32
MAX_WEAPON_ROLES = 2

# ── Brawlhalla Weapon Roles ─────────────────────────────────────────────────
WEAPONS = [
    {'name': 'Sword',        'emoji': 'emoji_11:1524877970680971406',  'emojiId': '1524877970680971406', 'role': 'Main: Sword'       },
    {'name': 'Hammer',       'emoji': 'emoji_20:1524878111798460560',  'emojiId': '1524878111798460560', 'role': 'Main: Hammer'      },
    {'name': 'Spear',        'emoji': 'emoji_12:1524877985897779445',  'emojiId': '1524877985897779445', 'role': 'Main: Spear'       },
    {'name': 'Katar',        'emoji': 'emoji_16:1524878047378145411',  'emojiId': '1524878047378145411', 'role': 'Main: Katar'       },
    {'name': 'Bow',          'emoji': 'emoji_23:1524878222259519679',  'emojiId': '1524878222259519679', 'role': 'Main: Bow'         },
    {'name': 'Axe',          'emoji': 'emoji_26:1524878272477794324',  'emojiId': '1524878272477794324', 'role': 'Main: Axe'         },
    {'name': 'Scythe',       'emoji': 'emoji_13:1524878002393972908',  'emojiId': '1524878002393972908', 'role': 'Main: Scythe'      },
    {'name': 'Rocket Lance', 'emoji': 'emoji_14:1524878016822640660',  'emojiId': '1524878016822640660', 'role': 'Main: Rocket Lance'},
    {'name': 'Orb',          'emoji': 'emoji_16:1524878032446161016',  'emojiId': '1524878032446161016', 'role': 'Main: Orb'         },
    {'name': 'Blasters',     'emoji': 'emoji_23:1524878237442773053',  'emojiId': '1524878237442773053', 'role': 'Main: Blasters'    },
    {'name': 'Gauntlets',    'emoji': 'emoji_11:1524877956684579036',  'emojiId': '1524877956684579036', 'role': 'Main: Gauntlets'   },
    {'name': 'Cannon',       'emoji': 'emoji_22:1524878204442116116',  'emojiId': '1524878204442116116', 'role': 'Main: Cannon'      },
    {'name': 'Greatsword',   'emoji': 'emoji_19:1524878082664694002',  'emojiId': '1524878082664694002', 'role': 'Main: Greatsword'  },
    {'name': 'Battle Boots', 'emoji': 'emoji_24:1524878253616267436',  'emojiId': '1524878253616267436', 'role': 'Main: Battle Boots'},
    {'name': 'Chakram',      'emoji': 'emoji_21:1524878128357445752',  'emojiId': '1524878128357445752', 'role': 'Main: Chakram'     },
]
WEAPON_EMOJI_MAP = {w['emojiId']: w for w in WEAPONS}

# ── Log channel ─────────────────────────────────────────────────────────────
_log_channel_id = None

# ── Persistence ─────────────────────────────────────────────────────────────

def load_data():
    if DATA_FILE.exists():
        d = json.loads(DATA_FILE.read_text(encoding='utf-8'))
        if 'pendingReports' not in d:
            d['pendingReports'] = []
        return d
    return {'tournament': None, 'elo': {}, 'history': [], 'pendingReports': []}

def save_data(data):
    DATA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

# ── ELO helpers ─────────────────────────────────────────────────────────────

def expected(a, b):
    return 1 / (1 + 10 ** ((b - a) / 400))

def update_elo(data, winner_id, loser_id, k_override=None):
    elo = data['elo']
    wid, lid = str(winner_id), str(loser_id)
    for uid in (wid, lid):
        if uid not in elo:
            elo[uid] = {'elo': DEFAULT_ELO, 'wins': 0, 'losses': 0, 'tournaments': 0}
    k = k_override if k_override is not None else K
    ea = expected(elo[wid]['elo'], elo[lid]['elo'])
    eb = expected(elo[lid]['elo'], elo[wid]['elo'])
    elo[wid]['elo']    = round(elo[wid]['elo'] + k * (1 - ea))
    elo[lid]['elo']    = round(elo[lid]['elo'] + k * (0 - eb))
    elo[wid]['wins']  += 1
    elo[lid]['losses'] += 1

# ── Rank system ─────────────────────────────────────────────────────────────

def get_rank(elo_val):
    if elo_val >= 2400: return {'name': 'Legend',   'color': '#FF6B35', 'k': 16}
    if elo_val >= 2000: return {'name': 'Diamond',  'color': '#B9F2FF', 'k': 20}
    if elo_val >= 1600: return {'name': 'Platinum', 'color': '#00B4D8', 'k': 24}
    if elo_val >= 1300: return {'name': 'Gold',     'color': '#FFD700', 'k': 28}
    if elo_val >= 1100: return {'name': 'Silver',   'color': '#C0C0C0', 'k': 30}
    if elo_val >= 900:  return {'name': 'Bronze',   'color': '#CD7F32', 'k': 32}
    return               {'name': 'Tin',      'color': '#808080', 'k': 32}

# ── Bracket helpers ─────────────────────────────────────────────────────────

def bracket_size(n):
    if n <= 1: return 2
    return 2 ** math.ceil(math.log2(n))

def seeded_slot_indices(size):
    slots = [0, 1]
    current = 2
    while current < size:
        new_slots = []
        for s in slots:
            new_slots.append(s)
            new_slots.append(current * 2 - 1 - s)
        slots = new_slots
        current *= 2
    return slots

def elo_seeded_slots(players, data):
    ranked = sorted(players, key=lambda p: (data['elo'].get(str(p), {}).get('elo', DEFAULT_ELO)), reverse=True)
    size    = bracket_size(len(ranked))
    indices = seeded_slot_indices(size)
    slots   = [None] * size
    for slot_i, seed_i in enumerate(indices):
        if seed_i < len(ranked):
            slots[slot_i] = ranked[seed_i]
    return slots

def make_bracket(slots):
    matches = []
    match_id = 1
    for i in range(0, len(slots), 2):
        p1 = slots[i]
        p2 = slots[i + 1] if i + 1 < len(slots) else None
        if p1 is None and p2 is None:
            continue
        if p1 is not None and p1 == p2:
            continue
        matches.append({'id': match_id, 'round': 1, 'p1': p1, 'p2': p2,
                        'winner': None, 'state': 'pending', 'duelChannelId': None})
        match_id += 1
    return matches

def resolve_byes(matches):
    for m in matches:
        if m['state'] != 'pending':
            continue
        if m['p1'] is None and m['p2'] is not None:
            m['winner'] = m['p2']; m['state'] = 'done'
        elif m['p2'] is None and m['p1'] is not None:
            m['winner'] = m['p1']; m['state'] = 'done'
    return matches

def advance_bracket(matches):
    rounds     = sorted(set(m['round'] for m in matches))
    last_round = rounds[-1]
    last       = [m for m in matches if m['round'] == last_round]
    seen       = set()
    winners    = []
    for m in last:
        if m['winner'] is not None and m['winner'] not in seen:
            seen.add(m['winner'])
            winners.append(m['winner'])
    if len(winners) <= 1:
        return matches
    mid        = max(m['id'] for m in matches) + 1
    next_round = last_round + 1
    for i in range(0, len(winners), 2):
        p1 = winners[i]
        p2 = winners[i + 1] if i + 1 < len(winners) else None
        if p1 == p2:
            p2 = None
        matches.append({'id': mid, 'round': next_round, 'p1': p1, 'p2': p2,
                        'winner': None, 'state': 'pending', 'duelChannelId': None})
        mid += 1
    return resolve_byes(matches)

def round_complete(matches, round_num):
    return all(m['state'] == 'done' for m in matches if m['round'] == round_num)

def current_round(matches):
    rounds = sorted(set(m['round'] for m in matches))
    for r in rounds:
        if not round_complete(matches, r):
            return r
    return rounds[-1] if rounds else 1

def pending_matches(matches):
    r = current_round(matches)
    return [m for m in matches if m['round'] == r and m['state'] == 'pending']

# ── Avatar fetcher (async, for top3 image) ──────────────────────────────────

async def fetch_avatar_bytes(session, url, size):
    fallback = Image.new('RGBA', (size, size), (60, 60, 80, 255))
    draw = ImageDraw.Draw(fallback)
    draw.ellipse([0, 0, size - 1, size - 1], fill=(60, 60, 80, 255))
    if not url:
        return fallback
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status != 200:
                return fallback
            data = await resp.read()
        img = Image.open(io.BytesIO(data)).convert('RGBA').resize((size, size), Image.LANCZOS)
        mask = Image.new('L', (size, size), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
        result = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        result.paste(img, mask=mask)
        return result
    except Exception:
        return fallback

def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def draw_rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    x0, y0, x1, y1 = xy
    if fill:
        draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill)
        draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill)
        draw.ellipse([x0, y0, x0 + 2*radius, y0 + 2*radius], fill=fill)
        draw.ellipse([x1 - 2*radius, y0, x1, y0 + 2*radius], fill=fill)
        draw.ellipse([x0, y1 - 2*radius, x0 + 2*radius, y1], fill=fill)
        draw.ellipse([x1 - 2*radius, y1 - 2*radius, x1, y1], fill=fill)
    if outline:
        for i in range(width):
            draw.arc([x0+i, y0+i, x0 + 2*radius - i, y0 + 2*radius - i], 180, 270, fill=outline)
            draw.arc([x1 - 2*radius+i, y0+i, x1-i, y0 + 2*radius-i], 270, 360, fill=outline)
            draw.arc([x0+i, y1 - 2*radius+i, x0 + 2*radius-i, y1-i], 90, 180, fill=outline)
            draw.arc([x1 - 2*radius+i, y1 - 2*radius+i, x1-i, y1-i], 0, 90, fill=outline)
            draw.line([x0 + radius, y0+i, x1 - radius, y0+i], fill=outline)
            draw.line([x0 + radius, y1-i, x1 - radius, y1-i], fill=outline)
            draw.line([x0+i, y0 + radius, x0+i, y1 - radius], fill=outline)
            draw.line([x1-i, y0 + radius, x1-i, y1 - radius], fill=outline)

async def build_top3_image(top3, guild):
    W, H = 1020, 560
    img = Image.new('RGBA', (W, H), (11, 9, 32, 255))
    draw = ImageDraw.Draw(img)

    # Grid lines
    for gx in range(0, W, 60):
        draw.line([(gx, 0), (gx, H)], fill=(255, 255, 255, 8))
    for gy in range(0, H, 60):
        draw.line([(0, gy), (W, gy)], fill=(255, 255, 255, 8))

    # Star particles
    stars = [(45,30,2),(150,70,1),(800,25,2),(900,80,1),(60,450,1),(350,510,2),
             (750,490,1),(970,380,1),(500,530,1),(250,400,1),(700,100,2),(870,300,1),
             (120,300,2),(600,480,2),(950,200,2),(400,60,2),(820,520,1)]
    for sx, sy, sr in stars:
        alpha = 46 if sr > 1 else 26
        draw.ellipse([sx-sr, sy-sr, sx+sr, sy+sr], fill=(255, 255, 255, alpha))

    # Title
    try:
        font_title = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 28)
        font_big   = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 38)
        font_med   = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 19)
        font_sml   = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 13)
        font_badge = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 17)
    except Exception:
        font_title = font_big = font_med = font_sml = font_badge = ImageFont.load_default()

    title_text = 'TOP 3  ·  ELO LEADERBOARD'
    draw.text((W // 2, 40), title_text, font=font_title, fill=(255, 210, 40, 230), anchor='mm')
    draw.line([(150, 62), (870, 62)], fill=(255, 210, 40, 100), width=2)

    GOLD   = (255, 210, 40)
    SILVER = (184, 207, 232)
    BRONZE = (217, 140, 69)

    columns = [
        {'rank_index': 1, 'x': 20,  'y': 145, 'w': 295, 'h': 375, 'av_sz': 88,  'color': SILVER, 'label': '2'},
        {'rank_index': 0, 'x': 355, 'y': 78,  'w': 315, 'h': 450, 'av_sz': 106, 'color': GOLD,   'label': '1'},
        {'rank_index': 2, 'x': 700, 'y': 185, 'w': 295, 'h': 335, 'av_sz': 80,  'color': BRONZE, 'label': '3'},
    ]

    async with aiohttp.ClientSession() as session:
        for col in columns:
            ri = col['rank_index']
            if ri >= len(top3):
                continue
            uid_str, stats = top3[ri]
            member    = guild.get_member(int(uid_str))
            disp_name = member.display_name if member else f'Player {uid_str[-4:]}'
            name      = (disp_name[:15] + '…') if len(disp_name) > 16 else disp_name
            wins      = stats.get('wins', 0)
            losses    = stats.get('losses', 0)
            elo_val   = stats.get('elo', DEFAULT_ELO)
            total     = wins + losses
            wr        = round(wins / total * 100) if total else 0
            x, y, w, h = col['x'], col['y'], col['w'], col['h']
            av_sz      = col['av_sz']
            color      = col['color']
            label      = col['label']
            cx         = x + w // 2

            # Card body
            draw_rounded_rect(draw, [x, y, x+w, y+h], radius=20,
                              fill=(31, 28, 62, 230), outline=color, width=2)

            # Top accent bar
            draw.rectangle([x+12, y, x+w-12, y+4], fill=(*color, 180))

            # Rank badge circle
            bx, by = x + w - 28, y + 30
            draw.ellipse([bx-22, by-22, bx+22, by+22], fill=color)
            draw.text((bx, by), f'#{label}', font=font_badge, fill=(11, 9, 32, 255), anchor='mm')

            # Crown for #1
            if label == '1':
                draw.text((cx, y + 44), '👑', font=font_sml, fill=GOLD, anchor='mm')

            # Avatar
            av_url = member.display_avatar.replace(size=128, format='png').url if member else None
            av_img = await fetch_avatar_bytes(session, av_url, av_sz)
            av_y   = y + 66 if label == '1' else y + 52
            av_x   = cx - av_sz // 2

            # Glow ring behind avatar
            ring_r = av_sz // 2 + 6
            draw.ellipse([cx - ring_r, av_y - ring_r + av_sz//2,
                          cx + ring_r, av_y + ring_r + av_sz//2], fill=(*color, 80))
            # White ring
            wring = av_sz // 2 + 2
            draw.ellipse([cx - wring, av_y - wring + av_sz//2,
                          cx + wring, av_y + wring + av_sz//2], fill=(255,255,255,200))

            img.paste(av_img, (av_x, av_y), av_img)

            # Name
            ty = av_y + av_sz + 22
            draw.text((cx, ty), name, font=font_med, fill=(255, 255, 255, 230), anchor='mm')

            # ELO number
            ty += 38 if label == '1' else 32
            elo_font = font_big if label == '1' else font_med
            draw.text((cx, ty), str(elo_val), font=elo_font, fill=(*color, 240), anchor='mm')

            # "ELO" small label
            ty += 16
            draw.text((cx, ty), 'E L O', font=font_sml, fill=(200, 210, 240, 115), anchor='mm')

            # Win-rate bar
            ty += 22
            bar_w = w - 50
            bar_x = x + 25
            bar_h = 7
            draw.rectangle([bar_x, ty, bar_x + bar_w, ty + bar_h], fill=(255,255,255,20))
            fill_w = max(0, round(bar_w * wr / 100))
            if fill_w > 0:
                draw.rectangle([bar_x, ty, bar_x + fill_w, ty + bar_h], fill=(*color, 200))

            # W/L/WR
            ty += 20
            draw.text((cx, ty), f'{wins}W  {losses}L  ·  {wr}% WR', font=font_sml,
                      fill=(195, 210, 235, 190), anchor='mm')

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf.read()

# ── Member fetch cache ───────────────────────────────────────────────────────

_member_fetched_at = {}

async def fetch_members(guild):
    last = _member_fetched_at.get(guild.id, 0)
    if time.time() - last < 60:
        return
    await guild.chunk()
    _member_fetched_at[guild.id] = time.time()
    try:
        data = load_data()
        if 'profiles' not in data:
            data['profiles'] = {}
        for member in guild.members:
            data['profiles'][str(member.id)] = {
                'name':   member.display_name,
                'avatar': str(member.display_avatar.replace(size=128, format='png').url),
            }
        save_data(data)
    except Exception:
        pass

def member_name(guild, uid):
    if uid is None:
        return 'BYE'
    m = guild.get_member(int(uid))
    return m.display_name if m else f'<{uid}>'

# ── Discord bot setup ────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members         = True
intents.reactions       = True
intents.guilds          = True
intents.guild_messages  = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ── Log helper ───────────────────────────────────────────────────────────────

async def bot_log(title, description, color=0x5865F2, fields=None):
    if not _log_channel_id:
        return
    try:
        guild = bot.get_guild(GUILD_ID)
        if not guild:
            return
        ch = guild.get_channel(int(_log_channel_id))
        if not ch:
            return
        embed = discord.Embed(title=title, description=description or '\u200b',
                              color=color, timestamp=datetime.now(timezone.utc))
        if fields:
            for f in fields:
                embed.add_field(name=f['name'], value=f['value'], inline=f.get('inline', False))
        await ch.send(embed=embed)
    except Exception:
        pass

# ── Admin check ──────────────────────────────────────────────────────────────

def is_admin(ctx):
    if ctx.author.guild_permissions.administrator:
        return True
    if any(r.name.lower() == 'tournament admin' for r in ctx.author.roles):
        return True
    return False

async def admin_only(ctx):
    if not is_admin(ctx):
        await ctx.reply('🔒 This command is **admin only**. You need the `Administrator` permission or the `Tournament Admin` role.')
        return False
    return True

# ── Round advance helper ─────────────────────────────────────────────────────

async def handle_round_advance(channel, guild, t, data):
    r = current_round(t['matches'])
    if not round_complete(t['matches'], r):
        return False

    t['matches'] = advance_bracket(t['matches'])
    next_pending  = pending_matches(t['matches'])
    rounds        = sorted(set(m['round'] for m in t['matches']))
    total_rounds  = len(rounds)

    def mname(uid):
        if uid is None: return 'BYE'
        m = guild.get_member(int(uid))
        return m.display_name if m else f'User#{str(uid)[-4:]}'

    # ── Tournament over ──────────────────────────────────────────────────────
    last_round   = max(m['round'] for m in t['matches'])
    last_matches = [m for m in t['matches'] if m['round'] == last_round and m['winner'] is not None]
    true_winner  = last_matches[0]['winner'] if not next_pending and len(last_matches) == 1 else None

    if true_winner:
        t['state']  = 'ended'
        t['winner'] = true_winner
        if str(true_winner) in data['elo']:
            data['elo'][str(true_winner)]['tournaments'] += 1
        data['history'].append({
            'name': t['name'], 'winner': true_winner,
            'players': len(t['players']), 'date': datetime.now(timezone.utc).isoformat(),
        })
        save_data(data)
        champ = guild.get_member(int(true_winner))
        champ_name = champ.display_name if champ else str(true_winner)
        embed = discord.Embed(
            title='🏆 Tournament Over!',
            description=f'**{champ_name}** is the champion of **{t["name"]}**! 🎉',
            color=0xFFD700)
        await channel.send(embed=embed)
        await bot_log(
            '🏆 Tournament Finished',
            f'**Tournament:** {t["name"]}\n**Champion:** {champ_name}\n'
            f'**Total players:** {len(t["players"])}\n**Total rounds:** {total_rounds}',
            0xFFD700)
        return True

    # ── Next round announcement ──────────────────────────────────────────────
    save_data(data)
    new_round   = current_round(t['matches'])
    if new_round == total_rounds:
        round_label = '🏆 Final'
    elif new_round == total_rounds - 1:
        round_label = '🥊 Semi-Final'
    else:
        round_label = f'⚔️ Round {new_round}'

    await bot_log(
        f'📢 {round_label} Started',
        f'**Tournament:** {t["name"]}\n**Round:** {new_round} of {total_rounds}\n'
        f'**Pending matches:** {sum(1 for m in next_pending if m["p2"] is not None)}',
        0xE74C3C)

    lines = []
    for m in next_pending:
        p1, p2 = mname(m['p1']), mname(m['p2'])
        if m['p2'] is None:
            lines.append(f'  [{str(m["id"]).zfill(2)}] **{p1}** — *auto-advance (BYE)*')
        else:
            lines.append(f'  [{str(m["id"]).zfill(2)}] **{p1}** vs **{p2}**')

    CHUNK = 16
    for i in range(0, len(lines), CHUNK):
        chunk = lines[i:i+CHUNK]
        page_label = f' ({i//CHUNK+1}/{math.ceil(len(lines)/CHUNK)})' if len(lines) > CHUNK else ''
        embed = discord.Embed(
            title=f'{round_label}{page_label} — Matches',
            description='\n'.join(chunk),
            color=0xE74C3C)
        embed.set_footer(text=f'Round {new_round} of {total_rounds} • Use !mymatch to see your opponent')
        await channel.send(embed=embed)
    return True

# ── Duel channel helper ──────────────────────────────────────────────────────

async def close_duel_channel(guild, match):
    if not match.get('duelChannelId'):
        return
    try:
        ch = guild.get_channel(int(match['duelChannelId']))
        if ch:
            await ch.delete(reason='Match finished')
    except Exception:
        pass
    match['duelChannelId'] = None

# ── Helper: get or create weapon role ───────────────────────────────────────

async def get_or_create_weapon_role(guild, role_name):
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        role = await guild.create_role(name=role_name, mentionable=False,
                                       reason='Weapon main reaction role')
    return role

# ════════════════════════════════════════════════════════════════════════════
# ── Commands ────────────────────────────────────────────────────────────────
# ════════════════════════════════════════════════════════════════════════════

@bot.command(name='create')
async def cmd_create(ctx, *, name: str = 'Brawlhalla Tournament'):
    if not await admin_only(ctx): return
    data = load_data()
    if data['tournament'] and data['tournament']['state'] != 'ended':
        return await ctx.reply('❌ A tournament is already running. Use `!end` to close it first.')
    data['tournament'] = {
        'name': name, 'state': 'registration', 'players': [], 'matches': [],
        'current_round': 1, 'winner': None, 'created_by': str(ctx.author.id),
        'created_at': datetime.now(timezone.utc).isoformat(),
    }
    save_data(data)
    embed = discord.Embed(
        title=f'🏆 {name}',
        description='A new **Brawlhalla** tournament has been created!\n\nType `!register` to join.\nAdmin: `!start` to begin once everyone has registered.',
        color=0xFFD700)
    embed.set_footer(text=f'Created by {ctx.author.display_name}')
    await ctx.channel.send(embed=embed)

@bot.command(name='register', aliases=['join_tournament', 'reg'])
async def cmd_register(ctx):
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'registration':
        return await ctx.reply('❌ No tournament is open for registration right now.')
    if str(ctx.author.id) in t['players']:
        return await ctx.reply("You're already registered!")
    t['players'].append(str(ctx.author.id))
    save_data(data)
    n = len(t['players'])
    await ctx.reply(f'✅ **{ctx.author.display_name}** has registered! ({n} player{"s" if n != 1 else ""} signed up)')

@bot.command(name='unregister', aliases=['leave_tournament'])
async def cmd_unregister(ctx):
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'registration':
        return await ctx.reply('❌ Registration is not open.')
    if str(ctx.author.id) not in t['players']:
        return await ctx.reply("You're not registered.")
    t['players'].remove(str(ctx.author.id))
    save_data(data)
    await ctx.reply(f'**{ctx.author.display_name}** has left the tournament.')

@bot.command(name='addjoin', aliases=['addplayer', 'forceadd'])
async def cmd_addjoin(ctx):
    if not await admin_only(ctx): return
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'registration':
        return await ctx.reply('❌ No tournament is open for registration right now.')
    if not ctx.message.mentions:
        return await ctx.reply('❌ Mention a player to add.')
    mentioned = ctx.message.mentions[0]
    if str(mentioned.id) in t['players']:
        return await ctx.reply(f'**{mentioned.display_name}** is already registered!')
    t['players'].append(str(mentioned.id))
    save_data(data)
    n = len(t['players'])
    await ctx.reply(f'✅ **{mentioned.display_name}** has been added! ({n} player{"s" if n != 1 else ""} signed up)')

@bot.command(name='joinbyid', aliases=['addid', 'addbyid'])
async def cmd_joinbyid(ctx, user_id: str = None):
    if not await admin_only(ctx): return
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'registration':
        return await ctx.reply('❌ No tournament is open for registration right now.')
    if not user_id:
        return await ctx.reply('❌ Provide a user ID.')
    if user_id in t['players']:
        return await ctx.reply(f'**{user_id}** is already registered!')
    t['players'].append(user_id)
    save_data(data)
    member = ctx.guild.get_member(int(user_id)) if user_id.isdigit() else None
    name   = member.display_name if member else f'User `{user_id}`'
    n = len(t['players'])
    await ctx.reply(f'✅ **{name}** has been added by ID! ({n} player{"s" if n != 1 else ""} signed up)')

@bot.command(name='addall', aliases=['addeveryone', 'joinall'])
async def cmd_addall(ctx):
    if not await admin_only(ctx): return
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'registration':
        return await ctx.reply('❌ No tournament is open for registration right now.')
    await fetch_members(ctx.guild)
    added, skipped = [], []
    for member in ctx.guild.members:
        if member.bot: continue
        if str(member.id) in t['players']:
            skipped.append(member.display_name)
        else:
            t['players'].append(str(member.id))
            added.append(member.display_name)
    save_data(data)
    desc = f'✅ Added **{len(added)}** member{"s" if len(added) != 1 else ""}.'
    if skipped:
        desc += f'\n⏭️ Skipped **{len(skipped)}** already registered.'
    desc += f'\n👥 Total players: **{len(t["players"])}**'
    embed = discord.Embed(title='📋 All Members Added to Tournament', description=desc, color=0x2ECC71)
    embed.set_footer(text=f'Run by {ctx.author.display_name}')
    await ctx.channel.send(embed=embed)

@bot.command(name='removejoin', aliases=['removeplayer', 'forceremove'])
async def cmd_removejoin(ctx):
    if not await admin_only(ctx): return
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'registration':
        return await ctx.reply('❌ Registration is not open.')
    if not ctx.message.mentions:
        return await ctx.reply('❌ Mention a player to remove.')
    mentioned = ctx.message.mentions[0]
    if str(mentioned.id) not in t['players']:
        return await ctx.reply(f'**{mentioned.display_name}** is not registered.')
    t['players'].remove(str(mentioned.id))
    save_data(data)
    n = len(t['players'])
    await ctx.reply(f'🗑️ **{mentioned.display_name}** has been removed. ({n} player{"s" if n != 1 else ""} remaining)')

@bot.command(name='players')
async def cmd_players(ctx):
    data = load_data()
    t = data['tournament']
    if not t: return await ctx.reply('No tournament active.')
    if not t['players']: return await ctx.reply('No players registered yet.')
    await fetch_members(ctx.guild)
    lines = []
    for i, uid in enumerate(t['players']):
        m = ctx.guild.get_member(int(uid))
        username = m.name if m else f'Unknown ({uid})'
        lines.append(f'`{i+1}.` {username}')
    embed = discord.Embed(
        title=f'👥 {t["name"]} — Players ({len(t["players"])})',
        description='\n'.join(lines), color=0x3498DB)
    await ctx.channel.send(embed=embed)

@bot.command(name='seedings')
async def cmd_seedings(ctx):
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'registration':
        return await ctx.reply('❌ No tournament in registration phase.')
    if not t['players']: return await ctx.reply('No players registered yet.')
    ranked = sorted(t['players'], key=lambda p: data['elo'].get(str(p), {}).get('elo', DEFAULT_ELO), reverse=True)
    medals = ['🥇', '🥈', '🥉'] + ['🔹'] * 50
    lines = []
    for i, uid in enumerate(ranked):
        m = ctx.guild.get_member(int(uid))
        name = m.display_name if m else f'<{uid}>'
        elo_val = data['elo'].get(str(uid), {}).get('elo', DEFAULT_ELO)
        lines.append(f'{medals[i]} Seed **#{i+1}** — {name} ({elo_val} ELO)')
    embed = discord.Embed(title=f'🌱 {t["name"]} — ELO Seedings', description='\n'.join(lines), color=0x2ECC71)
    embed.set_footer(text='Seed #1 and #2 can only meet in the Final • !start to begin')
    await ctx.channel.send(embed=embed)

@bot.command(name='start')
async def cmd_start(ctx, mode: str = 'random'):
    if not await admin_only(ctx): return
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'registration':
        return await ctx.reply('❌ No tournament is in registration phase.')
    if len(t['players']) < 2:
        return await ctx.reply('❌ Need at least 2 players to start.')

    # Deduplicate
    seen = set(); t['players'] = [p for p in t['players'] if not (p in seen or seen.add(p))]

    use_random = mode.lower() != 'seeded'
    if use_random:
        arr = t['players'][:]
        random.shuffle(arr)
        size  = bracket_size(len(arr))
        slots = arr + [None] * (size - len(arr))
    else:
        slots = elo_seeded_slots(t['players'], data)

    matches = resolve_byes(make_bracket(slots))
    t['matches']       = matches
    t['state']         = 'in_progress'
    t['current_round'] = 1
    save_data(data)

    await fetch_members(ctx.guild)
    round1   = [m for m in matches if m['round'] == 1]
    seedings = '🎲 Random draw' if use_random else '🌱 ELO seeded'

    start_embed = discord.Embed(
        title=f'⚔️ {t["name"]} has started! ({seedings})',
        description=f'**{len(t["players"])}** players registered • Single Elimination\nUse `!bracket` to see the full draw at any time.',
        color=0xE74C3C)
    await ctx.channel.send(embed=start_embed)

    for i in range(0, len(round1), 16):
        chunk = round1[i:i+16]
        page, total = i // 16 + 1, math.ceil(len(round1) / 16)
        lines = []
        for m in chunk:
            p1 = member_name(ctx.guild, m['p1'])
            p2 = member_name(ctx.guild, m['p2'])
            if m['state'] == 'done':
                lines.append(f'  [{str(m["id"]).zfill(2)}] {p1} vs {p2}  →  ✅ {member_name(ctx.guild, m["winner"])} *(auto-advance)*')
            else:
                lines.append(f'  [{str(m["id"]).zfill(2)}] **{p1}** vs **{p2}**')
        page_label = f' ({page}/{total})' if total > 1 else ''
        await ctx.channel.send(f'**⚔️ Round 1 Matches{page_label}**```\n' + '\n'.join(lines) + '\n```')

@bot.command(name='bracket')
async def cmd_bracket(ctx):
    data = load_data()
    t = data['tournament']
    if not t or not t['matches']:
        return await ctx.reply('No bracket yet.')
    await fetch_members(ctx.guild)
    PAGE_SIZE   = 16
    rounds      = sorted(set(m['round'] for m in t['matches']))
    total_rounds = len(rounds)
    round1_count = sum(1 for m in t['matches'] if m['round'] == 1)

    summary = discord.Embed(
        title=f'📊 {t["name"]} — Bracket Overview',
        description=(
            f'👥 **{len(t["players"])}** players registered\n'
            f'⚔️ **{round1_count}** matches in Round 1\n'
            f'🔢 **{total_rounds}** rounds total\n\n'
            + ('⚠️ Very few players — run `!addall` before `!start` to include everyone.' if len(t['players']) < 4 else '')
        ),
        color=0x3498DB)
    await ctx.channel.send(embed=summary)

    def match_line(m):
        p1 = member_name(ctx.guild, m['p1'])
        p2 = member_name(ctx.guild, m['p2'])
        if m['state'] == 'done':
            winner = f'✅ {member_name(ctx.guild, m["winner"])}' if m['winner'] is not None else '🚫 No-show'
            return f'  [{str(m["id"]).zfill(2)}] {p1} vs {p2}  →  {winner}'
        return f'  [{str(m["id"]).zfill(2)}] {p1} vs {p2}'

    all_lines = []
    for r in rounds:
        all_lines.append({'type': 'header', 'text': f'── Round {r} / {total_rounds} ──────────────────'})
        for m in [x for x in t['matches'] if x['round'] == r]:
            all_lines.append({'type': 'match', 'text': match_line(m)})

    pages, page, match_count = [], [], 0
    for line in all_lines:
        page.append(line['text'])
        if line['type'] == 'match':
            match_count += 1
            if match_count >= PAGE_SIZE:
                pages.append(page); page = []; match_count = 0
    if page: pages.append(page)

    for i, pg in enumerate(pages):
        header = f'📊 **{t["name"]}** — Bracket (Page {i+1}/{len(pages)})\n' if len(pages) > 1 else f'📊 **{t["name"]}** — Bracket\n'
        await ctx.channel.send(header + '```\n' + '\n'.join(pg) + '\n```')

@bot.command(name='games', aliases=['allgames', 'matchups'])
async def cmd_games(ctx):
    try:
        data = load_data()
        t = data['tournament']
        if not t:
            return await ctx.reply('❌ No tournament exists. Use `!create` to start one.')
        if not t['matches']:
            return await ctx.reply('❌ No bracket yet. Use `!start` or `!randombracket` to generate matches.')
        await fetch_members(ctx.guild)

        rounds       = sorted(set(m['round'] for m in t['matches']))
        total_rounds = len(rounds)
        active_round = current_round(t['matches'])

        for r in rounds:
            round_matches = [m for m in t['matches'] if m['round'] == r]
            is_active = r == active_round
            is_done   = all(m['state'] == 'done' for m in round_matches)

            if r == total_rounds:
                round_label, round_emoji, embed_color = 'Grand Final',    '🏆', 0xFFD700
            elif r == total_rounds - 1:
                round_label, round_emoji, embed_color = 'Semi-Finals',    '🥊', 0xFF6B35
            elif r == 1:
                round_label, round_emoji, embed_color = 'Round 1 — Group Stage', '⚔️', 0x5865F2
            else:
                round_label, round_emoji, embed_color = f'Round {r}',     '🔥', 0xE74C3C

            if is_active and not is_done:
                embed_color = 0x00FF7F

            CHUNK = 16
            chunks = [round_matches[i:i+CHUNK] for i in range(0, len(round_matches), CHUNK)]
            for ci, chunk in enumerate(chunks):
                page_label  = f' ({ci+1}/{len(chunks)})' if len(chunks) > 1 else ''
                status_tag  = ' — ✅ Completed' if is_done else (' — 🔴 LIVE' if is_active else ' — ⏳ Upcoming')
                lines = []
                for m in chunk:
                    p1 = member_name(ctx.guild, m['p1'])
                    p2 = member_name(ctx.guild, m['p2'])
                    if m['state'] == 'done':
                        w = member_name(ctx.guild, m['winner']) if m['winner'] is not None else 'No Contest'
                        lines.append(f'  ✅ [{str(m["id"]).zfill(2)}] {p1} vs {p2}  →  {w}')
                    else:
                        lines.append(f'  ⚔️  [{str(m["id"]).zfill(2)}] {p1} vs {p2}')
                embed = discord.Embed(
                    title=f'{round_emoji} {round_label}{page_label}{status_tag}',
                    description='```\n' + '\n'.join(lines) + '\n```',
                    color=embed_color)
                if is_active and not is_done and ci == 0:
                    pending_c = sum(1 for m in round_matches if m['state'] == 'pending' and m['p2'] is not None)
                    done_c    = sum(1 for m in round_matches if m['state'] == 'done')
                    embed.set_footer(text=f'{done_c}/{len(round_matches)} matches done • {pending_c} still pending')
                await ctx.channel.send(embed=embed)
    except Exception as err:
        await ctx.reply(f'❌ Error: {err}')

@bot.command(name='randombracket', aliases=['randomstart', 'shufflestart'])
async def cmd_randombracket(ctx):
    if not await admin_only(ctx): return
    data = load_data()
    t = data['tournament']
    if not t: return await ctx.reply('❌ No tournament. Use `!create` first.')
    if t['state'] != 'registration':
        return await ctx.reply('❌ Tournament is not in registration phase. Use `!end` then `!create` to start fresh.')
    if len(t['players']) < 2:
        return await ctx.reply('❌ Need at least 2 players. Use `!addall` to add everyone.')

    seen = set(); t['players'] = [p for p in t['players'] if not (p in seen or seen.add(p))]
    arr = t['players'][:]
    random.shuffle(arr)
    size  = bracket_size(len(arr))
    slots = arr + [None] * (size - len(arr))
    matches = resolve_byes(make_bracket(slots))
    t['matches'] = matches; t['state'] = 'in_progress'; t['current_round'] = 1
    save_data(data)
    await fetch_members(ctx.guild)

    embed = discord.Embed(
        title=f'🎲 {t["name"]} — Random Bracket Generated!',
        description=f'**{len(t["players"])}** players • Opponents randomly assigned\nShowing all Round 1 matchups below 👇',
        color=0xE74C3C)
    await ctx.channel.send(embed=embed)

    round1 = [m for m in matches if m['round'] == 1]
    CHUNK  = 16
    total  = math.ceil(len(round1) / CHUNK)
    for i in range(0, len(round1), CHUNK):
        chunk = round1[i:i+CHUNK]
        label = f' ({i//CHUNK+1}/{total})' if total > 1 else ''
        lines = []
        for m in chunk:
            p1 = member_name(ctx.guild, m['p1']); p2 = member_name(ctx.guild, m['p2'])
            if m['state'] == 'done':
                lines.append(f'[{str(m["id"]).zfill(2)}] {p1} vs {p2}  →  ✅ {member_name(ctx.guild, m["winner"])} (auto)')
            else:
                lines.append(f'[{str(m["id"]).zfill(2)}] {p1} vs {p2}')
        await ctx.channel.send(f'**⚔️ Round 1 Matchups{label}**```\n' + '\n'.join(lines) + '\n```')

@bot.command(name='matches')
async def cmd_matches(ctx):
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'in_progress':
        return await ctx.reply('No tournament in progress.')
    pend = pending_matches(t['matches'])
    if not pend: return await ctx.reply('No pending matches this round.')
    lines = []
    for m in pend:
        p1 = ctx.guild.get_member(int(m['p1']))
        p1n = p1.display_name if p1 else str(m['p1'])
        if m['p2']:
            p2 = ctx.guild.get_member(int(m['p2']))
            p2n = p2.display_name if p2 else str(m['p2'])
        else:
            p2n = 'BYE'
        lines.append(f'Match **#{m["id"]}**: **{p1n}** vs **{p2n}**')
    embed = discord.Embed(
        title=f'⚔️ Round {current_round(t["matches"])} — Pending Matches',
        description='\n'.join(lines), color=0xE67E22)
    await ctx.channel.send(embed=embed)

@bot.command(name='pick')
async def cmd_pick(ctx):
    if not await admin_only(ctx): return
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'in_progress':
        return await ctx.reply('No tournament in progress.')
    if not ctx.message.mentions:
        return await ctx.reply('❌ Mention the winner.')
    winner = ctx.guild.get_member(ctx.message.mentions[0].id)
    if not winner: return await ctx.reply('❌ Could not find that member.')
    pend = pending_matches(t['matches'])
    match = next((m for m in pend if str(m['p1']) == str(winner.id) or str(m['p2']) == str(winner.id)), None)
    if not match:
        return await ctx.reply(f'❌ **{winner.display_name}** has no pending match this round.')
    loser_id = str(match['p2']) if str(match['p1']) == str(winner.id) else str(match['p1'])
    match['winner'] = str(winner.id); match['state'] = 'done'
    if loser_id and loser_id != 'None':
        update_elo(data, winner.id, loser_id)
    await ctx.reply(f'✅ **{winner.display_name}** wins match **#{match["id"]}**!')
    await close_duel_channel(ctx.guild, match)
    await handle_round_advance(ctx.channel, ctx.guild, t, data)
    save_data(data)

@bot.command(name='report')
async def cmd_report(ctx):
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'in_progress':
        return await ctx.reply('❌ No tournament in progress.')
    if not ctx.message.mentions:
        return await ctx.reply('❌ Mention the winner: `!report @winner`')
    winner = ctx.message.mentions[0]
    uid    = str(ctx.author.id)
    pend   = pending_matches(t['matches'])
    match  = next((m for m in pend if
                   (str(m['p1']) == uid or str(m['p2']) == uid) and
                   (str(m['p1']) == str(winner.id) or str(m['p2']) == str(winner.id))), None)
    if not match:
        return await ctx.reply(f'❌ No pending match found between you and **{winner.display_name}**.')
    if any(r['matchId'] == match['id'] for r in data['pendingReports']):
        return await ctx.reply(f'⏳ A report for match **#{match["id"]}** is already waiting for admin approval.')
    loser_id = str(match['p2']) if str(match['p1']) == str(winner.id) else str(match['p1'])
    data['pendingReports'].append({
        'matchId':    match['id'],
        'winnerId':   str(winner.id),
        'loserId':    loser_id,
        'reporterId': uid,
        'channelId':  str(ctx.channel.id),
    })
    save_data(data)
    loser_member = ctx.guild.get_member(int(loser_id)) if loser_id and loser_id.isdigit() else None
    embed = discord.Embed(
        title='⏳ Result Pending Admin Approval',
        description=(
            f'**{ctx.author.display_name}** reports:\n\n'
            f'🏆 **Winner:** {winner.display_name}\n'
            f'❌ **Loser:** {loser_member.display_name if loser_member else loser_id}\n'
            f'🎮 **Match:** #{match["id"]}\n\n'
            f'An admin must confirm with `!approve {match["id"]}` or reject with `!deny {match["id"]}`.'),
        color=0xF39C12)
    embed.set_footer(text=f'Reported by {ctx.author.display_name}')
    await ctx.channel.send(embed=embed)

@bot.command(name='approve')
async def cmd_approve(ctx, match_id: str = None):
    if not await admin_only(ctx): return
    data = load_data()
    if not match_id or not match_id.isdigit():
        return await ctx.reply('❌ Usage: `!approve <matchId>`')
    mid = int(match_id)
    idx = next((i for i, r in enumerate(data['pendingReports']) if r['matchId'] == mid), -1)
    if idx == -1:
        return await ctx.reply(f'❌ No pending report found for match **#{mid}**.')
    report = data['pendingReports'][idx]
    t = data['tournament']
    if not t or t['state'] != 'in_progress':
        data['pendingReports'].pop(idx); save_data(data)
        return await ctx.reply('❌ No tournament in progress — report discarded.')
    match = next((m for m in t['matches'] if m['id'] == mid), None)
    if not match or match['state'] == 'done':
        data['pendingReports'].pop(idx); save_data(data)
        return await ctx.reply(f'❌ Match **#{mid}** is already resolved.')
    match['winner'] = report['winnerId']; match['state'] = 'done'
    if report['loserId'] and report['loserId'] != 'null':
        update_elo(data, report['winnerId'], report['loserId'])
    data['pendingReports'].pop(idx)
    win_member = ctx.guild.get_member(int(report['winnerId']))
    win_name   = win_member.display_name if win_member else report['winnerId']
    embed = discord.Embed(title='✅ Result Approved',
                          description=f'**{win_name}** wins match **#{mid}**!', color=0x2ECC71)
    embed.set_footer(text=f'Approved by {ctx.author.display_name}')
    await ctx.channel.send(embed=embed)
    await close_duel_channel(ctx.guild, match)
    await handle_round_advance(ctx.channel, ctx.guild, t, data)
    save_data(data)

@bot.command(name='deny')
async def cmd_deny(ctx, match_id: str = None):
    if not await admin_only(ctx): return
    data = load_data()
    if not match_id or not match_id.isdigit():
        return await ctx.reply('❌ Usage: `!deny <matchId>`')
    mid = int(match_id)
    idx = next((i for i, r in enumerate(data['pendingReports']) if r['matchId'] == mid), -1)
    if idx == -1:
        return await ctx.reply(f'❌ No pending report found for match **#{mid}**.')
    report = data['pendingReports'].pop(idx); save_data(data)
    win_member = ctx.guild.get_member(int(report['winnerId']))
    win_name   = win_member.display_name if win_member else report['winnerId']
    embed = discord.Embed(
        title='❌ Report Denied',
        description=f'The report for match **#{mid}** (winner: **{win_name}**) has been rejected.\nPlayers must re-submit with `!report @winner`.',
        color=0xE74C3C)
    embed.set_footer(text=f'Denied by {ctx.author.display_name}')
    await ctx.channel.send(embed=embed)

@bot.command(name='reportid')
async def cmd_reportid(ctx, match_id: str = None, user_id: str = None):
    if not await admin_only(ctx): return
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'in_progress':
        return await ctx.reply('No tournament in progress.')
    if not match_id or not user_id:
        return await ctx.reply('Usage: `!reportid <matchId> <userId>`')
    mid = int(match_id)
    match = next((m for m in t['matches'] if m['id'] == mid), None)
    if not match: return await ctx.reply(f'❌ Match #{mid} not found.')
    if match['state'] == 'done': return await ctx.reply(f'❌ Match #{mid} is already done.')
    if str(match['p1']) != user_id and str(match['p2']) != user_id:
        return await ctx.reply(f'❌ That user is not in match #{mid}.')
    loser_id = str(match['p2']) if str(match['p1']) == user_id else str(match['p1'])
    match['winner'] = user_id; match['state'] = 'done'
    if loser_id and loser_id != 'None':
        update_elo(data, user_id, loser_id)
    member = ctx.guild.get_member(int(user_id)) if user_id.isdigit() else None
    await ctx.reply(f'✅ **{member.display_name if member else user_id}** wins match **#{mid}**!')
    await close_duel_channel(ctx.guild, match)
    await handle_round_advance(ctx.channel, ctx.guild, t, data)
    save_data(data)

@bot.command(name='noshow', aliases=['kickboth', 'dqboth'])
async def cmd_noshow(ctx, *args):
    if not await admin_only(ctx): return
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'in_progress':
        return await ctx.reply('❌ No tournament in progress.')
    await fetch_members(ctx.guild)
    mentions = ctx.message.mentions

    if len(mentions) >= 2:
        a, b = mentions[0], mentions[1]
        match = next((m for m in t['matches']
                      if m['state'] == 'pending' and
                      ((str(m['p1']) == str(a.id) and str(m['p2']) == str(b.id)) or
                       (str(m['p1']) == str(b.id) and str(m['p2']) == str(a.id)))), None)
        if not match:
            return await ctx.reply(f'❌ No pending match found between **{a.display_name}** and **{b.display_name}**.')
    else:
        if not args or not args[0].isdigit():
            return await ctx.reply('❌ Usage: `!kickboth @player1 @player2` or `!kickboth <matchId>`')
        mid   = int(args[0])
        match = next((m for m in t['matches'] if m['id'] == mid), None)
        if not match: return await ctx.reply(f'❌ Match #{mid} not found.')
        if match['state'] == 'done': return await ctx.reply(f'❌ Match #{match["id"]} is already finished.')
        if match['p1'] is None or match['p2'] is None:
            return await ctx.reply(f'❌ Match #{match["id"]} has a BYE slot — use `!kick` instead.')

    if match['state'] == 'done': return await ctx.reply(f'❌ Match #{match["id"]} is already finished.')
    if match['p1'] is None or match['p2'] is None:
        return await ctx.reply(f'❌ Match #{match["id"]} has a BYE slot — use `!kick` instead.')

    NOSHOW_PENALTY = 16
    p1id, p2id = str(match['p1']), str(match['p2'])
    for uid in (p1id, p2id):
        if uid not in data['elo']:
            data['elo'][uid] = {'elo': DEFAULT_ELO, 'wins': 0, 'losses': 0, 'tournaments': 0}
        data['elo'][uid]['elo']    = max(0, data['elo'][uid]['elo'] - NOSHOW_PENALTY)
        data['elo'][uid]['losses'] += 1
    match['winner'] = None; match['state'] = 'done'
    t['players'] = [p for p in t['players'] if p not in (p1id, p2id)]
    p1m = ctx.guild.get_member(int(p1id)); p2m = ctx.guild.get_member(int(p2id))
    p1name = p1m.display_name if p1m else p1id
    p2name = p2m.display_name if p2m else p2id
    embed = discord.Embed(
        title=f'🚫 Match #{match["id"]} — Both Players Kicked',
        description=(f'**{p1name}** and **{p2name}** have both been removed from the tournament.\n'
                     f'Both lost **{NOSHOW_PENALTY} ELO** each.\n\nNeither player advances.'),
        color=0x95A5A6)
    embed.set_footer(text=f'Called by {ctx.author.display_name}')
    await ctx.channel.send(embed=embed)
    await close_duel_channel(ctx.guild, match)
    await handle_round_advance(ctx.channel, ctx.guild, t, data)
    save_data(data)

@bot.command(name='kick', aliases=['dq', 'disqualify'])
async def cmd_kick(ctx):
    if not await admin_only(ctx): return
    data = load_data()
    t = data['tournament']
    if not t or t['state'] not in ('registration', 'in_progress'):
        return await ctx.reply('❌ No active tournament.')
    if not ctx.message.mentions:
        return await ctx.reply('❌ Mention a player to remove.')
    target = ctx.guild.get_member(ctx.message.mentions[0].id)
    if not target: return await ctx.reply('❌ Could not find that member.')
    if str(target.id) not in t['players']:
        return await ctx.reply(f'❌ **{target.name}** is not in this tournament.')

    reply_line, their_match = '', None
    if t['state'] == 'registration':
        reply_line = f'🗑️ **{target.name}** has been removed from registration.'
    else:
        their_match = next((m for m in t['matches']
                            if m['state'] == 'pending' and
                            (str(m['p1']) == str(target.id) or str(m['p2']) == str(target.id))), None)
        if their_match:
            winner_id = str(their_match['p2']) if str(their_match['p1']) == str(target.id) else str(their_match['p1'])
            their_match['state'] = 'done'
            if winner_id and winner_id != 'None':
                their_match['winner'] = winner_id
                win_member = ctx.guild.get_member(int(winner_id))
                win_name   = win_member.name if win_member else winner_id
                reply_line = f'🚫 **{target.name}** removed. **{win_name}** advances via walkover.'
            else:
                their_match['winner'] = None
                reply_line = f'🚫 **{target.name}** removed (BYE slot — no opponent to advance).'
            await close_duel_channel(ctx.guild, their_match)
        else:
            reply_line = f'🚫 **{target.name}** removed from the tournament (was between rounds).'

    t['players'] = [p for p in t['players'] if p != str(target.id)]
    embed = discord.Embed(title='🚫 Player Removed', description=reply_line, color=0xE74C3C)
    embed.set_footer(text=f'Removed by {ctx.author.name}')
    await ctx.channel.send(embed=embed)
    if their_match:
        await handle_round_advance(ctx.channel, ctx.guild, t, data)
    save_data(data)

@bot.command(name='kickmatch', aliases=['kickid'])
async def cmd_kickmatch(ctx, match_id: str = None):
    if not await admin_only(ctx): return
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'in_progress':
        return await ctx.reply('❌ No tournament is currently running.')
    if not match_id or not match_id.isdigit():
        return await ctx.reply('❌ Usage: `!kickmatch <matchId>` — e.g. `!kickmatch 21`')
    mid   = int(match_id)
    match = next((m for m in t['matches'] if m['id'] == mid), None)
    if not match: return await ctx.reply(f'❌ Match #{mid} not found.')
    if match['state'] == 'done': return await ctx.reply(f'❌ Match #{mid} is already finished.')
    await fetch_members(ctx.guild)
    p1_in = ctx.guild.get_member(int(match['p1'])) is not None if match['p1'] else False
    p2_in = ctx.guild.get_member(int(match['p2'])) is not None if match['p2'] else False

    if match['p1'] and not p1_in and (match['p2'] is None or p2_in):
        ghost_id, survivor_id = match['p1'], match['p2']
    elif match['p2'] and not p2_in and (match['p1'] is None or p1_in):
        ghost_id, survivor_id = match['p2'], match['p1']
    elif not p1_in and not p2_in:
        return await ctx.reply(f'❌ Both players in match #{mid} are not in the server. Use `!kickboth {mid}` instead.')
    else:
        return await ctx.reply(f'❌ Both players in match #{mid} are still in the server — use `!kick @player` instead.')

    match['state'] = 'done'; match['winner'] = survivor_id
    await close_duel_channel(ctx.guild, match)
    if ghost_id: t['players'] = [p for p in t['players'] if str(p) != str(ghost_id)]
    survivor_m = ctx.guild.get_member(int(survivor_id)) if survivor_id else None
    survivor_n = survivor_m.display_name if survivor_m else (str(survivor_id) if survivor_id else 'nobody')
    embed = discord.Embed(
        title='🚫 Ghost Player Removed',
        description=f'Match #{mid}: ghost player removed.\n**{survivor_n}** advances via walkover.',
        color=0xE74C3C)
    embed.set_footer(text=f'Removed by {ctx.author.name}')
    await ctx.channel.send(embed=embed)
    await handle_round_advance(ctx.channel, ctx.guild, t, data)
    save_data(data)

@bot.command(name='swapin', aliases=['replaceplayer'])
async def cmd_swapin(ctx, match_id: str = None):
    if not await admin_only(ctx): return
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'in_progress':
        return await ctx.reply('❌ No tournament is currently running.')
    if not match_id or not match_id.isdigit():
        return await ctx.reply('❌ Usage: `!swapin <matchId> @player` — e.g. `!swapin 21 @sero`')
    if not ctx.message.mentions:
        return await ctx.reply('❌ Mention the player to swap in.')
    target = ctx.guild.get_member(ctx.message.mentions[0].id)
    if not target: return await ctx.reply('❌ Could not find that member.')
    mid   = int(match_id)
    match = next((m for m in t['matches'] if m['id'] == mid), None)
    if not match: return await ctx.reply(f'❌ Match #{mid} not found.')
    if match['state'] == 'done': return await ctx.reply(f'❌ Match #{mid} is already finished.')
    await fetch_members(ctx.guild)
    p1_in = ctx.guild.get_member(int(match['p1'])) is not None if match['p1'] else False
    p2_in = ctx.guild.get_member(int(match['p2'])) is not None if match['p2'] else False

    if match['p2'] is None or (not p2_in and p1_in):
        ghost_slot = 'p2'
    elif match['p1'] is None or (not p1_in and p2_in):
        ghost_slot = 'p1'
    else:
        return await ctx.reply(f'❌ No ghost slot found in match #{mid}. Both players appear to be in the server.')

    ghost_id = match[ghost_slot]
    if ghost_id: t['players'] = [p for p in t['players'] if str(p) != str(ghost_id)]

    # Remove the player's existing BYE win in same round, if any
    bye_idx = next((i for i, m in enumerate(t['matches'])
                    if m['round'] == match['round'] and m['state'] == 'done' and
                    str(m['winner']) == str(target.id) and
                    (m['p1'] is None or m['p2'] is None)), -1)
    if bye_idx != -1:
        t['matches'].pop(bye_idx)

    match[ghost_slot] = str(target.id)
    other_slot = 'p2' if ghost_slot == 'p1' else 'p1'
    other_m = ctx.guild.get_member(int(match[other_slot])) if match[other_slot] else None
    other_n = other_m.display_name if other_m else (str(match[other_slot]) if match[other_slot] else 'BYE')
    embed = discord.Embed(
        title='🔄 Player Swapped In',
        description=(f'Match #{mid} updated:\n**{target.display_name}** replaces the ghost player.\n\n'
                     f'⚔️ **{target.display_name}** vs **{other_n}**\n\n'
                     + (f'🗑️ {target.display_name}\'s BYE win was removed — they now play a real match.' if bye_idx != -1 else '')),
        color=0x2ECC71)
    embed.set_footer(text=f'Swapped in by {ctx.author.name}')
    await ctx.channel.send(embed=embed)
    save_data(data)

@bot.command(name='weaponroles', aliases=['weaponmains', 'wroles'])
async def cmd_weaponroles(ctx, sub: str = 'setup'):
    if not await admin_only(ctx): return
    sub = sub.lower()

    if sub == 'setup':
        await ctx.channel.send('⚙️ Setting up weapon roles…')
        for w in WEAPONS:
            if not discord.utils.get(ctx.guild.roles, name=w['role']):
                try:
                    await ctx.guild.create_role(name=w['role'], mentionable=False,
                                                reason='Weapon main reaction role')
                except Exception as e:
                    print(f'Could not create role "{w["role"]}": {e}')

        lines = '\n'.join(f'<:{w["emoji"]}> — **{w["name"]}**' for w in WEAPONS)
        embed = discord.Embed(
            title="⚔️ What's Your Main Weapon?",
            description=lines, color=0xE67E22)
        embed.set_footer(text='React to pick your weapon main (max 2)')
        sent_msg = await ctx.channel.send(embed=embed)

        for w in WEAPONS:
            try:
                emoji_id = int(w['emojiId'])
                emoji    = bot.get_emoji(emoji_id)
                if emoji:
                    await sent_msg.add_reaction(emoji)
            except Exception:
                pass

        data = load_data()
        data['weaponRoleMessageId'] = str(sent_msg.id)
        data['weaponRoleChannelId'] = str(sent_msg.channel.id)
        data['weaponSelections']    = {}
        save_data(data)
        try: await ctx.message.delete()
        except Exception: pass
        return

    if sub == 'clear':
        if not ctx.message.mentions:
            return await ctx.reply('❌ Mention a user: `!weaponroles clear @user`')
        target = ctx.guild.get_member(ctx.message.mentions[0].id)
        if not target: return await ctx.reply('❌ Could not find that member.')
        weapon_role_names = {w['role'] for w in WEAPONS}
        for role in target.roles:
            if role.name in weapon_role_names:
                try: await target.remove_roles(role)
                except Exception: pass
        data = load_data()
        if data.get('weaponSelections'):
            data['weaponSelections'].pop(str(target.id), None)
        save_data(data)
        return await ctx.reply(f'✅ Cleared all weapon roles from **{target.display_name}**.')

    await ctx.reply('❌ Usage: `!weaponroles setup` | `!weaponroles clear @user`')

@bot.command(name='duel', aliases=['match', 'startmatch'])
async def cmd_duel(ctx):
    if not await admin_only(ctx): return
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'in_progress':
        return await ctx.reply('❌ No tournament is currently running.')
    await fetch_members(ctx.guild)

    mentioned_member = ctx.guild.get_member(ctx.message.mentions[0].id) if ctx.message.mentions else None
    caller_id        = str(ctx.author.id)
    all_pending      = [m for m in t['matches'] if m['state'] == 'pending' and m['p1'] is not None and m['p2'] is not None]

    if mentioned_member:
        match = next((m for m in all_pending if
                      (str(m['p1']) == caller_id and str(m['p2']) == str(mentioned_member.id)) or
                      (str(m['p2']) == caller_id and str(m['p1']) == str(mentioned_member.id)) or
                      str(m['p1']) == str(mentioned_member.id) or
                      str(m['p2']) == str(mentioned_member.id)), None)
    else:
        match = next((m for m in all_pending if str(m['p1']) == caller_id or str(m['p2']) == caller_id), None)

    if not match:
        return await ctx.reply('❌ No pending match found for those players this tournament.')
    if match.get('duelChannelId'):
        existing = ctx.guild.get_channel(int(match['duelChannelId']))
        if existing:
            return await ctx.reply(f'⚔️ A duel channel already exists: {existing.mention}')
        match['duelChannelId'] = None

    p1 = ctx.guild.get_member(int(match['p1']))
    p2 = ctx.guild.get_member(int(match['p2']))
    if not p1 or not p2:
        return await ctx.reply('❌ Could not find both players in this server.')

    rounds      = sorted(set(m['round'] for m in t['matches']))
    total_r     = len(rounds)
    if match['round'] == total_r: round_label = 'Final'
    elif match['round'] == total_r - 1: round_label = 'Semi-Final'
    else: round_label = f'Round {match["round"]}'

    def safe_name(s): return ''.join(c for c in s.lower() if c.isalnum())[:20] or 'player'
    channel_name = f'match-{safe_name(p1.name)}-vs-{safe_name(p2.name)}'

    overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        p1: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        p2: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
    }
    admin_role = discord.utils.get(ctx.guild.roles, name='Tournament Admin')
    if admin_role:
        overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    try:
        duel_channel = await ctx.guild.create_text_channel(
            channel_name, overwrites=overwrites,
            reason=f'Duel channel for match #{match["id"]}')
    except Exception as err:
        return await ctx.reply(f'❌ Failed to create the channel: {err}\nMake sure the bot has **Manage Channels** permission.')

    match['duelChannelId'] = str(duel_channel.id)
    save_data(data)

    embed = discord.Embed(
        title=f'⚔️ {round_label} — Match #{match["id"]}',
        description=(f'Welcome to your private match room!\n\n'
                     f'🔵 **{p1.name}**\n🔴 **{p2.name}**\n\n'
                     f'Play your match, then ask an admin to report the result with `!pick @winner`.\n'
                     f'This channel will be **automatically deleted** once the result is submitted.'),
        color=0xE74C3C)
    embed.set_footer(text=f'{t["name"]} • {round_label} of {total_r} rounds')
    await duel_channel.send(content=f'{p1.mention} {p2.mention}', embed=embed)
    await ctx.reply(f'✅ Match room created: {duel_channel.mention}')

@bot.command(name='announce')
async def cmd_announce(ctx):
    if not await admin_only(ctx): return
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'in_progress':
        return await ctx.reply('No tournament in progress.')
    pend = pending_matches(t['matches'])
    if not pend: return await ctx.reply('No pending matches to announce.')
    lines = []
    for m in pend:
        p1m = ctx.guild.get_member(int(m['p1']))
        p2m = ctx.guild.get_member(int(m['p2'])) if m['p2'] else None
        p1  = f'<@{m["p1"]}>' if p1m else str(m['p1'])
        p2  = f'<@{m["p2"]}>' if p2m else (str(m['p2']) if m['p2'] else 'BYE')
        lines.append(f'Match **#{m["id"]}**: {p1} vs {p2}')
    await ctx.channel.send(f'📣 **Round {current_round(t["matches"])} — Fight!**\n' + '\n'.join(lines))

@bot.command(name='end')
async def cmd_end(ctx):
    if not await admin_only(ctx): return
    data = load_data()
    if not data['tournament']: return await ctx.reply('No active tournament.')
    data['tournament']['state'] = 'ended'
    save_data(data)
    await ctx.reply('🛑 Tournament has been ended.')

@bot.command(name='sub', aliases=['substitute', 'replace', 'swap'])
async def cmd_sub(ctx, *args):
    if not await admin_only(ctx): return
    data = load_data()
    t = data['tournament']
    if not t or t['state'] not in ('in_progress', 'registration'):
        return await ctx.reply('❌ No active tournament to substitute players in.')
    await fetch_members(ctx.guild)
    mentions = ctx.message.mentions

    old_member = new_member = None
    if len(mentions) >= 2:
        a, b = ctx.guild.get_member(mentions[0].id), ctx.guild.get_member(mentions[1].id)
        a_in = str(a.id) in t['players']
        b_in = str(b.id) in t['players']
        if a_in and not b_in:   old_member, new_member = a, b
        elif b_in and not a_in: old_member, new_member = b, a
        elif a_in and b_in:     return await ctx.reply('❌ Both players are already in the tournament.')
        else:                   return await ctx.reply('❌ Neither player is in the tournament.')
    elif len(mentions) == 1:
        raw_id = next((a for a in args if a.isdigit() and len(a) >= 15), None)
        if not raw_id:
            return await ctx.reply('❌ Usage: `!sub @player_in_tournament @replacement`\nOr: `!sub @player_in_tournament <userID>`')
        solo = ctx.guild.get_member(mentions[0].id)
        if str(solo.id) in t['players']:
            old_member = solo
            new_member = ctx.guild.get_member(int(raw_id))
            if not new_member:
                try: new_member = await ctx.guild.fetch_member(int(raw_id))
                except Exception: return await ctx.reply(f'❌ Could not find a server member with ID `{raw_id}`.')
        else:
            return await ctx.reply(f'❌ **{solo.name}** is not in this tournament.')
    else:
        return await ctx.reply('❌ Usage: `!sub @player_in_tournament @replacement`')

    if old_member.id == new_member.id:
        return await ctx.reply('❌ Both players are the same person.')
    if str(new_member.id) in t['players']:
        return await ctx.reply(f'❌ **{new_member.name}** is already in this tournament.')

    old_id, new_id = str(old_member.id), str(new_member.id)
    t['players'] = [new_id if p == old_id else p for p in t['players']]
    matches_affected = 0
    for m in t['matches']:
        if m['state'] != 'pending': continue
        changed = False
        if str(m['p1']) == old_id: m['p1'] = new_id; changed = True
        if str(m['p2']) == old_id: m['p2'] = new_id; changed = True
        if changed:
            matches_affected += 1
            await close_duel_channel(ctx.guild, m)
    save_data(data)
    embed = discord.Embed(
        title='🔄 Player Substituted',
        description=(f'**Out:** {old_member.name}\n**In:**  {new_member.name}\n\n'
                     f'{matches_affected} pending match{"es" if matches_affected != 1 else ""} updated.'
                     + ('\nDuel channels removed — use `!duel` to recreate them.' if matches_affected > 0 else '')),
        color=0x3498DB)
    embed.set_footer(text=f'Substituted by {ctx.author.name}')
    await ctx.channel.send(embed=embed)

@bot.command(name='rematch')
async def cmd_rematch(ctx, *, name: str = None):
    if not await admin_only(ctx): return
    data = load_data()
    if not data['tournament']:
        return await ctx.reply('No previous tournament to rematch.')
    old_players = data['tournament']['players']
    new_name    = name or f'{data["tournament"]["name"]} (Rematch)'
    data['tournament'] = {
        'name': new_name, 'state': 'registration', 'players': list(old_players),
        'matches': [], 'current_round': 1, 'winner': None,
        'created_by': str(ctx.author.id),
        'created_at': datetime.now(timezone.utc).isoformat(),
    }
    save_data(data)
    await ctx.reply(f'🔄 **{new_name}** created with the same {len(old_players)} players. Use `!start` to begin.')

@bot.command(name='top3')
async def cmd_top3(ctx):
    data = load_data()
    sorted_elo = sorted(data['elo'].items(), key=lambda x: x[1]['elo'], reverse=True)[:3]
    if not sorted_elo: return await ctx.reply('No ELO data yet.')
    await fetch_members(ctx.guild)
    buf = await build_top3_image(sorted_elo, ctx.guild)
    await ctx.channel.send(file=discord.File(io.BytesIO(buf), filename='top3.png'))

@bot.command(name='mymatch', aliases=['mynext', 'mygame'])
async def cmd_mymatch(ctx):
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'in_progress':
        return await ctx.reply('❌ No tournament is currently running.')
    if not t['matches']: return await ctx.reply('❌ No bracket generated yet.')
    await fetch_members(ctx.guild)
    uid = str(ctx.author.id)
    r   = current_round(t['matches'])

    match = next((m for m in t['matches']
                  if m['round'] == r and m['state'] == 'pending' and
                  (str(m['p1']) == uid or str(m['p2']) == uid)), None)
    if not match:
        next_r = r + 1
        match = next((m for m in t['matches']
                      if m['round'] == next_r and m['state'] == 'pending' and
                      (str(m['p1']) == uid or str(m['p2']) == uid)), None)

    if not match:
        lost = any(m['state'] == 'done' and m['winner'] is not None and
                   (str(m['p1']) == uid or str(m['p2']) == uid) and
                   str(m['winner']) != uid for m in t['matches'])
        if lost: return await ctx.reply("😔 You've been eliminated from the tournament. Better luck next time!")
        return await ctx.reply("❌ You don't have a match scheduled right now.")

    opponent  = str(match['p2']) if str(match['p1']) == uid else str(match['p1'])
    opp_name  = member_name(ctx.guild, opponent)
    round_num = match['round']
    rounds    = sorted(set(m['round'] for m in t['matches']))
    total_r   = len(rounds)
    if round_num == total_r:     round_label = '🏆 **Final**'
    elif round_num == total_r-1: round_label = '🥊 **Semi-Final**'
    else:                        round_label = f'⚔️ **Round {round_num}**'

    embed = discord.Embed(
        title='🎮 Your Next Match',
        description=(f'{round_label}\n\n**You:** {ctx.author.display_name}\n**vs**\n'
                     f'**Opponent:** {opp_name}\n\nMatch ID: `[{str(match["id"]).zfill(2)}]`'),
        color=0xE74C3C)
    embed.set_footer(text=f'Round {round_num} of {total_r} • Report result with !pick @winner')
    await ctx.reply(embed=embed)

@bot.command(name='elo')
async def cmd_elo(ctx):
    data = load_data()
    sorted_elo = sorted(data['elo'].items(), key=lambda x: x[1]['elo'], reverse=True)[:20]
    if not sorted_elo: return await ctx.reply('No ELO data yet.')
    medals = ['🥇', '🥈', '🥉'] + ['🔹'] * 17
    lines = []
    for i, (uid, s) in enumerate(sorted_elo):
        m    = ctx.guild.get_member(int(uid))
        name = m.display_name if m else f'<{uid}>'
        rank = get_rank(s['elo'])
        lines.append(f'{medals[i]} **{name}** — {s["elo"]} ELO ({rank["name"]}) | {s["wins"]}W {s["losses"]}L')
    embed = discord.Embed(title='📊 ELO Leaderboard', description='\n'.join(lines), color=0xFFD700)
    await ctx.channel.send(embed=embed)

@bot.command(name='resetelo')
async def cmd_resetelo(ctx):
    if not await admin_only(ctx): return
    data = load_data(); data['elo'] = {}; save_data(data)
    await ctx.reply('⚠️ ELO leaderboard has been reset.')

@bot.command(name='stats')
async def cmd_stats(ctx):
    data   = load_data()
    target = ctx.guild.get_member(ctx.message.mentions[0].id) if ctx.message.mentions else ctx.author
    s      = data['elo'].get(str(target.id))
    if not s: return await ctx.reply(f'**{target.display_name}** has no stats yet.')
    total   = s['wins'] + s['losses']
    winrate = round(s['wins'] / total * 100) if total else 0
    rank    = get_rank(s['elo'])
    color   = int(rank['color'].lstrip('#'), 16)
    embed   = discord.Embed(title=f'📈 {target.display_name} — Tournament Stats', color=color)
    embed.set_thumbnail(url=str(target.display_avatar.url))
    embed.add_field(name='ELO',             value=f'**{s["elo"]}**',        inline=True)
    embed.add_field(name='Rank',            value=f'**{rank["name"]}**',    inline=True)
    embed.add_field(name='Wins',            value=f'**{s["wins"]}**',       inline=True)
    embed.add_field(name='Losses',          value=f'**{s["losses"]}**',     inline=True)
    embed.add_field(name='Win Rate',        value=f'**{winrate}%**',        inline=True)
    embed.add_field(name='Tournaments Won', value=f'**{s["tournaments"]}**',inline=True)
    await ctx.channel.send(embed=embed)

@bot.command(name='history')
async def cmd_history(ctx):
    data = load_data()
    hist = data['history']
    if not hist: return await ctx.reply('No completed tournaments yet.')
    lines = []
    for i, h in enumerate(reversed(hist[-10:])):
        w     = ctx.guild.get_member(int(str(h['winner']))) if h.get('winner') else None
        wname = w.display_name if w else f'<{h["winner"]}>'
        date  = h['date'][:10]
        lines.append(f'`{i+1}.` **{h["name"]}** — 🥇 {wname} ({h["players"]} players) — {date}')
    embed = discord.Embed(title='📜 Tournament History', description='\n'.join(lines), color=0x95A5A6)
    await ctx.channel.send(embed=embed)

@bot.command(name='commands', aliases=['help_brawl', 'cmds'])
async def cmd_help(ctx):
    embed = discord.Embed(title='⚔️ Brawlhalla Tournament Bot — Commands', color=0xFFD700)
    embed.add_field(name='🏆 Tournament (🔒 Admin)',
        value='`!create [name]` — Create a tournament\n`!start` — Start with ELO seeding\n`!start random` — Random draw\n`!end` — Force end tournament\n`!rematch [name]` — New tournament with same players\n`!announce` — Ping players for pending matches\n`!remind` — Remind players who haven\'t played yet',
        inline=False)
    embed.add_field(name='📋 Tournament (Public)',
        value='`!seedings` — Preview ELO seed order\n`!bracket` — Show bracket\n`!matches` — Pending matches this round',
        inline=False)
    embed.add_field(name='👥 Players',
        value='`!register` — Join the tournament\n`!unregister` — Leave before start\n`!players` — List registered players\n`!addjoin @player` 🔒 — Force-add a player\n`!joinbyid <userId>` 🔒 — Add by Discord ID\n`!removejoin @player` 🔒 — Remove a player',
        inline=False)
    embed.add_field(name='🎮 Matches 🔒',
        value='`!pick @winner` 🔒 — Admin direct result\n`!report @winner` — Submit result (requires admin approval)\n`!approve <matchId>` 🔒 — Approve a pending report\n`!deny <matchId>` 🔒 — Reject a pending report\n`!reportid <id> <userId>` 🔒 — Submit by user ID\n`!duel @p1 @p2` 🔒 — Open private duel channel\n`!kick @player` 🔒 — Remove a player\n`!kickmatch <id>` 🔒 — Remove ghost from match by ID\n`!swapin <id> @player` 🔒 — Swap player into match',
        inline=False)
    embed.add_field(name='📊 Stats',
        value='`!top3` — Podium of top 3 players\n`!elo` — ELO leaderboard\n`!stats [@player]` — Player stats\n`!mvp` — MVP of current tournament\n`!history` — Past tournaments\n`!resetelo` 🔒 — Wipe the leaderboard',
        inline=False)
    embed.add_field(name='⚔️ Weapon Mains',
        value='`!weaponroles setup` 🔒 — Post the weapon-pick embed (creates roles automatically)\n`!weaponroles clear @player` 🔒 — Remove all weapon roles from a player\nReact to the embed to pick up to **2** weapon mains.',
        inline=False)
    embed.add_field(name='🎲 Fun', value='`!coinflip` — Flip a coin to decide stage-pick order', inline=False)
    embed.set_footer(text='🔒 = Admin only (Administrator permission or "Tournament Admin" role)')
    await ctx.channel.send(embed=embed)

@bot.command(name='remind')
async def cmd_remind(ctx):
    if not await admin_only(ctx): return
    data = load_data()
    t = data['tournament']
    if not t or t['state'] != 'in_progress':
        return await ctx.reply('❌ No tournament is currently in progress.')
    await fetch_members(ctx.guild)
    pend      = pending_matches(t['matches'])
    round_num = current_round(t['matches'])
    rounds    = sorted(set(m['round'] for m in t['matches']))
    total_r   = len(rounds)
    round_pending = [m for m in pend if m['p2'] is not None]
    if not round_pending:
        return await ctx.reply('✅ No pending matches this round — everyone has played!')

    invite_url = None
    try:
        invite = await ctx.channel.create_invite(max_age=86400, max_uses=0, unique=False,
                                                  reason='Tournament reminder')
        invite_url = invite.url
    except Exception:
        pass

    channel_url = f'https://discord.com/channels/{ctx.guild.id}/{ctx.channel.id}'
    pings, dm_results = [], []

    for m in round_pending:
        p1m = ctx.guild.get_member(int(m['p1']))
        p2m = ctx.guild.get_member(int(m['p2']))
        p1s = f'<@{m["p1"]}>' if p1m else f'`{m["p1"]}`'
        p2s = f'<@{m["p2"]}>' if p2m else f'`{m["p2"]}`'
        pings.append(f'{p1s} vs {p2s} — Match **#{m["id"]}**')

        for player, opponent in [(p1m, p2m), (p2m, p1m)]:
            if not player: continue
            opp_name = opponent.name if opponent else f'User#{str(m["p1"])[-4:] if player == p2m else str(m["p2"])[-4:]}'
            link_lines = [f'🔗 [Jump to tournament channel]({channel_url})']
            if invite_url: link_lines.append(f'📨 [Server invite link]({invite_url})')
            dm_embed = discord.Embed(
                title='⏰ Reminder — You have a match to play!',
                description=(f'**Tournament:** {t["name"]}\n**Round:** {round_num} of {total_r}\n'
                             f'**Match ID:** `[{str(m["id"]).zfill(2)}]`\n\n'
                             f'🆚 Your opponent is **{opp_name}**\n\n'
                             f'Contact them and play your match, then have an admin report the result with `!pick @winner`.\n\n'
                             + '\n'.join(link_lines)),
                color=0xFF6B35)
            dm_embed.set_footer(text=f'{t["name"]} • Round {round_num} of {total_r}')
            try:
                await player.send(embed=dm_embed)
                dm_results.append(f'✅ DM sent → **{player.name}**')
            except Exception:
                dm_results.append(f'⚠️ Couldn\'t DM **{player.name}** (DMs closed)')

    channel_embed = discord.Embed(
        title='⏰ Match Reminder — Play Your Match!',
        description='The following players still have a pending match this round:\n\n' + '\n'.join(pings),
        color=0xFF6B35)
    channel_embed.set_footer(text='A DM has been sent to each player with their opponent info')
    await ctx.channel.send(embed=channel_embed)

    summary = discord.Embed(
        title='📬 DM Delivery Report',
        description='\n'.join(dm_results),
        color=0xE67E22 if any(r.startswith('⚠️') for r in dm_results) else 0x2ECC71)
    await ctx.reply(embed=summary)

@bot.command(name='mvp')
async def cmd_mvp(ctx):
    data = load_data()
    t = data['tournament']
    if not t: return await ctx.reply('❌ No tournament data found.')
    completed = [m for m in t['matches'] if m.get('winner')]
    if not completed: return await ctx.reply('❌ No completed matches yet this tournament.')
    wins_map = {}
    for m in completed:
        wins_map[m['winner']] = wins_map.get(m['winner'], 0) + 1
    sorted_w = sorted(wins_map.items(), key=lambda x: x[1], reverse=True)
    top_id, top_wins = sorted_w[0]
    member = ctx.guild.get_member(int(top_id))
    lines = []
    for i, (uid, w) in enumerate(sorted_w[:5]):
        m    = ctx.guild.get_member(int(uid))
        n    = m.display_name if m else f'`{uid}`'
        medal = ['🥇','🥈','🥉'][i] if i < 3 else f'{i+1}.'
        lines.append(f'{medal} **{n}** — {w} win{"s" if w != 1 else ""}')
    embed = discord.Embed(title=f'🌟 Tournament MVP — {t["name"]}', description='\n'.join(lines), color=0xFFD700)
    embed.set_footer(text=f'{top_wins} win{"s" if top_wins != 1 else ""} so far')
    if member:
        embed.set_thumbnail(url=str(member.display_avatar.replace(size=64).url))
    await ctx.channel.send(embed=embed)

@bot.command(name='coinflip', aliases=['flip', 'coin'])
async def cmd_coinflip(ctx):
    result = '🌕 Heads' if random.random() < 0.5 else '🌑 Tails'
    embed  = discord.Embed(title='🪙 Coin Flip!', color=0xF1C40F)
    embed.set_footer(text='Stage picker goes first — good luck!')
    if ctx.message.mentions:
        winner = random.choice([ctx.author, ctx.message.mentions[0]])
        embed.description = f'**{result}**\n\n<@{winner.id}> wins the flip and picks the stage first!'
    else:
        embed.description = f'**{result}**'
    await ctx.channel.send(embed=embed)

@bot.command(name='setlog')
async def cmd_setlog(ctx):
    global _log_channel_id
    if not await admin_only(ctx): return
    data = load_data()
    data['logChannelId'] = str(ctx.channel.id)
    _log_channel_id = str(ctx.channel.id)
    save_data(data)
    embed = discord.Embed(
        title='📋 Log Channel Set',
        description=f'All bot activity will now be logged in <#{ctx.channel.id}>.\n\nUse `!unsetlog` to disable logging.',
        color=0x2ECC71, timestamp=datetime.now(timezone.utc))
    await ctx.channel.send(embed=embed)
    await bot_log('📋 Log Channel Configured',
                  f'Log channel set to <#{ctx.channel.id}> by **{ctx.author.display_name}**.', 0x2ECC71)

@bot.command(name='unsetlog')
async def cmd_unsetlog(ctx):
    global _log_channel_id
    if not await admin_only(ctx): return
    await bot_log('🔕 Logging Disabled',
                  f'Log channel removed by **{ctx.author.display_name}**. No further logs will be sent.', 0xE67E22)
    data = load_data()
    data.pop('logChannelId', None)
    _log_channel_id = None
    save_data(data)
    await ctx.reply('🔕 Bot logging disabled.')

# ════════════════════════════════════════════════════════════════════════════
# ── Events ──────────────────────────────────────────────────────────────────
# ════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    global _log_channel_id
    print(f'{bot.user} is online!')
    await bot.change_presence(activity=discord.Streaming(
        name='Brawlhalla for Kurd', url='https://www.twitch.tv/discord'))

    data = load_data()
    if data.get('logChannelId'):
        _log_channel_id = data['logChannelId']

    guild = bot.get_guild(GUILD_ID)
    if guild:
        try:
            await guild.chunk()
            data2 = load_data()
            if 'profiles' not in data2: data2['profiles'] = {}
            for member in guild.members:
                data2['profiles'][str(member.id)] = {
                    'name':   member.display_name,
                    'avatar': str(member.display_avatar.replace(size=128, format='png').url),
                }
            save_data(data2)
            print(f'Saved {len(guild.members)} player profiles')
        except Exception as e:
            print(f'Profile fetch error: {e}')

    await bot_log('🟢 Bot Online',
                  f'**{bot.user}** has connected and is ready.\n\nUse `!setlog` in any channel to direct logs there.',
                  0x2ECC71)

@bot.event
async def on_message(message):
    if message.author.bot: return
    if not message.guild: return

    if message.content.startswith(PREFIX):
        ctx = await bot.get_context(message)
        if ctx.valid:
            cmd_name = ctx.invoked_with
            if cmd_name and cmd_name.lower() != 'setlog':
                preview = message.content[:120] + ('…' if len(message.content) > 120 else '')
                asyncio.create_task(bot_log(
                    f'⌨️ `!{cmd_name}`',
                    f'**User:** {message.author.display_name} (`{message.author.id}`)\n'
                    f'**Channel:** <#{message.channel.id}>\n**Full command:** `{preview}`',
                    0x3498DB))
            try:
                await bot.invoke(ctx)
            except Exception as err:
                print(err)
                asyncio.create_task(bot_log(
                    '❌ Command Error',
                    f'**Command:** `!{cmd_name}`\n**User:** {message.author.display_name}\n**Error:** {err}',
                    0xE74C3C))
                await message.reply(f'❌ Error: {err}')
            return

    # Log non-command messages
    if not _log_channel_id: return
    if str(message.channel.id) == str(_log_channel_id): return
    content     = (message.content[:300] + '…' if len(message.content) > 300 else message.content) or '*(no text)*'
    attachments = f'\n📎 {message.attachments.__len__()} attachment(s)' if message.attachments else ''
    await bot_log(
        f'💬 Message in #{message.channel.name}',
        f'**{message.author.display_name}** (`{message.author.id}`):\n{content}{attachments}',
        0x778CA3)

@bot.event
async def on_message_edit(before, after):
    if not _log_channel_id: return
    if not after.author or after.author.bot: return
    if str(after.channel.id) == str(_log_channel_id): return
    if not after.guild: return
    if before.content == after.content: return
    b = (before.content or '*(unknown)*')[:200]
    a = (after.content  or '*(empty)*')[:200]
    await bot_log(
        f'✏️ Message Edited in #{after.channel.name}',
        f'**{after.author.display_name}** (`{after.author.id}`)\n\n**Before:** {b}\n**After:** {a}',
        0xF39C12)

@bot.event
async def on_message_delete(message):
    if not _log_channel_id: return
    if message.author and message.author.bot: return
    if str(message.channel.id) == str(_log_channel_id): return
    if not message.guild: return
    content = (message.content or '*(no text / not cached)*')[:300]
    who     = message.author.display_name if message.author else '*(unknown)*'
    uid     = str(message.author.id) if message.author else '?'
    await bot_log(
        f'🗑️ Message Deleted in #{message.channel.name}',
        f'**{who}** (`{uid}`):\n{content}', 0xE74C3C)

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id: return
    data = load_data()
    if not data.get('weaponRoleMessageId'): return
    if str(payload.message_id) != str(data['weaponRoleMessageId']): return

    emoji_id = str(payload.emoji.id) if payload.emoji.id else None
    weapon   = WEAPON_EMOJI_MAP.get(emoji_id)
    if not weapon: return

    guild  = bot.get_guild(payload.guild_id)
    if not guild: return
    member = guild.get_member(payload.user_id)
    if not member: member = await guild.fetch_member(payload.user_id)
    if not member: return

    role = await get_or_create_weapon_role(guild, weapon['role'])

    if 'weaponSelections' not in data: data['weaponSelections'] = {}
    selections = data['weaponSelections'].get(str(payload.user_id), [])

    if weapon['name'] in selections: return

    if len(selections) >= MAX_WEAPON_ROLES:
        # Remove the reaction silently
        channel = guild.get_channel(payload.channel_id)
        if channel:
            try:
                msg = await channel.fetch_message(payload.message_id)
                await msg.remove_reaction(payload.emoji, member)
            except Exception:
                pass
        return

    selections.append(weapon['name'])
    data['weaponSelections'][str(payload.user_id)] = selections
    save_data(data)
    await member.add_roles(role)

@bot.event
async def on_raw_reaction_remove(payload):
    if payload.user_id == bot.user.id: return
    data = load_data()
    if not data.get('weaponRoleMessageId'): return
    if str(payload.message_id) != str(data['weaponRoleMessageId']): return

    emoji_id = str(payload.emoji.id) if payload.emoji.id else None
    weapon   = WEAPON_EMOJI_MAP.get(emoji_id)
    if not weapon: return

    guild  = bot.get_guild(payload.guild_id)
    if not guild: return
    member = guild.get_member(payload.user_id)
    if not member:
        try: member = await guild.fetch_member(payload.user_id)
        except Exception: return

    role = discord.utils.get(guild.roles, name=weapon['role'])
    if role:
        try: await member.remove_roles(role)
        except Exception: pass

    if data.get('weaponSelections') and str(payload.user_id) in data['weaponSelections']:
        data['weaponSelections'][str(payload.user_id)] = [
            n for n in data['weaponSelections'][str(payload.user_id)] if n != weapon['name']
        ]
    save_data(data)

@bot.event
async def on_member_join(member):
    await bot_log(
        '📥 Member Joined',
        f'**{member.display_name}** (`{member.id}`) joined the server.\n'
        f'Account created: <t:{int(member.created_at.timestamp())}:R>',
        0x2ECC71)

@bot.event
async def on_member_remove(member):
    await bot_log(
        '📤 Member Left',
        f'**{member.display_name}** (`{member.id}`) left (or was kicked from) the server.',
        0xE67E22)

# ════════════════════════════════════════════════════════════════════════════
# ── Web server (aiohttp) ────────────────────────────────────────────────────
# ════════════════════════════════════════════════════════════════════════════

PORT         = int(os.environ.get('BOT_PORT', '8082'))
HEALTH_PORT  = 8099
PUBLIC_DIR   = Path(__file__).parent / 'public'

async def handle_ping(request):
    return web.Response(text='Bot is alive!')

async def handle_leaderboard(request):
    data  = load_data()
    guild = bot.get_guild(GUILD_ID)
    entries = []
    for i, (uid, s) in enumerate(sorted(data['elo'].items(), key=lambda x: x[1]['elo'], reverse=True)):
        member = guild.get_member(int(uid)) if guild else None
        total  = s['wins'] + s['losses']
        entries.append({
            'rank':        i + 1,
            'id':          uid,
            'name':        member.display_name if member else f'Player {uid[-4:]}',
            'avatar':      str(member.display_avatar.replace(size=64, format='png').url) if member else None,
            'elo':         s['elo'],
            'wins':        s['wins'],
            'losses':      s['losses'],
            'winrate':     round(s['wins'] / total * 100) if total else 0,
            'tournaments': s.get('tournaments', 0),
            'rankName':    get_rank(s['elo'])['name'],
            'rankColor':   get_rank(s['elo'])['color'],
        })
    return web.json_response(entries)

async def handle_tournament(request):
    data  = load_data()
    guild = bot.get_guild(GUILD_ID)
    t     = data.get('tournament')
    if not t:
        return web.json_response(None)

    def mname(uid):
        if not uid: return 'BYE'
        m = guild.get_member(int(uid)) if guild else None
        return m.display_name if m else f'Player {str(uid)[-4:]}'

    matches = [{**m, 'p1Name': mname(m['p1']), 'p2Name': mname(m['p2']),
                'winnerName': mname(m['winner']) if m['winner'] else None}
               for m in (t.get('matches') or [])]
    players = [{'id': pid, 'name': mname(pid),
                'elo': data['elo'].get(str(pid), {}).get('elo', DEFAULT_ELO)}
               for pid in (t.get('players') or [])]
    return web.json_response({**t, 'matches': matches, 'players': players})

async def handle_history(request):
    data  = load_data()
    guild = bot.get_guild(GUILD_ID)
    history = []
    for h in reversed(data.get('history') or []):
        w = guild.get_member(int(str(h['winner']))) if guild and h.get('winner') else None
        history.append({
            **h,
            'winnerName':   w.display_name if w else f'Player {str(h["winner"])[-4:]}',
            'winnerAvatar': str(w.display_avatar.replace(size=64, format='png').url) if w else None,
        })
    return web.json_response(history)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/ping', handle_ping)
    app.router.add_get('/api/leaderboard', handle_leaderboard)
    app.router.add_get('/api/tournament',  handle_tournament)
    app.router.add_get('/api/history',     handle_history)
    if PUBLIC_DIR.exists():
        app.router.add_static('/', PUBLIC_DIR, show_index=True)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f'Web dashboard on port {PORT}')

async def start_health_server():
    async def health(request):
        return web.Response(text='ok')
    app = web.Application()
    app.router.add_get('/', health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', HEALTH_PORT)
    await site.start()
    print(f'Health check on port {HEALTH_PORT}')

# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    TOKEN = os.environ.get('DISCORD_TOKEN')
    await start_health_server()
    await start_web_server()
    if not TOKEN:
        print('WARNING: DISCORD_TOKEN not set. Web dashboard is running but bot is offline.')
        await asyncio.Event().wait()
    else:
        async with bot:
            await bot.start(TOKEN)

if __name__ == '__main__':
    asyncio.run(main())
