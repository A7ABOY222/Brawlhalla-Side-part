const {
  Client,
  GatewayIntentBits,
  Partials,
  EmbedBuilder,
  ActivityType,
  AttachmentBuilder,
  ChannelType,
  PermissionsBitField,
} = require('discord.js');
const express = require('express');
const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');
const { createCanvas, loadImage } = require('@napi-rs/canvas');

// ── Config ─────────────────────────────────────────────────────────────────

const GUILD_ID   = '1514385970684755980';
const CHANNEL_ID = '1514388213547012197';
const DATA_FILE  = path.join(__dirname, 'tournament_data.json');
const PREFIX     = '!';
const DEFAULT_ELO = 1000;
const K = 32;

// ── Brawlhalla Weapon Roles ─────────────────────────────────────────────────
// emoji  = string passed to message.react()  → 'name:id' for custom emojis
// emojiId = reaction.emoji.id from Discord   → used as map key (names can repeat)
const WEAPONS = [
  { name: 'Sword',        emoji: 'emoji_11:1524877970680971406',  emojiId: '1524877970680971406', role: 'Main: Sword'        },
  { name: 'Hammer',       emoji: 'emoji_20:1524878111798460560',  emojiId: '1524878111798460560', role: 'Main: Hammer'       },
  { name: 'Spear',        emoji: 'emoji_12:1524877985897779445',  emojiId: '1524877985897779445', role: 'Main: Spear'        },
  { name: 'Katar',        emoji: 'emoji_16:1524878047378145411',  emojiId: '1524878047378145411', role: 'Main: Katar'        },
  { name: 'Bow',          emoji: 'emoji_23:1524878222259519679',  emojiId: '1524878222259519679', role: 'Main: Bow'          },
  { name: 'Axe',          emoji: 'emoji_26:1524878272477794324',  emojiId: '1524878272477794324', role: 'Main: Axe'          },
  { name: 'Scythe',       emoji: 'emoji_13:1524878002393972908',  emojiId: '1524878002393972908', role: 'Main: Scythe'       },
  { name: 'Rocket Lance', emoji: 'emoji_14:1524878016822640660',  emojiId: '1524878016822640660', role: 'Main: Rocket Lance' },
  { name: 'Orb',          emoji: 'emoji_16:1524878032446161016',  emojiId: '1524878032446161016', role: 'Main: Orb'          },
  { name: 'Blasters',     emoji: 'emoji_23:1524878237442773053',  emojiId: '1524878237442773053', role: 'Main: Blasters'     },
  { name: 'Gauntlets',    emoji: 'emoji_11:1524877956684579036',  emojiId: '1524877956684579036', role: 'Main: Gauntlets'    },
  { name: 'Cannon',       emoji: 'emoji_22:1524878204442116116',  emojiId: '1524878204442116116', role: 'Main: Cannon'       },
  { name: 'Greatsword',   emoji: 'emoji_19:1524878082664694002',  emojiId: '1524878082664694002', role: 'Main: Greatsword'   },
  { name: 'Battle Boots', emoji: 'emoji_24:1524878253616267436',  emojiId: '1524878253616267436', role: 'Main: Battle Boots' },
  { name: 'Chakram',      emoji: 'emoji_21:1524878128357445752',  emojiId: '1524878128357445752', role: 'Main: Chakram'      },
];
// Key by emoji ID — custom emoji names can repeat across different emojis
const WEAPON_EMOJI_MAP = new Map(WEAPONS.map(w => [w.emojiId, w]));
const MAX_WEAPON_ROLES = 2;

// ── Log channel ─────────────────────────────────────────────────────────────
let _logChannelId = null;

async function botLog(title, description, color = 0x5865F2, fields = []) {
  if (!_logChannelId) return;
  try {
    const guild = client.guilds.cache.get(GUILD_ID);
    if (!guild) return;
    const ch = guild.channels.cache.get(_logChannelId);
    if (!ch || !ch.isTextBased()) return;
    const embed = new EmbedBuilder()
      .setTitle(title)
      .setDescription(description || '\u200b')
      .setColor(color)
      .setTimestamp();
    if (fields.length) embed.addFields(fields);
    await ch.send({ embeds: [embed] });
  } catch { /* log channel unavailable */ }
}

// ── Persistence ────────────────────────────────────────────────────────────

function loadData() {
  if (fs.existsSync(DATA_FILE)) {
    const d = JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
    if (!d.pendingReports) d.pendingReports = [];
    return d;
  }
  return { tournament: null, elo: {}, history: [], pendingReports: [] };
}


function saveData(data) {
  fs.writeFileSync(DATA_FILE, JSON.stringify(data, null, 2));
}

// ── ELO helpers ────────────────────────────────────────────────────────────

function expected(a, b) {
  return 1 / (1 + Math.pow(10, (b - a) / 400));
}

function updateElo(data, winnerId, loserId, kOverride = null) {
  const elo = data.elo;
  const wid = String(winnerId);
  const lid = String(loserId);
  if (!elo[wid]) elo[wid] = { elo: DEFAULT_ELO, wins: 0, losses: 0, tournaments: 0 };
  if (!elo[lid]) elo[lid] = { elo: DEFAULT_ELO, wins: 0, losses: 0, tournaments: 0 };
  const k  = kOverride !== null ? kOverride : K;
  const ea = expected(elo[wid].elo, elo[lid].elo);
  const eb = expected(elo[lid].elo, elo[wid].elo);
  elo[wid].elo    = Math.round(elo[wid].elo + k * (1 - ea));
  elo[lid].elo    = Math.round(elo[lid].elo + k * (0 - eb));
  elo[wid].wins  += 1;
  elo[lid].losses += 1;
}

// ── Rank system ────────────────────────────────────────────────────────────

function getRank(eloVal) {
  if (eloVal >= 2400) return { name: 'Legend',   color: '#FF6B35', k: 16 };
  if (eloVal >= 2000) return { name: 'Diamond',  color: '#B9F2FF', k: 20 };
  if (eloVal >= 1600) return { name: 'Platinum', color: '#00B4D8', k: 24 };
  if (eloVal >= 1300) return { name: 'Gold',     color: '#FFD700', k: 28 };
  if (eloVal >= 1100) return { name: 'Silver',   color: '#C0C0C0', k: 30 };
  if (eloVal >= 900)  return { name: 'Bronze',   color: '#CD7F32', k: 32 };
  return                     { name: 'Tin',      color: '#808080', k: 32 };
}

// ── Bracket helpers ────────────────────────────────────────────────────────

function bracketSize(n) {
  if (n <= 1) return 2;
  return Math.pow(2, Math.ceil(Math.log2(n)));
}

function seededSlotIndices(size) {
  let slots = [0, 1];
  let current = 2;
  while (current < size) {
    slots = slots.flatMap(s => [s, current * 2 - 1 - s]);
    current *= 2;
  }
  return slots;
}

function eloSeededSlots(players, data) {
  const ranked = [...players].sort((a, b) => {
    const ea = (data.elo[String(a)] || {}).elo || DEFAULT_ELO;
    const eb = (data.elo[String(b)] || {}).elo || DEFAULT_ELO;
    return eb - ea;
  });
  const size    = bracketSize(ranked.length);
  const indices = seededSlotIndices(size);
  const slots   = new Array(size).fill(null);
  indices.forEach((seedI, slotI) => {
    if (seedI < ranked.length) slots[slotI] = ranked[seedI];
  });
  return slots;
}

function makeBracket(slots) {
  const matches = [];
  let matchId = 1;
  for (let i = 0; i < slots.length; i += 2) {
    const p1 = slots[i], p2 = slots[i + 1];
    if (p1 === null && p2 === null) continue;
    if (p1 !== null && p1 === p2) continue;
    matches.push({ id: matchId++, round: 1, p1, p2, winner: null, state: 'pending' });
  }
  return matches;
}

function resolveByes(matches) {
  for (const m of matches) {
    if (m.state !== 'pending') continue;
    if (m.p1 === null && m.p2 !== null) { m.winner = m.p2; m.state = 'done'; }
    else if (m.p2 === null && m.p1 !== null) { m.winner = m.p1; m.state = 'done'; }
  }
  return matches;
}

function advanceBracket(matches) {
  const rounds    = [...new Set(matches.map(m => m.round))].sort((a, b) => a - b);
  const lastRound = rounds[rounds.length - 1];
  const last      = matches.filter(m => m.round === lastRound);
  const seen      = new Set();
  const winners   = [];
  for (const m of last) {
    if (m.winner !== null && !seen.has(m.winner)) {
      seen.add(m.winner);
      winners.push(m.winner);
    }
  }
  if (winners.length <= 1) return matches;
  let mid       = Math.max(...matches.map(m => m.id)) + 1;
  const nextRound = lastRound + 1;
  for (let i = 0; i < winners.length; i += 2) {
    const p1 = winners[i];
    let p2   = winners[i + 1] !== undefined ? winners[i + 1] : null;
    if (p1 === p2) p2 = null;
    matches.push({ id: mid++, round: nextRound, p1, p2, winner: null, state: 'pending' });
  }
  return resolveByes(matches);
}

function roundComplete(matches, roundNum) {
  return matches.filter(m => m.round === roundNum).every(m => m.state === 'done');
}

function currentRound(matches) {
  const rounds = [...new Set(matches.map(m => m.round))].sort((a, b) => a - b);
  for (const r of rounds) {
    if (!roundComplete(matches, r)) return r;
  }
  return rounds[rounds.length - 1];
}

function pendingMatches(matches) {
  const r = currentRound(matches);
  return matches.filter(m => m.round === r && m.state === 'pending');
}

function renderBracket(matches, guild) {
  function name(uid) {
    if (uid === null) return 'BYE';
    const m = guild.members.cache.get(String(uid));
    return m ? m.displayName : `<${uid}>`;
  }
  const lines = ['```'];
  const rounds = [...new Set(matches.map(m => m.round))].sort((a, b) => a - b);
  for (const r of rounds) {
    const roundMatches = matches.filter(m => m.round === r);
    if (!roundMatches.length) continue;
    lines.push(`── Round ${r} ──────────────────`);
    for (const m of roundMatches) {
      const p1 = name(m.p1), p2 = name(m.p2);
      if (m.state === 'done') {
        const winner = m.winner !== null ? `✅ ${name(m.winner)}` : '🚫 No-show';
        lines.push(`  [${String(m.id).padStart(2, '0')}] ${p1} vs ${p2}  →  ${winner}`);
      } else {
        lines.push(`  [${String(m.id).padStart(2, '0')}] ${p1} vs ${p2}`);
      }
    }
  }
  lines.push('```');
  return lines.join('\n');
}

// ── Avatar fetcher ─────────────────────────────────────────────────────────

function fetchBuffer(url) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : http;
    mod.get(url, (res) => {
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => resolve(Buffer.concat(chunks)));
      res.on('error', reject);
    }).on('error', reject);
  });
}

async function fetchAvatar(url, size) {
  const fallback = createCanvas(size, size);
  const fctx     = fallback.getContext('2d');
  fctx.fillStyle  = '#3c3c50';
  fctx.beginPath();
  fctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
  fctx.fill();
  if (!url) return fallback;
  try {
    const buf = await fetchBuffer(url);
    const img = await loadImage(buf);
    const c   = createCanvas(size, size);
    const ctx = c.getContext('2d');
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
    ctx.clip();
    ctx.drawImage(img, 0, 0, size, size);
    return c;
  } catch {
    return fallback;
  }
}

// ── Top 3 image ────────────────────────────────────────────────────────────

