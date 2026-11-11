#!/usr/bin/env python3
"""Plot the empirical KnR distribution and quartile examples from saved DK rows."""
import argparse
from collections import Counter, defaultdict
import csv
import json
import math
import os
from pathlib import Path

os.environ.setdefault('MPLCONFIGDIR','/tmp/bridge-knr-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.font_manager import FontProperties, fontManager
from matplotlib.patches import Rectangle
from matplotlib.ticker import MultipleLocator, PercentFormatter
import numpy as np

from analyze_dk_knr_spades import knr_five

FONT=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
fontManager.addfont(str(FONT));FP=FontProperties(fname=str(FONT))
plt.rcParams.update({'font.family':FP.get_name(),'font.size':11,'axes.unicode_minus':False,
                     'pdf.fonttype':3,'axes.spines.top':False,'axes.spines.right':False})
INK='#18354b';MUTED='#506779';BLUE='#5489ab';TEAL='#007f86';ORANGE='#bf7400';PURPLE='#8353a2'
QUARTILE_COLORS=[TEAL,ORANGE,PURPLE]
W,H=12,8.5


def text(fig,x,y,s,size=11,color=INK,**kw):
    return fig.text(x,y,s,fontsize=size,fontproperties=FP,color=color,va='top',**kw)


def page(title,subtitle,number):
    fig=plt.figure(figsize=(W,H),facecolor='white')
    text(fig,.045,.957,title,23)
    text(fig,.046,.903,subtitle,10.2,MUTED)
    fig.add_artist(Rectangle((.045,.877),.91,.002,transform=fig.transFigure,color=INK))
    text(fig,.045,.031,'DK｜無對有｜最新 3–2／4–1 禁倍校正｜同伴五張黑桃、2♠X 為最佳之一',8.5,MUTED)
    text(fig,.955,.031,f'{number} / 3',8.5,MUTED,ha='right')
    return fig


def family(cards):
    """Retain honors and intermediates that change this observed suit's score."""
    head=''.join(c for c in 'AKQJT' if c in cards)
    if '9' in cards:
        if 'T' in cards or len(head) in (2,3):head+='9'
        elif '8' in cards:head+='98'
    return head+'x'*(5-len(head))


def table(fig,box,headers,rows,widths,size=10):
    x,y,w,h=box;n=len(rows)+1;dy=h/n
    boundaries=np.cumsum([0]+widths)*w+x
    artists=[]
    for i,row in enumerate([headers]+rows):
        yy=y+h-(i+1)*dy
        fig.add_artist(Rectangle((x,yy),w,dy,transform=fig.transFigure,
                                 facecolor=INK if i==0 else '#edf3f7' if i%2 else 'white',
                                 edgecolor='white',linewidth=.5))
        for j,cell in enumerate(row):
            t=text(fig,boundaries[j]+.006,yy+dy*.76,str(cell),size,
                   'white' if i==0 else INK)
            artists.append((t,boundaries[j],boundaries[j+1],yy,yy+dy))
    return artists


def validate_table(fig,artists):
    fig.canvas.draw();renderer=fig.canvas.get_renderer();inverse=fig.transFigure.inverted()
    for artist,x0,x1,y0,y1 in artists:
        b=artist.get_window_extent(renderer).transformed(inverse)
        assert b.x0>=x0 and b.x1<=x1-.002,(artist.get_text(),'horizontal overflow')
        assert b.y0>=y0 and b.y1<=y1,(artist.get_text(),'vertical overflow')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('directory',nargs='?',type=Path,
        default=Path(__file__).resolve().parent/'run_v5_10000/no_double_policy/knr_spades')
    args=ap.parse_args();out=args.directory
    with (out/'two_sx_optimal_ranked.csv').open(encoding='utf-8-sig') as f:
        rows=list(csv.DictReader(f))
    n=len(rows);assert n==1047
    by_score=defaultdict(list)
    for r in rows:
        r['number']=int(r['number']);r['knr_suit_points']=float(r['knr_suit_points'])
        assert knr_five(r['north_spades'])['knr_suit_points']==r['knr_suit_points']
        by_score[r['knr_suit_points']].append(r)
    values=sorted(r['knr_suit_points'] for r in rows)
    quartiles=[]
    for name,p in [('Q1',.25),('Q2',.5),('Q3',.75)]:
        rank=math.ceil(n*p);value=values[rank-1]
        assert value==float(np.quantile(values,p,method='linear'))
        first=1+sum(x<value for x in values);last=sum(x<=value for x in values)
        quartiles.append(dict(name=name,percentile=p,rank=rank,score=value,
            tied_rank_first=first,tied_rank_last=last,n_equal=last-first+1,
            cumulative_below=(first-1)/n,cumulative_at_or_below=last/n,
            families=dict(Counter(family(r['north_spades']) for r in by_score[value]).most_common())))
    assert [q['score'] for q in quartiles]==[2.,4.25,5.5]
    groups=[]
    for score,rs in sorted(by_score.items()):
        families=Counter(family(r['north_spades']) for r in rs)
        groups.append(dict(score=score,n=len(rs),frequency=len(rs)/n,
                           families=dict(families.most_common()),
                           examples=[r['north_spades'] for r in sorted(rs,key=lambda r:(r['two_sx_is_unique']!='True',r['number']))[:2]]))
    with (out/'score_groups.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['score','n','frequency','families','examples']);w.writeheader()
        for g in groups:w.writerow(dict(g,families='; '.join(f'{k}: {v}' for k,v in g['families'].items()),
                                        examples='; '.join(g['examples'])))
    examples=[3,1111,282,35,2234,4002]
    by_number={r['number']:r for r in rows}
    report=dict(n=n,definition='Full KnR suit contribution; each deal has equal weight; 2SX among cooptimal terminals.',
                quartile_method='Inverse empirical CDF: rank ceil(p*n); numpy linear interpolation gives identical results.',
                quartiles=quartiles,groups=groups,examples=[by_number[i] for i in examples],
                pattern_note='x represents a lower card that does not change the score in that row. All AKQJT are retained; 9/8 are shown when they affect the score.',
                formula_source='https://www.rpbridge.net/8j19.htm')
    (out/'visualization_data.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')

    with PdfPages(out/'knr_distribution.pdf',metadata={'Title':'五張黑桃：KnR 分數、頻率與四分位牌例'}) as pdf:
        fig=page('五張黑桃：KnR 單套分數的頻率分布',
                 '1,047 副｜每副等權｜完整黑桃分項＝大牌控制＋牌組品質｜柱上數字為副數',1)
        ax=fig.add_axes([.075,.36,.88,.455])
        scores=[g['score'] for g in groups];freq=[g['frequency']*100 for g in groups]
        colors=[next((c for q,c in zip(quartiles,QUARTILE_COLORS) if q['score']==s),BLUE) for s in scores]
        bars=ax.bar(scores,freq,width=.19,color=colors,zorder=3)
        for bar,g in zip(bars,groups):
            ax.text(bar.get_x()+bar.get_width()/2,bar.get_height()+.12,str(g['n']),
                    ha='center',va='bottom',fontsize=9,color=INK)
        ax.set_xlim(.15,9.85);ax.set_ylim(0,12.1)
        ax.xaxis.set_major_locator(MultipleLocator(.5));ax.xaxis.set_minor_locator(MultipleLocator(.25))
        ax.yaxis.set_major_formatter(PercentFormatter(100));ax.set_ylabel('占這 1,047 副的比例')
        ax.set_xlabel('KnR 黑桃單套分數');ax.grid(axis='y',color='#dce5eb',linewidth=.7,zorder=0)
        ax.tick_params(labelsize=9)
        for q,c in zip(quartiles,QUARTILE_COLORS):
            ax.axvline(q['score'],color=c,linestyle='--',linewidth=1.2,alpha=.8,zorder=2)
            ax.text(q['score'],11.45,f"{q['name']} = {q['score']:.2f}",ha='center',va='center',
                    fontsize=11,color=c,bbox=dict(facecolor='white',edgecolor='none',pad=2))
        captions=[('下四分位｜25%','QTxxx（不帶 9）／Q98xx'),
                  ('中位數｜50%','KJxxx（不帶 T、9）／KT9xx'),
                  ('上四分位｜75%','KQxxx（不帶 J、T、9）')]
        for i,(q,c,(title,holding)) in enumerate(zip(quartiles,QUARTILE_COLORS,captions)):
            x=.045+i*.31
            fig.add_artist(Rectangle((x,.135),.29,.155,transform=fig.transFigure,facecolor='#edf3f7',edgecolor='none'))
            text(fig,x+.012,.276,title,10.8,c)
            text(fig,x+.012,.242,f"{q['score']:.2f}",21,c)
            text(fig,x+.012,.199,holding,10.3)
            text(fig,x+.012,.168,f"同分 {q['n_equal']} 副｜排名 {q['tied_rank_first']}–{q['tied_rank_last']}",9.3,MUTED)
        text(fig,.045,.104,'分數是離散值，同分群會跨過分位位置；Q1 不表示恰有 25% 嚴格低於 2.00 分。',10,MUTED)
        text(fig,.045,.073,'最高頻分數為 5.75（107 副，10.22%）。x 為不改變該列分數的小牌；T 代表 10。',10,MUTED)
        fig.savefig(out/'knr_distribution.png',dpi=190,facecolor='white');pdf.savefig(fig);plt.close(fig)

        fig=page('各分數組的典型牌組',
                 '列出全部 27 個實際出現的分數；括號內為該模式副數，各列頻率合計為 100%',2)
        data=[]
        for g in groups:
            marker=next((q['name'] for q in quartiles if q['score']==g['score']),'')
            patterns='、'.join(f'{k} ({v})' for k,v in g['families'].items())
            data.append([f"{g['score']:.2f}",str(g['n']),f"{g['frequency']:.2%}",patterns,marker])
        artists=table(fig,(.045,.13,.91,.72),['KnR 分數','副數','頻率','典型牌組（副數）','分位點'],
                      data,[.13,.09,.12,.56,.10],size=10.0)
        validate_table(fig,artists)
        text(fig,.045,.102,'x 限於不改變該列分數的小牌；例如 KJxxx 在 4.25 分這列不能含 T 或 9。',10,MUTED)
        text(fig,.045,.073,'A、K、Q、J、T 均完整列出；9、8 僅在影響分數時另列。牌組強度不等於保證王牌墩數。',10,MUTED)
        fig.savefig(out/'knr_score_groups.png',dpi=190,facecolor='white');pdf.savefig(fig);plt.close(fig)

        fig=page('四分位數處的實際同伴手牌',
                 '六副皆為 2♠X 唯一最佳終約；點擊「開啟 Handviewer」可勘驗全副牌與完整叫序',3)
        for i,number in enumerate(examples):
            r=by_number[number];assert r['two_sx_is_unique']=='True'
            row=i//2;col=i%2;x=.045+col*.47;top=.847-row*.24
            q=quartiles[row];color=QUARTILE_COLORS[row]
            fig.add_artist(Rectangle((x,top-.207),.44,.207,transform=fig.transFigure,
                                     facecolor='#edf3f7',edgecolor='none'))
            text(fig,x+.014,top-.013,f"{q['name']} · {r['knr_suit_points']:.2f} 分｜第 {number} 副",13,color)
            text(fig,x+.014,top-.056,f"♠ {r['north_spades']}",15)
            text(fig,x+.226,top-.056,f"♥ {r['north_hearts']}",15)
            text(fig,x+.014,top-.098,f"♦ {r['north_diamonds']}",15)
            text(fig,x+.226,top-.098,f"♣ {r['north_clubs']}",15)
            down=8-int(r['east_2S_tricks'])
            text(fig,x+.014,top-.139,f"全手 {r['north_hcp']} HCP｜東家 2♠X 宕 {down}｜我方 +{r['par_score_ns']}",10,MUTED)
            text(fig,x+.014,top-.174,'開啟 Handviewer ↗',10,color,url=r['handviewer_url'])
        text(fig,.045,.101,'QT764 的同分中點百分位約 21%；Q1 也落在這個 2.00 分群，橫跨排名 170–263。',9.7,MUTED)
        text(fig,.045,.071,'公式：Richard Pavlicek 的 KnR 26 步逐套版本。這裡不計旁門，也不分攤整手最後的調整分。',9.7,MUTED,
             url='https://www.rpbridge.net/8j19.htm')
        fig.savefig(out/'knr_quartile_examples.png',dpi=190,facecolor='white');pdf.savefig(fig);plt.close(fig)
    print(json.dumps(dict(n=n,pdf=str(out/'knr_distribution.pdf'),pages=3,
                         quartiles=[q['score'] for q in quartiles],frequency_sum=sum(g['frequency'] for g in groups)),indent=2))


if __name__=='__main__':
    main()
