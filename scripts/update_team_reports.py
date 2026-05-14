#!/usr/bin/env python3
"""update_team_reports.py — 月次チーム詳報更新スクリプト

ESPN API + NBA Stats からデータを収集し、Gemini API で30チーム分の
詳報を生成して NBAlandscape.html に反映する。

Usage:
    python scripts/update_team_reports.py [--dry-run]

Environment:
    GEMINI_API_KEY  — Gemini API キー（必須）

References:
    - team_report_methodology.md（出力仕様、ライティングルール）
    - prompt_methodology.md（既存Gemini統合の方法論）
"""

import os
import sys
import json
import re
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from datetime import datetime, timezone, timedelta

# ═══════════════════════════════════════
#  設定
# ═══════════════════════════════════════

GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.0-flash')
HTML_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'NBAlandscape.html')

# NBAシーズン年を動的に計算 (10月以降は翌年がシーズン年)
def _nba_season_year():
    now = datetime.now()
    return now.year + 1 if now.month >= 10 else now.year

def _nba_season_str():
    y = _nba_season_year()
    return f'{y-1}-{str(y)[2:]}'

NBA_SEASON_YEAR = _nba_season_year()

ESPN_STANDINGS_URL = f'https://site.api.espn.com/apis/v2/sports/basketball/nba/standings?season={NBA_SEASON_YEAR}'
ESPN_NEWS_URL = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news?limit=30'

# NBA Stats (Advanced Team Stats)
NBA_STATS_TEAM_URL = (
    'https://stats.nba.com/stats/leaguedashteamstats'
    '?Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment='
    '&Height=&ISTRound=&LastNGames=0&LeagueID=00&Location='
    '&MeasureType=Advanced&Month=0&OpponentTeamID=0&Outcome='
    '&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0'
    '&PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=N'
    f'&Season={_nba_season_str()}&SeasonSegment=&SeasonType=Regular+Season'
    '&ShotClockRange=&StarterBench=&TeamID=0&TwoWay=0'
    '&VsConference=&VsDivision='
)

# NBA Stats (Per-Game Player Stats, top scorers)
NBA_STATS_PLAYER_URL = (
    'https://stats.nba.com/stats/leaguedashplayerstats'
    '?Conference=&DateFrom=&DateTo=&Division=&GameScope=&GameSegment='
    '&Height=&ISTRound=&LastNGames=0&LeagueID=00&Location='
    '&MeasureType=Base&Month=0&OpponentTeamID=0&Outcome='
    '&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0'
    '&PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=N'
    f'&Season={_nba_season_str()}&SeasonSegment=&SeasonType=Regular+Season'
    '&ShotClockRange=&StarterBench=&TeamID=0&TwoWay=0'
    '&VsConference=&VsDivision='
)

NBA_STATS_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.nba.com/',
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
    'Origin': 'https://www.nba.com',
}

# ESPN略称 → 内部略称（NBAlandscape.htmlのid属性と対応）
ESPN_ABBR_MAP = {
    'OKC': 'OKC', 'SA': 'SAS', 'HOU': 'HOU', 'DEN': 'DEN', 'LAL': 'LAL',
    'MIN': 'MIN', 'PHX': 'PHX', 'GS': 'GSW', 'POR': 'POR', 'LAC': 'LAC',
    'MEM': 'MEM', 'DAL': 'DAL', 'UTAH': 'UTA', 'NO': 'NOP', 'SAC': 'SAC',
    'CLE': 'CLE', 'BOS': 'BOS', 'NY': 'NYK', 'MIL': 'MIL', 'IND': 'IND',
    'ORL': 'ORL', 'MIA': 'MIA', 'DET': 'DET', 'ATL': 'ATL', 'CHI': 'CHI',
    'PHI': 'PHI', 'TOR': 'TOR', 'BKN': 'BKN', 'CHA': 'CHA', 'WSH': 'WAS',
}