async function buildTop3Image(top3, guild) {
  const W = 1020, H = 560;
  const canvas = createCanvas(W, H);
  const ctx    = canvas.getContext('2d');

  // ── Background ─────────────────────────────────────────────────────────
  const bgGrad = ctx.createLinearGradient(0, 0, W, H);
  bgGrad.addColorStop(0,   '#0b0920');
  bgGrad.addColorStop(0.5, '#12103a');
  bgGrad.addColorStop(1,   '#090717');
  ctx.fillStyle = bgGrad;
  ctx.fillRect(0, 0, W, H);

  // Subtle grid lines
  ctx.strokeStyle = 'rgba(255,255,255,0.03)';
  ctx.lineWidth = 1;
  for (let gx = 0; gx < W; gx += 60) { ctx.beginPath(); ctx.moveTo(gx,0); ctx.lineTo(gx,H); ctx.stroke(); }
  for (let gy = 0; gy < H; gy += 60) { ctx.beginPath(); ctx.moveTo(0,gy); ctx.lineTo(W,gy); ctx.stroke(); }

  // Star particles
  const starData = [[45,30,1.5],[150,70,1],[800,25,1.5],[900,80,1],[60,450,1],[350,510,1.5],
                    [750,490,1],[970,380,1],[500,530,1],[250,400,1],[700,100,1.5],[870,300,1],
                    [120,300,2],[600,480,2],[950,200,2],[400,60,1.5],[820,520,1]];
  for (const [sx, sy, sr] of starData) {
    ctx.beginPath();
    ctx.arc(sx, sy, sr, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(255,255,255,${sr > 1.2 ? 0.18 : 0.1})`;
    ctx.fill();
  }

  // ── Title ───────────────────────────────────────────────────────────────
  const titleGrad = ctx.createLinearGradient(250, 0, 770, 0);
  titleGrad.addColorStop(0,   '#ffd228');
  titleGrad.addColorStop(0.5, '#ffffff');
  titleGrad.addColorStop(1,   '#ffd228');
  ctx.save();
  ctx.font = 'bold 30px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillStyle = titleGrad;
  ctx.shadowBlur = 12;
  ctx.shadowColor = '#ffd228';
  ctx.fillText('🏆   TOP 3  ·  ELO LEADERBOARD', W / 2, 48);
  ctx.restore();

  // Title divider
  const divGrad = ctx.createLinearGradient(150, 0, 870, 0);
  divGrad.addColorStop(0,   'transparent');
  divGrad.addColorStop(0.3, 'rgba(255,210,40,0.5)');
  divGrad.addColorStop(0.7, 'rgba(255,210,40,0.5)');
  divGrad.addColorStop(1,   'transparent');
  ctx.strokeStyle = divGrad;
  ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(150, 60); ctx.lineTo(870, 60); ctx.stroke();

  // ── Cards: 2nd LEFT · 1st CENTER · 3rd RIGHT ────────────────────────────
  const GOLD   = '#ffd228', SILVER = '#b8cfe8', BRONZE = '#d98c45';

  const columns = [
    { rankIndex:1, x:20,  y:145, w:295, h:375, avSz:88,  color:SILVER, label:'2' },
    { rankIndex:0, x:355, y:78,  w:315, h:450, avSz:106, color:GOLD,   label:'1' },
    { rankIndex:2, x:700, y:185, w:295, h:335, avSz:80,  color:BRONZE, label:'3' },
  ];

  for (const col of columns) {
    if (col.rankIndex >= top3.length) continue;
    const [uidStr, stats] = top3[col.rankIndex];
    const member   = guild.members.cache.get(uidStr);
    const dispName = member ? member.displayName : `Player ${uidStr.slice(-4)}`;
    const name     = dispName.length > 16 ? dispName.slice(0, 15) + '…' : dispName;
    const { wins, losses, elo } = stats;
    const total = wins + losses;
    const wr    = total ? Math.round(wins / total * 100) : 0;
    const { x, y, w, h, avSz, color, label } = col;
    const cx = x + w / 2;

    // ── Card shadow
    ctx.save();
    ctx.shadowBlur  = 30;
    ctx.shadowColor = color;
    ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 4;
    ctx.fillStyle = 'rgba(0,0,0,0.01)';
    roundRect(ctx, x, y, w, h, 20); ctx.fill();
    ctx.restore();

    // ── Card body gradient
    const cardGrad = ctx.createLinearGradient(x, y, x, y + h);
    cardGrad.addColorStop(0, '#1f1c3e');
    cardGrad.addColorStop(1, '#11102a');
    ctx.fillStyle = cardGrad;
    roundRect(ctx, x, y, w, h, 20); ctx.fill();

    // ── Card border (glowing)
    ctx.save();
    ctx.shadowBlur  = 18; ctx.shadowColor = color;
    ctx.strokeStyle = color; ctx.lineWidth = 1.8;
    roundRect(ctx, x, y, w, h, 20); ctx.stroke();
    ctx.restore();

    // ── Top accent bar (gradient fade in/out)
    const accentGrad = ctx.createLinearGradient(x, y, x + w, y);
    accentGrad.addColorStop(0,   'transparent');
    accentGrad.addColorStop(0.2, color);
    accentGrad.addColorStop(0.8, color);
    accentGrad.addColorStop(1,   'transparent');
    ctx.fillStyle = accentGrad;
    roundRect(ctx, x + 12, y, w - 24, 4, 2); ctx.fill();

    // ── Inner glow at top of card
    const innerGlow = ctx.createRadialGradient(cx, y, 0, cx, y, w * 0.6);
    innerGlow.addColorStop(0, `${color}18`);
    innerGlow.addColorStop(1, 'transparent');
    ctx.fillStyle = innerGlow;
    roundRect(ctx, x, y, w, h * 0.5, 20); ctx.fill();

    // ── Rank badge (circle, top-right)
    const bx = x + w - 28, by = y + 30;
    ctx.save();
    ctx.shadowBlur = 14; ctx.shadowColor = color;
    ctx.beginPath(); ctx.arc(bx, by, 22, 0, Math.PI * 2);
    ctx.fillStyle = color; ctx.fill();
    ctx.restore();
    ctx.font = 'bold 17px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillStyle = '#0b0920';
    ctx.fillText(`#${label}`, bx, by + 6);

    // ── Crown for #1
    if (label === '1') {
      ctx.font = '32px serif';
      ctx.textAlign = 'center';
      ctx.fillStyle = GOLD;
      ctx.fillText('👑', cx, y + 52);
    }

    // ── Avatar
    const avUrl = member?.displayAvatarURL({ size: 128, extension: 'png' }) || null;
    const avImg = await fetchAvatar(avUrl, avSz);
    const avX   = cx - avSz / 2;
    const avY   = label === '1' ? y + 66 : y + 52;

    // Outer glow ring
    ctx.save();
    ctx.shadowBlur = 28; ctx.shadowColor = color;
    ctx.beginPath();
    ctx.arc(cx, avY + avSz / 2, avSz / 2 + 6, 0, Math.PI * 2);
    ctx.fillStyle = color; ctx.fill();
    ctx.restore();

    // Inner white ring
    ctx.beginPath();
    ctx.arc(cx, avY + avSz / 2, avSz / 2 + 2, 0, Math.PI * 2);
    ctx.fillStyle = '#ffffff';
    ctx.fill();

    // Avatar clipped circle
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, avY + avSz / 2, avSz / 2, 0, Math.PI * 2);
    ctx.clip();
    ctx.drawImage(avImg, avX, avY, avSz, avSz);
    ctx.restore();

    // ── Name
    let ty = avY + avSz + 22;
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 19px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(name, cx, ty);

    // ── ELO number (big, glowing)
    ty += label === '1' ? 40 : 34;
    ctx.save();
    ctx.font = `bold ${label === '1' ? 42 : 36}px sans-serif`;
    ctx.fillStyle = color;
    ctx.textAlign = 'center';
    ctx.shadowBlur = 10; ctx.shadowColor = color;
    ctx.fillText(elo.toString(), cx, ty);
    ctx.restore();

    // "ELO" small label
    ty += 14;
    ctx.font = '12px sans-serif';
    ctx.fillStyle = 'rgba(200,210,240,0.45)';
    ctx.fillText('E L O', cx, ty);

    // ── Win-rate bar
    ty += 22;
    const barW = w - 50, barX = x + 25, barH = 7;
    ctx.fillStyle = 'rgba(255,255,255,0.08)';
    roundRect(ctx, barX, ty, barW, barH, 3.5); ctx.fill();

    const fillW = Math.max(0, Math.round(barW * wr / 100));
    if (fillW > 0) {
      const barFill = ctx.createLinearGradient(barX, 0, barX + fillW, 0);
      barFill.addColorStop(0, `${color}cc`);
      barFill.addColorStop(1, color);
      ctx.save();
      ctx.shadowBlur = 6; ctx.shadowColor = color;
      ctx.fillStyle = barFill;
      roundRect(ctx, barX, ty, fillW, barH, 3.5); ctx.fill();
      ctx.restore();
    }

    // ── W / L / WR
    ty += 22;
    ctx.font = '13px sans-serif';
    ctx.fillStyle = 'rgba(195,210,235,0.75)';
    ctx.fillText(`${wins}W  ${losses}L  ·  ${wr}% WR`, cx, ty);
  }

  return canvas.toBuffer('image/png');
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

// ── Discord client ─────────────────────────────────────────────────────────

const _memberFetchedAt = new Map();
async function fetchMembers(guild) {
  const last = _memberFetchedAt.get(guild.id) || 0;
  if (Date.now() - last < 60_000) return;
  await guild.members.fetch();
  _memberFetchedAt.set(guild.id, Date.now());

  // ── Persist player profiles (name + avatar) so the dashboard can show them ─
  try {
    const data = loadData();
    if (!data.profiles) data.profiles = {};
    guild.members.cache.forEach(member => {
      data.profiles[member.id] = {
        name:   member.displayName,
        avatar: member.user.displayAvatarURL({ size: 128, extension: 'png' }),
      };
    });
    saveData(data);
  } catch { /* non-critical */ }
}

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.GuildVoiceStates,
    GatewayIntentBits.GuildMembers,
    GatewayIntentBits.MessageContent,
    GatewayIntentBits.GuildMessageReactions,
  ],
  partials: [Partials.Message, Partials.Channel, Partials.Reaction],
});

// ── Command handler ────────────────────────────────────────────────────────

const commands = new Map();

function cmd(names, fn) {
  const list = Array.isArray(names) ? names : [names];
  for (const n of list) commands.set(n.toLowerCase(), fn);
}

// ── Admin check ────────────────────────────────────────────────────────────
// Admins = members with Administrator permission OR a role named "Tournament Admin"
function isAdmin(msg) {
  if (msg.member.permissions.has('Administrator')) return true;
  if (msg.member.roles.cache.some(r => r.name.toLowerCase() === 'tournament admin')) return true;
  return false;
}

function adminOnly(msg) {
  if (!isAdmin(msg)) {
    msg.reply('🔒 This command is **admin only**. You need the `Administrator` permission or the `Tournament Admin` role.');
    return false;
  }
  return true;
}

// ── Round advance helper ────────────────────────────────────────────────────
// Call after any match result is saved. Advances bracket if round is done,
// posts the new round's matches (or the winner), and returns true if the
// tournament ended so callers can skip their own reply.
async function handleRoundAdvance(channel, guild, t, data) {
  const r = currentRound(t.matches);
  if (!roundComplete(t.matches, r)) return false;

  t.matches = advanceBracket(t.matches);
  const nextPending = pendingMatches(t.matches);
  const rounds      = [...new Set(t.matches.map(m => m.round))].sort((a, b) => a - b);
  const totalRounds = rounds.length;

  function mname(uid) {
    if (uid === null) return 'BYE';
    const mem = guild.members.cache.get(String(uid));
    return mem ? mem.displayName : `User#${String(uid).slice(-4)}`;
  }

  // ── Tournament over ──────────────────────────────────────────────────────
  const lastRound   = Math.max(...t.matches.map(m => m.round));
  const lastMatches = t.matches.filter(m => m.round === lastRound && m.winner != null);
  const trueWinner  = nextPending.length === 0 && lastMatches.length === 1
    ? lastMatches[0].winner
    : null;

  if (trueWinner) {
    t.state  = 'ended';
    t.winner = trueWinner;
    if (data.elo[trueWinner]) data.elo[trueWinner].tournaments += 1;
    data.history.push({
      name: t.name, winner: trueWinner,
      players: t.players.length, date: new Date().toISOString(),
    });
    saveData(data);
    const champ = guild.members.cache.get(String(trueWinner));
    const champName = champ ? champ.displayName : trueWinner;
    const embed = new EmbedBuilder()
      .setTitle('🏆 Tournament Over!')
      .setDescription(`**${champName}** is the champion of **${t.name}**! 🎉`)
      .setColor(0xFFD700);
    await channel.send({ embeds: [embed] });
    await botLog(
      '🏆 Tournament Finished',
      `**Tournament:** ${t.name}\n**Champion:** ${champName}\n**Total players:** ${t.players.length}\n**Total rounds:** ${totalRounds}`,
      0xFFD700
    );
    return true;
  }

  // ── Next round announcement ──────────────────────────────────────────────
  saveData(data);
  const newRound = currentRound(t.matches);
  const roundLabel = newRound === totalRounds ? '🏆 Final' : newRound === totalRounds - 1 ? '🥊 Semi-Final' : `⚔️ Round ${newRound}`;

  await botLog(
    `📢 ${roundLabel} Started`,
    `**Tournament:** ${t.name}\n**Round:** ${newRound} of ${totalRounds}\n**Pending matches:** ${nextPending.filter(m => m.p2 !== null).length}`,
    0xE74C3C
  );

  const lines = nextPending.map(m => {
    const p1 = mname(m.p1), p2 = mname(m.p2);
    if (m.p2 === null) return `  [${String(m.id).padStart(2,'0')}] **${p1}** — *auto-advance (BYE)*`;
    return `  [${String(m.id).padStart(2,'0')}] **${p1}** vs **${p2}**`;
  });

  // Paginate at 16 matches per message
  const CHUNK = 16;
  for (let i = 0; i < lines.length; i += CHUNK) {
    const chunk = lines.slice(i, i + CHUNK);
    const pageLabel = lines.length > CHUNK ? ` (${Math.floor(i/CHUNK)+1}/${Math.ceil(lines.length/CHUNK)})` : '';
    const embed = new EmbedBuilder()
      .setTitle(`${roundLabel}${pageLabel} — Matches`)
      .setDescription(chunk.join('\n'))
      .setColor(0xE74C3C)
      .setFooter({ text: `Round ${newRound} of ${totalRounds} • Use !mymatch to see your opponent` });
    await channel.send({ embeds: [embed] });
  }
  return true;
}

