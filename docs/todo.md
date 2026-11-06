# 待辦（實作面）

框架或工具更新後要回頭處理的事；完成後刪除該列。

| 項目 | 觸發條件 | 內容 |
|---|---|---|
| 轉換器升級 | 使用者發佈 0.15.1 轉換器套件 | 拿掉 `--force` 匯入、inline 色碼、repeat 內 PNG 圖示與 @key 的繞道 |
| publish 改為 include 清單 | AT-047 | 落地後重新 publish，用 `publish --list` 確認只含執行期檔案；不再手動刪 node_modules／tests 等 |
| `compile --game` 納入檢查 | AT-036（已落地，SDK 待重建） | 重建 SDK 後，在 tests/README 與各 check 前加 `xtatrium compile --game E:\coding4\Sherefox`，端點錯誤在打包前就擋下 |
| 尾聲出錯牌的系統台詞 | M5c | Ch.2 S05 L047、Ch.3 S06 L046 是尾聲答錯（−30）時的結算台詞（設計確認） |
| 熱身失敗的收尾台詞 | M5c | 設計已補 SCR_CH03_S04_F001～F004：熱身失敗（失誤 3 次）時取代 L006～L009 播放；重新匯入在地化並接上分支 |
| 重新論戰的開場台詞 | M5c | 重試時開場台詞會再播一次 |
| 全部調查完畢自動確認 | M5c | §1.7「全部調查完畢」自動跳結束確認未做 |
| 鑑定台詞 | M5c | `evidence.appraisalKey` 沒有地方播放 |
| 對手筆記、預估列候選比較、狀態列旗標、臨場硬接、讀對預兆統計 | M5c | 論戰畫面尚未實作的設計項目（§4.4、§4.2） |
| 背景音樂循環 | 音效素材到位後 | 框架目前只有單次音效；需向 XTAtrium 提出循環／淡入淡出／停止的需求 |
| 接上背景音樂與音效 | 使用者交付 `audio/` 素材 | `game.json` 加 `audio.music`（OGG，loop／loopStart／loopEnd）與 `audio.cues`（WAV，category）；音樂掛鉤（M5c）接一個 `atrium.music.play`（頻道 bgm、淡入約 1 秒）；音效依 docs/audio-requests.md 的觸發時機接 `sound` 節點；缺檔會在載入時失敗，所以只宣告已到的檔案 |