# 内部略称 → HTMLのid属性
TEAMS = {
    'OKC': {'id': 'okc', 'name': 'Oklahoma City Thunder', 'conf': 'west'},
    'SAS': {'id': 'sas', 'name': 'San Antonio Spurs', 'conf': 'west'},
    'HOU': {'id': 'hou', 'name': 'Houston Rockets', 'conf': 'west'},
    'DEN': {'id': 'den', 'name': 'Denver Nuggets', 'conf': 'west'},
    'LAL': {'id': 'lal', 'name': 'Los Angeles Lakers', 'conf': 'west'},
    'MIN': {'id': 'min', 'name': 'Minnesota Timberwolves', 'conf': 'west'},
    'PHX': {'id': 'phx', 'name': 'Phoenix Suns', 'conf': 'west'},
    'GSW': {'id': 'gsw', 'name': 'Golden State Warriors', 'conf': 'west'},
    'POR': {'id': 'por', 'name': 'Portland Trail Blazers', 'conf': 'west'},
    'LAC': {'id': 'lac', 'name': 'LA Clippers', 'conf': 'west'},
    'MEM': {'id': 'mem', 'name': 'Memphis Grizzlies', 'conf': 'west'},
    'DAL': {'id': 'dal', 'name': 'Dallas Mavericks', 'conf': 'west'},
    'UTA': {'id': 'uta', 'name': 'Utah Jazz', 'conf': 'west'},
    'NOP': {'id': 'nop', 'name': 'New Orleans Pelicans', 'conf': 'west'},
    'SAC': {'id': 'sac', 'name': 'Sacramento Kings', 'conf': 'west'},
    'DET': {'id': 'det', 'name': 'Detroit Pistons', 'conf': 'east'},
    'BOS': {'id': 'bos', 'name': 'Boston Celtics', 'conf': 'east'},
    'NYK': {'id': 'nyk', 'name': 'New York Knicks', 'conf': 'east'},
    'CLE': {'id': 'cle', 'name': 'Cleveland Cavaliers', 'conf': 'east'},
    'TOR': {'id': 'tor', 'name': 'Toronto Raptors', 'conf': 'east'},
    'PHI': {'id': 'phi', 'name': 'Philadelphia 76ers', 'conf': 'east'},
    'ORL': {'id': 'orl', 'name': 'Orlando Magic', 'conf': 'east'},
    'MIA': {'id': 'mia', 'name': 'Miami Heat', 'conf': 'east'},
    'ATL': {'id': 'atl', 'name': 'Atlanta Hawks', 'conf': 'east'},
    'CHA': {'id': 'cha', 'name': 'Charlotte Hornets', 'conf': 'east'},
    'CHI': {'id': 'chi', 'name': 'Chicago Bulls', 'conf': 'east'},
    'MIL': {'id': 'mil', 'name': 'Milwaukee Bucks', 'conf': 'east'},
    'BKN': {'id': 'bkn', 'name': 'Brooklyn Nets', 'conf': 'east'},
    'WAS': {'id': 'was', 'name': 'Washington Wizards', 'conf': 'east'},
    'IND': {'id': 'ind', 'name': 'Indiana Pacers', 'conf': 'east'},
}

# NBA Stats チーム名 → 内部略称
NBA_STATS_TEAM_MAP = {
    'Oklahoma City Thunder': 'OKC', 'San Antonio Spurs': 'SAS',
    'Houston Rockets': 'HOU', 'Denver Nuggets': 'DEN',
    'Los Angeles Lakers': 'LAL', 'Minnesota Timberwolves': 'MIN',
    'Phoenix Suns': 'PHX', 'Golden State Warriors': 'GSW',
    'Portland Trail Blazers': 'POR', 'LA Clippers': 'LAC',
    'Memphis Grizzlies': 'MEM', 'Dallas Mavericks': 'DAL',
    'Utah Jazz': 'UTA', 'New Orleans Pelicans': 'NOP',
    'Sacramento Kings': 'SAC', 'Detroit Pistons': 'DET',
    'Boston Celtics': 'BOS', 'New York Knicks': 'NYK',
    'Cleveland Cavaliers': 'CLE', 'Toronto Raptors': 'TOR',
    'Philadelphia 76ers': 'PHI', 'Orlando Magic': 'ORL',
    'Miami Heat': 'MIA', 'Atlanta Hawks': 'ATL',
    'Charlotte Hornets': 'CHA', 'Chicago Bulls': 'CHI',
    'Milwaukee Bucks': 'MIL', 'Brooklyn Nets': 'BKN',
    'Washington Wizards': 'WAS', 'Indiana Pacers': 'IND',
}