// ── Duel channel helper ─────────────────────────────────────────────────────
async function closeDuelChannel(guild, match) {
  if (!match.duelChannelId) return;
  try {
    const ch = await guild.channels.fetch(match.duelChannelId).catch(() => null);
    if (ch) await ch.delete('Match finished');
  } catch { /* already deleted */ }
  match.duelChannelId = null;
}

// ── Commands ───────────────────────────────────────────────────────────────

cmd('create', async (msg, args) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  if (data.tournament && data.tournament.state !== 'ended') {
    return msg.reply('❌ A tournament is already running. Use `!end` to close it first.');
  }
  const name = args.join(' ') || 'Brawlhalla Tournament';
  data.tournament = {
    name,
    state: 'registration',
    players: [],
    matches: [],
    current_round: 1,
    winner: null,
    created_by: msg.author.id,
    created_at: new Date().toISOString(),
  };
  saveData(data);
  const embed = new EmbedBuilder()
    .setTitle(`🏆 ${name}`)
    .setDescription('A new **Brawlhalla** tournament has been created!\n\nType `!register` to join.\nAdmin: `!start` to begin once everyone has registered.')
    .setColor(0xFFD700)
    .setFooter({ text: `Created by ${msg.member.displayName}` });
  msg.channel.send({ embeds: [embed] });
});

cmd(['register', 'join_tournament', 'reg'], async (msg) => {
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'registration') return msg.reply('❌ No tournament is open for registration right now.');
  const uid = BigInt(msg.author.id);
  if (t.players.includes(msg.author.id)) return msg.reply('You\'re already registered!');
  t.players.push(msg.author.id);
  saveData(data);
  msg.reply(`✅ **${msg.member.displayName}** has registered! (${t.players.length} player${t.players.length !== 1 ? 's' : ''} signed up)`);
});

cmd(['unregister', 'leave_tournament'], async (msg) => {
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'registration') return msg.reply('❌ Registration is not open.');
  if (!t.players.includes(msg.author.id)) return msg.reply('You\'re not registered.');
  t.players = t.players.filter(id => id !== msg.author.id);
  saveData(data);
  msg.reply(`**${msg.member.displayName}** has left the tournament.`);
});

cmd(['addjoin', 'addplayer', 'forceadd'], async (msg) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'registration') return msg.reply('❌ No tournament is open for registration right now.');
  const mentioned = msg.mentions.members.first();
  if (!mentioned) return msg.reply('❌ Mention a player to add.');
  if (t.players.includes(mentioned.id)) return msg.reply(`**${mentioned.displayName}** is already registered!`);
  t.players.push(mentioned.id);
  saveData(data);
  msg.reply(`✅ **${mentioned.displayName}** has been added! (${t.players.length} player${t.players.length !== 1 ? 's' : ''} signed up)`);
});

cmd(['joinbyid', 'addid', 'addbyid'], async (msg, args) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'registration') return msg.reply('❌ No tournament is open for registration right now.');
  const userId = args[0];
  if (!userId) return msg.reply('❌ Provide a user ID.');
  if (t.players.includes(userId)) return msg.reply(`**${userId}** is already registered!`);
  t.players.push(userId);
  saveData(data);
  const member = msg.guild.members.cache.get(userId);
  const name = member ? member.displayName : `User \`${userId}\``;
  msg.reply(`✅ **${name}** has been added by ID! (${t.players.length} player${t.players.length !== 1 ? 's' : ''} signed up)`);
});

cmd(['addall', 'addeveryone', 'joinall'], async (msg) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'registration') return msg.reply('❌ No tournament is open for registration right now.');
  await fetchMembers(msg.guild);
  const added = [];
  const skipped = [];
  for (const [, member] of msg.guild.members.cache) {
    if (member.user.bot) continue;
    if (t.players.includes(member.id)) {
      skipped.push(member.displayName);
    } else {
      t.players.push(member.id);
      added.push(member.displayName);
    }
  }
  saveData(data);
  let desc = `✅ Added **${added.length}** member${added.length !== 1 ? 's' : ''}.`;
  if (skipped.length) desc += `\n⏭️ Skipped **${skipped.length}** already registered.`;
  desc += `\n👥 Total players: **${t.players.length}**`;
  const embed = new EmbedBuilder()
    .setTitle('📋 All Members Added to Tournament')
    .setDescription(desc)
    .setColor(0x2ECC71)
    .setFooter({ text: `Run by ${msg.member.displayName}` });
  msg.channel.send({ embeds: [embed] });
});

cmd(['removejoin', 'removeplayer', 'forceremove'], async (msg) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'registration') return msg.reply('❌ Registration is not open.');
  const mentioned = msg.mentions.members.first();
  if (!mentioned) return msg.reply('❌ Mention a player to remove.');
  if (!t.players.includes(mentioned.id)) return msg.reply(`**${mentioned.displayName}** is not registered.`);
  t.players = t.players.filter(id => id !== mentioned.id);
  saveData(data);
  msg.reply(`🗑️ **${mentioned.displayName}** has been removed. (${t.players.length} player${t.players.length !== 1 ? 's' : ''} remaining)`);
});

cmd('players', async (msg) => {
  const data = loadData();
  const t = data.tournament;
  if (!t) return msg.reply('No tournament active.');
  if (!t.players.length) return msg.reply('No players registered yet.');
  await fetchMembers(msg.guild);
  const lines = t.players.map((id, i) => {
    const m = msg.guild.members.cache.get(String(id));
    const username = m ? `${m.user.username}` : `Unknown (${id})`;
    return `\`${i + 1}.\` ${username}`;
  });
  const embed = new EmbedBuilder()
    .setTitle(`👥 ${t.name} — Players (${t.players.length})`)
    .setDescription(lines.join('\n'))
    .setColor(0x3498DB);
  msg.channel.send({ embeds: [embed] });
});

cmd('seedings', async (msg) => {
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'registration') return msg.reply('❌ No tournament in registration phase.');
  if (!t.players.length) return msg.reply('No players registered yet.');
  const ranked = [...t.players].sort((a, b) => {
    const ea = (data.elo[String(a)] || {}).elo || DEFAULT_ELO;
    const eb = (data.elo[String(b)] || {}).elo || DEFAULT_ELO;
    return eb - ea;
  });
  const medals = ['🥇', '🥈', '🥉', ...Array(50).fill('🔹')];
  const lines = ranked.map((id, i) => {
    const m = msg.guild.members.cache.get(String(id));
    const name = m ? m.displayName : `<${id}>`;
    const eloVal = (data.elo[String(id)] || {}).elo || DEFAULT_ELO;
    return `${medals[i]} Seed **#${i + 1}** — ${name} (${eloVal} ELO)`;
  });
  const embed = new EmbedBuilder()
    .setTitle(`🌱 ${t.name} — ELO Seedings`)
    .setDescription(lines.join('\n'))
    .setColor(0x2ECC71)
    .setFooter({ text: 'Seed #1 and #2 can only meet in the Final • !start to begin' });
  msg.channel.send({ embeds: [embed] });
});

cmd('start', async (msg, args) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'registration') return msg.reply('❌ No tournament is in registration phase.');
  if (t.players.length < 2) return msg.reply('❌ Need at least 2 players to start.');

  const seen = new Set();
  t.players = t.players.filter(id => { if (seen.has(id)) return false; seen.add(id); return true; });

  const useRandom = (args[0] || 'random').toLowerCase() !== 'seeded';
  let slots;
  if (useRandom) {
    // Fisher-Yates shuffle — truly random, unbiased
    const arr = [...t.players];
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    const size = bracketSize(arr.length);
    slots = [...arr, ...Array(size - arr.length).fill(null)];
  } else {
    slots = eloSeededSlots(t.players, data);
  }

  const matches = resolveByes(makeBracket(slots));
  t.matches = matches;
  t.state = 'in_progress';
  t.current_round = 1;
  saveData(data);

  await fetchMembers(msg.guild);

  // Show ALL round 1 matches (including BYE auto-advances), 16 per message
  const round1 = matches.filter(m => m.round === 1);
  const seedings = useRandom ? '🎲 Random draw' : '🌱 ELO seeded';

  const startEmbed = new EmbedBuilder()
    .setTitle(`⚔️ ${t.name} has started! (${seedings})`)
    .setDescription(`**${t.players.length}** players registered • Single Elimination\nUse \`!bracket\` to see the full draw at any time.`)
    .setColor(0xE74C3C);
  await msg.channel.send({ embeds: [startEmbed] });

  // Paginate round 1 matches at 16 per message
  function memberName(uid) {
    if (uid === null) return 'BYE';
    const mem = msg.guild.members.cache.get(String(uid));
    return mem ? mem.displayName : `<${uid}>`;
  }
  for (let i = 0; i < round1.length; i += 16) {
    const chunk = round1.slice(i, i + 16);
    const page = Math.floor(i / 16) + 1;
    const totalPages = Math.ceil(round1.length / 16);
    const lines = chunk.map(m => {
      const p1 = memberName(m.p1), p2 = memberName(m.p2);
      if (m.state === 'done') return `  [${String(m.id).padStart(2,'0')}] ${p1} vs ${p2}  →  ✅ ${memberName(m.winner)} *(auto-advance)*`;
      return `  [${String(m.id).padStart(2,'0')}] **${p1}** vs **${p2}**`;
    });
    const pageLabel = totalPages > 1 ? ` (${page}/${totalPages})` : '';
    await msg.channel.send(`**⚔️ Round 1 Matches${pageLabel}**\`\`\`\n${lines.join('\n')}\n\`\`\``);
  }
});

cmd('bracket', async (msg) => {
  const data = loadData();
  const t = data.tournament;
  if (!t || !t.matches.length) return msg.reply('No bracket yet.');

  await fetchMembers(msg.guild);

  const PAGE_SIZE = 16;
  const rounds = [...new Set(t.matches.map(m => m.round))].sort((a, b) => a - b);
  const totalRounds = rounds.length;
  const round1Count = t.matches.filter(m => m.round === 1).length;
  const totalPlayers = t.players.length;

  // Always show a summary header first
  const summaryEmbed = new EmbedBuilder()
    .setTitle(`📊 ${t.name} — Bracket Overview`)
    .setDescription(
      `👥 **${totalPlayers}** players registered\n` +
      `⚔️ **${round1Count}** matches in Round 1\n` +
      `🔢 **${totalRounds}** rounds total\n\n` +
      (totalPlayers < 4 ? '⚠️ Very few players — run `!addall` before `!start` to include everyone.' : '')
    )
    .setColor(0x3498DB);
  await msg.channel.send({ embeds: [summaryEmbed] });

  function name(uid) {
    if (uid === null) return 'BYE';
    const mem = msg.guild.members.cache.get(String(uid));
    return mem ? mem.displayName : `<${uid}>`;
  }

  function matchLine(m) {
    const p1 = name(m.p1), p2 = name(m.p2);
    if (m.state === 'done') {
      const winner = m.winner !== null ? `✅ ${name(m.winner)}` : '🚫 No-show';
      return `  [${String(m.id).padStart(2, '0')}] ${p1} vs ${p2}  →  ${winner}`;
    }
    return `  [${String(m.id).padStart(2, '0')}] ${p1} vs ${p2}`;
  }

  // Build all lines with round headers, then paginate every PAGE_SIZE matches
  const allLines = [];
  for (const r of rounds) {
    const roundMatches = t.matches.filter(m => m.round === r);
    allLines.push({ type: 'header', text: `── Round ${r} / ${totalRounds} ──────────────────` });
    for (const m of roundMatches) allLines.push({ type: 'match', text: matchLine(m) });
  }

  // Group into pages of PAGE_SIZE matches each
  const pages = [];
  let page = [];
  let matchCount = 0;
  for (const line of allLines) {
    if (line.type === 'header') {
      page.push(line.text);
    } else {
      page.push(line.text);
      matchCount++;
      if (matchCount >= PAGE_SIZE) {
        pages.push(page);
        page = [];
        matchCount = 0;
      }
    }
  }
  if (page.length) pages.push(page);

  const totalPages = pages.length;
  for (let i = 0; i < pages.length; i++) {
    const header = totalPages > 1 ? `📊 **${t.name}** — Bracket (Page ${i + 1}/${totalPages})\n` : `📊 **${t.name}** — Bracket\n`;
    await msg.channel.send(header + '```' + '\n' + pages[i].join('\n') + '\n```');
  }
});

