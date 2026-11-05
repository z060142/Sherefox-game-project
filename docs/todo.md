# 待辦（實作面）

框架或工具更新後要回頭處理的事；完成後刪除該列。

| 項目 | 觸發條件 | 內容 |
|---|---|---|
| 升級 XTAtrium SDK | AT-043／AT-045（v0.15.1 改釘）／AT-046 落地 | 重跑 `E:\coding4\XTArtrium\tools\install-sdk.ps1 -Out E:\coding4\xtatrium-sdk`，全部 check 重跑 |
| `atrium.ui.list` 遷移 | AT-046 | `join` 參數移除，改用 fields 的 `table:<t>[<key>].<col>`、`coll:`、`map:` 來源；可刪掉 `data/flow/` 的合成鍵表（flowDrawer、flowSlot、flowChain、flowBook） |
| 具名參數字串 | AT-046 `atrium.textf` | WARN_BOARD_*、MSG_INV_MISSED、UI_BOARD_THRESHOLD、UI_DEB_* 預估列等改用 textf |
| 跨流程脈衝同 tick | AT-043 | 拿掉「UI 指令值在 debLock 的 tick 內不可變」的限制（docs/debate-engine.md §7） |
| 空表宣告欄位 | AT-043 | `debScript` 等改用 `"columns"` 宣告，取代只有標題列的 CSV |
| 引擎精簡 | 任何時候 | 用 `atrium.gate`／`expr.truth` 取代 compare＋state 閘（約 190 節點） |
| 轉換器升級 | 使用者發佈 0.15.1 轉換器套件 | 拿掉 `--force` 匯入、inline 色碼、repeat 內 PNG 圖示與 @key 的繞道 |
| 蒐證反應台詞 | M5 | `hotspots.lines` 的台詞（亞瑟的吐槽等）目前沒播；investigate 彈窗加說話者＋台詞 port |
| 英文報頭 | M5 | 英文模式報紙左上「The London Lantern」折兩行 |
