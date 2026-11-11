# 續叫搜尋檢查（python3 source/reproduce.py --mode tests 的輸出）

- 小局面窮舉 oracle：600 個隨機局面（正式起點 2♠X、叫品上限 3♣ 或 3♦；以及隨機起點，含三線南北合約與兩種保護假設），不記憶、不化簡，逐一列舉所有合法叫牌序列，莊家由完整叫序重新判定。比對 C++ 搜尋的值與最佳終局集合，化簡與不化簡兩種模式。
- 化簡對照：data 前 25 副真實牌，叫品到 7NT 的全範圍，三種假設，化簡版與不化簡版的值與最佳終局集合。

```
oracle cases 600 x 2 modes; mismatches 0
collapse check boards 25 x3, mismatches 0
```

# 抽樣重算（python3 source/reproduce.py --mode sample --count 200）

從種子重抽前 200 副，重新計算雙夢家與三種假設的續叫搜尋、重新匯出，與 data/results.jsonl 前 200 列逐列比對：

```
比對 200 副：不一致 0 副 []
```