cmd(['games', 'allgames', 'matchups'], async (msg) => {
  try {
    const data = loadData();
    const t = data.tournament;
    if (!t) return msg.reply('❌ No tournament exists. Use `!create` to start one.');
    if (!t.matches || t.matches.length === 0) return msg.reply('❌ No bracket yet. Use `!start` or `!randombracket` to generate matches.');

    await fetchMembers(msg.guild);

    function mname(uid) {
      if (uid === null) return 'BYE';
      const mem = msg.guild.members.cache.get(String(uid));
      return mem ? mem.displayName : `User#${String(uid).slice(-4)}`;
    }

    const rounds = [...new Set(t.matches.map(m => m.round))].sort((a, b) => a - b);
    const totalRounds = rounds.length;
    const activeRound = currentRound(t.matches);

    for (const r of rounds) {
      const roundMatches = t.matches.filter(m => m.round === r);
      const isActive = r === activeRound;
      const isDone   = roundMatches.every(m => m.state === 'done');

      // ── Round label ──────────────────────────────────────────────────────
      let roundLabel, roundEmoji, embedColor;
      if (r === totalRounds) {
        roundLabel = 'Grand Final';
        roundEmoji = '🏆';
        embedColor = 0xFFD700;
      } else if (r === totalRounds - 1) {
        roundLabel = 'Semi-Finals';
        roundEmoji = '🥊';
        embedColor = 0xFF6B35;
      } else if (r === 1) {
        roundLabel = 'Round 1 — Group Stage';
        roundEmoji = '⚔️';
        embedColor = 0x5865F2;
      } else {
        roundLabel = `Round ${r}`;
        roundEmoji = '🔥';
        embedColor = 0xE74C3C;
      }

      // Active round gets a brighter banner
      if (isActive && !isDone) embedColor = 0x00FF7F;

      // ── Build match lines ─────────────────────────────────────────────────
      const CHUNK = 16;
      const chunks = [];
      for (let i = 0; i < roundMatches.length; i += CHUNK) {
        chunks.push(roundMatches.slice(i, i + CHUNK));
      }

      for (let ci = 0; ci < chunks.length; ci++) {
        const chunk = chunks[ci];
        const pageLabel = chunks.length > 1 ? ` (${ci + 1}/${chunks.length})` : '';

        const lines = chunk.map(m => {
          const p1 = mname(m.p1), p2 = mname(m.p2);
          if (m.state === 'done') {
            const w = m.winner !== null ? mname(m.winner) : 'No Contest';
            return `  ✅ [${String(m.id).padStart(2,'0')}] ${p1} vs ${p2}  →  ${w}`;
          }
          return `  ⚔️  [${String(m.id).padStart(2,'0')}] ${p1} vs ${p2}`;
        });

        let statusTag = isDone ? ' — ✅ Completed' : isActive ? ' — 🔴 LIVE' : ' — ⏳ Upcoming';

        const embed = new EmbedBuilder()
          .setTitle(`${roundEmoji} ${roundLabel}${pageLabel}${statusTag}`)
          .setDescription('```\n' + lines.join('\n') + '\n```')
          .setColor(embedColor);

        if (isActive && !isDone && ci === 0) {
          const pending = roundMatches.filter(m => m.state === 'pending' && m.p2 !== null).length;
          const done    = roundMatches.filter(m => m.state === 'done').length;
          embed.setFooter({ text: `${done}/${roundMatches.length} matches done • ${pending} still pending` });
        }

        await msg.channel.send({ embeds: [embed] });
      }
    }
  } catch (err) {
    console.error('[games]', err);
    msg.reply(`❌ Error: ${err.message}`);
  }
});

cmd(['randombracket', 'randomstart', 'shufflestart'], async (msg) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const t = data.tournament;
  if (!t) return msg.reply('❌ No tournament. Use `!create` first.');
  if (t.state !== 'registration') return msg.reply('❌ Tournament is not in registration phase. Use `!end` then `!create` to start fresh.');
  if (t.players.length < 2) return msg.reply('❌ Need at least 2 players. Use `!addall` to add everyone.');

  // Deduplicate
  const seen = new Set();
  t.players = t.players.filter(id => { if (seen.has(id)) return false; seen.add(id); return true; });

  // Fisher-Yates shuffle
  const arr = [...t.players];
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  const size = bracketSize(arr.length);
  const slots = [...arr, ...Array(size - arr.length).fill(null)];
  const matches = resolveByes(makeBracket(slots));

  t.matches = matches;
  t.state   = 'in_progress';
  t.current_round = 1;
  saveData(data);

  await fetchMembers(msg.guild);

  function mname(uid) {
    if (uid === null) return 'BYE';
    const mem = msg.guild.members.cache.get(String(uid));
    return mem ? mem.displayName : `User#${String(uid).slice(-4)}`;
  }

  const startEmbed = new EmbedBuilder()
    .setTitle(`🎲 ${t.name} — Random Bracket Generated!`)
    .setDescription(`**${t.players.length}** players • Opponents randomly assigned\nShowing all Round 1 matchups below 👇`)
    .setColor(0xE74C3C);
  await msg.channel.send({ embeds: [startEmbed] });

  const round1 = matches.filter(m => m.round === 1);
  const CHUNK = 16;
  const total = Math.ceil(round1.length / CHUNK);
  for (let i = 0; i < round1.length; i += CHUNK) {
    const chunk = round1.slice(i, i + CHUNK);
    const label = total > 1 ? ` (${Math.floor(i / CHUNK) + 1}/${total})` : '';
    const lines = chunk.map(m => {
      const p1 = mname(m.p1), p2 = mname(m.p2);
      if (m.state === 'done') return `[${String(m.id).padStart(2,'0')}] ${p1} vs ${p2}  →  ✅ ${mname(m.winner)} (auto)`;
      return `[${String(m.id).padStart(2,'0')}] ${p1} vs ${p2}`;
    });
    await msg.channel.send(`**⚔️ Round 1 Matchups${label}**\`\`\`\n${lines.join('\n')}\n\`\`\``);
  }
});

cmd('matches', async (msg) => {
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'in_progress') return msg.reply('No tournament in progress.');
  const pending = pendingMatches(t.matches);
  if (!pending.length) return msg.reply('No pending matches this round.');
  const lines = pending.map(m => {
    const p1 = msg.guild.members.cache.get(String(m.p1))?.displayName || m.p1;
    const p2 = m.p2 ? (msg.guild.members.cache.get(String(m.p2))?.displayName || m.p2) : 'BYE';
    return `Match **#${m.id}**: **${p1}** vs **${p2}**`;
  });
  const embed = new EmbedBuilder()
    .setTitle(`⚔️ Round ${currentRound(t.matches)} — Pending Matches`)
    .setDescription(lines.join('\n'))
    .setColor(0xE67E22);
  msg.channel.send({ embeds: [embed] });
});

// !pick — admin-direct result (no approval needed)
cmd('pick', async (msg) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'in_progress') return msg.reply('No tournament in progress.');
  const winner = msg.mentions.members.first();
  if (!winner) return msg.reply('❌ Mention the winner.');
  const pending = pendingMatches(t.matches);
  const match = pending.find(m =>
    String(m.p1) === winner.id || String(m.p2) === winner.id
  );
  if (!match) return msg.reply(`❌ **${winner.displayName}** has no pending match this round.`);

  const loserId = String(match.p1) === winner.id ? match.p2 : match.p1;
  match.winner = winner.id;
  match.state  = 'done';
  if (loserId !== null) updateElo(data, winner.id, loserId);

  await msg.reply(`✅ **${winner.displayName}** wins match **#${match.id}**!`);
  await closeDuelChannel(msg.guild, match);
  await handleRoundAdvance(msg.channel, msg.guild, t, data);
  saveData(data);
});

// !report — player submits result, waits for admin !approve
cmd('report', async (msg) => {
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'in_progress') return msg.reply('❌ No tournament in progress.');
  const winner = msg.mentions.members.first();
  if (!winner) return msg.reply('❌ Mention the winner: `!report @winner`');

  // Find their pending match
  const uid = msg.author.id;
  const pending = pendingMatches(t.matches);
  const match = pending.find(m =>
    (String(m.p1) === uid || String(m.p2) === uid) &&
    (String(m.p1) === winner.id || String(m.p2) === winner.id)
  );
  if (!match) return msg.reply(`❌ No pending match found between you and **${winner.displayName}**.`);

  // Block duplicate pending reports for same match
  if (data.pendingReports.find(r => r.matchId === match.id))
    return msg.reply(`⏳ A report for match **#${match.id}** is already waiting for admin approval.`);

  const loserId = String(match.p1) === winner.id ? String(match.p2) : String(match.p1);

  // Save pending report
  data.pendingReports.push({
    matchId: match.id,
    winnerId: winner.id,
    loserId,
    reporterId: uid,
    channelId: msg.channel.id,
  });
  saveData(data);

  const loserMember = msg.guild.members.cache.get(loserId);
  const embed = new EmbedBuilder()
    .setTitle('⏳ Result Pending Admin Approval')
    .setDescription(
      `**${msg.member.displayName}** reports:\n\n` +
      `🏆 **Winner:** ${winner.displayName}\n` +
      `❌ **Loser:** ${loserMember ? loserMember.displayName : loserId}\n` +
      `🎮 **Match:** #${match.id}\n\n` +
      `An admin must confirm with \`!approve ${match.id}\` or reject with \`!deny ${match.id}\`.`
    )
    .setColor(0xF39C12)
    .setFooter({ text: `Reported by ${msg.member.displayName}` });
  await msg.channel.send({ embeds: [embed] });
});

// !approve <matchId> — admin confirms a pending report
cmd('approve', async (msg, args) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const matchId = parseInt(args[0]);
  if (!matchId) return msg.reply('❌ Usage: `!approve <matchId>`');

  const idx = data.pendingReports.findIndex(r => r.matchId === matchId);
  if (idx === -1) return msg.reply(`❌ No pending report found for match **#${matchId}**.`);

  const report = data.pendingReports[idx];
  const t = data.tournament;
  if (!t || t.state !== 'in_progress') {
    data.pendingReports.splice(idx, 1);
    saveData(data);
    return msg.reply('❌ No tournament in progress — report discarded.');
  }

  const match = t.matches.find(m => m.id === matchId);
  if (!match || match.state === 'done') {
    data.pendingReports.splice(idx, 1);
    saveData(data);
    return msg.reply(`❌ Match **#${matchId}** is already resolved.`);
  }

  match.winner = report.winnerId;
  match.state  = 'done';
  if (report.loserId && report.loserId !== 'null')
    updateElo(data, report.winnerId, report.loserId);

  data.pendingReports.splice(idx, 1);

  const winnerMember = msg.guild.members.cache.get(report.winnerId);
  const winName = winnerMember ? winnerMember.displayName : report.winnerId;

  const embed = new EmbedBuilder()
    .setTitle('✅ Result Approved')
    .setDescription(`**${winName}** wins match **#${matchId}**!`)
    .setColor(0x2ECC71)
    .setFooter({ text: `Approved by ${msg.member.displayName}` });
  await msg.channel.send({ embeds: [embed] });
  await closeDuelChannel(msg.guild, match);
  await handleRoundAdvance(msg.channel, msg.guild, t, data);
  saveData(data);
});

// !deny <matchId> — admin rejects a pending report
cmd('deny', async (msg, args) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const matchId = parseInt(args[0]);
  if (!matchId) return msg.reply('❌ Usage: `!deny <matchId>`');

  const idx = data.pendingReports.findIndex(r => r.matchId === matchId);
  if (idx === -1) return msg.reply(`❌ No pending report found for match **#${matchId}**.`);

  const report = data.pendingReports[idx];
  data.pendingReports.splice(idx, 1);
  saveData(data);

  const winnerMember = msg.guild.members.cache.get(report.winnerId);
  const winName = winnerMember ? winnerMember.displayName : report.winnerId;

  const embed = new EmbedBuilder()
    .setTitle('❌ Report Denied')
    .setDescription(`The report for match **#${matchId}** (winner: **${winName}**) has been rejected.\nPlayers must re-submit with \`!report @winner\`.`)
    .setColor(0xE74C3C)
    .setFooter({ text: `Denied by ${msg.member.displayName}` });
  await msg.channel.send({ embeds: [embed] });
});