ESPN_NAME_TO_ABBR = {}
for abbr, t in TEAMS.items():
    ESPN_NAME_TO_ABBR[t['name']] = abbr
    if t['name'] == 'LA Clippers':
        ESPN_NAME_TO_ABBR['Los Angeles Clippers'] = abbr


# ═══════════════════════════════════════
#  HTTP ユーティリティ
# ═══════════════════════════════════════

def fetch_json(url, headers=None, timeout=15, label=''):
    """URLからJSONを取得。失敗時はNoneを返す。"""
    h = headers or {}
    req = Request(url, headers=h)
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            print(f'  ✓ {label or url[:60]}')
            return data
    except (HTTPError, URLError, json.JSONDecodeError, TimeoutError) as e:
        print(f'  ✗ {label or url[:60]}: {e}')
        return None


# ═══════════════════════════════════════
#  データ収集
# ═══════════════════════════════════════

def collect_standings():
    """ESPN Standings API → {abbr: {record, seed, streak, l10, diff, ppg, oppg}}"""
    print('\n[1/4] ESPN Standings API...')
    data = fetch_json(ESPN_STANDINGS_URL, label='ESPN Standings')
    if not data:
        return {}

    result = {}
    for conf in (data.get('children') or []):
        for entry in (conf.get('standings', {}).get('entries') or []):
            espn_abbr = entry.get('team', {}).get('abbreviation', '')
            abbr = ESPN_ABBR_MAP.get(espn_abbr, espn_abbr)
            if abbr not in TEAMS:
                continue

            def stat_val(name):
                for s in (entry.get('stats') or []):
                    if s.get('name') == name or s.get('type') == name:
                        return s.get('displayValue', str(s.get('value', '')))
                return ''

            result[abbr] = {
                'record': stat_val('overall'),
                'seed': stat_val('playoffSeed'),
                'streak': stat_val('streak'),
                'l10': stat_val('Last Ten Games'),
                'diff': stat_val('differential'),
                'ppg': stat_val('avgPointsFor'),
                'oppg': stat_val('avgPointsAgainst'),
            }

    print(f'  → {len(result)} teams collected')
    return result


def collect_news():
    """ESPN News API → {abbr: [{type, headline, description}]}"""
    print('\n[2/4] ESPN News API...')
    data = fetch_json(ESPN_NEWS_URL, label='ESPN News')
    if not data:
        return {}

    grouped = {}
    for article in (data.get('articles') or []):
        if article.get('type') == 'Media':
            continue
        teams = [c.get('description', '') for c in (article.get('categories') or [])
                 if c.get('type') == 'team']
        for team_name in teams:
            abbr = ESPN_NAME_TO_ABBR.get(team_name)
            if not abbr:
                continue
            if abbr not in grouped:
                grouped[abbr] = []
            grouped[abbr].append({
                'type': article.get('type', ''),
                'headline': article.get('headline', ''),
                'description': article.get('description', ''),
            })

    print(f'  → {len(grouped)} teams with news')
    return grouped


def collect_team_advanced_stats():
    """NBA Stats API → {abbr: {ortg, drtg, net_rtg, pace, ...}}"""
    print('\n[3/4] NBA Stats Team Advanced...')
    data = fetch_json(NBA_STATS_TEAM_URL, headers=NBA_STATS_HEADERS,
                      timeout=20, label='NBA Stats Team Advanced')
    if not data:
        return {}

    result_sets = data.get('resultSets', [])
    if not result_sets:
        return {}

    headers_list = result_sets[0].get('headers', [])
    rows = result_sets[0].get('rowSet', [])

    # ヘッダーからインデックスを探す
    def idx(name):
        try:
            return headers_list.index(name)
        except ValueError:
            return None

    i_name = idx('TEAM_NAME')
    i_ortg = idx('OFF_RATING')
    i_drtg = idx('DEF_RATING')
    i_net = idx('NET_RATING')
    i_pace = idx('PACE')
    i_ts = idx('TS_PCT')

    result = {}
    for row in rows:
        team_name = row[i_name] if i_name is not None else ''
        abbr = NBA_STATS_TEAM_MAP.get(team_name)
        if not abbr:
            continue
        result[abbr] = {
            'ortg': round(row[i_ortg], 1) if i_ortg is not None and row[i_ortg] else '',
            'drtg': round(row[i_drtg], 1) if i_drtg is not None and row[i_drtg] else '',
            'net_rtg': round(row[i_net], 1) if i_net is not None and row[i_net] else '',
            'pace': round(row[i_pace], 1) if i_pace is not None and row[i_pace] else '',
            'ts_pct': round(row[i_ts] * 100, 1) if i_ts is not None and row[i_ts] else '',
        }

    print(f'  → {len(result)} teams collected')
    return result


