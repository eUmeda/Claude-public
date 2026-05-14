/**
 * nba-common.js — NBA/WNBA サイト共通モジュール
 *
 * 使い方: <script src="js/nba-common.js"></script>
 * 各ページの IIFE 内で NBACommon.* として参照。
 *
 * 2026-02-14 初版
 */
const NBACommon = (function () {
  'use strict';

  // ═══ NBA 30 Teams ═══
  // key = ESPN abbreviation
  const NBA_TEAMS = {
    OKC:  {id:1610612760, ja:'サンダー',       slug:'thunder',       elId:'okc',  conf:'west'},
    SA:   {id:1610612759, ja:'スパーズ',       slug:'spurs',         elId:'sas',  conf:'west'},
    HOU:  {id:1610612745, ja:'ロケッツ',       slug:'rockets',       elId:'hou',  conf:'west'},
    DEN:  {id:1610612743, ja:'ナゲッツ',       slug:'nuggets',       elId:'den',  conf:'west'},
    LAL:  {id:1610612747, ja:'レイカーズ',     slug:'lakers',        elId:'lal',  conf:'west'},
    MIN:  {id:1610612750, ja:'ウルブズ',       slug:'timberwolves',  elId:'min',  conf:'west'},
    PHX:  {id:1610612756, ja:'サンズ',         slug:'suns',          elId:'phx',  conf:'west'},
    GS:   {id:1610612744, ja:'ウォリアーズ',   slug:'warriors',      elId:'gsw',  conf:'west'},
    POR:  {id:1610612757, ja:'ブレイザーズ',   slug:'blazers',       elId:'por',  conf:'west'},
    LAC:  {id:1610612746, ja:'クリッパーズ',   slug:'clippers',      elId:'lac',  conf:'west'},
    MEM:  {id:1610612763, ja:'グリズリーズ',   slug:'grizzlies',     elId:'mem',  conf:'west'},
    DAL:  {id:1610612742, ja:'マーベリックス', slug:'mavericks',     elId:'dal',  conf:'west'},
    UTAH: {id:1610612762, ja:'ジャズ',         slug:'jazz',          elId:'uta',  conf:'west'},
    NO:   {id:1610612740, ja:'ペリカンズ',     slug:'pelicans',      elId:'nop',  conf:'west'},
    SAC:  {id:1610612758, ja:'キングス',       slug:'kings',         elId:'sac',  conf:'west'},
    DET:  {id:1610612765, ja:'ピストンズ',     slug:'pistons',       elId:'det',  conf:'east'},
    BOS:  {id:1610612738, ja:'セルティックス', slug:'celtics',       elId:'bos',  conf:'east'},
    NY:   {id:1610612752, ja:'ニックス',       slug:'knicks',        elId:'nyk',  conf:'east'},
    CLE:  {id:1610612739, ja:'キャバリアーズ', slug:'cavaliers',     elId:'cle',  conf:'east'},
    TOR:  {id:1610612761, ja:'ラプターズ',     slug:'raptors',       elId:'tor',  conf:'east'},
    PHI:  {id:1610612755, ja:'76ers',          slug:'sixers',        elId:'phi',  conf:'east'},
    ORL:  {id:1610612753, ja:'マジック',       slug:'magic',         elId:'orl',  conf:'east'},
    MIA:  {id:1610612748, ja:'ヒート',         slug:'heat',          elId:'mia',  conf:'east'},
    ATL:  {id:1610612737, ja:'ホークス',       slug:'hawks',         elId:'atl',  conf:'east'},
    CHA:  {id:1610612766, ja:'ホーネッツ',     slug:'hornets',       elId:'cha',  conf:'east'},
    CHI:  {id:1610612741, ja:'ブルズ',         slug:'bulls',         elId:'chi',  conf:'east'},
    MIL:  {id:1610612749, ja:'バックス',       slug:'bucks',         elId:'mil',  conf:'east'},
    BKN:  {id:1610612751, ja:'ネッツ',         slug:'nets',          elId:'bkn',  conf:'east'},
    WSH:  {id:1610612764, ja:'ウィザーズ',     slug:'wizards',       elId:'was',  conf:'east'},
    IND:  {id:1610612754, ja:'ペイサーズ',     slug:'pacers',        elId:'ind',  conf:'east'}
  };

  // ═══ WNBA 13 Teams ═══
  const WNBA_TEAMS = {
    ATL:  {id:20,     ja:'ドリーム',       slug:'dream',         conf:'east'},
    CHI:  {id:19,     ja:'スカイ',         slug:'sky',           conf:'east'},
    CON:  {id:18,     ja:'サン',           slug:'sun',           conf:'east'},
    IND:  {id:3,      ja:'フィーバー',     slug:'fever',         conf:'east'},
    NY:   {id:17,     ja:'リバティ',       slug:'liberty',       conf:'east'},
    WSH:  {id:14,     ja:'ミスティクス',   slug:'mystics',       conf:'east'},
    DAL:  {id:16,     ja:'ウィングス',     slug:'wings',         conf:'west'},
    GS:   {id:129689, ja:'ヴァルキリーズ', slug:'valkyries',     conf:'west'},
    LV:   {id:6,      ja:'エイシズ',       slug:'aces',          conf:'west'},
    LA:   {id:8,      ja:'スパークス',     slug:'sparks',        conf:'west'},
    MIN:  {id:7,      ja:'リンクス',       slug:'lynx',          conf:'west'},
    PHX:  {id:9,      ja:'マーキュリー',   slug:'mercury',       conf:'west'},
    SEA:  {id:5,      ja:'ストーム',       slug:'storm',         conf:'west'}
  };

  // ═══ Season Utilities ═══
  function getNBASeason() {
    const now = new Date();
    return now.getMonth() >= 9 ? now.getFullYear() + 1 : now.getFullYear();
  }

  function getSeasonPhase() {
    const now = new Date();
    const m = now.getMonth() + 1;
    const d = now.getDate();
    if (m >= 10 || m === 9) return 'preseason';
    if (m >= 7) return 'offseason';
    if (m === 6 || (m === 5 && d >= 15)) return 'finals';
    if (m >= 4) return 'playoffs';
    if (m === 2 && d >= 10 && d <= 20) return 'allstar';
    if (m === 2 && d >= 1 && d < 10) return 'deadline';
    return 'regular';
  }

  const PHASE_LABELS = {
    preseason: 'プレシーズン',
    regular:   'レギュラーシーズン',
    deadline:  'トレードデッドライン',
    allstar:   'オールスターブレイク',
    playoffs:  'プレーオフ',
    finals:    'NBAファイナル',
    offseason: 'オフシーズン'
  };

  // ═══ Logo Helpers ═══
  function logoUrl(nbaId) {
    return `https://cdn.nba.com/logos/nba/${nbaId}/global/L/logo.svg`;
  }
  function espnLogo(abbr) {
    return `https://a.espncdn.com/i/teamlogos/nba/500/${abbr.toLowerCase()}.png`;
  }
  function wnbaLogo(teamId) {
    return `https://a.espncdn.com/combiner/i?img=/i/teamlogos/wnba/500/${teamId}.png&h=100&w=100`;
  }

  // ═══ ESPN Data Helpers ═══
  function stat(entry, name) {
    const s = (entry.stats || []).find(s => s.name === name || s.type === name);
    return s ? (s.displayValue || s.value) : '';
  }

  async function fetchJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${url}`);
    return r.json();
  }

  // ═══ ESPN API URLs ═══
  function standingsURL(league, season) {
    const s = season || getNBASeason();
    const l = league || 'nba';
    return `https://site.api.espn.com/apis/v2/sports/basketball/${l}/standings?season=${s}`;
  }
  function scoreboardURL(league, params) {
    const l = league || 'nba';
    const p = params ? '?' + new URLSearchParams(params).toString() : '';
    return `https://site.api.espn.com/apis/site/v2/sports/basketball/${l}/scoreboard${p}`;
  }
  function teamsURL(league) {
    const l = league || 'nba';
    return `https://site.api.espn.com/apis/site/v2/sports/basketball/${l}/teams`;
  }
  function draftURL() {
    return 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/draft';
  }

  // ═══ Site Navigation ═══
  const SITE_PAGES = [
    { href: 'NBAlandscape.html',  label: 'NBA勢力図',    icon: '🗺️' },
    { href: 'playoffs.html',      label: 'プレーオフ',    icon: '🏆' },
    { href: 'offseason.html',     label: 'オフシーズン',  icon: '☀️' },
    { href: 'gleague-wnba.html',  label: 'WNBA/GL',      icon: '🏀' },
    { href: 'basketball-research-map.html', label: '研究', icon: '📚' }
  ];

  function buildSiteNav(currentPage) {
    const phase = getSeasonPhase();
    const phaseHighlight = {
      'regular': 'NBAlandscape.html',
      'deadline': 'NBAlandscape.html',
      'allstar': 'NBAlandscape.html',
      'playoffs': 'playoffs.html',
      'finals': 'playoffs.html',
      'offseason': 'offseason.html',
      'preseason': 'offseason.html'
    };

    return SITE_PAGES.map(p => {
      const isCurrent = p.href === currentPage;
      const isPhaseActive = phaseHighlight[phase] === p.href && !isCurrent;
      let cls = 'site-nav-link';
      if (isCurrent) cls += ' current';
      if (isPhaseActive) cls += ' phase-active';
      return `<a href="${p.href}" class="${cls}">${p.icon} ${p.label}</a>`;
    }).join('');
  }

  // ═══ Common CSS (inject into page) ═══
  const COMMON_CSS = `
    :root {
      --bg-deep: #0a0c10;
      --bg-card: #12151c;
      --bg-card-hover: #181c26;
      --accent-west: #e85d26;
      --accent-east: #2d7dd2;
      --accent-gold: #d4a843;
      --accent-red: #c9362c;
      --text-primary: #e8e6e1;
      --text-secondary: #8a8d95;
      --text-muted: #555960;
      --border: #1e222c;
    }
    * { margin:0; padding:0; box-sizing:border-box; }
    html { scroll-behavior:smooth; }
    body {
      font-family:'Noto Sans JP',sans-serif;
      background:var(--bg-deep);
      color:var(--text-primary);
      line-height:1.7;
    }
    a { color:var(--accent-gold); text-decoration:none; }
    a:hover { opacity:.8; }

    .site-nav {
      position:sticky; top:0; z-index:100;
      background:rgba(10,12,16,.92); backdrop-filter:blur(12px);
      border-bottom:1px solid var(--border);
      padding:.6rem 1.5rem;
      display:flex; align-items:center; gap:.8rem;
      overflow-x:auto; white-space:nowrap;
      scrollbar-width:none;
    }
    .site-nav::-webkit-scrollbar { display:none; }
    .site-nav-link {
      font-family:'Oswald',sans-serif;
      font-size:.68rem; letter-spacing:.12em;
      text-transform:uppercase;
      padding:.5rem .3rem;
      color:var(--text-secondary);
      transition:color .3s;
      border-bottom:2px solid transparent;
    }
    .site-nav-link:hover { color:var(--text-primary); opacity:1; }
    .site-nav-link.current {
      color:var(--accent-gold);
      border-bottom-color:var(--accent-gold);
    }
    .site-nav-link.phase-active {
      color:var(--accent-red);
      animation:phasePulse 2s infinite;
    }
    @keyframes phasePulse {
      0%,100%{opacity:1} 50%{opacity:.5}
    }

    .section {
      max-width:1100px; margin:0 auto; padding:4rem 1.5rem;
    }
    .section-header {
      margin-bottom:3rem; padding-bottom:1.5rem;
      border-bottom:1px solid var(--border);
    }
    .section-label {
      font-family:'Oswald',sans-serif;
      font-size:.65rem; letter-spacing:.4em;
      text-transform:uppercase; margin-bottom:.5rem;
    }
    .section-label.west { color:var(--accent-west); }
    .section-label.east { color:var(--accent-east); }
    .section-label.gold { color:var(--accent-gold); }
    .section-title {
      font-family:'Oswald',sans-serif;
      font-size:clamp(1.8rem,4vw,2.8rem);
      font-weight:600; line-height:1.15;
    }
    .section-intro {
      margin-top:1rem; font-size:.95rem;
      color:var(--text-secondary); max-width:720px; line-height:1.9;
    }

    .hero {
      position:relative; min-height:60vh;
      display:flex; flex-direction:column;
      justify-content:center; align-items:center;
      text-align:center; padding:2rem;
      background:radial-gradient(ellipse 80% 60% at 20% 80%,rgba(232,93,38,.08) 0%,transparent 50%),
                 radial-gradient(ellipse 80% 60% at 80% 20%,rgba(45,125,210,.08) 0%,transparent 50%),
                 var(--bg-deep);
    }
    .hero-label {
      font-family:'Oswald',sans-serif;
      font-size:.75rem; letter-spacing:.35em;
      text-transform:uppercase; color:var(--accent-gold);
      margin-bottom:1.5rem;
      opacity:0; animation:fadeUp .8s .2s forwards;
    }
    .hero h1 {
      font-family:'Oswald',sans-serif;
      font-size:clamp(2.2rem,5vw,4rem);
      font-weight:700; line-height:1.1;
      opacity:0; animation:fadeUp .8s .4s forwards;
    }
    .hero h1 .west { color:var(--accent-west); }
    .hero h1 .east { color:var(--accent-east); }
    .hero-sub {
      font-size:clamp(.9rem,1.8vw,1.1rem);
      color:var(--text-secondary);
      max-width:640px; line-height:1.9;
      margin-top:1rem;
      opacity:0; animation:fadeUp .8s .6s forwards;
    }
    @keyframes fadeUp {
      from{opacity:0;transform:translateY(20px)}
      to{opacity:1;transform:translateY(0)}
    }

    .footer {
      text-align:center; padding:3rem 1.5rem;
      border-top:1px solid var(--border);
      max-width:1100px; margin:0 auto;
    }
    .footer p { font-size:.72rem; color:var(--text-muted); line-height:1.7; }
    .footer-credit {
      margin-top:.8rem;
      font-family:'Oswald',sans-serif;
      font-size:.6rem; letter-spacing:.2em;
      color:var(--accent-gold); text-transform:uppercase;
    }

    .standings { width:100%; border-collapse:collapse; font-size:.82rem; }
    .standings th {
      font-family:'Oswald',sans-serif; font-size:.65rem;
      letter-spacing:.12em; text-transform:uppercase;
      color:var(--text-muted); padding:.6rem .5rem;
      text-align:left; border-bottom:1px solid var(--border);
    }
    .standings td { padding:.55rem .5rem; border-bottom:1px solid rgba(255,255,255,.03); vertical-align:middle; }
    .standings a { color:var(--text-primary); text-decoration:none; }
    .standings a:hover { color:var(--accent-gold); }
    .st-logo { width:22px; height:22px; vertical-align:middle; }
    .tier-top td:first-child { border-left:3px solid var(--accent-gold); }
    .tier-mid td:first-child { border-left:3px solid var(--accent-west); }
    .tier-playin td:first-child { border-left:3px solid rgba(255,255,255,.15); }
    .tier-out td:first-child { border-left:3px solid rgba(255,255,255,.05); }
    .tier-out { opacity:.55; }

    .table-wrap { overflow-x:auto; margin:0 auto; max-width:800px; }

    .game-card {
      flex-shrink:0; width:200px;
      background:var(--bg-card); border:1px solid var(--border);
      border-radius:6px; padding:.8rem; transition:border-color .3s;
    }
    .game-card:hover { border-color:rgba(212,168,67,.2); }
    .game-card.game-live { border-left:3px solid #e74c3c; }
    .game-card.game-final { opacity:.75; }
    .game-card.game-scheduled { opacity:.6; }
    .game-status {
      font-family:'Oswald',sans-serif;
      font-size:.6rem; letter-spacing:.1em;
      text-transform:uppercase; margin-bottom:.5rem; color:var(--text-muted);
    }
    .game-status.status-live { color:#e74c3c; }
    .game-status.status-final { color:var(--accent-gold); }
    .game-team { display:flex; align-items:center; gap:.5rem; padding:.25rem 0; font-size:.8rem; }
    .game-team-logo { width:20px; height:20px; }
    .game-team-abbr { flex:1; font-size:.78rem; }
    .game-team-score {
      font-family:'Oswald',sans-serif;
      font-size:1rem; font-weight:600; min-width:2rem; text-align:right;
    }
    .game-team.winner .game-team-score { color:var(--accent-gold); }
    .game-team.winner .game-team-abbr { color:var(--text-primary); font-weight:500; }

    .scoreboard-wrap {
      display:flex; gap:1rem; padding:1rem 0;
      overflow-x:auto; scrollbar-width:none;
    }
    .scoreboard-wrap::-webkit-scrollbar { display:none; }

    .tab-bar {
      display:flex; gap:0; border-bottom:1px solid var(--border);
      margin-bottom:2rem;
    }
    .tab-btn {
      font-family:'Oswald',sans-serif;
      font-size:.75rem; letter-spacing:.1em;
      text-transform:uppercase; padding:.8rem 1.5rem;
      background:none; border:none; color:var(--text-secondary);
      cursor:pointer; border-bottom:2px solid transparent;
      transition:color .3s, border-color .3s;
    }
    .tab-btn:hover { color:var(--text-primary); }
    .tab-btn.active { color:var(--accent-gold); border-bottom-color:var(--accent-gold); }
    .tab-panel { display:none; }
    .tab-panel.active { display:block; }

    .placeholder-msg {
      text-align:center; padding:4rem 2rem;
      color:var(--text-muted); font-size:.9rem;
    }
    .placeholder-msg .icon { font-size:3rem; margin-bottom:1rem; display:block; }
  `;

  function injectCSS() {
    if (document.getElementById('nba-common-css')) return;
    const style = document.createElement('style');
    style.id = 'nba-common-css';
    style.textContent = COMMON_CSS;
    document.head.appendChild(style);
  }

  // ═══ Scoreboard renderer (reusable) ═══
  function renderScoreboard(events, wrapEl, statusEl, league) {
    const lgStr = league || 'nba';
    if (!events.length) {
      wrapEl.innerHTML = '<div class="placeholder-msg">本日の試合はありません</div>';
      if (statusEl) statusEl.textContent = '試合なし';
      return false;
    }

    let hasLive = false;
    let html = '';
    for (const ev of events) {
      const comp = ev.competitions[0];
      const st = comp.status.type;
      const isLive = st.state === 'in';
      const isFinal = st.completed;
      const isScheduled = st.state === 'pre';
      if (isLive) hasLive = true;

      const away = comp.competitors.find(c => c.homeAway === 'away');
      const home = comp.competitors.find(c => c.homeAway === 'home');
      const awayWin = isFinal && Number(away.score) > Number(home.score);
      const homeWin = isFinal && Number(home.score) > Number(away.score);
      const statusClass = isLive ? 'status-live' : isFinal ? 'status-final' : '';
      const cardClass = isLive ? 'game-live' : isFinal ? 'game-final' : 'game-scheduled';

      let statusText = st.shortDetail || '';
      if (isScheduled) {
        const date = new Date(comp.date);
        statusText = date.toLocaleTimeString('ja-JP', {hour:'2-digit',minute:'2-digit',timeZone:'Asia/Tokyo'}) + ' JST';
      }

      const logoFn = lgStr === 'wnba' ? (a) => wnbaLogo(a) : (a) => espnLogo(a);

      html += `<div class="game-card ${cardClass}">
        <div class="game-status ${statusClass}">${statusText}</div>
        <div class="game-team ${awayWin?'winner':''}">
          <img class="game-team-logo" src="${logoFn(away.team.id || away.team.abbreviation)}" alt="${away.team.abbreviation}" onerror="this.style.display='none'" loading="lazy">
          <span class="game-team-abbr">${away.team.abbreviation}</span>
          <span class="game-team-score">${isScheduled?'':away.score}</span>
        </div>
        <div class="game-team ${homeWin?'winner':''}">
          <img class="game-team-logo" src="${logoFn(home.team.id || home.team.abbreviation)}" alt="${home.team.abbreviation}" onerror="this.style.display='none'" loading="lazy">
          <span class="game-team-abbr">${home.team.abbreviation}</span>
          <span class="game-team-score">${isScheduled?'':home.score}</span>
        </div>
      </div>`;
    }
    wrapEl.innerHTML = html;

    if (statusEl) {
      const now = new Date().toLocaleString('ja-JP', {timeZone:'Asia/Tokyo',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'});
      statusEl.textContent = (hasLive ? '🔴 ライブ更新中' : `${events.length}試合`) + ` ・ ${now} JST`;
    }
    return hasLive;
  }

  // ═══ Public API ═══
  return {
    NBA_TEAMS, WNBA_TEAMS,
    getNBASeason, getSeasonPhase, PHASE_LABELS,
    logoUrl, espnLogo, wnbaLogo,
    stat, fetchJSON,
    standingsURL, scoreboardURL, teamsURL, draftURL,
    buildSiteNav, injectCSS,
    renderScoreboard,
    SITE_PAGES
  };
})();