cmd('reportid', async (msg, args) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'in_progress') return msg.reply('No tournament in progress.');
  const matchId = parseInt(args[0]);
  const userId  = args[1];
  if (!matchId || !userId) return msg.reply('Usage: `!reportid <matchId> <userId>`');
  const match = t.matches.find(m => m.id === matchId);
  if (!match) return msg.reply(`❌ Match #${matchId} not found.`);
  if (match.state === 'done') return msg.reply(`❌ Match #${matchId} is already done.`);
  if (String(match.p1) !== userId && String(match.p2) !== userId) return msg.reply(`❌ That user is not in match #${matchId}.`);
  const loserId = String(match.p1) === userId ? match.p2 : match.p1;
  match.winner = userId;
  match.state  = 'done';
  if (loserId !== null) updateElo(data, userId, loserId);
  const member = msg.guild.members.cache.get(userId);
  await msg.reply(`✅ **${member ? member.displayName : userId}** wins match **#${matchId}**!`);
  await closeDuelChannel(msg.guild, match);
  await handleRoundAdvance(msg.channel, msg.guild, t, data);
  saveData(data);
});

cmd(['noshow', 'kickboth', 'dqboth'], async (msg, args) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'in_progress') return msg.reply('❌ No tournament in progress.');

  await fetchMembers(msg.guild);
  const mentions = [...msg.mentions.members.values()];

  let match;
  if (mentions.length >= 2) {
    // Support: !kickboth @p1 @p2 — find their shared pending match
    const [a, b] = mentions;
    match = t.matches.find(m =>
      m.state === 'pending' &&
      ((String(m.p1) === a.id && String(m.p2) === b.id) ||
       (String(m.p1) === b.id && String(m.p2) === a.id))
    );
    if (!match) return msg.reply(`❌ No pending match found between **${a.displayName}** and **${b.displayName}**.`);
  } else {
    // Support: !kickboth <matchId>
    const matchId = parseInt(args[0]);
    if (!matchId) return msg.reply('❌ Usage: `!kickboth @player1 @player2` or `!kickboth <matchId>`');
    match = t.matches.find(m => m.id === matchId);
    if (!match) return msg.reply(`❌ Match #${matchId} not found.`);
    if (match.state === 'done') return msg.reply(`❌ Match #${match.id} is already finished.`);
    if (match.p1 === null || match.p2 === null) return msg.reply(`❌ Match #${match.id} has a BYE slot — use \`!kick\` instead.`);
  }

  if (match.state === 'done') return msg.reply(`❌ Match #${match.id} is already finished.`);
  if (match.p1 === null || match.p2 === null) return msg.reply(`❌ Match #${match.id} has a BYE slot — use \`!kick\` instead.`);

  const NOSHOW_PENALTY = 16;
  const p1id = String(match.p1);
  const p2id = String(match.p2);
  const elo = data.elo;
  if (!elo[p1id]) elo[p1id] = { elo: DEFAULT_ELO, wins: 0, losses: 0, tournaments: 0 };
  if (!elo[p2id]) elo[p2id] = { elo: DEFAULT_ELO, wins: 0, losses: 0, tournaments: 0 };
  elo[p1id].elo = Math.max(0, elo[p1id].elo - NOSHOW_PENALTY);
  elo[p2id].elo = Math.max(0, elo[p2id].elo - NOSHOW_PENALTY);
  elo[p1id].losses += 1;
  elo[p2id].losses += 1;

  match.winner = null;
  match.state  = 'done';

  // Remove both players from the tournament roster
  t.players = t.players.filter(id => id !== p1id && id !== p2id);

  const p1m    = msg.guild.members.cache.get(p1id);
  const p2m    = msg.guild.members.cache.get(p2id);
  const p1name = p1m ? p1m.displayName : p1id;
  const p2name = p2m ? p2m.displayName : p2id;

  const noShowEmbed = new EmbedBuilder()
    .setTitle(`🚫 Match #${match.id} — Both Players Kicked`)
    .setDescription(
      `**${p1name}** and **${p2name}** have both been removed from the tournament.\n` +
      `Both lost **${NOSHOW_PENALTY} ELO** each.\n\n` +
      `Neither player advances.`
    )
    .setColor(0x95A5A6)
    .setFooter({ text: `Called by ${msg.member.displayName}` });
  await msg.channel.send({ embeds: [noShowEmbed] });
  await closeDuelChannel(msg.guild, match);
  await handleRoundAdvance(msg.channel, msg.guild, t, data);
  saveData(data);
});

cmd(['kick', 'dq', 'disqualify'], async (msg) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const t = data.tournament;
  if (!t || !['registration', 'in_progress'].includes(t.state))
    return msg.reply('❌ No active tournament.');
  const target = msg.mentions.members.first();
  if (!target) return msg.reply('❌ Mention a player to remove.');

  // Check the player is actually in this tournament
  if (!t.players.includes(target.id))
    return msg.reply(`❌ **${target.user.username}** is not in this tournament.`);

  let replyLine = '';
  let theirMatch = null;

  if (t.state === 'registration') {
    // Simple removal during sign-ups — no matches exist yet
    replyLine = `🗑️ **${target.user.username}** has been removed from registration.`;
  } else {
    // In-progress: find any pending match and resolve it
    theirMatch = t.matches.find(m =>
      m.state === 'pending' &&
      (String(m.p1) === target.id || String(m.p2) === target.id)
    );

    if (theirMatch) {
      const winnerId = String(theirMatch.p1) === target.id ? String(theirMatch.p2) : String(theirMatch.p1);
      theirMatch.state = 'done';
      if (winnerId && winnerId !== 'null') {
        theirMatch.winner = winnerId;
        const winnerMember = msg.guild.members.cache.get(winnerId);
        const winnerName = winnerMember ? winnerMember.user.username : winnerId;
        replyLine = `🚫 **${target.user.username}** removed. **${winnerName}** advances via walkover.`;
      } else {
        theirMatch.winner = null;
        replyLine = `🚫 **${target.user.username}** removed (BYE slot — no opponent to advance).`;
      }
      await closeDuelChannel(msg.guild, theirMatch);
    } else {
      replyLine = `🚫 **${target.user.username}** removed from the tournament (was between rounds).`;
    }
  }

  // Remove from players list
  t.players = t.players.filter(id => id !== target.id);

  const embed = new EmbedBuilder()
    .setTitle('🚫 Player Removed')
    .setDescription(replyLine)
    .setColor(0xE74C3C)
    .setFooter({ text: `Removed by ${msg.member.user.username}` });
  await msg.channel.send({ embeds: [embed] });

  if (theirMatch) await handleRoundAdvance(msg.channel, msg.guild, t, data);
  saveData(data);
});

// ── kickmatch: remove a ghost player (not in server) from a match by ID ────
cmd(['kickmatch', 'kickid'], async (msg, args) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'in_progress') return msg.reply('❌ No tournament is currently running.');

  const matchId = parseInt(args[0], 10);
  if (!matchId) return msg.reply('❌ Usage: `!kickmatch <matchId>` — e.g. `!kickmatch 21`');

  const match = t.matches.find(m => m.id === matchId);
  if (!match) return msg.reply(`❌ Match #${matchId} not found.`);
  if (match.state === 'done') return msg.reply(`❌ Match #${matchId} is already finished.`);

  await fetchMembers(msg.guild);

  const p1inServer = match.p1 ? msg.guild.members.cache.has(String(match.p1)) : false;
  const p2inServer = match.p2 ? msg.guild.members.cache.has(String(match.p2)) : false;

  let ghostId, survivorId;

  if (match.p1 && !p1inServer && (match.p2 === null || p2inServer)) {
    ghostId    = match.p1;
    survivorId = match.p2;
  } else if (match.p2 && !p2inServer && (match.p1 === null || p1inServer)) {
    ghostId    = match.p2;
    survivorId = match.p1;
  } else if (!p1inServer && !p2inServer) {
    return msg.reply(`❌ Both players in match #${matchId} are not in the server. Use \`!kickboth ${matchId}\` instead.`);
  } else {
    return msg.reply(`❌ Both players in match #${matchId} are still in the server — use \`!kick @player\` instead.`);
  }

  match.state  = 'done';
  match.winner = survivorId || null;
  await closeDuelChannel(msg.guild, match);

  // Remove ghost from players list
  if (ghostId) t.players = t.players.filter(id => String(id) !== String(ghostId));

  const survivorMember = survivorId ? msg.guild.members.cache.get(String(survivorId)) : null;
  const survivorName   = survivorMember ? survivorMember.displayName : (survivorId || 'nobody');

  const embed = new EmbedBuilder()
    .setTitle('🚫 Ghost Player Removed')
    .setDescription(`Match #${matchId}: ghost player removed.\n**${survivorName}** advances via walkover.`)
    .setColor(0xE74C3C)
    .setFooter({ text: `Removed by ${msg.member.user.username}` });
  await msg.channel.send({ embeds: [embed] });

  await handleRoundAdvance(msg.channel, msg.guild, t, data);
  saveData(data);
});

// ── swapin: move a player from their BYE win into a match, replacing a ghost ─
cmd(['swapin', 'replaceplayer'], async (msg, args) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'in_progress') return msg.reply('❌ No tournament is currently running.');

  const matchId = parseInt(args[0], 10);
  if (!matchId) return msg.reply('❌ Usage: `!swapin <matchId> @player` — e.g. `!swapin 21 @sero`');

  const target = msg.mentions.members.first();
  if (!target) return msg.reply('❌ Mention the player to swap in.');

  const match = t.matches.find(m => m.id === matchId);
  if (!match) return msg.reply(`❌ Match #${matchId} not found.`);
  if (match.state === 'done') return msg.reply(`❌ Match #${matchId} is already finished.`);

  await fetchMembers(msg.guild);

  // Detect which slot is the ghost (not in server, or null)
  const p1inServer = match.p1 ? msg.guild.members.cache.has(String(match.p1)) : false;
  const p2inServer = match.p2 ? msg.guild.members.cache.has(String(match.p2)) : false;

  let ghostSlot = null;
  if (match.p2 === null || (!p2inServer && p1inServer)) ghostSlot = 'p2';
  else if (match.p1 === null || (!p1inServer && p2inServer)) ghostSlot = 'p1';
  else return msg.reply(`❌ No ghost slot found in match #${matchId}. Both players appear to be in the server.`);

  const ghostId = match[ghostSlot];

  // Remove ghost from players list
  if (ghostId) t.players = t.players.filter(id => String(id) !== String(ghostId));

  // Find and remove the player's existing BYE win in the same round, if any
  const byeMatchIdx = t.matches.findIndex(m =>
    m.round === match.round &&
    m.state === 'done' &&
    String(m.winner) === target.id &&
    (m.p1 === null || m.p2 === null)
  );

  if (byeMatchIdx !== -1) {
    t.matches.splice(byeMatchIdx, 1);
  }

  // Swap the player into the ghost slot
  match[ghostSlot] = target.id;

  const otherSlot = ghostSlot === 'p1' ? 'p2' : 'p1';
  const otherMember = match[otherSlot] ? msg.guild.members.cache.get(String(match[otherSlot])) : null;
  const otherName   = otherMember ? otherMember.displayName : (match[otherSlot] || 'BYE');

  const embed = new EmbedBuilder()
    .setTitle('🔄 Player Swapped In')
    .setDescription(
      `Match #${matchId} updated:\n**${target.displayName}** replaces the ghost player.\n\n` +
      `⚔️ **${target.displayName}** vs **${otherName}**\n\n` +
      (byeMatchIdx !== -1 ? `🗑️ ${target.displayName}'s BYE win was removed — they now play a real match.` : '')
    )
    .setColor(0x2ECC71)
    .setFooter({ text: `Swapped in by ${msg.member.user.username}` });
  await msg.channel.send({ embeds: [embed] });

  saveData(data);
});