def collect_player_stats():
    """NBA Stats Player API → {abbr: [{name, ppg, rpg, apg, ...}]}"""
    print('\n[4/4] NBA Stats Player Stats...')
    data = fetch_json(NBA_STATS_PLAYER_URL, headers=NBA_STATS_HEADERS,
                      timeout=20, label='NBA Stats Player Stats')
    if not data:
        return {}

    result_sets = data.get('resultSets', [])
    if not result_sets:
        return {}

    headers_list = result_sets[0].get('headers', [])
    rows = result_sets[0].get('rowSet', [])

    def idx(name):
        try:
            return headers_list.index(name)
        except ValueError:
            return None

    i_player = idx('PLAYER_NAME')
    i_team = idx('TEAM_ABBREVIATION')
    i_gp = idx('GP')
    i_ppg = idx('PTS')
    i_rpg = idx('REB')
    i_apg = idx('AST')
    i_fg = idx('FG_PCT')
    i_3p = idx('FG3_PCT')
    i_min = idx('MIN')

    # チームごとに選手をPPG順に集める
    team_players = {}
    for row in rows:
        team_abbr_raw = row[i_team] if i_team is not None else ''
        # NBA Stats の略称を内部略称にマッピング
        abbr = ESPN_ABBR_MAP.get(team_abbr_raw, team_abbr_raw)
        if abbr not in TEAMS:
            continue

        gp = row[i_gp] if i_gp is not None else 0
        if gp < 15:  # 出場試合が少なすぎる選手はスキップ
            continue

        ppg = row[i_ppg] if i_ppg is not None else 0
        player = {
            'name': row[i_player] if i_player is not None else '',
            'ppg': round(ppg, 1),
            'rpg': round(row[i_rpg], 1) if i_rpg is not None else 0,
            'apg': round(row[i_apg], 1) if i_apg is not None else 0,
            'fg_pct': round(row[i_fg] * 100, 1) if i_fg is not None and row[i_fg] else 0,
            'fg3_pct': round(row[i_3p] * 100, 1) if i_3p is not None and row[i_3p] else 0,
            'min': round(row[i_min], 1) if i_min is not None else 0,
            'gp': gp,
        }
        if abbr not in team_players:
            team_players[abbr] = []
        team_players[abbr].append(player)

    # 各チーム上位3選手を抽出
    result = {}
    for abbr, players in team_players.items():
        players.sort(key=lambda p: p['ppg'], reverse=True)
        result[abbr] = players[:3]

    print(f'  → {len(result)} teams with player data')
    return result


# ═══════════════════════════════════════
#  Gemini API
# ═══════════════════════════════════════

# ──────────────────────────────────────────────
#  プロンプト設計根拠（LLM-prompt論文フォルダより）
#
#  [CFPO, arxiv2502.04295]
#    セクションラベル + セパレータの明示で8-20pt改善。
#    → XMLタグでセクション構造化、コンポーネントを明確に分離。
#
#  [Format Impact, arxiv2408.02442]
#    厳しいJSON制約はreasoning品質を落とす。
#    responseMimeType で JSON を強制するため、prompt自体は
#    内容品質（文体・構成・情報選択）に集中させる。
#    → 出力形式セクションを簡素化、ライティング指示を充実。
#
#  [Prompt Report, arxiv2406.06608]
#    few-shot examples 3-5個で品質が決定的に向上。
#    self-verification 指示で精度向上。
#    → 実際の出力サンプル3個を <examples> に含める。
#
#  [Anthropic公式: Use XML tags]
#    XMLタグで命令とコンテキストの混同を防止。
#    → <role>, <task>, <rules>, <examples>, <output_format> で構造化。
#
#  [Anthropic公式: Give Claude a role]
#    具体的なロール設定で精度・一貫性が向上。
#    → 「家族の食卓で読める」「新聞のコラム欄風」の文脈を付与。
# ──────────────────────────────────────────────

