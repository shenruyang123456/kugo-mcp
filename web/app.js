const $ = id => document.getElementById(id);
let current = null;
let busy = false;
let lastCover = '';
let recommendationsKey = '';
let lastLyrics = null;
let noticeUntil = 0;
let latestPoll = 0;
let lyricLines = [];
let lastLyricIndex = null;
const text = (id, value) => { $(id).textContent = value; };

function parseLyrics(lrc) {
  const entries = [];
  for (const line of (lrc || '').split(/\r?\n/)) {
    const stamps = [...line.matchAll(/\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]/g)];
    const content = line.replace(/\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]/g, '').trim();
    if (!content) continue;
    for (const stamp of stamps) {
      const fraction = Number((stamp[3] || '').padEnd(3, '0'));
      entries.push({time: (Number(stamp[1]) * 60 + Number(stamp[2])) * 1000 + fraction, text: content});
    }
  }
  return entries.sort((a, b) => a.time - b.time);
}

function updateLyric() {
  if (!current?.connected) { text('lyricCurrent', '等待连接酷狗'); lastLyricIndex = null; return; }
  if (!lyricLines.length) { text('lyricCurrent', current.lyrics_status || '暂无同步歌词'); return; }
  if (current.position_ms == null || !current.position_sampled_at || Date.now() - current.position_sampled_at > 6000) {
    text('lyricCurrent', '等待播放进度'); lastLyricIndex = null; return;
  }
  const elapsed = current.song?.playback === 'playing' ? Math.min(Math.max(Date.now() - current.position_sampled_at, 0), 3500) : 0;
  const position = current.position_ms + elapsed;
  let index = -1;
  for (let i = 0; i < lyricLines.length && lyricLines[i].time <= position; i++) index = i;
  if (index !== lastLyricIndex) {
    lastLyricIndex = index;
    text('lyricCurrent', index < 0 ? '前奏' : lyricLines[index].text);
  }
}

function display(data) {
  current = data;
  const song = data.song || {};
  const parts = (song.title || '').split(' - ');
  const title = parts.length > 1 ? parts.slice(1).join(' - ') : (song.title || '等待音乐');
  const artist = parts.length > 1 ? parts[0] : '连接酷狗后显示歌曲信息';
  text('title', title);
  text('artist', artist);
  text('mode', data.mode || '模式暂不可用');
  $('connection').classList.toggle('online', !!data.connected);
  $('connection').lastChild.textContent = data.connected ? ' 酷狗已连接' : ' 连接中断';
  $('retry').hidden = !!data.connected;
  if (!busy && Date.now() >= noticeUntil) text('notice', data.connected ? '' : data.message || '无法连接酷狗');
  const playing = song.playback === 'playing';
  $('play').disabled = !data.connected || busy;
  $('play').setAttribute('aria-label', playing ? '暂停' : '播放');
  $('play').setAttribute('title', playing ? '暂停' : '播放');
  text('playState', !data.connected ? '等待连接' : playing ? '播放中' : song.playback === 'stopped' ? '已停止' : '已暂停');
  $('playIcon').toggleAttribute('hidden', playing);
  $('pauseIcon').toggleAttribute('hidden', !playing);
  const lyricsKey = JSON.stringify([song.hash, data.lyrics, data.lyrics_status]);
  if (lyricsKey !== lastLyrics) {
    lastLyrics = lyricsKey;
    lyricLines = parseLyrics(data.lyrics);
    lastLyricIndex = null;
  }
  updateLyric();
  if ((data.cover || '') !== lastCover) {
    lastCover = data.cover || '';
    const image = $('coverImage');
    image.hidden = true;
    $('coverFallback').hidden = false;
    if (lastCover) {
      image.onload = () => { image.hidden = false; $('coverFallback').hidden = true; };
      image.onerror = () => { image.hidden = true; $('coverFallback').hidden = false; };
      image.src = lastCover;
    }
  }
  const rows = data.recommendations || [];
  const key = JSON.stringify([rows, data.daily_error]);
  if (key !== recommendationsKey) {
    recommendationsKey = key;
    const list = $('recommendations');
    list.replaceChildren();
    rows.forEach((item, index) => {
      const row = document.createElement('button'); row.className = 'rec'; row.type = 'button';
      row.disabled = !data.connected;
      row.setAttribute('aria-label', `播放 ${item.title || '未知歌曲'} ${item.artist || ''}`);
      row.addEventListener('click', () => runAction('/api/play-recommendation', {index: index + 1, hash: item.hash}));
      const number = document.createElement('span'); number.className = 'rec-number'; number.textContent = String(index + 1).padStart(2, '0');
      const info = document.createElement('div');
      const title = document.createElement('span'); title.className = 'rec-title'; title.textContent = item.title || '未知歌曲';
      const artist = document.createElement('span'); artist.className = 'rec-artist'; artist.textContent = item.artist || '未知歌手';
      info.append(title, artist); row.append(number, info); list.append(row);
    });
    if (!rows.length) { const empty = document.createElement('p'); empty.className = 'list-empty'; empty.textContent = data.daily_error || '暂无推荐'; list.append(empty); }
  }
  document.querySelectorAll('.rec').forEach(row => { row.disabled = !data.connected || busy; });
  text('count', rows.length ? String(rows.length).padStart(2, '0') : '—');
}
async function poll() {
  const request = ++latestPoll;
  try { const response = await fetch('/api/state', {cache:'no-store'}); if (!response.ok) throw Error('状态不可用'); const data = await response.json(); if (request === latestPoll) display(data); }
  catch { if (request === latestPoll) display({connected:false, message:'网页服务连接中断', recommendations: current?.recommendations || []}); }
}
async function runAction(path, payload) {
  if (busy || !current?.connected) return;
  busy = true; $('play').disabled = true; text('notice', '正在操作酷狗…');
  document.querySelectorAll('.rec').forEach(row => { row.disabled = true; });
  try {
    const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    if (!response.ok) { const data = await response.json(); throw Error(data.error || '操作失败'); }
    text('notice', '');
  } catch (error) { text('notice', error.message); noticeUntil = Date.now() + 4000; }
  finally { busy = false; await poll(); }
}
$('play').addEventListener('click', () => runAction('/api/control', {action: current?.song?.playback === 'playing' ? 'pause' : 'play'}));
async function refreshConnection() {
  try { await fetch('/api/refresh', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}); }
  finally { await poll(); }
}
$('retry').addEventListener('click', () => { text('notice', '正在重新读取酷狗…'); refreshConnection().catch(() => poll()); });
refreshConnection().catch(() => poll());
setInterval(poll, 1500); setInterval(updateLyric, 250);
