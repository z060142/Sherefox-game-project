# 待辦（實作面）

框架或工具更新後要回頭處理的事；完成後刪除該列。

| 項目 | 觸發條件 | 內容 |
|---|---|---|
| 尚未用 textf 的佔位字串 | 設計補上顯示時機或字串鍵 | `MSG_INV_MISSED`／`WARN_INV_END`／`MSG_INV_RESCUE`：結束蒐證沒有確認與結算畫面（docs/flows.md §4.4、§7.1 第 4 項）；`UI_BOARD_THRESHOLD`：缺 `{stage}`（前期／中期／後期）的字串鍵（§7.3）；`UI_DEB_PREVIEW`：`{mult}` 是哪個倍率未定（§4.8） |
| UI bundle 的舊展開鍵 | 下一次 `xtatrium pack` | `ui/project/shared/strings` 已刪掉 M4c 的 `<KEY>__<值>` 鍵（`tools/build_data.py` 同步時），`ui/bundle/` 重新 pack 後才跟著少（遊戲側不讀它們） |
| 轉換器升級 | 使用者發佈 0.15.1 轉換器套件 | 拿掉 `--force` 匯入、inline 色碼、repeat 內 PNG 圖示與 @key 的繞道 |
| 蒐證反應台詞 | M5 | `hotspots.lines` 的台詞（亞瑟的吐槽等）目前沒播；investigate 彈窗加說話者＋台詞 port |
| 英文報頭 | M5 | 英文模式報紙左上「The London Lantern」折兩行 |
| 新字串接線 | M4c 完成後 | 重新匯入在地化；SCENE_CH0x_* → investigate `area_name`；HS_CH03_01_NOTE_REPORT（信任度 ≥3 的遺體筆記）；G-01_DESC／G-01_REASON／S-01_DESC（S-01 名稱沿用 G-01_SUB）；UI_TAG_SEP 作為標籤分隔 |
| publish 改為 include 清單 | AT-047 | 落地後重新 publish，用 `publish --list` 確認只含執行期檔案；不再手動刪 node_modules／tests 等 |
| 行動按鈕可用狀態 | AT-047 `bare: true` | debate 的 `act_enabled`（list<bool>）、`act_reason`（list<string>）改用 `atrium.ui.list` 的 `bare` 模式寫入 |
