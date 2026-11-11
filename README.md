# 對手停在 2♠，要不要重開賭倍：一萬副牌的雙夢家模擬資料

文章：[對手停在 2♠，單張黑桃的 11 點要不要重開賭倍？](https://hackmd.io/@TpKotoba/rkRPQFWAzg)（本 repo 的 docs/article.md 是同一篇文章的原始檔）

北家發牌，南北無身價、東西有身價。南家固定拿 ♠3 ♥9754 ♦AKT8 ♣A764，叫牌是 Pass–1♠–賭倍–Pass–1NT–2♥–Pass–2♠–Pass–Pass，南家選擇 Pass 或重開賭倍。Pass 時東家打未賭倍的 2♠；賭倍時由西家開始，四家以全資訊搜尋最佳續叫（續叫 Par）。每副牌比較兩者的分數，換算成 IMP 與 BAM。

| 假設 | 平均 IMP | BAM 得分率 | 賭倍勝／和／負 |
| :--- | ---: | ---: | ---: |
| 原始續叫 Par | +0.2209 | 66.585% | 6,127／1,063／2,810 |
| 只保護 3–2 | +0.4276 | 67.865% | 6,197／1,179／2,624 |
| 保護 3–2 與 4–1 | +0.6295 | 69.520% | 6,291／1,322／2,387 |

保護假設：南北三線有王合約、恰好八張配合、東西王牌為指定分配（3–2，或 3–2 與 4–1）時，東西不賭倍。

## 目錄

| 路徑 | 內容 |
| :--- | :--- |
| data/results.jsonl | 逐副結果：牌、各家牌型與點力、雙夢家墩數表、Pass 與三種假設下賭倍的完整叫序、合約、分數、IMP、BAM、最佳合約集合 |
| data/results.csv | 同上的扁平表格 |
| data/deals.pbn | 一萬副牌（PBN） |
| data/schema.json | 欄位定義 |
| data/raw/current/ | 原始執行輸出：deals.json、dds.jsonl、results.jsonl、保護假設的兩個結果檔、抽樣與亂數紀錄 |
| source/current/ | 篩牌條件（rules.json、filter_deals.py、nt_choice.py、knr_suit.py）、DDS 呼叫、續叫搜尋（C++）、統計與檢查程式 |
| source/reproduce.py | 檢查與重現入口 |
| source/export_data.py | 由 data/raw/current 產生 data/ 下的整理檔 |
| source/recompute_audit.py | 抽樣重算雙夢家與續叫搜尋的檢查程式 |
| audits/current/ | 統計摘要、分組貢獻、各項檢查紀錄 |
| audits/full_seed_replay_cancelled.json | 從亂數種子完整重抽的檢查紀錄：中途停止，未完成 |
| docs/article.md | 文章原始檔 |
| metadata.json | 模型與資料摘要 |
| MANIFEST.sha256 | 除自身以外所有檔案的 SHA-256 |

## 檢查與重現

```
pip install -r source/requirements.txt
sha256sum -c MANIFEST.sha256
python3 source/reproduce.py --mode verify
```

verify 模式只讀現有資料：核對檔案雜湊、篩牌條件、叫序合法性、分數與 IMP／BAM 的換算，不重算雙夢家。sample 與 full 模式需要 C++17 編譯器，會在 --output 指定的新目錄中重新抽牌（full 模式並重算雙夢家與續叫搜尋），耗時很長。

## 讀資料時要注意

- 續叫 Par 每副只保存一條最佳叫牌路徑。路徑中間的叫品是搜尋的產物，沒有約定意義；可以讀的是最後的合約、莊家與分數。
- best_contract_unique 記錄的是最佳合約是否唯一；最佳叫牌路徑是否唯一沒有記錄。
- 篩牌只用牌張與叫牌條件，沒有用到雙夢家或續叫 Par 的結果。
- source_run、source_number 等欄位是原始執行的內部編號，只用於追溯；牌號以 board 欄位為準。