// ── weaponroles: post the reaction-role embed for weapon mains ───────────────
cmd(['weaponroles', 'weaponmains', 'wroles'], async (msg, args) => {
  if (!adminOnly(msg)) return;

  const sub = (args[0] || 'setup').toLowerCase();

  // ── !weaponroles setup ────────────────────────────────────────────────────
  if (sub === 'setup') {
    // Create any missing weapon roles in the server
    const guild = msg.guild;
    await msg.channel.send('⚙️ Setting up weapon roles…');

    for (const w of WEAPONS) {
      const exists = guild.roles.cache.find(r => r.name === w.role);
      if (!exists) {
        try {
          await guild.roles.create({ name: w.role, mentionable: false, reason: 'Weapon main reaction role' });
        } catch (e) {
          console.log(`Could not create role "${w.role}": ${e.message}`);
        }
      }
    }

    const lines = WEAPONS.map(w => `<:${w.emoji}> — **${w.name}**`).join('\n');

    const embed = new EmbedBuilder()
      .setTitle('⚔️ What\'s Your Main Weapon?')
      .setDescription(lines)
      .setColor(0xE67E22)
      .setFooter({ text: 'React to pick your weapon main (max 2)' });

    const sentMsg = await msg.channel.send({ embeds: [embed] });

    // React with every weapon emoji in order
    for (const w of WEAPONS) {
      try { await sentMsg.react(w.emoji); } catch { /* emoji may not render */ }
    }

    // Persist the message/channel ID and reset all selections (fresh embed = fresh slate)
    const data = loadData();
    data.weaponRoleMessageId  = sentMsg.id;
    data.weaponRoleChannelId  = sentMsg.channel.id;
    data.weaponSelections     = {};
    saveData(data);

    await msg.delete().catch(() => {});
    return;
  }

  // ── !weaponroles clear @user ─────────────────────────────────────────────
  if (sub === 'clear') {
    const target = msg.mentions.members.first();
    if (!target) return msg.reply('❌ Mention a user: `!weaponroles clear @user`');

    const weaponRoleNames = new Set(WEAPONS.map(w => w.role));
    const toRemove = target.roles.cache.filter(r => weaponRoleNames.has(r.name));
    for (const [, role] of toRemove) {
      await target.roles.remove(role).catch(() => {});
    }

    const data = loadData();
    if (data.weaponSelections) delete data.weaponSelections[target.id];
    saveData(data);

    return msg.reply(`✅ Cleared all weapon roles from **${target.displayName}**.`);
  }

  msg.reply('❌ Usage: `!weaponroles setup` | `!weaponroles clear @user`');
});

cmd(['duel', 'match', 'startmatch'], async (msg) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'in_progress') return msg.reply('❌ No tournament is currently running.');

  await fetchMembers(msg.guild);

  // Find the match for the two players — either mentioned or the caller's own match
  const mentioned = msg.mentions.members.first();
  const callerId  = msg.author.id;

  let match = null;
  const allPending = t.matches.filter(m => m.state === 'pending' && m.p1 !== null && m.p2 !== null);

  if (mentioned) {
    match = allPending.find(m =>
      (String(m.p1) === callerId && String(m.p2) === mentioned.id) ||
      (String(m.p2) === callerId && String(m.p1) === mentioned.id) ||
      (String(m.p1) === mentioned.id) ||
      (String(m.p2) === mentioned.id)
    );
  } else {
    match = allPending.find(m =>
      String(m.p1) === callerId || String(m.p2) === callerId
    );
  }

  if (!match) return msg.reply('❌ No pending match found for those players this tournament.');
  if (match.duelChannelId) {
    const existing = msg.guild.channels.cache.get(match.duelChannelId);
    if (existing) return msg.reply(`⚔️ A duel channel already exists: ${existing}`);
    match.duelChannelId = null; // stale ref — re-create
  }

  const p1 = msg.guild.members.cache.get(String(match.p1));
  const p2 = msg.guild.members.cache.get(String(match.p2));
  if (!p1 || !p2) return msg.reply('❌ Could not find both players in this server.');

  const rounds     = [...new Set(t.matches.map(m => m.round))].sort((a, b) => a - b);
  const totalR     = rounds.length;
  const roundLabel = match.round === totalR ? 'Final' : match.round === totalR - 1 ? 'Semi-Final' : `Round ${match.round}`;

  // Safe channel name: lowercase, no spaces, max 100 chars
  const safeName = (s) => s.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 20) || 'player';
  const channelName = `match-${safeName(p1.user.username)}-vs-${safeName(p2.user.username)}`;

  // Build permission overwrites
  const overwrites = [
    { id: msg.guild.roles.everyone, deny: [PermissionsBitField.Flags.ViewChannel] },
    { id: p1.id, allow: [PermissionsBitField.Flags.ViewChannel, PermissionsBitField.Flags.SendMessages, PermissionsBitField.Flags.ReadMessageHistory] },
    { id: p2.id, allow: [PermissionsBitField.Flags.ViewChannel, PermissionsBitField.Flags.SendMessages, PermissionsBitField.Flags.ReadMessageHistory] },
  ];
  // Give admins and Tournament Admin role access too
  const adminRole = msg.guild.roles.cache.find(r => r.name.toLowerCase() === 'tournament admin');
  if (adminRole) overwrites.push({ id: adminRole.id, allow: [PermissionsBitField.Flags.ViewChannel, PermissionsBitField.Flags.SendMessages, PermissionsBitField.Flags.ReadMessageHistory] });

  let duelChannel;
  try {
    duelChannel = await msg.guild.channels.create({
      name: channelName,
      type: ChannelType.GuildText,
      permissionOverwrites: overwrites,
      reason: `Duel channel for match #${match.id}`,
    });
  } catch (err) {
    console.error('[duel] channel create failed:', err);
    return msg.reply('❌ Failed to create the channel. Make sure the bot has **Manage Channels** permission.');
  }

  match.duelChannelId = duelChannel.id;
  saveData(data);

  // Welcome embed inside the new channel
  const embed = new EmbedBuilder()
    .setTitle(`⚔️ ${roundLabel} — Match #${match.id}`)
    .setDescription(
      `Welcome to your private match room!\n\n` +
      `🔵 **${p1.user.username}**\n` +
      `🔴 **${p2.user.username}**\n\n` +
      `Play your match, then ask an admin to report the result with \`!pick @winner\`.\n` +
      `This channel will be **automatically deleted** once the result is submitted.`
    )
    .setColor(0xE74C3C)
    .setFooter({ text: `${t.name} • ${roundLabel} of ${totalR} rounds` });

  await duelChannel.send({ content: `${p1} ${p2}`, embeds: [embed] });
  await msg.reply(`✅ Match room created: ${duelChannel}`);
});

cmd('announce', async (msg) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'in_progress') return msg.reply('No tournament in progress.');
  const pending = pendingMatches(t.matches);
  if (!pending.length) return msg.reply('No pending matches to announce.');
  const lines = pending.map(m => {
    const p1m = msg.guild.members.cache.get(String(m.p1));
    const p2m = m.p2 ? msg.guild.members.cache.get(String(m.p2)) : null;
    const p1 = p1m ? `<@${m.p1}>` : String(m.p1);
    const p2 = p2m ? `<@${m.p2}>` : (m.p2 ? String(m.p2) : 'BYE');
    return `Match **#${m.id}**: ${p1} vs ${p2}`;
  });
  msg.channel.send(`📣 **Round ${currentRound(t.matches)} — Fight!**\n${lines.join('\n')}`);
});

cmd('end', async (msg) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  if (!data.tournament) return msg.reply('No active tournament.');
  data.tournament.state = 'ended';
  saveData(data);
  msg.reply('🛑 Tournament has been ended.');
});

cmd(['sub', 'substitute', 'replace', 'swap'], async (msg, args) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const t = data.tournament;
  if (!t || (t.state !== 'in_progress' && t.state !== 'registration'))
    return msg.reply('❌ No active tournament to substitute players in.');

  await fetchMembers(msg.guild);

  const mentions = [...msg.mentions.members.values()];

  // ── Resolve OLD player (must be in the tournament) ───────────────────────
  // Auto-detect from the two mentions: whichever is IN the tournament is "out"
  let oldMember = null, newMember = null;

  if (mentions.length >= 2) {
    const [a, b] = mentions;
    const aIn = t.players.includes(a.id);
    const bIn = t.players.includes(b.id);
    if (aIn && !bIn)       { oldMember = a; newMember = b; }
    else if (bIn && !aIn)  { oldMember = b; newMember = a; }
    else if (aIn && bIn)   return msg.reply('❌ Both players are already in the tournament.');
    else                   return msg.reply(`❌ Neither player is in the tournament. Mention the player to remove first.`);
  } else if (mentions.length === 1) {
    // One mention + one raw ID in args: `!sub @oldplayer 123456789`
    const rawId = args.find(a => /^\d{15,20}$/.test(a) && !msg.content.includes(`<@${a}>`) && !msg.content.includes(`<@!${a}>`));
    if (!rawId) return msg.reply('❌ Usage: `!sub @player_in_tournament @replacement`\nOr: `!sub @player_in_tournament <userID>`');
    const solo = mentions[0];
    if (t.players.includes(solo.id)) {
      oldMember = solo;
      // Try to resolve new player by ID
      const resolved = msg.guild.members.cache.get(rawId) || await msg.guild.members.fetch(rawId).catch(() => null);
      if (!resolved) return msg.reply(`❌ Could not find a server member with ID \`${rawId}\`.`);
      newMember = resolved;
    } else {
      return msg.reply(`❌ **${solo.user.username}** is not in this tournament.`);
    }
  } else {
    return msg.reply('❌ Usage: `!sub @player_in_tournament @replacement`');
  }

  if (oldMember.id === newMember.id) return msg.reply('❌ Both players are the same person.');
  if (t.players.includes(newMember.id))
    return msg.reply(`❌ **${newMember.user.username}** is already in this tournament.`);

  const oldId = oldMember.id;
  const newId = newMember.id;

  // Swap in player roster
  t.players = t.players.map(id => id === oldId ? newId : id);

  // Swap in all pending matches (leave completed matches as historical record)
  let matchesAffected = 0;
  for (const m of t.matches) {
    if (m.state !== 'pending') continue;
    let changed = false;
    if (String(m.p1) === oldId) { m.p1 = newId; changed = true; }
    if (String(m.p2) === oldId) { m.p2 = newId; changed = true; }
    if (changed) {
      matchesAffected++;
      await closeDuelChannel(msg.guild, m);
    }
  }

  saveData(data);

  const embed = new EmbedBuilder()
    .setTitle('🔄 Player Substituted')
    .setDescription(
      `**Out:** ${oldMember.user.username}\n` +
      `**In:**  ${newMember.user.username}\n\n` +
      `${matchesAffected} pending match${matchesAffected !== 1 ? 'es' : ''} updated.` +
      (matchesAffected > 0 ? `\nDuel channels removed — use \`!duel\` to recreate them.` : '')
    )
    .setColor(0x3498DB)
    .setFooter({ text: `Substituted by ${msg.member.user.username}` });
  await msg.channel.send({ embeds: [embed] });
});

cmd(['rematch', 'rematch'], async (msg, args) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  if (!data.tournament) return msg.reply('No previous tournament to rematch.');
  const oldPlayers = data.tournament.players;
  const name = args.join(' ') || `${data.tournament.name} (Rematch)`;
  data.tournament = {
    name,
    state: 'registration',
    players: [...oldPlayers],
    matches: [],
    current_round: 1,
    winner: null,
    created_by: msg.author.id,
    created_at: new Date().toISOString(),
  };
  saveData(data);
  msg.reply(`🔄 **${name}** created with the same ${oldPlayers.length} players. Use \`!start\` to begin.`);
});

cmd('top3', async (msg) => {
  const data = loadData();
  const sorted = Object.entries(data.elo).sort((a, b) => b[1].elo - a[1].elo).slice(0, 3);
  if (sorted.length < 1) return msg.reply('No ELO data yet.');
  await fetchMembers(msg.guild);
  const buf  = await buildTop3Image(sorted, msg.guild);
  const att  = new AttachmentBuilder(buf, { name: 'top3.png' });
  msg.channel.send({ files: [att] });
});

cmd(['mymatch', 'mynext', 'mygame'], async (msg) => {
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'in_progress') return msg.reply('❌ No tournament is currently running.');
  if (!t.matches || !t.matches.length) return msg.reply('❌ No bracket generated yet.');

  await fetchMembers(msg.guild);

  function mname(uid) {
    if (uid === null) return 'BYE';
    const mem = msg.guild.members.cache.get(String(uid));
    return mem ? mem.displayName : `User#${String(uid).slice(-4)}`;
  }

  const uid = msg.author.id;
  const r = currentRound(t.matches);

  // Find the player's pending match in the current round first
  let match = t.matches.find(m =>
    m.round === r && m.state === 'pending' &&
    (String(m.p1) === uid || String(m.p2) === uid)
  );

  // If not in current round, check if they already won and are waiting for next round
  if (!match) {
    const nextRound = r + 1;
    match = t.matches.find(m =>
      m.round === nextRound && m.state === 'pending' &&
      (String(m.p1) === uid || String(m.p2) === uid)
    );
  }

  if (!match) {
    // Check if they were eliminated
    const lost = t.matches.some(m =>
      m.state === 'done' && m.winner !== null &&
      (String(m.p1) === uid || String(m.p2) === uid) &&
      String(m.winner) !== uid
    );
    if (lost) return msg.reply('😔 You\'ve been eliminated from the tournament. Better luck next time!');
    return msg.reply('❌ You don\'t have a match scheduled right now.');
  }

  const opponent = String(match.p1) === uid ? match.p2 : match.p1;
  const oppName  = mname(opponent);
  const round    = match.round;
  const rounds   = [...new Set(t.matches.map(m => m.round))].sort((a, b) => a - b);
  const totalR   = rounds.length;
  const roundLabel = round === totalR ? '🏆 **Final**' : round === totalR - 1 ? '🥊 **Semi-Final**' : `⚔️ **Round ${round}**`;

  const embed = new EmbedBuilder()
    .setTitle('🎮 Your Next Match')
    .setDescription(
      `${roundLabel}\n\n` +
      `**You:** ${msg.member.displayName}\n` +
      `**vs**\n` +
      `**Opponent:** ${oppName}\n\n` +
      `Match ID: \`[${String(match.id).padStart(2, '0')}]\``
    )
    .setColor(0xE74C3C)
    .setFooter({ text: `Round ${round} of ${totalR} • Report result with !win @opponent or !lose` });
  msg.reply({ embeds: [embed] });
});

