# 待辦（實作面）

框架或工具更新後要回頭處理的事；完成後刪除該列。

| 項目 | 觸發條件 | 內容 |
|---|---|---|
| 轉換器升級 | 使用者發佈 0.15.1 轉換器套件 | 拿掉 `--force` 匯入、inline 色碼、repeat 內 PNG 圖示與 @key 的繞道 |
| publish 改為 include 清單 | AT-047 | 落地後重新 publish，用 `publish --list` 確認只含執行期檔案；不再手動刪 node_modules／tests 等 |
| 接上其餘音效、音量設定 | 使用者交付更多 `audio/` 素材；設定畫面加「聲音」列 | BGM 與 SFX_DEB_WIN／LOSE 已接（2026-11-06）。新音效：`tools/gen_flows.py` `SFX` 加 ID（`game.json` `audio.cues` 由它產生），依 docs/audio-requests.md 的觸發時機接 `sound` 節點；新 BGM：`MUSIC` 加一列（循環點依 `audio/README.md` 量測）。音量：`atrium.audio.volume`（master／bgm／se），設計 01-systems 的「聲音」項 |
| BGM03／BGM04 的場景對應 | 設計定出逐場景的 BGM | 兩首已宣告但沒有時機用到（docs/audio-requests.md §6）；定案後在劇本資料加場景 BGM，經 `world.bgmMoment` 優先於 `daily` |
