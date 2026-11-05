# UI port 合約

狀態：草案 2026-11-06（M0）。本文件是 UI（`ui/boards/` → `ui/project/`）與流圖（`flows/`）之間的合約；改合約先改本文件，再改板子與流圖。依據：`docs/architecture.md` §1、§2；XTAtrium docs 04 §4.2（端點位址）。

## 共同規則

- 方向以 UI 文件為準：`out` 由 UI 送出，流圖以 `ui#<surface>.<port>` 讀取；`in` 由流圖寫入（`ui#<surface>.<port>` 當邊的終點），UI 以 `bind:` 顯示。
- 流圖不得讀 `in` port、不得寫 `out` port（XTFrame 53 §53.5.4）。
- 值型（number／string／bool）`out` port 只用 `set(<port>, <值>)`：每次 `set` 都會儲存並發出一次 emit（同值也會發），這是 XTFrame 27 §27.13 的設計。event 型 `out` port 只用 `emit(<port>)`。兩者不混用（主線 2026-11-06 裁定；lint `trigger.setThenEmit` 將檢查）。
- 已知轉換器問題（下一版轉換器修正）：重新 import 時未經編輯器修改的觸發器不會更新（T-618，暫用 `--force`）；置中的 dock 被錨成 `left top`（T-619）。
- 介面上的固定文字一律是字串鍵（`@key`），字串表在 `ui/project/shared/strings/<lang>.csv`（RFC 4180，`key,text`，有標頭列）。

## title（標題畫面，1280×720）

| port | 型別 | 方向 | 意義 |
|---|---|---|---|
| `chapter` | number | out | 玩家在目錄欄選了章節：值為章節編號 1、2、3（預設 0 = 尚未選擇）。每次點擊送出一次，同一章重複點擊也會送出。 |
| `lang_toggle` | event | out | 玩家按了語言切換（中文／English）。UI 不自己切換語言，只送出事件。 |
| `lang_en` | bool | in | 目前語言是否為英文：`true` 時切換鈕的「English」反白，`false` 時「中文」反白（預設 `false`）。 |

流圖側（`flows/main.xtflow`）：

| 來源 | 去向 | 說明 |
|---|---|---|
| `ui#title.chapter` | `world.chapter`（number，`game.json` 宣告，初始 0） | 記錄所選章節；後續章節流程讀 `world.chapter`。 |
| `ui#title.lang_toggle` | 語言切換 | 目標：翻轉 `world.language`（zh-TW ↔ en），並由 `world.language` 推出 `lang_en`。XTAtrium 在地化（08 §8.1，AT-031）落地前沒有 `world.language`，暫以 `toggle` 節點直接驅動 `ui#title.lang_en`（只切換反白，不切換文字）。 |

字串鍵：`UI_PAPER_MAST`、`UI_TITLE_KICKER`、`UI_TITLE_LANG`、`UI_TITLE_LANG_ZH`、`UI_TITLE_LANG_EN`、`UI_TITLE_LEAD`、`UI_TITLE_LOGO`、`UI_TITLE_SUB`、`UI_TITLE_CONTENTS`、`UI_TITLE_CH1`、`UI_TITLE_CH2`、`UI_TITLE_CH3`。

## vn（日常、事件、劇情對白，1280×720）

依據：系統規格 §4.2「SCR_DAILY／SCR_EVENT」、美術風格 §五「日常與事件」。顯示文字全部由流圖以 `atrium.text` 解好後寫入 string port；UI 只負責排版與演出。

| port | 型別 | 方向 | 意義 |
|---|---|---|---|
| `bg` | string | in | 背景 id（`office_night`、`office_day`、`kitchen_morning`、`clockshop`、`dock_fog`、`barge_deck`、`boiler_room`…；空字串＝純色新聞紙底）。未知 id 顯示純色底。 |
| `slot_l`、`slot_c`、`slot_r` | string | in | 三個立繪位置的角色 id（`sherefox`、`arthur`、`baskerville`、`victor`、`wolfhart`、`valet`、`partner`…；空字串＝無人）。 |
| `focus` | number | in | 正在說話的位置：0 無（旁白）、1 左、2 中、3 右；說話者亮、其餘變暗。 |
| `speaker` | string | in | 名牌文字（已在地化）；空字串時隱藏名牌。 |
| `line` | string | in | 對白內文（已在地化，含舞台指示的括號）。 |
| `line_seq` | number | in | 每換一行 +1；UI 以它重播文字出現的演出（同一句重送也會重播）。 |
| `style` | number | in | 0 一般對白、1 亞瑟筆記旁白（手寫筆記字體）、2 系統訊息。 |
| `choice_count` | number | in | 0～4，目前顯示的選項數；> 0 時對白框下方豎排顯示選項，且 `advance` 不送出。 |
| `choice1`～`choice4` | string | in | 選項文字（已在地化）。 |
| `choice_locked1`～`choice_locked4` | bool | in | 該選項是劇情證物解鎖的隱藏選項（帶銅製鑰匙圖示）。 |
| `trust` | number | in | 警督信任度 0～5；−1 隱藏警徽列（Ch.3 前）。 |
| `chapter_title` | string | in | 右上角章節名稱（已在地化）。 |
| `advance` | event | out | 推進到下一句（點擊對白區、Enter／空白）。選項顯示中不送出。 |
| `choose` | number | out | 玩家選了第幾個選項（1～4）。 |
| `auto` | event | out | 切換自動播放。 |
| `skip` | event | out | 切換快轉。 |
| `log` | event | out | 開啟對話紀錄（原型可先不實作畫面，只送事件）。 |

## paper（報紙：開場頭版、轉場報紙，1280×720）

依據：系統規格 §3.3、§4.2「SCR_PAPER」、美術風格 §四、§五。

| port | 型別 | 方向 | 意義 |
|---|---|---|---|
| `page` | number | in | 1 頭版、2 第二版與側欄。 |
| `mast` | number | in | 報頭版本：0 平常版、1 號外版、2 滲透版（Ch.8 後；原型只用 0）。 |
| `dateline` | string | in | 日期線（例「1887 年 10 月 14 日・濃霧　每份一便士」）。 |
| `headline` | string | in | 頭條。 |
| `subhead` | string | in | 副標。 |
| `body` | string | in | 頭版內文。 |
| `page2_head`、`page2_body` | string | in | 第二版標題與內文（下一案的引子）。 |
| `side` | string | in | 側欄短訊（城市短訊）。 |
| `ad` | string | in | 廣告欄。 |
| `stamp` | number | in | 頁面印章：0 無、1 結案、2 更正（敗北）。 |
| `next` | event | out | 翻頁／看完（左鍵、Enter、→）。 |
| `prev` | event | out | 回上一頁（←）。 |