SYSTEM_PROMPT = """<role>
あなたは日本のスポーツ新聞でNBAコラムを担当するベテランライターです。
読者は「NBAを最近見始めた家族」。食卓で読んでもらえる、カジュアルだが正確な文章を書きます。
常体（だ/である調）で、堅すぎず、データに裏打ちされた短文レポートが持ち味です。
</role>

<task>
提供されるデータ（順位表・チームスタッツ・選手スタッツ・ニュース）を読み、
NBA全30チームそれぞれに「tag」（キャッチフレーズ）と「body」（詳報本文）を生成してください。
</task>

<rules>
## キャッチフレーズ（tag）
- 3〜27文字。中央値14文字を目安に
- 新聞の見出し風。体言止めか短い述語で終わる
- チームの今季のストーリーを一行で伝える
- 上位チームは具体的な特徴を、下位チームは短く象徴的に

## 本文（body）
- 150〜320文字
- HTML <strong>タグで選手名・歴史的数字・リーグ順位称号を囲む（1〜8箇所）
- だ/である調。句点で区切る。読点は息継ぎの位置だけ
- 選手名はカタカナ表記。初出フルネーム、2回目以降はファミリーネーム
- 数字は半角。PPG, RPG 等の英語略語を併用
- 文長を揃えない。短文→長文→短文のリズムで
- 楽観で締めない。不確実性があれば最後に書く

## 構成パターン
上位チーム（シード1-6位）:
  象徴的な数字 → エースのスタッツ → サポート選手 → 怪我/懸念 → トレード → 1文の展望
中位チーム（7-10位、プレーイン圏）:
  立ち位置 → キープレイヤー2-3人 → プラス材料 → マイナス材料
下位チーム（ロッタリー圏）:
  なぜこうなったか → 若手の成長 or アセット → 将来

## <strong> の判断基準
する: 選手名（主力・トレード目玉・ルーキー）、歴史的数字（24-1等）、リーグ順位称号（得点王、DRTG 1位）
しない: 一般的なスタッツ値（20 PPG等）、チーム名、日付

## 禁止
- 「注目です」「期待されます」のような空疎な結び
- 全チーム同じ文長
- 「〜の証です」「〜と言えるでしょう」系の修辞
- 文頭の「今季の」の繰り返し
- 下位チームを貶す表現
- 提供データにない情報の創作（自分の知識で補足しない）
</rules>

<examples>
以下は過去の出力例です。文体・文字数・bold使いの参考にしてください。

<example id="top_team">
チーム: OKC（西1位）
tag: 連覇を狙うディフェンシブ・マシン
body: 開幕<strong>24-1</strong>は2015-16ウォリアーズに並ぶ歴代最高記録。リーグ最高の守備レーティング（107.3 DRTG）とネットレーティング（+11.9）。<strong>SGA</strong>が31.8 PPG・40% 3PTでMVP最有力候補。<strong>チェット・ホルムグレン</strong>が初のオールスター。<strong>ケイソン・ウォレス</strong>がスティール王（2.1 SPG）。ただし直近10試合は5-5。SGAが腹部の故障でオールスター欠場、ジェイレン・ウィリアムズもハムストリングで離脱中。デッドラインで76ersから<strong>ジャレッド・マケイン</strong>を獲得し、若手の層を厚くした。怪我さえなければ連覇の本命。
</example>

<example id="mid_team">
チーム: CLE（東4位）
tag: 64勝の二日酔い、ハーデンに賭ける
body: 昨季<strong>64-18</strong>の輝きが嘘のように、<strong>ドノバン・ミッチェル</strong>をHOUへ放出。代わりに<strong>ジェイレン・グリーン</strong>と指名権を手に入れたが、チームケミストリーは未完成。<strong>ジェームズ・ハーデン</strong>がデッドラインでCHIから加入し、ダリアス・ガーランドとのバックコート再構築が急務。エバン・モーブリーが2年目の飛躍で21.2 PPGを記録しているのが救い。ただし守備は昨季のDRTG 1位から大きく後退。ハーデンのフィットに全てが懸かる。
</example>

<example id="bottom_team">
チーム: SAC（西15位）
tag: どん底
body: 開幕から崩壊が止まらず西の最下位に沈んだ。<strong>デアーロン・フォックス</strong>をHOUへ放出し、完全なリビルドに舵を切った。<strong>キーガン・マレー</strong>が残った数少ないアセットだが、24歳の彼を軸にした再建の青写真はまだ見えない。2026年と2027年のドラフト1巡目指名権を保有しており、ロッタリーでの上位指名が唯一の光。
</example>
</examples>

<output_format>
JSONオブジェクト。キーは3文字のチーム略称（大文字）。
各チームに "tag" と "body" の2フィールド。
</output_format>

<verification>
出力前に以下を確認してください:
- 30チーム全てのキーが揃っているか
- bodyの文字数が150〜320に収まっているか（HTMLタグを除いた純テキストで数える）
- <strong>タグの開始と閉じが対応しているか
- 提供データにない事実を書いていないか
- トレードの記述が送り側・受け側で矛盾していないか
</verification>"""