cmd('elo', async (msg) => {
  const data = loadData();
  const sorted = Object.entries(data.elo).sort((a, b) => b[1].elo - a[1].elo).slice(0, 20);
  if (!sorted.length) return msg.reply('No ELO data yet.');
  const medals = ['🥇', '🥈', '🥉', ...Array(17).fill('🔹')];
  const lines = sorted.map(([id, s], i) => {
    const m    = msg.guild.members.cache.get(id);
    const name = m ? m.displayName : `<${id}>`;
    const rank = getRank(s.elo);
    return `${medals[i]} **${name}** — ${s.elo} ELO (${rank.name}) | ${s.wins}W ${s.losses}L`;
  });
  const embed = new EmbedBuilder()
    .setTitle('📊 ELO Leaderboard')
    .setDescription(lines.join('\n'))
    .setColor(0xFFD700);
  msg.channel.send({ embeds: [embed] });
});

cmd('resetelo', async (msg) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  data.elo = {};
  saveData(data);
  msg.reply('⚠️ ELO leaderboard has been reset.');
});

cmd('stats', async (msg) => {
  const data = loadData();
  const target = msg.mentions.members.first() || msg.member;
  const s = data.elo[target.id];
  if (!s) return msg.reply(`**${target.displayName}** has no stats yet.`);
  const total   = s.wins + s.losses;
  const winrate = total > 0 ? Math.round(s.wins / total * 100) : 0;
  const rank    = getRank(s.elo);
  const embed = new EmbedBuilder()
    .setTitle(`📈 ${target.displayName} — Tournament Stats`)
    .setColor(parseInt(rank.color.replace('#', ''), 16))
    .setThumbnail(target.displayAvatarURL())
    .addFields(
      { name: 'ELO',           value: `**${s.elo}**`,          inline: true },
      { name: 'Rank',          value: `**${rank.name}**`,       inline: true },
      { name: 'Wins',          value: `**${s.wins}**`,          inline: true },
      { name: 'Losses',        value: `**${s.losses}**`,        inline: true },
      { name: 'Win Rate',      value: `**${winrate}%**`,        inline: true },
      { name: 'Tournaments Won', value: `**${s.tournaments}**`, inline: true },
    );
  msg.channel.send({ embeds: [embed] });
});

cmd('history', async (msg) => {
  const data = loadData();
  const hist = data.history;
  if (!hist.length) return msg.reply('No completed tournaments yet.');
  const lines = [...hist].reverse().slice(0, 10).map((h, i) => {
    const w = msg.guild.members.cache.get(String(h.winner));
    const wname = w ? w.displayName : `<${h.winner}>`;
    const date = h.date.slice(0, 10);
    return `\`${i + 1}.\` **${h.name}** — 🥇 ${wname} (${h.players} players) — ${date}`;
  });
  const embed = new EmbedBuilder()
    .setTitle('📜 Tournament History')
    .setDescription(lines.join('\n'))
    .setColor(0x95A5A6);
  msg.channel.send({ embeds: [embed] });
});

cmd(['commands', 'help_brawl', 'cmds'], async (msg) => {
  const adminTag = isAdmin(msg) ? '' : ' *(admin only)*';
  const embed = new EmbedBuilder()
    .setTitle('⚔️ Brawlhalla Tournament Bot — Commands')
    .setColor(0xFFD700)
    .addFields(
      { name: '🏆 Tournament (🔒 Admin)', value: '`!create [name]` — Create a tournament\n`!start` — Start with ELO seeding\n`!start random` — Random draw\n`!end` — Force end tournament\n`!rematch [name]` — New tournament with same players\n`!announce` — Ping players for pending matches\n`!remind` — Remind players who haven\'t played yet', inline: false },
      { name: '📋 Tournament (Public)', value: '`!seedings` — Preview ELO seed order\n`!bracket` — Show bracket\n`!matches` — Pending matches this round', inline: false },
      { name: '👥 Players', value: '`!register` — Join the tournament\n`!unregister` — Leave before start\n`!players` — List registered players\n`!addjoin @player` 🔒 — Force-add a player\n`!joinbyid <userId>` 🔒 — Add by Discord ID\n`!removejoin @player` 🔒 — Remove a player', inline: false },
      { name: '🎮 Matches 🔒', value: '`!pick @winner` 🔒 — Admin direct result\n`!report @winner` — Submit result (requires admin approval)\n`!approve <matchId>` 🔒 — Approve a pending report\n`!deny <matchId>` 🔒 — Reject a pending report\n`!reportid <id> <userId>` 🔒 — Submit by user ID\n`!duel @p1 @p2` 🔒 — Open private duel channel\n`!kick @player` 🔒 — Remove a player\n`!kickmatch <id>` 🔒 — Remove ghost (left server) from match by ID\n`!swapin <id> @player` 🔒 — Swap player into match (replaces ghost, removes their BYE win)', inline: false },
      { name: '📊 Stats', value: '`!top3` — Podium of top 3 players\n`!elo` — ELO leaderboard\n`!stats [@player]` — Player stats\n`!mvp` — MVP of current tournament\n`!history` — Past tournaments\n`!resetelo` 🔒 — Wipe the leaderboard', inline: false },
      { name: '⚔️ Weapon Mains', value: '`!weaponroles setup` 🔒 — Post the weapon-pick embed (creates roles automatically)\n`!weaponroles clear @player` 🔒 — Remove all weapon roles from a player\nReact to the embed to pick up to **2** weapon mains. Picking a 3rd auto-removes the oldest.', inline: false },
      { name: '🎲 Fun', value: '`!coinflip` — Flip a coin to decide stage-pick order', inline: false },
    )
    .setFooter({ text: '🔒 = Admin only (Administrator permission or "Tournament Admin" role)' });
  msg.channel.send({ embeds: [embed] });
});


// ── !remind — ping players who have not yet played their current match ──────
cmd('remind', async (msg) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  const t = data.tournament;
  if (!t || t.state !== 'in_progress') return msg.reply('❌ No tournament is currently in progress.');

  await fetchMembers(msg.guild);

  const pending = pendingMatches(t.matches);
  const round   = currentRound(t.matches);
  const rounds  = [...new Set(t.matches.map(m => m.round))].sort((a, b) => a - b);
  const totalR  = rounds.length;
  const roundPending = pending.filter(m => m.p2 !== null); // skip BYEs
  if (!roundPending.length) return msg.reply('✅ No pending matches this round — everyone has played!');

  function mname(uid) {
    const mem = msg.guild.members.cache.get(String(uid));
    return mem ? mem.user.username : `User#${String(uid).slice(-4)}`;
  }

  // Create a server invite (reusable, 24h, unlimited uses)
  let inviteUrl = null;
  try {
    const invite = await msg.channel.createInvite({ maxAge: 86400, maxUses: 0, unique: false, reason: 'Tournament reminder' });
    inviteUrl = invite.url;
  } catch {
    // Bot may lack CREATE_INSTANT_INVITE — fall back gracefully
  }

  // Direct link to the tournament channel
  const channelUrl = `https://discord.com/channels/${msg.guild.id}/${msg.channel.id}`;

  const pings     = [];
  const dmResults = [];

  for (const m of roundPending) {
    const p1 = msg.guild.members.cache.get(String(m.p1));
    const p2 = msg.guild.members.cache.get(String(m.p2));
    const p1str = p1 ? `<@${m.p1}>` : `\`${m.p1}\``;
    const p2str = p2 ? `<@${m.p2}>` : `\`${m.p2}\``;
    pings.push(`${p1str} vs ${p2str} — Match **#${m.id}**`);

    // DM each player about their opponent
    for (const [player, opponent] of [[p1, p2], [p2, p1]]) {
      if (!player) continue;
      const oppName = opponent ? opponent.user.username : mname(m.p1 === player.id ? m.p2 : m.p1);

      const linkLines = [`🔗 [Jump to tournament channel](${channelUrl})`];
      if (inviteUrl) linkLines.push(`📨 [Server invite link](${inviteUrl})`);

      const dmEmbed = new EmbedBuilder()
        .setTitle('⏰ Reminder — You have a match to play!')
        .setDescription(
          `**Tournament:** ${t.name}\n` +
          `**Round:** ${round} of ${totalR}\n` +
          `**Match ID:** \`[${String(m.id).padStart(2, '0')}]\`\n\n` +
          `🆚 Your opponent is **${oppName}**\n\n` +
          `Contact them and play your match, then have an admin report the result with \`!pick @winner\`.\n\n` +
          linkLines.join('\n')
        )
        .setColor(0xFF6B35)
        .setFooter({ text: `${t.name} • Round ${round} of ${totalR}` });

      try {
        await player.send({ embeds: [dmEmbed] });
        dmResults.push(`✅ DM sent → **${player.user.username}**`);
      } catch {
        dmResults.push(`⚠️ Couldn't DM **${player.user.username}** (DMs closed)`);
      }
    }
  }

  // Channel embed with @mentions
  const channelEmbed = new EmbedBuilder()
    .setTitle('⏰ Match Reminder — Play Your Match!')
    .setDescription(`The following players still have a pending match this round:\n\n${pings.join('\n')}`)
    .setColor(0xFF6B35)
    .setFooter({ text: 'A DM has been sent to each player with their opponent info' });
  await msg.channel.send({ embeds: [channelEmbed] });

  // Admin-only summary of DM delivery
  const summaryEmbed = new EmbedBuilder()
    .setTitle('📬 DM Delivery Report')
    .setDescription(dmResults.join('\n'))
    .setColor(dmResults.some(r => r.startsWith('⚠️')) ? 0xE67E22 : 0x2ECC71);
  await msg.reply({ embeds: [summaryEmbed] });
});

// ── !mvp — most wins in the current tournament ──────────────────────────────
cmd('mvp', async (msg) => {
  const data = loadData();
  const t = data.tournament;
  if (!t) return msg.reply('❌ No tournament data found.');
  const completedMatches = t.matches.filter(m => m.winner);
  if (!completedMatches.length) return msg.reply('❌ No completed matches yet this tournament.');

  const winsMap = {};
  for (const m of completedMatches) {
    winsMap[m.winner] = (winsMap[m.winner] || 0) + 1;
  }
  const sorted = Object.entries(winsMap).sort((a, b) => b[1] - a[1]);
  const [topId, topWins] = sorted[0];
  const member = msg.guild.members.cache.get(String(topId));
  const name = member ? member.displayName : `User \`${topId}\``;
  const avatar = member ? member.user.displayAvatarURL({ size: 64 }) : null;

  const lines = sorted.slice(0, 5).map(([id, w], i) => {
    const m = msg.guild.members.cache.get(String(id));
    const n = m ? m.displayName : `\`${id}\``;
    const medal = ['🥇', '🥈', '🥉'][i] || `${i + 1}.`;
    return `${medal} **${n}** — ${w} win${w !== 1 ? 's' : ''}`;
  });

  const embed = new EmbedBuilder()
    .setTitle(`🌟 Tournament MVP — ${t.name}`)
    .setDescription(lines.join('\n'))
    .setColor(0xFFD700)
    .setFooter({ text: `${topWins} win${topWins !== 1 ? 's' : ''} so far` });
  if (avatar) embed.setThumbnail(avatar);
  msg.channel.send({ embeds: [embed] });
});

// ── !coinflip — decide who picks the stage ──────────────────────────────────
cmd(['coinflip', 'flip', 'coin'], async (msg) => {
  const result = Math.random() < 0.5 ? '🌕 Heads' : '🌑 Tails';
  const mentioned = msg.mentions.users.first();
  const challenger = msg.author;
  const embed = new EmbedBuilder()
    .setTitle('🪙 Coin Flip!')
    .setColor(0xF1C40F)
    .setFooter({ text: 'Stage picker goes first — good luck!' });

  if (mentioned) {
    const winner = Math.random() < 0.5 ? challenger : mentioned;
    embed.setDescription(`**${result}**\n\n<@${winner.id}> wins the flip and picks the stage first!`);
  } else {
    embed.setDescription(`**${result}**`);
  }
  msg.channel.send({ embeds: [embed] });
});

