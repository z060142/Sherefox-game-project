# 待辦（實作面）

框架或工具更新後要回頭處理的事；完成後刪除該列。

| 項目 | 觸發條件 | 內容 |
|---|---|---|
| 轉換器升級 | 使用者發佈 0.15.1 轉換器套件 | 拿掉 `--force` 匯入、inline 色碼、repeat 內 PNG 圖示與 @key 的繞道 |
| publish 改為 include 清單 | AT-047 | 落地後重新 publish，用 `publish --list` 確認只含執行期檔案；不再手動刪 node_modules／tests 等 |
| 接上背景音樂與音效 | 使用者交付 `audio/` 素材 | `game.json` 加 `audio.music`（OGG，loop／loopStart／loopEnd）與 `audio.cues`（WAV，category）；音樂掛鉤（M5c）接一個 `atrium.music.play`（頻道 bgm、淡入約 1 秒）；音效依 docs/audio-requests.md 的觸發時機接 `sound` 節點；缺檔會在載入時失敗，所以只宣告已到的檔案 |