def build_user_prompt(standings, news, team_stats, player_stats):
    """収集データをXMLタグで構造化してプロンプトに統合

    [CFPO知見] コンポーネント間をXMLタグで明確に分離することで
    モデルがデータセクションと指示を混同するリスクを低減。
    [Anthropic公式] タグ名でデータを参照可能にする（"Using the data in <standings>..."）。
    """
    now_jst = datetime.now(timezone(timedelta(hours=9)))
    date_str = now_jst.strftime('%Y年%m月%d日')

    parts = [f'以下のデータ（{date_str} 取得）を使って、NBA全30チームの tag と body を生成してください。']
    parts.append('データは <standings>, <team_stats>, <player_stats>, <news> の4セクションに分かれています。')
    parts.append('')

    # --- Standings ---
    parts.append('<standings>')
    if standings:
        for conf_label, conf_key in [('Western', 'west'), ('Eastern', 'east')]:
            parts.append(f'## {conf_label} Conference')
            conf_teams = [(a, s) for a, s in standings.items()
                          if TEAMS.get(a, {}).get('conf') == conf_key]
            conf_teams.sort(key=lambda x: int(x[1].get('seed') or 99))
            for abbr, s in conf_teams:
                parts.append(
                    f"{abbr} ({s.get('seed','?')}位): {s.get('record','')} "
                    f"streak:{s.get('streak','')} L10:{s.get('l10','')} "
                    f"diff:{s.get('diff','')} PPG:{s.get('ppg','')} OppPPG:{s.get('oppg','')}"
                )
    else:
        parts.append('（取得失敗）')
    parts.append('</standings>')

    # --- Team Advanced Stats ---
    parts.append('')
    parts.append('<team_stats>')
    if team_stats:
        for abbr in sorted(team_stats.keys()):
            ts = team_stats[abbr]
            parts.append(
                f"{abbr}: ORTG:{ts.get('ortg','')} DRTG:{ts.get('drtg','')} "
                f"NetRTG:{ts.get('net_rtg','')} Pace:{ts.get('pace','')} "
                f"TS%:{ts.get('ts_pct','')}"
            )
    else:
        parts.append('（取得失敗 — <standings> のデータだけで書いてください）')
    parts.append('</team_stats>')

    # --- Player Stats ---
    parts.append('')
    parts.append('<player_stats>')
    if player_stats:
        for abbr in sorted(player_stats.keys()):
            players = player_stats[abbr]
            lines = []
            for p in players:
                lines.append(
                    f"  {p['name']}: {p['ppg']} PPG / {p['rpg']} RPG / {p['apg']} APG "
                    f"FG%:{p['fg_pct']} 3PT%:{p['fg3_pct']} ({p['gp']}GP)"
                )
            parts.append(f"[{abbr}]")
            parts.extend(lines)
    else:
        parts.append('（取得失敗 — <standings> と <news> だけで書いてください）')
    parts.append('</player_stats>')

    # --- News ---
    parts.append('')
    parts.append('<news>')
    if news:
        for abbr in sorted(news.keys()):
            for a in news[abbr][:2]:
                parts.append(
                    f"[{abbr}] ({a['type']}) {a['headline']}"
                    + (f" — {a['description']}" if a['description'] else '')
                )
    else:
        parts.append('（取得失敗）')
    parts.append('</news>')

    parts.append('')
    parts.append('上記4セクションのデータだけに基づいて、30チーム全ての tag と body を生成してください。')
    parts.append('データにない事実は書かないでください。')
    return '\n'.join(parts)


