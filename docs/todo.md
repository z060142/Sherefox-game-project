# 待辦（實作面）

框架或工具更新後要回頭處理的事；完成後刪除該列。

| 項目 | 觸發條件 | 內容 |
|---|---|---|
| 轉換器升級 | 使用者發佈 0.15.1 轉換器套件 | 拿掉 `--force` 匯入、inline 色碼、repeat 內 PNG 圖示與 @key 的繞道 |
| 轉換器暫存外洩 | 升級轉換器時 | `xtframe-import dc` 每次在 `%TEMP%` 留一個 `xt-import-dc-*` 資料夾不清（2026-11-06 清掉 3315 個、167 MB）；向 XTFrame 回報，升級後確認不再累積 |
| publish 改為 include 清單 | AT-047 | 落地後重新 publish，用 `publish --list` 確認只含執行期檔案；不再手動刪 node_modules／tests 等 |
| 接上其餘音效、音量設定 | 使用者交付更多 `audio/` 素材；設定畫面加「聲音」列 | BGM 與 SFX_DEB_WIN／LOSE 已接（2026-11-06）。新音效：`tools/gen_flows.py` `SFX` 加 ID（`game.json` `audio.cues` 由它產生），依 docs/audio-requests.md 的觸發時機接 `sound` 節點；新 BGM：`MUSIC` 加一列（循環點依 `audio/README.md` 量測）。音量：`atrium.audio.volume`（master／bgm／se），設計 01-systems 的「聲音」項 |
| BGM18（Wolfhart 主題） | 使用者交付 `audio/bgm/BGM18.*` | 設計的 cue 表已用到（Ch.2 S06 L009、Ch.3 S07 L009 起），目前走 fallback（靜音、BGM03）。交付後：量循環點、`tools/gen_flows.py` `MUSIC` 加一列，重跑 `tools/build_data.py`（`bgmCues` 自動改用 BGM18）與 `tools/gen_flows.py`；`tests/check_music.py` 的 `ch2_lose` 不經過勝利分支，不受影響 |
| 調查點座標 | 使用者決定開工（2026-11-11：先等 XTFrame 主線工作完成） | `data/hotspots.json` 45 筆全是 `placeholder: true` 的格狀座標（設計文件沒給座標），遊戲執行時用它們覆蓋看板的範例 `spots`，所以與背景對不上；編輯器裡對得上的是看板 `Investigate.dc.html` 的 6 筆廚房範例資料。做法：`build_data.py` 加一張座標表合併進 hotspots，廚房先沿用範例的 5 筆，其餘對背景標點後給使用者看疊圖；不是可見物件的點（亞瑟（袖口）、大門門縫）問設計 session |
