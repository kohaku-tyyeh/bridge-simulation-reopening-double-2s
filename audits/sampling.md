# 抽樣檢查

- 接續測試（種子 7、每 7 副 checkpoint）：一次抽 30 副，與「抽 14 副後在輸出尾端加一列殘留、再從 checkpoint 接續到 30 副」比較，deals.jsonl 逐位元組結果：相同。
- 完整種子重播：以 source/sample.py 與 source/filters/ 用種子 2026111201 從頭重抽 10,000 副（22,276,328 次洗牌），deals.jsonl 與 sampling_summary.json 和正式輸出逐位元組相同。
- 每副入樣時檢查：52 張完整不重複、南家牌不變、filter_deals.deal_failures 為空；重複牌排除 0 副。
- 第一個拒絕原因計數見 sampling_summary.json；prefilter_E_majors 是東家黑桃少於五張或紅心少於四張（east_failures 的必要條件，先行快速略過）。