// ── !setlog — set this channel as the bot activity log channel ───────────────
cmd('setlog', async (msg) => {
  if (!adminOnly(msg)) return;
  const data = loadData();
  data.logChannelId = msg.channel.id;
  _logChannelId = msg.channel.id;
  saveData(data);
  const embed = new EmbedBuilder()
    .setTitle('📋 Log Channel Set')
    .setDescription(`All bot activity will now be logged in <#${msg.channel.id}>.\n\nUse \`!unsetlog\` to disable logging.`)
    .setColor(0x2ECC71)
    .setTimestamp();
  await msg.channel.send({ embeds: [embed] });
  await botLog('📋 Log Channel Configured', `Log channel set to <#${msg.channel.id}> by **${msg.member.displayName}**.`, 0x2ECC71);
});

cmd('unsetlog', async (msg) => {
  if (!adminOnly(msg)) return;
  await botLog('🔕 Logging Disabled', `Log channel removed by **${msg.member.displayName}**. No further logs will be sent.`, 0xE67E22);
  const data = loadData();
  delete data.logChannelId;
  _logChannelId = null;
  saveData(data);
  msg.reply('🔕 Bot logging disabled.');
});

// ── Events ─────────────────────────────────────────────────────────────────

client.once('clientReady', async () => {
  console.log(`${client.user.tag} is online!`);
  client.user.setActivity('Brawlhalla for Kurd', { type: ActivityType.Streaming, url: 'https://www.twitch.tv/discord' });

  // Load persisted log channel
  const startData = loadData();
  if (startData.logChannelId) _logChannelId = startData.logChannelId;

  const guild = client.guilds.cache.get(GUILD_ID);
  if (guild) {
    // Fetch all members on startup so the dashboard has names + avatars immediately
    try {
      await guild.members.fetch();
      const startData2 = loadData();
      if (!startData2.profiles) startData2.profiles = {};
      guild.members.cache.forEach(member => {
        startData2.profiles[member.id] = {
          name:   member.displayName,
          avatar: member.user.displayAvatarURL({ size: 128, extension: 'png' }),
        };
      });
      saveData(startData2);
      console.log(`Saved ${guild.members.cache.size} player profiles`);
    } catch (e) {
      console.log(`Profile fetch error: ${e.message}`);
    }

  }

  await botLog(
    '🟢 Bot Online',
    `**${client.user.tag}** has connected and is ready.\n\nUse \`!setlog\` in any channel to direct logs there.`,
    0x2ECC71
  );
});

// ── Single messageCreate handler (commands + message logging) ────────────────
client.on('messageCreate', async (msg) => {
  if (msg.author.bot) return;
  if (!msg.guild) return;

  // ── Command handling ──────────────────────────────────────────────────────
  if (msg.content.startsWith(PREFIX)) {
    const parts   = msg.content.slice(PREFIX.length).trim().split(/\s+/);
    const name    = parts[0].toLowerCase();
    const args    = parts.slice(1);
    const handler = commands.get(name);

    if (handler) {
      if (name !== 'setlog') {
        const preview = msg.content.length > 120 ? msg.content.slice(0, 120) + '…' : msg.content;
        botLog(
          `⌨️ \`!${name}\``,
          `**User:** ${msg.member?.displayName ?? msg.author.username} (\`${msg.author.id}\`)\n**Channel:** <#${msg.channel.id}>\n**Full command:** \`${preview}\``,
          0x3498DB
        ).catch(() => {});
      }

      try {
        await handler(msg, args, client);
      } catch (err) {
        console.error(err);
        botLog(
          '❌ Command Error',
          `**Command:** \`!${name}\`\n**User:** ${msg.member?.displayName ?? msg.author.username}\n**Error:** ${err.message}`,
          0xE74C3C
        ).catch(() => {});
        msg.reply(`❌ Error: ${err.message}`);
      }
      return; // don't also log this as a plain message
    }
  }

  // ── Log non-command messages ──────────────────────────────────────────────
  if (!_logChannelId) return;
  if (msg.channel.id === _logChannelId) return;

  const content     = msg.content.length > 300 ? msg.content.slice(0, 300) + '…' : (msg.content || '*(no text)*');
  const attachments = msg.attachments.size > 0 ? `\n📎 ${msg.attachments.size} attachment(s)` : '';

  await botLog(
    `💬 Message in #${msg.channel.name}`,
    `**${msg.member?.displayName ?? msg.author.username}** (\`${msg.author.id}\`):\n${content}${attachments}`,
    0x778CA3
  );
});

// ── Log message edits ────────────────────────────────────────────────────────
client.on('messageUpdate', async (oldMsg, newMsg) => {
  if (!_logChannelId) return;
  if (!newMsg.author || newMsg.author.bot) return;
  if (newMsg.channel.id === _logChannelId) return;
  if (!newMsg.guild) return;
  if (oldMsg.content === newMsg.content) return; // embed expansion, not a real edit

  const before = (oldMsg.content || '*(unknown)*').slice(0, 200);
  const after  = (newMsg.content || '*(empty)*').slice(0, 200);

  await botLog(
    `✏️ Message Edited in #${newMsg.channel.name}`,
    `**${newMsg.member?.displayName ?? newMsg.author.username}** (\`${newMsg.author.id}\`)\n\n**Before:** ${before}\n**After:** ${after}`,
    0xF39C12
  );
});

// ── Log message deletes ──────────────────────────────────────────────────────
client.on('messageDelete', async (msg) => {
  if (!_logChannelId) return;
  if (msg.author?.bot) return;
  if (msg.channel.id === _logChannelId) return;
  if (!msg.guild) return;

  const content = (msg.content || '*(no text / not cached)*').slice(0, 300);
  const who = msg.member?.displayName ?? msg.author?.username ?? '*(unknown)*';

  await botLog(
    `🗑️ Message Deleted in #${msg.channel.name}`,
    `**${who}** (\`${msg.author?.id ?? '?'}\`):\n${content}`,
    0xE74C3C
  );
});

// ── Weapon reaction-role handlers ────────────────────────────────────────────

// Helper: get or create a weapon role by name
async function getOrCreateWeaponRole(guild, roleName) {
  let role = guild.roles.cache.find(r => r.name === roleName);
  if (!role) {
    role = await guild.roles.create({ name: roleName, mentionable: false, reason: 'Weapon main reaction role' });
  }
  return role;
}

client.on('messageReactionAdd', async (reaction, user) => {
  if (user.bot) return;

  // Fetch partial objects if needed
  try {
    if (reaction.partial) await reaction.fetch();
    if (reaction.message.partial) await reaction.message.fetch();
  } catch { return; }

  const data = loadData();
  if (!data.weaponRoleMessageId) return;
  if (reaction.message.id !== data.weaponRoleMessageId) return;

  const emojiKey = reaction.emoji.id;
  const weapon = WEAPON_EMOJI_MAP.get(emojiKey);
  if (!weapon) return;

  const guild  = reaction.message.guild;
  const member = await guild.members.fetch(user.id).catch(() => null);
  if (!member) return;

  const role = await getOrCreateWeaponRole(guild, weapon.role);

  // Track selections per user (ordered list)
  if (!data.weaponSelections) data.weaponSelections = {};
  const selections = data.weaponSelections[user.id] || [];

  // Already has this weapon role — nothing to do
  if (selections.includes(weapon.name)) return;

  // Hard limit — silently remove the reaction, no role given
  if (selections.length >= MAX_WEAPON_ROLES) {
    await reaction.users.remove(user.id).catch(() => {});
    return;
  }

  selections.push(weapon.name);
  data.weaponSelections[user.id] = selections;
  saveData(data);

  await member.roles.add(role).catch(() => {});
});

client.on('messageReactionRemove', async (reaction, user) => {
  if (user.bot) return;

  try {
    if (reaction.partial) await reaction.fetch();
    if (reaction.message.partial) await reaction.message.fetch();
  } catch { return; }

  const data = loadData();
  if (!data.weaponRoleMessageId) return;
  if (reaction.message.id !== data.weaponRoleMessageId) return;

  const emojiKey = reaction.emoji.id;
  const weapon = WEAPON_EMOJI_MAP.get(emojiKey);
  if (!weapon) return;

  const guild  = reaction.message.guild;
  const member = await guild.members.fetch(user.id).catch(() => null);
  if (!member) return;

  // Remove role
  const role = guild.roles.cache.find(r => r.name === weapon.role);
  if (role) await member.roles.remove(role).catch(() => {});

  // Remove from selection tracking
  if (data.weaponSelections && data.weaponSelections[user.id]) {
    data.weaponSelections[user.id] = data.weaponSelections[user.id].filter(n => n !== weapon.name);
  }
  saveData(data);
});

// ── Log members joining / leaving ────────────────────────────────────────────
client.on('guildMemberAdd', async (member) => {
  await botLog(
    '📥 Member Joined',
    `**${member.displayName}** (\`${member.id}\`) joined the server.\nAccount created: <t:${Math.floor(member.user.createdTimestamp / 1000)}:R>`,
    0x2ECC71
  );
});

client.on('guildMemberRemove', async (member) => {
  await botLog(
    '📤 Member Left',
    `**${member.displayName}** (\`${member.id}\`) left (or was kicked from) the server.`,
    0xE67E22
  );
});

// ── Keep-alive web server ──────────────────────────────────────────────────

const app  = express();
const PORT = parseInt(process.env.BOT_PORT || '8082');
const HEALTH_PORT = 8099;

// Keep-alive health check on 8099
http.createServer((_, res) => res.end('ok')).listen(HEALTH_PORT, '0.0.0.0');

app.use(express.static(path.join(__dirname, 'public')));

app.get('/ping', (_, res) => res.send('Bot is alive!'));

app.get('/api/leaderboard', (_, res) => {
  const data = loadData();
  const guild = client.guilds.cache.get(GUILD_ID);
  const entries = Object.entries(data.elo)
    .sort((a, b) => b[1].elo - a[1].elo)
    .map(([id, s], i) => {
      const member = guild ? guild.members.cache.get(id) : null;
      const total = s.wins + s.losses;
      return {
        rank: i + 1,
        id,
        name: member ? member.displayName : `Player ${id.slice(-4)}`,
        avatar: member ? member.displayAvatarURL({ size: 64, extension: 'png' }) : null,
        elo: s.elo,
        wins: s.wins,
        losses: s.losses,
        winrate: total > 0 ? Math.round(s.wins / total * 100) : 0,
        tournaments: s.tournaments || 0,
        rankName: getRank(s.elo).name,
        rankColor: getRank(s.elo).color,
      };
    });
  res.json(entries);
});

app.get('/api/tournament', (_, res) => {
  const data = loadData();
  const guild = client.guilds.cache.get(GUILD_ID);
  const t = data.tournament;
  if (!t) return res.json(null);

  function memberName(id) {
    if (!id) return 'BYE';
    const m = guild ? guild.members.cache.get(String(id)) : null;
    return m ? m.displayName : `Player ${String(id).slice(-4)}`;
  }

  const matches = (t.matches || []).map(m => ({
    ...m,
    p1Name: memberName(m.p1),
    p2Name: memberName(m.p2),
    winnerName: m.winner ? memberName(m.winner) : null,
  }));

  const players = (t.players || []).map(id => ({
    id,
    name: memberName(id),
    elo: (data.elo[String(id)] || {}).elo || DEFAULT_ELO,
  }));

  res.json({ ...t, matches, players });
});

app.get('/api/history', (_, res) => {
  const data = loadData();
  const guild = client.guilds.cache.get(GUILD_ID);
  const history = [...(data.history || [])].reverse().map((h, i) => {
    const w = guild ? guild.members.cache.get(String(h.winner)) : null;
    return {
      ...h,
      winnerName: w ? w.displayName : `Player ${String(h.winner).slice(-4)}`,
      winnerAvatar: w ? w.displayAvatarURL({ size: 64, extension: 'png' }) : null,
    };
  });
  res.json(history);
});

app.listen(PORT, '0.0.0.0', () => console.log(`Web dashboard on port ${PORT}`));

// ── Start bot ──────────────────────────────────────────────────────────────

const TOKEN = process.env.DISCORD_TOKEN;
if (!TOKEN) {
  console.warn('WARNING: DISCORD_TOKEN not set. Web dashboard is running but bot is offline. Player names will show as short IDs until the bot connects.');
} else {
  client.login(TOKEN).catch(err => {
    console.error('Failed to login to Discord:', err.message);
  });
}