def call_gemini(system_prompt, user_prompt, api_key):
    """Gemini API を呼んで JSON を返す"""
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={api_key}'

    payload = json.dumps({
        'system_instruction': {'parts': [{'text': system_prompt}]},
        'contents': [{'parts': [{'text': user_prompt}]}],
        'generationConfig': {
            'temperature': 0.5,
            'maxOutputTokens': 16384,
            'responseMimeType': 'application/json',
        }
    }).encode('utf-8')

    req = Request(url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            with urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                raw = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
                # JSON抽出（```json ... ``` のラッパーを除去）
                cleaned = re.sub(r'^```json?\s*', '', raw.strip())
                cleaned = re.sub(r'\s*```$', '', cleaned).strip()

                try:
                    obj = json.loads(cleaned)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    # JSONブロックを探す
                    match = re.search(r'\{[\s\S]*\}', cleaned)
                    if match:
                        try:
                            return json.loads(match.group(0))
                        except json.JSONDecodeError:
                            pass

                if attempt < max_retries:
                    print(f'  ⚠ JSON parse failed, retrying ({attempt + 1}/{max_retries})...')
                    time.sleep(3)
                    continue
                raise ValueError(f'Gemini returned unparseable response: {raw[:200]}')

        except (HTTPError, URLError) as e:
            if attempt < max_retries:
                print(f'  ⚠ Gemini API error: {e}, retrying ({attempt + 1}/{max_retries})...')
                time.sleep(5)
                continue
            raise

    raise RuntimeError('Gemini API failed after retries')


# ═══════════════════════════════════════
#  HTML更新
# ═══════════════════════════════════════

def update_html(html_path, reports, standings):
    """NBAlandscape.html のチームカードを更新"""
    with open(html_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    now_jst = datetime.now(timezone(timedelta(hours=9)))
    date_str = now_jst.strftime('%Y/%m/%d %H:%M')

    updated_count = 0

    for abbr, report in reports.items():
        if abbr not in TEAMS:
            continue
        team_id = TEAMS[abbr]['id']
        tag_text = report.get('tag', '')
        body_html = report.get('body', '')
        record = standings.get(abbr, {}).get('record', '') if standings else ''
        seed = standings.get(abbr, {}).get('seed', '') if standings else ''

        if not tag_text or not body_html:
            continue

        # team-card の開始行を探す
        card_start = None
        for i, line in enumerate(lines):
            if f'id="{team_id}"' in line:
                card_start = i
                break

        if card_start is None:
            print(f'  ⚠ Card not found for {abbr} (id="{team_id}")')
            continue

        # card_start から10行以内を検索して更新
        for j in range(card_start, min(card_start + 12, len(lines))):
            # tch-rec（勝敗記録）
            if record and 'class="tch-rec"' in lines[j]:
                lines[j] = re.sub(
                    r'(<div class="tch-rec">)[^<]*(</div>)',
                    lambda m: m.group(1) + record + m.group(2),
                    lines[j]
                )

            # tch-rank（シード順位）
            if seed and 'class="tch-rank' in lines[j]:
                lines[j] = re.sub(
                    r'(<div class="tch-rank (?:west|east)">)\d*(</div>)',
                    lambda m: m.group(1) + str(seed) + m.group(2),
                    lines[j]
                )

            # tch-tag（キャッチフレーズ）
            if 'class="tch-tag"' in lines[j]:
                lines[j] = re.sub(
                    r'(<div class="tch-tag">)[^<]*(</div>)',
                    lambda m: m.group(1) + tag_text + m.group(2),
                    lines[j]
                )

            # tch-body（本文、<strong>タグ含む）
            if 'class="tch-body"' in lines[j]:
                lines[j] = re.sub(
                    r'(<div class="tch-body">).*?(</div>)',
                    lambda m: m.group(1) + body_html + m.group(2),
                    lines[j]
                )

        updated_count += 1

    # フッターの日付を更新 (id="footer-timestamp")
    for i, line in enumerate(lines):
        if 'データは' in line and ('時点' in line or 'footer-timestamp' in line):
            lines[i] = re.sub(
                r'データは[^。]*。',
                f'データは{date_str}時点（月次自動更新）。',
                lines[i]
            )
            break

    with open(html_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    return updated_count


# ═══════════════════════════════════════
#  品質チェック
# ═══════════════════════════════════════

def quality_check(reports):
    """team_report_methodology.md §4 の品質チェック"""
    print('\n[Quality Check]')
    warnings = []

    for abbr, r in reports.items():
        tag = r.get('tag', '')
        body = r.get('body', '')

        # 文字数チェック
        tag_len = len(tag)
        if tag_len < 3 or tag_len > 27:
            warnings.append(f'  {abbr}: tag length {tag_len} (expected 3-27)')

        # bodyからHTMLタグを除去して文字数カウント
        body_text = re.sub(r'<[^>]+>', '', body)
        body_len = len(body_text)
        if body_len < 120 or body_len > 350:  # 少し余裕を持たせる
            warnings.append(f'  {abbr}: body length {body_len} (expected ~150-320)')

        # bold数チェック
        bold_count = body.count('<strong>')
        if bold_count == 0:
            warnings.append(f'  {abbr}: no <strong> tags in body')
        elif bold_count > 10:
            warnings.append(f'  {abbr}: too many <strong> tags ({bold_count})')

    # 30チーム揃っているか
    missing = [a for a in TEAMS if a not in reports]
    if missing:
        warnings.append(f'  Missing teams: {", ".join(missing)}')

    if warnings:
        print(f'  ⚠ {len(warnings)} warnings:')
        for w in warnings:
            print(w)
    else:
        print('  ✓ All checks passed')

    return warnings


# ═══════════════════════════════════════
#  メイン
# ═══════════════════════════════════════

def main():
    dry_run = '--dry-run' in sys.argv

    api_key = os.environ.get('GEMINI_API_KEY', '')
    if not api_key:
        print('ERROR: GEMINI_API_KEY environment variable is required')
        sys.exit(1)

    if not os.path.exists(HTML_FILE):
        print(f'ERROR: {HTML_FILE} not found')
        sys.exit(1)

    print('=' * 60)
    print('NBA Team Report Monthly Update')
    print(f'Date: {datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST")}')
    print(f'Model: {GEMINI_MODEL}')
    print(f'Dry run: {dry_run}')
    print('=' * 60)

    # ── データ収集 ──
    standings = collect_standings()
    news = collect_news()
    team_stats = collect_team_advanced_stats()
    player_stats = collect_player_stats()

    if not standings:
        print('\nERROR: Standings data is required. Cannot continue.')
        sys.exit(1)

    # ── プロンプト構築 ──
    print('\n[Prompt] Building...')
    user_prompt = build_user_prompt(standings, news, team_stats, player_stats)
    print(f'  Prompt length: {len(user_prompt)} chars')

    # ── Gemini API ──
    print(f'\n[Gemini] Calling {GEMINI_MODEL}...')
    reports = call_gemini(SYSTEM_PROMPT, user_prompt, api_key)
    print(f'  → {len(reports)} team reports generated')

    # ── 品質チェック ──
    warnings = quality_check(reports)

    if dry_run:
        print('\n[Dry Run] Skipping HTML update.')
        print('\n--- Sample Output (first 3 teams) ---')
        for i, (abbr, r) in enumerate(reports.items()):
            if i >= 3:
                break
            print(f'\n{abbr}:')
            print(f'  tag: {r.get("tag", "")}')
            body_preview = r.get('body', '')[:100]
            print(f'  body: {body_preview}...')
        sys.exit(0)

    # ── HTML更新 ──
    print(f'\n[HTML] Updating {HTML_FILE}...')
    count = update_html(HTML_FILE, reports, standings)
    print(f'  → {count} team cards updated')

    # ── 結果サマリー ──
    print('\n' + '=' * 60)
    print(f'DONE: {count}/30 teams updated')
    if warnings:
        print(f'WARNINGS: {len(warnings)} (see above)')
    print('=' * 60)


if __name__ == '__main__':
    main()
