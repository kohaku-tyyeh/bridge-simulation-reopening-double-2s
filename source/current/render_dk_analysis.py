#!/usr/bin/env python3
"""Render the saved DK contract analysis as a Chinese PDF and PNG.

Usage: .venv/bin/python render_dk_analysis.py run_v5_10000
No deals, double-dummy tricks, or continuation Par are recomputed.
Inputs are saved run files only; no development /tmp data is used.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/bridge-report-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.font_manager import FontProperties, fontManager
from matplotlib.patches import Rectangle
import numpy as np

FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
if not FONT.exists():
    raise SystemExit(f"Required CJK font not found: {FONT}")
fontManager.addfont(str(FONT))
FP = FontProperties(fname=str(FONT))
plt.rcParams.update({
    "font.family": FP.get_name(), "font.size": 10,
    # Noto CJK TTC contains CFF outlines. Type 3 embeds vector glyphs without
    # incorrectly advertising those CFF outlines as a TrueType FontFile2.
    "axes.unicode_minus": False, "pdf.fonttype": 3,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": "#bdc7d1", "axes.labelcolor": "#324355",
    "xtick.color": "#324355", "ytick.color": "#324355",
})

INK = "#193249"
MUTED = "#506478"
BLUE = "#176f91"
TEAL = "#087e78"
RED = "#bf514b"
PALE = "#eef4f7"
GREY = "#94a5b2"
W, H = 12, 8.5
CHECKS = []

CATEGORY = {
    "NS_down": "我方宕約",
    "NS_making": "我方做成",
    "EW_2SX_available": "敵方 2♠X 可選",
    "EW_making_partscore": "敵方做成部分合約",
    "EW_making_game": "敵方做成成局",
    "EW_other_down": "敵方其他宕約",
    "mixed_NS_making_or_EW_down": "我方做成／敵方宕約同分",
}
HEART = {
    "A_present": "有 A（可帶其他大牌）",
    "KQ_or_KQJ": "KQ 或 KQJ；無 A",
    "K_or_KJ": "K 或 KJ；無 A、Q",
    "Q_or_QJ": "Q 或 QJ；無 A、K",
    "J_only": "只有 J",
    "no_AKQJ": "無 A、K、Q、J",
}
HEART_ORDER = list(HEART)


def pct(x, digits=2):
    return f"{x * 100:.{digits}f}%"


def signed(x, digits=3):
    return f"{x:+.{digits}f}"


def contract(s):
    side, bid = s.split()
    for ascii_suit, symbol in [("S", "♠"), ("H", "♥"), ("D", "♦"), ("C", "♣")]:
        bid = bid.replace(ascii_suit, symbol)
    return ("我方 " if side == "NS" else "敵方 ") + bid


def text(fig, x, y, s, size=11, color=INK, weight="normal", **kw):
    return fig.text(x, y, s, fontsize=size, color=color, va="top", fontproperties=FP,
                    weight=weight, **kw)


def new_page(title, subtitle, page):
    fig = plt.figure(figsize=(W, H), facecolor="white")
    fig._cell_checks = []
    text(fig, .045, .956, title, 22)
    text(fig, .046, .904, subtitle, 10.3, MUTED)
    fig.add_artist(Rectangle((.045, .881), .91, .0025, transform=fig.transFigure,
                             color=BLUE, linewidth=0))
    text(fig, .045, .031, "DK 最新版｜10,000 副｜無對有｜條件 Par 近似｜正 IMP 代表賭倍較佳", 8.3, MUTED)
    text(fig, .955, .031, f"{page} / 7", 8.3, MUTED, ha="right")
    return fig


def heading(fig, x, y, label, size=12):
    text(fig, x, y, label, size, BLUE)


def table(fig, box, headers, rows, widths=None, size=10, align=None):
    """Fixed-size table with per-cell bounds checked before PDF output."""
    x, y, w, h = box
    nr, nc = len(rows) + 1, len(headers)
    widths = np.array(widths or [1 / nc] * nc, dtype=float)
    widths /= widths.sum()
    dx = widths * w
    dy = h / nr
    align = align or ["left"] + ["right"] * (nc - 1)
    for r, cells in enumerate([headers] + rows):
        yy = y + h - (r + 1) * dy
        bg = INK if r == 0 else (PALE if r % 2 else "white")
        fig.add_artist(Rectangle((x, yy), w, dy, transform=fig.transFigure,
                                 facecolor=bg, edgecolor="white", linewidth=.7))
        xx = x
        for c, value in enumerate(cells):
            a = align[c]
            px = xx + .006 if a == "left" else xx + dx[c] - .006
            if a == "center":
                px = xx + dx[c] / 2
            artist = fig.text(px, yy + dy / 2, str(value), va="center", ha=a,
                              fontsize=size, color="white" if r == 0 else INK,
                              fontproperties=FP)
            fig._cell_checks.append((artist, (xx + .004, yy + .001,
                                             dx[c] - .008, dy - .002)))
            xx += dx[c]


def finish(fig, pdf=None, png=None, page="overview"):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    shrunk = 0
    for artist, bounds in fig._cell_checks:
        allowed = matplotlib.transforms.Bbox.from_bounds(*bounds).transformed(fig.transFigure)
        actual = artist.get_window_extent(renderer)
        factor = min(1., allowed.width / max(actual.width, 1), allowed.height / max(actual.height, 1))
        if factor < 1:
            artist.set_fontsize(artist.get_fontsize() * factor * .98)
            shrunk += 1
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    errors = []
    for artist, bounds in fig._cell_checks:
        allowed = matplotlib.transforms.Bbox.from_bounds(*bounds).transformed(fig.transFigure)
        actual = artist.get_window_extent(renderer)
        if actual.width > allowed.width + 1 or actual.height > allowed.height + 1:
            errors.append(artist.get_text())
    for artist in fig.texts:
        b = artist.get_window_extent(renderer)
        if b.x0 < -1 or b.y0 < -1 or b.x1 > fig.bbox.width + 1 or b.y1 > fig.bbox.height + 1:
            errors.append("page boundary: " + artist.get_text())
    minimum = min((a.get_fontsize() for a, _ in fig._cell_checks), default=10)
    CHECKS.append({"page": page, "cell_count": len(fig._cell_checks),
                   "auto_fit_cells": shrunk, "minimum_table_font_pt": round(minimum, 2),
                   "overflow_errors": errors})
    if errors:
        raise ValueError(f"Text overflow on {page}: {errors}")
    if minimum < 8:
        raise ValueError(f"Table font too small on {page}: {minimum:.2f} pt")
    if pdf:
        pdf.savefig(fig)
    if png:
        fig.savefig(png, dpi=180, facecolor="white")
    plt.close(fig)


def metrics(fig, overview, y=.838):
    cards = [
        ("平均 IMP 差", signed(overview["mean_imp"], 4),
         "抽樣 95% 區間 +0.392 ～ +0.586"),
        ("BAM 配對得分", pct(overview["bam_mean"], 3),
         "勝 63.56%｜和 9.39%｜負 27.05%"),
        ("大輸 ≥ 8 IMP", "10.14%", "1,014 副；其中 ≥ 10 IMP 為 363 副"),
    ]
    for i, (label, val, note) in enumerate(cards):
        x = .045 + .31 * i
        fig.add_artist(Rectangle((x, y - .145), .29, .145, transform=fig.transFigure,
                                 facecolor=PALE, edgecolor="none"))
        text(fig, x + .014, y - .014, label, 11, MUTED)
        text(fig, x + .014, y - .049, val, 25, TEAL if i < 2 else RED)
        text(fig, x + .014, y - .112, note, 8.4, MUTED)


def imp_plot(fig, box, rows, fontsize=9):
    ax = fig.add_axes(box)
    ct = {r["imp_diff"]: r["n"] for r in rows}
    xs = np.arange(-15, 15)
    vals = [ct.get(int(k), 0) / 100 for k in xs]
    ax.bar(xs, vals, color=[RED if x < 0 else GREY if x == 0 else TEAL for x in xs], width=.8)
    ax.set_xticks(range(-15, 15))
    ax.tick_params(axis="both", labelsize=fontsize)
    ax.set_ylabel("頻率（%）", fontsize=10)
    ax.set_xlabel("逐副 IMP 差：賭倍 Par − 放過 2♠", fontsize=10)
    ax.grid(axis="y", color="#e0e7ec", linewidth=.5)
    ax.set_axisbelow(True)
    return ax


def contribution_plot(fig, box, components, fontsize=9):
    ax = fig.add_axes(box)
    vals = [r["contribution_to_overall_mean"] for r in components]
    labels = [CATEGORY[r["category"]] for r in components]
    ys = np.arange(len(vals))
    ax.barh(ys, vals, color=[TEAL if v >= 0 else RED for v in vals], height=.65)
    ax.set_yticks(ys, labels, fontsize=fontsize)
    ax.invert_yaxis()
    ax.axvline(0, color=MUTED, linewidth=.6)
    ax.set_xlim(-1.45, 1.25)
    ax.set_xlabel("對全體平均 IMP 的貢獻（可相加）", fontsize=10)
    ax.grid(axis="x", color="#e0e7ec", linewidth=.5)
    ax.set_axisbelow(True)
    for y, v in zip(ys, vals):
        if v < -.5:
            ax.text(v / 2, y, signed(v, 4), va="center", ha="center", fontsize=9, color="white")
        else:
            ax.text(v + (.025 if v >= 0 else -.025), y, signed(v, 4),
                    va="center", ha="left" if v >= 0 else "right", fontsize=9)
    return ax


def factor_rows(part, labelmap=None, order=None):
    return [[labelmap.get(k, k) if labelmap else k, f"{part[k]['n']:,}",
             signed(part[k]["mean_imp"]), pct(part[k]["bam_mean"], 1),
             pct(part[k]["loss8_rate"], 1)] for k in (order or part)]


def parse_hands(pbn):
    start, data = pbn.split(":", 1)
    seats = "NESW"
    order = seats[seats.index(start):] + seats[:seats.index(start)]
    return {seat: hand.split(".") for seat, hand in zip(order, data.split())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", type=Path,
                        default=Path(__file__).resolve().parent / "run_v5_10000")
    args = parser.parse_args()
    run = args.run_dir.resolve()
    out = run / "contract_analysis"
    a = json.loads((out / "analysis.json").read_text())
    factors = json.loads((out / "factors.json").read_text())
    results = [json.loads(s) for s in (run / "results.jsonl").read_text().splitlines() if s]
    summary = json.loads((run / "summary.json").read_text())
    o, comps, p = a["overview"], a["components"], factors["partitions"]
    assert len(results) == o["n"] == 10000
    assert sum(r["delta_imp"] for r in results) == o["sum_imp"] == 4889
    assert sum(r["n"] for r in comps) == o["n"]
    assert sum(r["sum_imp"] for r in comps) == o["sum_imp"]
    assert len(a["contract_presence"]) == 59
    assert abs(summary["mean_imp"] - o["mean_imp"]) < 1e-12

    # Mutually exclusive classification uses all cooptimal contracts, never one representative.
    def cls(r):
        cs = r["optimal_contracts"]
        sides = {"NS" if c["declarer"] in "NS" else "EW" for c in cs}
        if len(sides) > 1:
            return "mixed_NS_making_or_EW_down"
        if sides == {"NS"}:
            return "NS_down" if r["double_par_score_ns"] < 0 else "NS_making"
        if any(c["level"] == 2 and c["strain"] == "S" and c["doubled"] == 1 for c in cs):
            return "EW_2SX_available"
        if r["double_par_score_ns"] > 0:
            return "EW_other_down"
        game = {c["level"] >= {"C": 5, "D": 5, "H": 4, "S": 4, "N": 3}[c["strain"]] for c in cs}
        assert len(game) == 1
        return "EW_making_game" if True in game else "EW_making_partscore"

    classified = defaultdict(list)
    for r in results:
        classified[cls(r)].append(r)
    assert {k: len(v) for k, v in classified.items()} == {r["category"]: r["n"] for r in comps}

    pdf_path = out / "report.pdf"
    with PdfPages(pdf_path, metadata={"Title": "DK 最新版：賭倍後條件 Par 合約統計", "Author": "Bridge simulation analysis", "Subject": "10000 saved deals; NS nonvulnerable versus EW vulnerable"}) as pdf:
        fig = new_page("賭倍後的合約：DK 最新版一萬副", "條件 Par 近似的統計報告｜讀取既有牌局與計算結果，未重跑抽牌、DDS 或 Par", 1)
        metrics(fig, o)
        heading(fig, .045, .654, "比較的是什麼")
        text(fig, .045, .622,
             "南家：♠3  ♥9754  ♦AKT8  ♣A764；我方無身價，敵方有身價。\n"
             "叫序：Pass–(1♠)–X–(Pass)；1NT–(2♥)–Pass–(2♠)；Pass–(Pass)–？\n"
             "Pass：東家 2♠ 不賭倍的雙明手分數。X：從南家賭倍、輪西家續叫後，\n"
             "保留既有叫序限制，讓四家自由續叫的完全資訊 Par；後續不限制西家 Pass。\n"
             "所有分數均為南北視角；每副先將兩方案分差換成 IMP，再求平均。",
             11, linespacing=1.65)
        heading(fig, .045, .400, "多個最優合約，如何計數")
        text(fig, .045, .366,
             "6,506 副有多個最優終約；合併同方莊家後，仍有 5,172 副有多個標籤。\n"
             "合約出現率（presence）＝該合約出現在最優集合中的牌局比例；\n"
             "同副每個標籤只計一次，但不同標籤可以重疊，合計為 190.71%。\n"
             "這不是人類實際選約的機率，也沒有任選一個代表合約來替代分布。",
             11, linespacing=1.65)
        heading(fig, .045, .183, "解讀範圍")
        text(fig, .045, .150,
             "BAM 是兩方案逐副比較，非真實牌場 MP%。95% 區間只反映給定篩牌與 Par 模型的抽樣誤差。\n"
             "本報告不估計人類叫牌、攻防失誤或篩牌模型誤差；隱藏手牌分組是事後關聯，不能當成桌上資訊。\n"
             f"資料：run_v5_10000｜seed {summary['seed']}｜平均原始分差 {o['mean_raw_delta']:+.3f} 分。",
             10, MUTED, linespacing=1.5)
        finish(fig, pdf, page=1)

        fig = new_page("全部 59 種最優合約的出現頻率", "每副按「我／敵方、階數、花色、倍數」去重；同副可出現多列，所以頻率不能相加", 2)
        rows = [[contract(r["contract"]), f"{r['n']:,}", pct(r["frequency"]), signed(r["mean_imp"], 2)]
                for r in a["contract_presence"]]
        table(fig, (.045, .125, .442, .724), ["合約標籤", "副數", "出現率", "組內 IMP"], rows[:30], [.36, .18, .23, .23], size=10)
        table(fig, (.513, .125, .442, .724), ["合約標籤", "副數", "出現率", "組內 IMP"], rows[30:], [.36, .18, .23, .23], size=10)
        text(fig, .045, .097, "X＝賭倍；XX＝再賭倍。組內 IMP 是所有含該標籤牌局的平均差，不代表該合約獨立造成的效果。", 9.2, MUTED)
        text(fig, .045, .069, "成局階數不等於做成：例如敵方 3NT 出現 34 副，其中 29 副做成、5 副宕約。完整得失分析見第 4 頁。", 9.2, MUTED)
        finish(fig, pdf, page=2)

        fig = new_page("IMP 差的完整頻率分布", "正值：賭倍較佳；負值：放過 2♠ 較佳。原始分數贏但只差 10 分者，可能換算為 0 IMP", 3)
        imp_plot(fig, [.07, .56, .88, .28], a["imp_frequency"])
        freq = {r["imp_diff"]: r for r in a["imp_frequency"]}
        rows = [[f"{k:+d}" if k else "0", f"{freq.get(k, {}).get('n', 0):,}",
                 pct(freq.get(k, {}).get("frequency", 0)), signed(freq.get(k, {}).get("contribution_to_overall_mean", 0), 4)]
                for k in range(-15, 15)]
        table(fig, (.045, .115, .442, .37), ["IMP 差", "副數", "頻率", "均值貢獻"], rows[:15], [.2, .24, .25, .31], size=9.5)
        table(fig, (.513, .115, .442, .37), ["IMP 差", "副數", "頻率", "均值貢獻"], rows[15:], [.2, .24, .25, .31], size=9.5)
        text(fig, .045, .090, "正 IMP 5,085 副；0 IMP 2,210 副；負 IMP 2,705 副。另有 1,271 副原始分數勝出、但 IMP 差為 0。", 9.2, MUTED)
        text(fig, .045, .063, "正 IMP 合計 +21,843，負 IMP 合計 −16,954；淨 +4,889 ÷ 10,000 ＝ +0.4889 IMP。表列觀測範圍 −15 至 +14。", 9.2, MUTED)
        finish(fig, pdf, page=3)

        fig = new_page("七個互斥成分：收益與損失從哪裡來", "按整個最優合約集合分類，無任意決勝規則；各列副數與「全體貢獻」可相加", 4)
        rows = [[CATEGORY[r["category"]], f"{r['n']:,}", pct(r["frequency"]), signed(r["mean_imp"]),
                 signed(r["contribution_to_overall_mean"], 4), str(r["loss8"]), str(r["loss10"])] for r in comps]
        table(fig, (.045, .580, .91, .266), ["互斥成分", "副數", "比例", "組內 IMP", "全體貢獻", "輸 ≥ 8", "輸 ≥ 10"], rows,
              [.30, .10, .12, .12, .14, .11, .11], size=10.2)
        text(fig, .045, .554,
             "「我方宕約／做成」指所有最優終約均由我方主打；「2♠X 可選」在本批全為敵方宕約。\n"
             "其餘敵方組按做成／宕約與成局階數區分；最後一組同時有我方做成及敵方宕約，分數相同。", 9.5, MUTED, linespacing=1.5)
        heading(fig, .045, .455, "我方宕約的深度")
        nd = defaultdict(list)
        for r in classified["NS_down"]:
            nd[r["double_par_score_ns"]].append(r)
        rows = [[str(s), f"{len(rs):,}", signed(sum(r["delta_imp"] for r in rs) / 10000, 4)]
                for s, rs in sorted(nd.items(), reverse=True)]
        table(fig, (.045, .203, .282, .215), ["NS 分數", "副數", "全體貢獻"], rows, [.32, .26, .42], size=10)
        heading(fig, .365, .455, "留在敵方 2♠X")
        xd = defaultdict(list)
        for r in classified["EW_2SX_available"]:
            xd[r["double_par_score_ns"]].append(r)
        rows = [[str(s), f"{len(rs):,}", signed(sum(r["delta_imp"] for r in rs) / 10000, 4)]
                for s, rs in sorted(xd.items())]
        table(fig, (.365, .289, .275, .129), ["NS 分數", "副數", "全體貢獻"], rows, [.32, .27, .41], size=10)
        text(fig, .365, .261, "2♠X 均優於放過 2♠。\n但僅 25.22% 的牌有此最優選項。", 9.6, MUTED, linespacing=1.6)
        heading(fig, .680, .455, "大輸 ≥ 8 IMP 的來源")
        tail_rows = [["我方宕約", "713", "70.32%"], ["敵方成局", "298", "29.39%"], ["敵方部分合約", "3", "0.30%"]]
        table(fig, (.680, .289, .275, .129), ["來源", "副數", "大輸占比"], tail_rows, [.49, .20, .31], size=9.5)
        text(fig, .680, .261, "敵方成局 298 副，貢獻 −0.2987。\n4♠ 做成 264；3NT 做成 29；\n4♥ 做成 6；其中一副重疊。", 9.6, MUTED, linespacing=1.6)
        text(fig, .045, .143, "宕約不必然輸給 Pass：我方 −100 的 2,066 副中，有 2,039 副仍勝過放過 2♠；該組淨貢獻 +0.0701 IMP。", 10, MUTED)
        text(fig, .045, .099, "大輸 ≥ 8 IMP 占 10.14%；大贏 ≥ 8 IMP 占 1.69%。較多小勝支撐正均值，但輸局的平均幅度較大。", 10, MUTED)
        finish(fig, pdf, page=4)

        fig = new_page("Par 分數分布，與放過 2♠ 的底線", "左表是賭倍分支的最優 NS 分數；右表按東家未賭倍 2♠ 的雙明手墩數分組", 5)
        rows = [[f"{r['par_score_ns']:+d}", f"{r['n']:,}", pct(r["frequency"]), signed(r["mean_imp"], 2)]
                for r in a["par_score_frequency"]]
        table(fig, (.045, .119, .442, .727), ["Par 分數", "副數", "比例", "組內 IMP"], rows, [.25, .23, .25, .27], size=10.1)
        rows = [[str(r["east_2S_tricks"]), f"{r['n']:,}", signed(r["mean_imp"], 2), pct(r["loss8"] / r["n"], 1)]
                for r in a["baseline_2S_tricks"]]
        table(fig, (.535, .530, .420, .316), ["2♠ 墩數", "副數", "組內 IMP", "輸 ≥ 8"], rows, [.23, .23, .27, .27], size=10.3)
        heading(fig, .535, .484, "最常見的分數轉換")
        rows = [[f"{r['pass_score_ns']:+d} → {r['double_par_score_ns']:+d}", f"{r['n']:,}", signed(r["mean_imp"], 1)]
                for r in a["score_transitions"][:6]]
        table(fig, (.535, .225, .420, .219), ["Pass → X Par", "副數", "IMP 差"], rows, [.48, .25, .27], size=10)
        text(fig, .535, .185, f"平均 NS 分數：Pass {o['mean_pass_score_ns']:.3f}；X Par {o['mean_double_par_score_ns']:.3f}。\n"
             "2♠ 本來就能取 10 墩以上時，賭倍重開多半不利。\n"
             "此為雙明手事後分組；桌上並不知道實際可取墩數。", 10, MUTED, linespacing=1.5)
        text(fig, .045, .075, "Par 分數相同的不同合約不重複計數；左表頻率合計 100%。右表每一列的分母為該墩數組副數。", 9.2, MUTED)
        finish(fig, pdf, page=5)

        fig = new_page("同伴紅心與低花：隱藏手牌的事後關聯", "北家紅心較長、低花配合較差時，本批結果較差；紅心大牌的影響不能只用點數相加理解", 6)
        headers = ["北家條件", "副數", "平均 IMP", "BAM", "輸 ≥ 8"]
        heading(fig, .045, .851, "紅心長度")
        table(fig, (.045, .707, .442, .105), headers,
              factor_rows(p["north_heart_length"], {"2": "♥ 2 張", "3": "♥ 3 張"}), [.33, .17, .18, .16, .16], size=10)
        heading(fig, .535, .851, "我方最佳低花配合總張數")
        table(fig, (.535, .672, .420, .140), headers,
              factor_rows(p["north_best_minor_fit"], {"7": "低花最多 7 張", "8": "低花最多 8 張", "9": "低花最多 9 張"}), [.34, .17, .18, .15, .16], size=9.8)
        heading(fig, .045, .654, "紅心大牌：互斥類別")
        table(fig, (.045, .367, .442, .249), headers,
              factor_rows(p["north_heart_category"], HEART, HEART_ORDER), [.38, .15, .17, .15, .15], size=9.6)
        heading(fig, .535, .616, "同時分紅心長度與大牌")
        cross_rows = []
        for cat in HEART_ORDER:
            r2, r3 = p["north_heart_category_by_length"]["2|" + cat], p["north_heart_category_by_length"]["3|" + cat]
            cross_rows.append([HEART[cat].split("（")[0].split("；")[0],
                               f"{r2['n']:,}", signed(r2["mean_imp"], 2), f"{r3['n']:,}", signed(r3["mean_imp"], 2)])
        table(fig, (.535, .329, .420, .249), ["紅心大牌", "♥2 副數", "IMP", "♥3 副數", "IMP"], cross_rows,
              [.32, .18, .16, .18, .16], size=9.5)
        heading(fig, .045, .321, "大輸機制與紅心長度")
        tail_by_length = defaultdict(Counter)
        for r in results:
            if r["delta_imp"] <= -8:
                tail_by_length[len(parse_hands(r["pbn"])["N"][1])][cls(r)] += 1
        rows = []
        for k in [2, 3]:
            ct = tail_by_length[k]
            rows.append([f"♥ {k} 張", str(sum(ct.values())), str(ct["NS_down"]), str(ct["EW_making_game"]), str(ct["EW_making_partscore"])])
        table(fig, (.045, .176, .442, .105), ["北家", "大輸", "我方宕", "敵成局", "敵部分"], rows, [.25, .18, .19, .19, .19], size=9.7)
        text(fig, .535, .276,
             "♥A 組平均 +2.015；只有 K/KJ 組 −0.117；\n"
             "只有 Q/QJ 組 −0.637；無四種大牌組 +1.380。\n"
             "故不能概括為「紅心點力越多，賭倍越不利」。",
             10.3, MUTED, linespacing=1.6)
        adj = factors["adjusted_associations"]["ace_at_same_north_hcp_and_shape"]["delta_imp"]["coefficients"]["heart_ace"]
        equal_hcp = factors["adjusted_associations"]["A_only_versus_KJ_same_four_heart_hcp"]["delta_imp"]
        eq = equal_hcp["coefficients"]["heart_ace"]
        supported = equal_hcp["support_by_feature"]["heart_ace"]["deals_in_strata_with_variation"]
        text(fig, .045, .129,
             f"固定北家 HCP 與牌型的分層關聯：有 ♥A 相對無 ♥A，IMP 差約 {adj['estimate']:+.3f}（HC3 95% 區間 {adj['ci95'][0]:+.3f}～{adj['ci95'][1]:+.3f}）。\n"
             f"同紅心 4 HCP 的 A-only vs KJ、再控制北家 HCP／牌型：{eq['estimate']:+.3f} IMP，95% {eq['ci95'][0]:+.3f}～{eq['ci95'][1]:+.3f}；n={equal_hcp['n']:,}，共同支持 {supported:,}。\n"
             "仍是隱藏牌事後關聯：紅心長度與低花配合、東家牌型及點力位置相互牽動，不能視為換一張牌的因果效果。", 9.3, MUTED, linespacing=1.55)
        finish(fig, pdf, page=6)

        fig = new_page("其他手牌因素，以及如何使用這些統計", "所有列均為既有合法樣本中的條件平均；不能分別相加，也不能推斷固定南家之外的打法規則", 7)
        heads = ["條件", "副數", "平均 IMP", "輸 ≥ 8"]
        def small_rows(key, suffix="", order=None):
            return [[k + suffix, f"{p[key][k]['n']:,}", signed(p[key][k]["mean_imp"]), pct(p[key][k]["loss8_rate"], 1)] for k in (order or p[key])]
        heading(fig, .045, .851, "北家 HCP")
        table(fig, (.045, .589, .282, .225), heads, small_rows("north_hcp", order=sorted(p["north_hcp"], key=int)), [.24, .23, .29, .24], size=9.6)
        heading(fig, .365, .851, "東家 HCP")
        table(fig, (.365, .552, .275, .262), heads, small_rows("east_hcp"), [.24, .23, .29, .24], size=9.6)
        heading(fig, .680, .851, "西家 HCP")
        table(fig, (.680, .552, .275, .262), heads, small_rows("west_hcp"), [.24, .23, .29, .24], size=9.6)
        heading(fig, .045, .506, "北家黑桃長度")
        table(fig, (.045, .278, .282, .188), heads, small_rows("north_spade_length", " 張"), [.25, .22, .29, .24], size=9.6)
        heading(fig, .365, .506, "東家 ♠–♥ 長度")
        table(fig, (.365, .278, .275, .188), heads, small_rows("east_major_shape"), [.25, .22, .29, .24], size=9.6)
        heading(fig, .680, .506, "西家黑桃長度")
        table(fig, (.680, .278, .275, .188), heads, small_rows("west_spade_length", " 張"), [.25, .22, .29, .24], size=9.6)
        heading(fig, .045, .232, "模型內的結論與限制")
        text(fig, .045, .196,
             "這批 DK 牌在既定篩牌與完全資訊續叫模型內，賭倍平均 +0.489 IMP、BAM 68.255%；兩種計分都偏向賭倍。\n"
             "正均值主要由可保留 2♠X 與我方做成支撐；我方受罰及敵方成局削弱優勢。BAM 的較高勝率不代表 IMP 無大輸尾端。\n"
             "北家越強、西家越弱時結果較佳，但全副 40 HCP 固定：各家的點力與牌型彼此相關，不能當作獨立因素相加。\n"
             "稀少組（例如西家單張 ♠ 僅 6 副、東家 12 HCP 僅 52 副）不宜推廣；完整篩牌條件仍決定本分析適用範圍。",
             10.2, MUTED, linespacing=1.6)
        finish(fig, pdf, page=7)

    # Standalone summary image designed to be readable when opened on iOS.
    fig = new_page("DK 一萬副：賭倍略有 IMP 優勢，BAM 優勢較大", "固定 ♠3 ♥9754 ♦AKT8 ♣A764｜無對有｜賭倍後歷史受限 Par vs 放過東家 2♠", "摘要")
    metrics(fig, o)
    heading(fig, .045, .648, "七個互斥成分的 IMP 貢獻")
    contribution_plot(fig, [.25, .195, .33, .405], comps, fontsize=10)
    heading(fig, .64, .648, "逐副 IMP 差的頻率")
    ax = imp_plot(fig, [.67, .28, .28, .31], a["imp_frequency"], fontsize=8)
    ax.set_xticks([-15, -10, -5, 0, 5, 10, 14])
    ax.set_xlabel("IMP 差", fontsize=10)
    text(fig, .64, .210, "大輸 ≥ 8：1,014 副\n我方宕約 713｜敵成局 298｜其他 3\n大贏 ≥ 8：169 副", 10, MUTED, linespacing=1.6)
    text(fig, .045, .110,
         "合約出現率可重疊：51.72% 的牌有多個最優合約標籤；Par 並未指定人類選約機率。\n"
         "條件模型內的抽樣統計；未涵蓋篩牌誤差或實戰失誤。隱藏手牌分組僅為事後關聯。", 10, MUTED, linespacing=1.55)
    # Replace PDF-specific page footer in the standalone image.
    for t in fig.texts:
        if t.get_text() == "摘要 / 7":
            t.set_text("run_v5_10000")
    finish(fig, png=out / "overview.png", page="overview")
    (out / "render_validation.json").write_text(json.dumps({
        "pdf_pages": 7, "inputs": ["analysis.json", "factors.json", "results.jsonl", "summary.json"],
        "checks": CHECKS, "no_dds_or_par_recomputed": True,
    }, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"pdf": str(pdf_path), "pages": 7, "png": str(out / "overview.png"),
                      "overflow_errors": 0, "minimum_table_font_pt": min(c["minimum_table_font_pt"] for c in CHECKS)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
