# UI port 合約

狀態：草案 2026-11-06（M0）。本文件是 UI（`ui/boards/` → `ui/project/`）與流圖（`flows/`）之間的合約；改合約先改本文件，再改板子與流圖。依據：`docs/architecture.md` §1、§2；XTAtrium docs 04 §4.2（端點位址）。

## 共同規則

- 方向以 UI 文件為準：`out` 由 UI 送出，流圖以 `ui#<surface>.<port>` 讀取；`in` 由流圖寫入（`ui#<surface>.<port>` 當邊的終點），UI 以 `bind:` 顯示。
- 流圖不得讀 `in` port、不得寫 `out` port（XTFrame 53 §53.5.4）。
- 值型（number／string／bool）`out` port 只用 `set(<port>, <值>)`：每次 `set` 都會儲存並發出一次 emit（同值也會發），這是 XTFrame 27 §27.13 的設計。event 型 `out` port 只用 `emit(<port>)`。兩者不混用（主線 2026-11-06 裁定；lint `trigger.setThenEmit` 將檢查）。
- 用 `xtframe-view` 量測或截圖時一律加 `--lang zh-TW`（或 `en`）：未指定語言時目前顯示原始鍵名，版面寬度會不同（T-623 修正前）。
- 已知轉換器問題（下一版轉換器修正）：重新 import 時未經編輯器修改的觸發器不會更新（T-618，暫用 `--force`）；置中的 dock 被錨成 `left top`（T-619）。
- 介面上的固定文字一律是字串鍵（`@key`），字串表在 `ui/project/shared/strings/<lang>.csv`（RFC 4180，`key,text`，有標頭列）。
- 板子的行內 `style` 不寫 `var(--token)`，改寫色碼（token 的值）：import 會把兩個以上元素相同的行內樣式合併成 `shared/base.xts` 的共用 class，而 `base.xts` 沒有宣告 token，編譯時警告「var(--x) is undefined」且顏色落回初始值；`<helmet>` 裡的 class 規則照常用 `var()`。另外，UI 的 `.xts` 只宣告它整值用到的 token，若別的 UI 的共用 class 用到某個 token，該 UI 也要至少整值用一次（例如 cutin 為此用了一次 `var(--copper)`）。

## title（標題畫面，1280×720）

| port | 型別 | 方向 | 意義 |
|---|---|---|---|
| `chapter` | number | out | 玩家在目錄欄選了章節：值為章節編號 1、2、3（預設 0 = 尚未選擇）。每次點擊送出一次，同一章重複點擊也會送出。 |
| `lang_toggle` | event | out | 玩家按了語言切換（中文／English）。UI 不自己切換語言，只送出事件。 |
| `lang_en` | bool | in | 目前語言是否為英文：`true` 時切換鈕的「English」反白，`false` 時「中文」反白（預設 `false`）。 |
| `ended` | bool | in | 「待續」結尾卡：`true` 時整個標題畫面被結尾卡蓋住（流圖在 Ch.4 預告報紙之後顯示 title 並設為 `true`）；預設 `false`。 |
| `end_dismiss` | event | out | 玩家在結尾卡上點一下或按 Enter／Space：要求關掉結尾卡。UI 不自己關，流圖把 `ended` 設回 `false`。 |

流圖側（`flows/main.xtflow`）：

| 來源 | 去向 | 說明 |
|---|---|---|
| `ui#title.chapter` | 步驟執行器 | 跳到該章 `steps` 的第一列（idx 0）。`world.chapter`（number，`game.json` 宣告，初始 0）＝**目前步驟所屬的章**（`steps.chapter`），由 `main` 寫入；開始時與所選章相同，之後隨步驟前進（Ch.3 末尾的最終報紙與 `end` 仍是 3）。見 `docs/flows.md` §2、§4.1。 |
| `ui#title.lang_toggle` | 語言切換 | 翻轉 `main` 的 `lang` 狀態，寫入 `world.language`（zh-TW ↔ en）；`lang_en` 由 `lang` 推出。`world.language` 被外部寫入（`--lang`）時狀態跟著它。 |
| `ui#title.end_dismiss` | 結尾卡 | `main` 把 `ui#title.ended` 設回 `false`（步驟仍是 `end`，標題與目錄照常顯示，選章即重新開始）；再次進入 `end` 步驟時結尾卡重新出現。 |

UI 側實作（板子 `ui/boards/project/Title.dc.html`）：

- **目錄欄**：每章一個可聚焦的 `<div class="entry">`（`btn-ch1`～`btn-ch3`，`tabindex="0"`，Enter／Space 由預設的鍵盤啟用觸發點擊），內含兩個元素：`Ch.n`（純文字、兩種語言相同，銅色小字）與 `@CHAP_0n_TITLE`（章名）。字串表沒有 `UI_CHAP_NO`（只有含 `{n}`／`{chapterTitle}` 佔位的 `UI_CHAPTER_CARD`），UI 無法填佔位，所以章號寫成字面。不用 `<button>`：按鈕裡放兩個子元素會被折成一段 rich text，子元素上的 `@key` 不會解析。點擊 → `set(chapter, n)`。
- **結尾卡（`ended`）**：`#end-card` 以 `bind:display="ended"` 蓋住整個畫面（報頭圖、粗細雙線、大字 `UI_TO_BE_CONTINUED`、下方小字 `UI_TITLE_LOGO`），吃掉所有點擊（目錄與語言切換都按不到）；`ended` 變更時播 `end-in`（500 ms 淡入，大字由 1.12 倍縮入）並取得焦點（`tabindex="0"`、`focus()`）。在卡上點一下（`click:emit(end_dismiss)`；Enter／Space 由預設的鍵盤啟用觸發同一個點擊）→ `end_dismiss`；卡片本身不關，等流圖把 `ended` 設回 `false`。

字串鍵：`UI_PAPER_MAST`、`UI_TITLE_KICKER`、`UI_TITLE_LANG`、`UI_TITLE_LANG_ZH`、`UI_TITLE_LANG_EN`、`UI_TITLE_LEAD`、`UI_TITLE_LOGO`、`UI_TITLE_SUB`、`UI_TITLE_CONTENTS`、`CHAP_01_TITLE`、`CHAP_02_TITLE`、`CHAP_03_TITLE`、`UI_TO_BE_CONTINUED`。`UI_TITLE_CH1`～`UI_TITLE_CH3` 已退役，並自 `ui/project/shared/strings/<lang>.csv` 移除。

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

UI 側實作（板子 `ui/boards/project/Vn.dc.html`）：

- **背景切換**：每個已知背景 id 各有一張 `<img id="bg-<id>">`，以 `bind:display="bg | eq('<id>')"` 只顯示相符的那一張；其他值（含空字串、未知 id）全部隱藏，露出新聞紙底色（下方墨色漸層也一併隱藏）。`bg` 變更時播 `bg-in`（360 ms 淡入）。已知 id：`office_night`、`office_day`、`kitchen_morning`、`clockshop`、`dock_fog`、`barge_deck`、`boiler_room`、`debate`；圖檔 `ui/boards/_blob/bg_<id>.jpg`（1280×720 JPEG，品質 88；2026-11-06 由 PNG 轉換，bundle 由 24.8 MB 降到 15.6 MB）。
- **立繪切換**：三個位置（`slot-l`、`slot-c`、`slot-r`）各有一組 `<img id="ch-<位置>-<id>">`，每個已知角色 id 一張去背圖，以 `bind:display="slot_x | eq('<id>')"` 只顯示相符的一張，未知或空 id 什麼都不畫（三組引用同一批圖檔，打包時去重）。位置元素綁 `class.dim = focus | ne(n)`（左 1、中 2、右 3）與 `class.narr = focus | eq(0)`：`.dim` 且非 `.narr` 時套色彩調整（亮度 −0.14、飽和度 −0.5，220 ms 過渡）；`focus` 0 時三人都不變暗。`slot_x` 變更時播 `ink-in-<位置>`（420 ms 淡入）。疊放順序：中在最下，左、右在上。不用符號：XTAtrium 會把符號實例內的每個元素（路徑 id 帶 `/`）登記成 `ui.vn.<id>.<事件>` 訊號而對每個發出「not a valid signal name」警告（一個 vn 畫面 225 行）。已知 id：`sherefox`、`arthur`、`baskerville`、`victor`、`wolfhart`、`valet`（Ch.2 費奇）、`partner`（Ch.3 皮爾斯）；圖檔 `ui/boards/_blob/char_<id>.png`（440×660）。
- 新增背景或角色：在板子多加一張 `<img>`（同樣的 `eq` 綁定）並重新 import；流圖與合約不變。圖檔一律平放在 `_blob/` 下，因為 `xtframe-import` 的 blob id 只能是單一檔名（`/_blob/<file>`），不能有子目錄。
- **文字演出**：`line_seq` 每次變更（及畫面顯示時）播 `reveal`：整句 260 ms 淡入並上移 6 px。逐字顯示（`text-reveal`）目前寫不進板子：轉換器把 `text-reveal` 當成樣式子集外的屬性丟掉。
- **style**：0 一般（新聞紙底、雙線頂線）；1 亞瑟筆記（`.note`：舊紙底、銅色頂線、橫格線、銅色左邊線；只有 NotoSansTC Regular 一種中文字面，所以用 `skewX(-6deg)` 模擬手寫斜度，英文同樣斜排）；2 系統訊息（`.sys`：深墨底、新聞紙色字、置中）。
- **選項**：`choice_count` > 0 時選項豎排在對白下方，對白框以底邊錨定、向上長高；第 n 個選項在 `choice_count` ≥ n 時顯示，`choice_lockedn` 為真時帶銅製鑰匙圖示並改銅色框字。
- **輸入**：左鍵點場景或對白框、Enter、Space → `advance`（只在 `choice_count` = 0 時）；點選項或數字鍵 1～4 → `set(choose, n)`（n ≤ `choice_count`）；快捷列（對白框右上的三個頁籤）點擊 → `auto`／`skip`／`log`；A → `auto`，Backspace → `log`。鍵盤觸發需要 UI 根元素持有焦點：根元素有 `tabindex="0" autofocus`，`key-activation="none"`。
- **其他**：`speaker` 空字串時隱藏名牌；`chapter_title` 空字串時隱藏章節頁籤；`trust` −1 時隱藏警徽列，0～5 時五枚警徽中前 `trust` 枚填銅色。
- 未做（合約沒有對應 port 或屬宿主行為）：獸耳族名牌角落小圖示、右鍵隱藏介面、Ctrl 長按快轉、滾輪開紀錄。

字串鍵：`BTN_AUTO`、`BTN_FAST`、`BTN_LOG`。

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
| `picture` | string | in | 頭版鋼版畫 id（`ch01`～`ch04` → `paper_ch0x.jpg`；空字串＝無圖，內文改排五欄）。版面（設計 session 2026-11-06 核准）：頭條 → 鋼版畫橫跨 3 欄 ＋ 導言 2 欄 → 「側欄・上一案結果」條。 |
| `result_head`、`result_sub` | string | in | 「側欄・上一案結果」條的標題與副標（NEWS_xx_WIN／NOTO／LOSE）；空字串隱藏該條（Ch.1）。 |
| `next` | event | out | 翻頁／看完（左鍵、Enter、→）。 |
| `prev` | event | out | 回上一頁（←）。 |

UI 側實作（板子 `ui/boards/project/Paper.dc.html`）：

- **page**：1 顯示頭版（`#p1`），2 顯示第二版（`#p2`），其他值兩頁都不顯示；變更時播 `flip`（280 ms 淡入並右移收回）。頁尾中央的頁碼直接顯示 `page`。
- **頭版**：報頭圖（與 title 共用同一檔）居中，左右耳框；雙線；`dateline` 置中；`headline` 大標最多兩行（中文 52 px、英文 40 px，以 `:lang(en)` 切換），放在 124 px 高的 flex 框裡垂直置中（一行的頭條不會在下方留白），顯示與變更時播 `intro`（活字落下）。
- **有圖（`picture` 非空）**：頭條下一列：左側鋼版畫框橫跨 3 欄（700 px 寬，`object-fit: cover`，960×640 原圖上下會裁掉一些），右側 2 欄先放 `subhead`（斜體，最多三行，在 72 px 高的框裡垂直置中），細線下是導言兩欄（下述位移法）。已知 id：`ch01`～`ch04` → `_blob/paper_ch0x.jpg`（每個 id 一張 `<img>`，`bind:display="picture | eq('ch0x')"`）；未知 id 只畫空框。
- **無圖（`picture` 空字串）**：`subhead` 置中橫跨全頁（兩行），其下內文五欄。
- **多欄內文的做法**：每欄各放一份同樣綁 `body` 的文字，欄寬相同所以斷行相同；第 k 欄把文字往上位移 (k−1) × 欄高，外層 `overflow: hidden`，看起來就是同一段文字逐欄接下去。欄寬 216 px（約 14 個中文字），欄高在有「上一案結果」條時 198 px（9 行）、沒有時 264 px（12 行）。有圖時只有兩欄（中文約 250 字），無圖時五欄。英文的有圖導言用較小的內文字（設計 session 2026-11-06 核准）：`:lang(en) #lead-col-1-text`／`#lead-col-2-text` 13 px、行高 16.5 px（198 px＝12 行、264 px＝16 行，位移量不變），Ch.1～4 開場內文（473～677 字元）都排得下；中文維持 15／22 px。超出的部分被截掉。第二版內文三欄同法（250 px 寬、462 px 高）。
- **側欄・上一案結果（`result_head`、`result_sub`）**：頁尾線上方一條舊紙底、上粗下細框線的橫條：左端深墨底標籤 `UI_PAPER_PREV_CASE`（UI-only 鍵「上一案結果」），右側 `result_head`（粗體一行）與 `result_sub`（斜體一行，空字串隱藏；兩行在條內垂直置中）。`result_head` 空字串時整條隱藏，同時 `#p1` 帶上 `class.tall`（`bind:class.tall="result_head | eq('')"`）：鋼版畫框與各欄改用較高的尺寸，位移量跟著換（`<helmet>` 的 `.tall #…` 規則，進 `<layout>`），頁面一直排到頁尾。
- **mast**：0 平常版（左耳「倫敦提燈報」、右耳「頭版」）；1 號外（兩耳改為銅底「號外」）；2 滲透版（報頭粗線改狼影紫 `#3b2a4a`；token 表尚無此色）。
- **第二版**：頁眉（左「第二版」、中報名、右 `dateline`）；`page2_head` 非空時是標題與三欄 `page2_body`，右側欄「城市短訊」（`side`）與「廣告」雙框（`ad`）。`page2_head` 空字串時（原型的轉場報紙都沒有第二版文章：`papers.page2HeadKey` 全空白）`#p2` 帶上 `class.wide`：文章區隱藏，城市短訊（左 680 px，頭條字體 30 px 粗體）與廣告（右 456 px，28 px）展開占滿整頁，中間一道直線。
- **stamp**：1 結案、2 更正；朱紅印章（雙框、旋轉 −9°）疊在畫面左下（有圖時蓋在鋼版畫上），兩頁都顯示；變更時播 `stamp-in`（180 ms 蓋印）。
- **輸入**：左鍵（畫面任一處）、Enter、Space、→、PageDown → `next`；←、PageUp → `prev`。鍵盤同 vn，根元素持有焦點。
- **預設值**（截圖用）：Ch.2 開場（`CH02_OPEN`：`HEAD_CH02`、`HEAD_CH02_SUB`、`SCR_CH02_S01_L003`、`NEWS_SIDE_01`），`picture` = `ch02`，上一案結果條是 Ch.1 的 `NEWS_01_END`（板子預設沒有副標；在地化包 2026-11-06 起 `NEWS_01_END_SUB` 是它的副標，流圖會送出），第二版沒有文章（展開版）。
- 已知落差：「收入剪報簿」提示（系統規格 §4.2）沒有對應 port，未做。

字串鍵：`UI_PAPER_MAST`、`UI_PAPER_PAGE1`、`UI_PAPER_PAGE2`、`UI_PAPER_SIDE`、`UI_PAPER_ADS`、`UI_PAPER_EXTRA`、`UI_PAPER_STAMP_CLOSED`、`UI_PAPER_STAMP_FIX`、`UI_PAPER_PREV_CASE`（新增，UI-only）。

## investigate（蒐證，1280×720）

依據：系統規格 §1、§4.2「SCR_INV」、美術風格 §五「蒐證」。調查點清單由流圖以 `atrium.ui.list` 寫入（XTAtrium 08 §8.4：來源為集合 `spotsHere`〔map：調查點 id → 狀態〕，join `hotspots` 表）。

| port | 型別 | 方向 | 意義 |
|---|---|---|---|
| `bg` | string | in | 目前區域的背景 id（同 vn）。 |
| `area_name` | string | in | 區域／場景名稱（已在地化）。 |
| `nav_prev`、`nav_next` | bool | in | 左右箭頭是否可用（Ch.3 的三個場景以此切換）。 |
| `spots` | list<struct{id: string, name: string, x: number, y: number, w: number, h: number, type: number, state: number}> | in | 本區調查點。`type`：0 檢視、1 證物、2 證詞、3 機關、4 鎖定；`state`：0 未調查、1 已調查（灰色）、2 不可用（鎖定）。座標為 1280×720 畫面上的矩形。 |
| `ticks`、`ticks_max` | number | in | 懷錶刻度（剩餘／總數）；`ticks_max` 0 表示不限（Ch.1）。剩 3 格以下時懷錶轉紅（UI 自行判斷）。 |
| `appraise_left` | number | in | 鑑定剩餘次數；−1 隱藏鑑定箱（Ch.1）。 |
| `trust` | number | in | 警徽信任度 0～5；−1 隱藏。 |
| `book_new` | number | in | 證物冊新取得數（紅點）；0 不顯示。 |
| `can_end` | bool | in | 「結束蒐證」可按（必需證物已齊）。 |
| `hint` | string | in | 亞瑟（Ch.1 為 Sherefox 自言自語）的提示氣泡文字；空字串隱藏。 |
| `hint_seq` | number | in | 每換一則提示 +1，重播氣泡。 |
| `popup_kind` | number | in | 0 無、1 情報文字、2 取得證物卡、3 取得證詞卡。 |
| `popup_title`、`popup_body` | string | in | 彈窗標題（卡名）與內文（情報或證物說明）。 |
| `popup_grade` | number | in | 取得卡片時的等級框：0 一般、1 關鍵、2 劇情、3 黃金、4 替代。 |
| `popup_seq` | number | in | 每開一次彈窗 +1。 |
| `spot` | string | out | 玩家點了哪個調查點（id）；彈窗開著時不送出。 |
| `nav` | number | out | −1 往左、+1 往右切換區域。 |
| `dismiss` | event | out | 關閉彈窗。 |
| `book` | event | out | 開證物冊。 |
| `ask_hint` | event | out | 點亞瑟頭像要一句提示。 |
| `end` | event | out | 結束蒐證（只在 `can_end` 為 true 時送出）。 |

UI 側實作（板子 `ui/boards/project/Investigate.dc.html`）：

- **場景與調查點同一個框**：背景（同 vn 的 `bg-<id>` 圖組與 `eq` 綁定、`bg-in` 淡入）與調查點清單放在同一個 1280×720 的 `#scene` 裡，以 `left: calc(50% - 640px); top: calc(50% - 360px)` 置中、不滿版；寬螢幕兩側露出深墨底。這樣 `spots` 的矩形永遠對得上畫面（滿版 `cover` 會依螢幕比例縮放裁切背景，矩形就偏了）。用 `calc` 而不用 `data-xt-anchor="center"`：後者被錨成 `left top`（T-619）。
- **調查點**：`<repeat port="spots">`，每筆一個 `#spot`，以 `translate-x／-y = item(x)／item(y)`、`width／height = item(w)／item(h) | range(0, 1280／720, 0px, 1280px／720px)` 放到矩形上；本身透明。滑鼠移上去才出現：鉛筆圈（兩道略錯開的橢圓框線＋燈火金微光）、類型圖示圓章（`type` 0～4：放大鏡、齒輪、對話框、鑰匙、封條）與名稱條（`item(name)`）。`state` 1（已調查）：常駐淡灰圈與去色圖示，右下角加勾；`state` 2（不可用）：常駐朱紅框的圖示。點擊 → `set(spot, item(id))`，`popup_kind` ≠ 0 時不送。
- **圖示一律是 PNG**（`_blob/ico_*.png`，44×44，由 SVG 轉出，見 `_blob/bg_README.md`）：XTFrame 0.15.0 不畫 `<repeat>` 範本裡的行內 `<svg>`（圖片照常）。範本裡的 `@key` 文字也不會在地化（顯示鍵名），所以清單項目內不放固定文字（「已調查」改用勾號表示）。
- **左上**：小標 `UI_INV_KICKER`；蒸汽懷錶（`ticks_max` > 0：指針轉到 `ticks／ticks_max` 的比例、右側「剩餘／總數」；`ticks_max` 0：不畫指針，顯示 `UI_INV_TICKS_FREE`）；`ticks` ≤ 3 且 `ticks_max` > 0 時錶殼與數字換朱紅（兩組 SVG 以 class 切換）。下一行鑑定箱＋`UI_INV_APPR`＋「×`appraise_left`」，−1 時整行隱藏。
- **上方中央**：區域名稱牌，左右箭頭；`nav_prev／nav_next` 為 false 時箭頭變淡且點擊不送。點擊或 Q／E → `set(nav, -1／1)`。
- **右上**：警徽列，同 vn（`trust` −1 隱藏）。
- **左下**：亞瑟頭像（`char_arthur.png` 裁頭部）點擊 → `emit(ask_hint)`；提示氣泡 `hint` 空字串隱藏，`hint_seq` 變更時播 `hint-in`。
- **右下**：`BTN_MENU_EVIDENCE`（`book_new` > 0 時右上角紅點顯示數字）→ `emit(book)`；`BTN_INV_END`，`can_end` 為 false 時灰色且點擊不送。
- **彈窗**：`popup_kind` > 0 時全畫面墨色遮罩（吃掉所有點擊）。1：新聞紙情報卡（小標 `UI_POINT_LOOK`、`popup_title`、`popup_body`），點任一處 → `emit(dismiss)`。2／3：剪報卡，等級框色依 `popup_grade`（0 黃銅、1 銀、2 舊紙＋深墨框＋朱紅「私人收藏」印 `UI_EVBOOK_TAB_PLOT`、3 金框＋金光、4 破損黃銅＝虛線框舊紙），小標為等級名 `UI_GRADE_*`（3 證詞卡改 `UI_POINT_TALK`）；點任一處先播 `fly`（420 ms，卡片縮小飛向證物冊按鈕）再 `emit(dismiss)`。`popup_seq` 變更時兩種卡都播 `pop-in`。Esc／Enter／Space → `emit(dismiss)`（不播飛入）。
- **鍵盤**（根元素持有焦點，同 vn）：Q／E 切區域、Tab 證物冊、F 結束蒐證（`can_end` 時）、Esc／Enter／Space 關彈窗。
- **預設值**（截圖用）：Ch.1 事務所廚房、6 個調查點（布丁盤已調查）、刻度不限、鑑定 2、證物冊紅點 1、Sherefox 自言自語 `SHF_C1_IDLE`；彈窗內容預設為「空空的布丁盤」，但 `popup_kind` 預設 0（不開窗）。
- 未做（合約沒有對應 port）：區域箭頭的封條狀態圖示、「調查點常亮」輔助選項與 Shift 顯示全部調查點、案件筆記按鈕、外地章「無警方支援」灰色徽章（合約以 `trust` −1 隱藏）、亞瑟／Sherefox 頭像切換（Ch.1 提示是 Sherefox 自言自語，頭像仍是亞瑟）、場景平移、刻度剩 3 格的提示音。

字串鍵：`UI_INV_KICKER`（新增）、`UI_INV_TICKS_FREE`、`UI_INV_APPR`（新增）、`UI_POINT_LOOK`、`UI_POINT_TALK`、`UI_GRADE_NORMAL`、`UI_GRADE_KEY`、`UI_GRADE_PLOT`、`UI_GRADE_GOLDEN`、`UI_GRADE_SUB`、`UI_EVBOOK_TAB_PLOT`、`BTN_MENU_EVIDENCE`、`BTN_INV_END`、`BTN_CLOSE`。新增的鍵只在 `ui/project/shared/strings/<lang>.csv`，尚未進根目錄 `strings/`。

## board（線索板，1280×720）

依據：系統規格 §2、§4.2「SCR_BOARD」、美術風格 §五「線索板」。

**原型簡化**：推理鏈本來就是一直線、最多 5 張、最多 3 條、板上最多 15 張，所以板面直接做成「3 條鏈 × 5 格」的軟木板：卡片放進某條鏈的某一格，與同鏈左右相鄰的卡自動相連，連結的類型（實證／詭辯／無效）由流圖判定後寫回。不做自由擺放與任意拉線；規則與設計文件相同。

| port | 型別 | 方向 | 意義 |
|---|---|---|---|
| `drawer` | list<struct{id: string, name: string, grade: number, appraised: bool, reason_set: bool, placed: bool}> | in | 證物抽屜：本案可參戰的卡（含本章可用的黃金線索、替代證物）。 |
| `slots` | list<struct{chain: number, pos: number, id: string, name: string, grade: number}> | in | 板面 15 格（chain 0～2、pos 0～4）；`id` 空字串＝空格。 |
| `links` | list<struct{chain: number, pos: number, kind: number}> | in | 每條鏈第 pos 與 pos+1 格之間的連結：0 無、1 實證、2 詭辯、3 無效（紅色火花，該卡會被彈回）、4 含黃金線索的實證。 |
| `chain_info` | list<struct{chain: number, cards: number, solid: number, soph: number, dmg: number}> | in | 推理鏈列表的銅牌：張數、實證數、詭辯數、預估傷害。 |
| `sel_id` | string | in | 詳情面板顯示的卡；空字串隱藏面板。 |
| `sel_name`、`sel_desc` | string | in | 卡名、說明（已在地化）。 |
| `sel_tags` | string | in | 已揭露標籤的顯示文字（以「・」連接）；未鑑定的顯示「？」。 |
| `sel_grade` | number | in | 等級（同 investigate）。 |
| `sel_reason1`～`sel_reason3` | string | in | 三個歸類理由（已在地化）；黃金線索時只有 1。 |
| `sel_reason` | number | in | 已選的理由 0（未定）～3。 |
| `sel_fixed` | bool | in | 理由已固定（黃金線索）。 |
| `sel_can_appraise` | bool | in | 「交給亞瑟」可按。 |
| `appraise_left` | number | in | 鑑定剩餘次數。 |
| `opponent_name`、`threshold_text` | string | in | 左上對手與類型、上方論破門檻提示（已在地化）。 |
| `remark` | string | in | 亞瑟的一句話（拉出詭辯時皺眉、首次實證、無效連結等）；空字串隱藏。 |
| `remark_seq` | number | in | 每換一句 +1。 |
| `select` | string | out | 點了抽屜或板上的某張卡（id）。 |
| `place` | number | out | 把選中的卡放進格子：值 = chain × 5 + pos（0～14）。 |
| `unplace` | string | out | 把板上的卡收回抽屜（id）。 |
| `reason` | number | out | 為選中的卡選理由 1～3。 |
| `appraise` | event | out | 把選中的卡交給亞瑟鑑定。 |
| `to_debate` | event | out | 進入論戰（確認流程由流圖以 vn 系統訊息或彈窗處理）。 |

UI 側實作（板子 `ui/boards/project/Board.dc.html`）：

- **整張板是一個 1280×720 的 `#sheet`**，以 `calc(50% - 640px)` 置中，不同比例時整體不散開。
- **頂列**：小標 `UI_BOARD_TITLE`、`UI_BOARD_OPPONENT`＋`opponent_name`；`threshold_text`（舊紙底、朱紅左線，最多兩行）；鑑定箱＋「×`appraise_left`」；`BTN_TO_DEBATE` → `emit(to_debate)`（Enter 同）。
- **左：證物抽屜**：`<repeat port="drawer">`，每筆一條剪報：左緣等級色條、卡名（兩行）、`appraised` 為 false 時朱紅「?」、`reason_set` 時打勾、`placed` 時釘針圖示並變淡；`item(id) | eq(sel_id)` 時反白。點擊 → `set(select, item(id))`。列表 476 px 高、可捲動（約 8 筆可見）。下方圖例：`UI_BOARD_LINK_SOLID`、`UI_BOARD_LINK_SOPH`、`UI_BOARD_LINK_INVALID`（新增）。
- **中：軟木板**（`_blob/ui_cork.jpg` 平鋪、銅框）3 列 × 5 格，列首 I／II／III。15 個空格框是固定元素，點擊 → `set(place, chain × 5 + pos)`（常數 0～14）。剪報卡是 `<repeat port="slots">`，以 `translate = item(pos) × 132 + 40、item(chain) × 140 + 18` 放到格上，`id` 空字串不畫；卡頂朱紅圖釘、等級色條（一般黃銅、關鍵銀、黃金金框＋金光、替代虛線框舊紙）、卡名四行；選中時朱紅外框。左鍵 → `set(select, item(id))`，右鍵 → `set(unplace, item(id))`；Delete → `set(unplace, sel_id)`（`sel_id` 非空時）。
- **連結**：`<repeat port="links">`，每筆畫在第 pos 與 pos+1 格的圖釘之間（畫在卡片之上、不吃點擊）：1 朱紅線（紅線）、2 鉛筆虛線＋中點裂紋齒輪（弱點）、3 剪刀（無效）、4 金線＋中點星（鏈外事實）、0 不畫。
- **下：推理鏈銅牌**：三塊固定的牌子，第 k 塊讀 `chain_info | item(k)`（**假設流圖依 chain 0、1、2 的順序送三筆**），顯示 `UI_BOARD_CHAIN_NO`＋I／II／III、`UI_BOARD_DMG`＋`dmg`（四捨五入）、`cards`＋`UI_BOARD_CARDS`、`UI_BOARD_SOLID`＋`solid`、`UI_BOARD_SOPH`＋`soph`；`cards` < 2 時改顯示 `UI_BOARD_CHAIN_EMPTY` 並變淡。用固定牌子而不用清單，是因為清單範本內的 `@key` 不會在地化。
- **右：詳情面板**（`sel_id` 空字串隱藏）：等級小標 `UI_GRADE_*`（依 `sel_grade`）、頂端等級色條、`sel_name`、`sel_tags`、`sel_desc`（四行）、`UI_BOARD_REASON`；`sel_reason` 0 時顯示 `UI_BOARD_REASON_NONE`，`sel_fixed` 時顯示 `UI_BOARD_REASON_FIXED`；三個理由列（`sel_reasonN` 空字串時該列隱藏，所以黃金線索只剩一列），選中的列深墨底、朱紅圓點；點擊 → `set(reason, n)`，`sel_fixed` 時不送。`BTN_APPRAISE` → `emit(appraise)`，`sel_can_appraise` 為 false 時灰色且不送。
- **亞瑟的一句話**：軟木板底部，頭像＋氣泡（兩行），`remark` 空字串隱藏，`remark_seq` 變更時播 `remark-in`。
- **預設值**（截圖用）：Ch.2，抽屜 7 張（E02_01～E02_07，其中 6 張已上板；任務單寫「抽屜 5 張」與兩條鏈共 6 張衝突，取「抽屜列出全部可參戰卡」），鏈 I：E02_03→E02_02→E02_04→E02_05（三條實證），鏈 II：E02_06→E02_01（詭辯：E02_01 選了錯誤理由「老闆私藏的稀有零件」），詳情面板為 E02_01，亞瑟台詞 `ART_SOPH_2`。
- 未做（合約沒有對應 port 或屬拖曳）：拖曳放卡與拖曳拉線、平移縮放、抽屜分頁、對手類型圖示與 `UI_TYPE_*` 滑鼠提示、五大標籤圖示、強攻／醜聞／動機圖示、已鑑定鋼印、推理輔助金齒輪、無效連結的火花動畫與卡片彈回演出、改理由時連結閃爍、1～3 選鏈。

字串鍵：`UI_BOARD_TITLE`、`UI_BOARD_OPPONENT`（新增）、`UI_BOARD_DRAWER`、`UI_BOARD_LINK_SOLID`、`UI_BOARD_LINK_SOPH`、`UI_BOARD_LINK_INVALID`（新增）、`UI_BOARD_CHAIN_NO`（新增）、`UI_BOARD_CARDS`（新增）、`UI_BOARD_SOLID`（新增）、`UI_BOARD_SOPH`（新增）、`UI_BOARD_DMG`（新增）、`UI_BOARD_CHAIN_EMPTY`、`UI_BOARD_REASON`、`UI_BOARD_REASON_NONE`、`UI_BOARD_REASON_FIXED`、`UI_GRADE_*`、`BTN_APPRAISE`、`BTN_TO_DEBATE`。

## debate（熱身、布丁論戰、主論戰，1280×720）

依據：系統規格 §4.4、附錄 A、美術風格 §五「論戰」（號外版型：對手主張以頭條字體排成節點，四個行動是鉛字塊，主導權是蒸汽壓力錶，預兆在「小道消息」欄）。規則全部在流圖；UI 只顯示狀態、收集選擇、播放揭示演出。數字與文字都由流圖算好、在地化後寫入。

**模式與對手**

| port | 型別 | 方向 | 意義 |
|---|---|---|---|
| `mode` | number | in | 0 主論戰、1 熱身（只開放反駁，無壓力錶）、2 Ch.1 布丁論戰（無壓力錶，顯示矛盾計數）。 |
| `opp_char` | string | in | 對手立繪 id（同 vn）；`me_char` 固定 `sherefox`。 |
| `opp_name`、`opp_type` | string | in | 對手名牌與類型（犯人／庇護者…，已在地化）。 |
| `hp_me`、`hp_me_max`、`hp_opp`、`hp_opp_max` | number | in | 壓力錶（主導權）；`mode` ≠ 0 時隱藏。數值可含小數，顯示時 UI 去掉多餘的 0（例 52.5）。 |
| `counter_text` | string | in | Ch.1 的「矛盾 n／2　剩 r 回合」或熱身的「失誤 n／3」；空字串隱藏。 |
| `round_text` | string | in | 「第 n 回合」。 |

**對手主張鏈與預兆**

| port | 型別 | 方向 | 意義 |
|---|---|---|---|
| `nodes` | list<struct{id: string, text: string, state: number, src: string}> | in | 主張節點（上方一排，最多 5）。`state`：0 一般、1 亮起、2 脆弱、3 第二說詞（紫框）、4 粉碎中（播放碎裂後由流圖移除）；`src` 非空時角落顯示「來自：你漏掉的證物」。 |
| `claim_preview` | string | in | 節點旁的主張傷害預告（例「主張 26＋4×3＝38」）。 |
| `tell_line` | string | in | 預兆台詞（對手立繪旁的泡泡）。 |
| `tell_gesture` | string | in | 小動作的文字描述（原型以字幕代替動畫，例「拉袖口、鞠躬」）。 |
| `tell_clarity` | number | in | 0 明示、1 模糊、2 劇本（鎖上的齒輪）。偽裝在 UI 上與無依據的明示相同（Ch.1～3 不會出現）。 |
| `tell_basis` | string | in | 依據小銅牌文字（觀察／規則 3／教學／狐耳直覺／困獸）；空字串不顯示。 |
| `tell_a`、`tell_b` | number | in | 候選行動圖示：0 主張、1 猛攻、2 補強、3 設陷；`tell_b` −1 表示只有一個（明示）。 |
| `tell_star` | number | in | 標 ★ 的候選：−1 無、0 = a、1 = b。 |
| `tell_star_text` | string | in | ★ 的說明（「較可能（規則 1）」）。 |
| `hand` | number | in | 對手手牌數（卡背剪影）；0 隱藏。 |

**我方推理鏈與行動**

| port | 型別 | 方向 | 意義 |
|---|---|---|---|
| `chains` | list<struct{chain: number, pos: number, id: string, name: string, link: number, sel: bool}> | in | 下方的推理鏈（同 board 的 3×5；`link` 為與右鄰的連結，含 5＝已援護、6＝本回合斷開；`sel` 為目前選中的鏈段）。 |
| `act_enabled` | list<bool> | in | 四個行動按鈕可按與否，依序 實證連鎖／詭辯／反駁／觀察。 |
| `act_reason` | list<string> | in | 不可按時按鈕下的小字（例「失守：這一回合不能反駁」）。 |
| `sel_act` | number | in | 目前選的行動 0 無、1～4。 |
| `parry_cards` | list<struct{id: string, name: string}> | in | 反駁時下方滑出的破解證物；空清單＝不顯示選擇器。 |
| `summary` | string | in | 鎖定確認列文字（例「反駁　對準：…　出示：E02_04」）；空字串隱藏確認列。 |
| `preview`、`preview_vs` | string | in | 預估列與依候選行動的小字。 |
| `can_lock` | bool | in | 「鎖定」可按。 |
| `instinct_left`、`assist_left` | number | in | 狐耳直覺燈、援護燈（亮燈數）。 |
| `instinct_ok` | bool | in | 狐耳直覺目前可用。 |
| `assist_armed` | bool | in | 援護已預先啟動（確認列多一行提示）。 |
| `act` | number | out | 選行動 1～4。 |
| `seg` | number | out | 點我方鏈上的卡：chain × 5 + pos（第一次＝鏈段起點，第二次＝終點；流圖判斷）。 |
| `target` | string | out | 點對手節點改選攻擊目標。 |
| `card` | string | out | 在反駁選擇器中選卡。 |
| `lock` | event | out | 鎖定。 |
| `back` | event | out | 返回上一步（鎖定前）。 |
| `instinct` | event | out | 使用狐耳直覺。 |
| `assist` | event | out | 啟動／取消援護。 |

**狀態**

| port | 型別 | 方向 | 意義 |
|---|---|---|---|
| `st_shaken` | number | in | 動搖剩餘回合（0 無；顯示「動搖」銅牌與 ×1.5 燈）。 |
| `st_break` | bool | in | 論破回合（「現在是論破的時機」）。 |
| `st_tail` | number | in | 尾聲剩餘回合（0 無；兩錶之間的「尾聲」銅牌）。 |
| `st_hachiku` | number | in | 破竹層數 0～3（Ch.1 為預覽，UI 以淡色顯示：`st_hachiku_preview`）。 |
| `st_hachiku_preview` | bool | in | 破竹只作預覽（Ch.1）。 |
| `st_konju`、`st_shisshu` | number | in | 困獸、失守剩餘回合（0 無）。 |
| `st_flags` | string | in | 狀態列其他項目（不能補強／必定攻擊／聽眾不耐…），已在地化、以「・」連接。 |

**揭示與結算演出**

| port | 型別 | 方向 | 意義 |
|---|---|---|---|
| `phase` | number | in | 0 選擇中、1 揭示中（行動牌翻開與演出）、2 結算數字、3 論戰結束。選擇中以外，行動按鈕不可按。 |
| `reveal_me`、`reveal_opp` | number | in | 翻開的行動牌：我方 1～4、對手 0～3（另 4＝垂死反撲）。 |
| `reveal_seq` | number | in | 每回合揭示 +1，重播翻牌演出（3～6 秒，依 `reveal_combo` 的演出順序）。 |
| `reveal_combo` | number | in | 0 我攻對手守、1 我守對手攻、2 交鋒、3 僵持。 |
| `reveal_line` | string | in | 揭示時的台詞（對手陳述或 Sherefox 的「等一下！」）。 |
| `float_opp`、`float_me` | string | in | 從錶上彈出的數字（例「−35」「+10」）；空字串不彈。 |
| `result_line` | string | in | 本回合結算的一句話（MSG_DEB_*）。 |
| `skip` | event | out | 快轉揭示（按住／點一下跳到結算數字）。 |
| `next` | event | out | 揭示播完後繼續（自動播放時由流圖計時）。 |

UI 側實作（板子 `ui/boards/project/Debate.dc.html`）：

- **整體**：背景 `_blob/bg_debate.jpg` 滿版；其餘全部放在一張 1280×720 的 `#sheet`（`calc(50% - 640px)` 置中），寬螢幕兩側露出背景。號外版型：左上報頭條（`UI_PAPER_MAST`＋朱紅「號外」`UI_PAPER_EXTRA`＋`round_text`），其下雙線；對手立繪在右（`opp_char` 用與 vn 相同的 `eq` 圖組，`char_<id>.png`，300×450），Sherefox 立繪固定在左。`show` 時播 `intro`（印刷滾筒由左往右刷過，600 ms，播完自隱）。立繪在 `phase` 0 時循環播 `fidget`（1.5 秒一輪的輕微起伏，代替小動作動畫），`phase` ≠ 0 時暫停；`opp_char` 變更時播 `ink-in`。
- **對手主張鏈（`nodes`）**：上方五個**固定欄位**，第 k 欄讀 `nodes | item(k)`（`id` 空字串不顯示，所以清單照順序最多 5 筆），欄間以銅管相連。不用 `<repeat>`：清單範本裡的 `@key` 不會在地化，而節點的小標（`UI_NODE_NORMAL`／`UI_NODE_LIT`／`UI_NODE_FRAGILE`／`UI_NODE_SECOND`）與 `UI_NODE_STURDY_SRC` 都是固定文字。每欄是一塊頭條鉛字（頭條字體三行，英文四行）。`state` 1 亮起：朱紅外框＋燈火金光暈（呼吸）＋朱紅小標與 ▼；2 脆弱：右下裂紋、閃爍；3 第二說詞：狼影紫小標、淡紫底；4 粉碎中：朱筆一劃劃掉頭條（320 ms）後下墜淡出（900 ms，停在透明，等流圖移除）。`src` 非空時角落顯示 `UI_NODE_STURDY_SRC`（UI 不顯示 `src` 的內容）。點擊 → `set(target, nodes[k].id)`（`phase` 0 時）。`claim_preview` 在主張列右下（朱紅小字，空字串隱藏）。
- **小道消息欄（預兆）**：欄頭 `UI_DEB_GOSSIP`（新增）＋右側狐耳直覺鈕（`BTN_DEB_INSTINCT`，兩顆燈依 `instinct_left`；`instinct_ok` 為 false 時灰且不送；點擊或 F → `emit(instinct)`，同時畫面邊緣暗下 0.5 秒）；台詞泡泡（`tell_line`，中文加「」、英文加“”，以 `:lang(en)` 切換；泡泡尾巴指向立繪；空字串隱藏）；小動作字幕（`tell_gesture`，手形小圖示）；黃銅眼睛（`tell_clarity` 0 全睜＋`UI_DEB_TELL_CLEAR`、1 半睜＋`UI_DEB_TELL_FUZZY`、2 鎖頭＋`UI_DEB_TELL_SCRIPT`）與依據小銅牌（`tell_basis`，空字串隱藏）；候選行動牌 A／B（圖示＋`UI_ACT_*`；`tell_b` −1 時只有一張；`tell_star` 0／1 的那張金框加星）；`tell_star_text` 在最下方。
- **壓力錶**：兩個 SVG 圓錶（銅框、新聞紙錶面），指針 `rotate = hp | range(0, hp_max, -120, 120)`（右滿左零，240° 行程），錶環三段：50% 以上白、20～50% 琥珀、20% 以下鏽紅；中央數字 `format('{0}／{1}')`（數字以 %.6g 印出，52.5 不會多 0）。數字依區段變色，鏽紅區錶面抖動。對手錶在右上（`st_shaken` > 0：錶下掛 `UI_DEB_PREVIEW_SHAKEN`「動搖 ×1.5」銅牌與燈、洩壓閥冒汽；`st_break`：錶外一圈朱紅呼吸光環），我方錶在左下。`mode` ≠ 0 時兩錶都隱藏，右上改為報框顯示 `counter_text`。`float_opp`／`float_me` 變更時數字從錶旁彈出並淡出（1.4 秒），同時錶側噴一團白汽。
- **對手名牌與手牌**：右側 `opp_name`＋`opp_type`；`hand` > 0 時顯示 1～3 張卡背剪影＋「×n」。
- **狀態圖示**（常駐，失效時淡到 22%）：困獸（朱紅爪痕，對手錶左下，兩顆燈＝`st_konju`，滑鼠移上顯示 `UI_STATE_KONJU_TIP`）；失守（淡墨裂開的方印，我方錶左上，一顆燈，移上顯示 `UI_STATE_SHISSHU_TIP`）；破竹（綠竹節，我方錶右上，依 `st_hachiku` 亮起裂痕＋「×n」，3 層金框；`st_hachiku_preview` 時 50% 淡色）。`UI_STATE_HACHIKU_TIP` 含 `{dmg}`／`{ctr}` 佔位，UI 無法填值，破竹沒有滑鼠提示。
- **我方推理鏈（`chains`）**：同 board 的 3×5，`<repeat>` 剪報小卡依 `item(chain)`、`item(pos)` 定位（`id` 空字串不畫），與右鄰的連結畫在卡右側的間隙：1 紅線、2 鉛筆虛線＋弱點齒輪、3 剪刀、4 金線＋星、5 已援護（虛線＋銅色繃帶圈裡的弱點齒輪）、6 本回合斷開（兩段斷線＋朱紅斜劃）。`sel` 為 true 的卡朱紅框、淡黃底。卡上方疊 15 個**固定透明格**，點擊 → `set(seg, chain × 5 + pos)`（常數 0～14，`phase` 0 時），所以空格也會送出，由流圖判斷。
- **反駁選擇器（`parry_cards`）**：第一筆 `id` 非空時，預估框上方滑出一塊（`picker-in`，220 ms），小標 `MSG_DEB_SELECT_PARRY`，卡片兩欄（證物 id＋卡名兩行），可捲動；點擊 → `set(card, item(id))`。與設計「從畫面下方滑出」不同：放在推理鏈上方，鏈保持可見（論破回合仍可點鏈段，由流圖判斷是否改出示推理鏈），所以沒有做 `BTN_DEB_PARRY_CHAIN` 分頁。合約沒有「已選的卡」port，選中的卡只在確認列文字中看得到。
- **預估框**：`UI_DEB_PREVIEW_LABEL`（新增）＋`preview`（兩行）＋`preview_vs`（兩行小字）；`preview` 空字串時整框隱藏。
- **確認列**：`summary` 空字串隱藏；`assist_armed` 時多一行 `UI_DEB_ASSIST_ARMED`（燈火金）。右側 `BTN_BACK`（→ `emit(back)`）與 `BTN_DEB_LOCK`（`can_lock` 為 false 時灰且不送；→ `emit(lock)`）；`phase` ≠ 0 時兩鈕換成 `UI_DEB_LOCKED` 框。
- **四個行動（鉛字塊）**：`UI_ACT_GROUP_ATK`「攻」＋實證連鎖、詭辯 │ 黃銅隔條 │ `UI_ACT_GROUP_DEF`「守」＋反駁、觀察；左上角小字 1～4。`sel_act` 選中的塊反白（新聞紙底、朱紅底線與光暈）；`act_enabled | item(i)` 為 false 時灰，`act_reason | item(i)` 印在塊內下方；`st_shisshu` > 0 時反駁塊蓋一道裂紋；`phase` ≠ 0 時整列變淡。**灰色的塊仍會送出 `act`**（`phase` 0 時）：系統規格 §4.4 要求失守時按下反駁要跳 MSG_DEB_NOPARRY_SHISSHU，所以由流圖判斷是否接受並顯示原因；流圖不得因此選取不可按的行動。
- **援護**：左下亞瑟頭像（`char_arthur.png` 裁頭部）＋`BTN_DEB_ASSIST`＋燈（`assist_left`；2 時才出現第二顆）；`assist_armed` 時燈火金框光；`assist_left` 0 且未待命時頭像去色。點擊或 V → `emit(assist)`（`phase` 0 時）。
- **狀態列**（右下）：`UI_DEB_STATUS_LABEL`（新增）；`st_break` → 朱紅 `UI_DEB_STATUS_BREAK_TURN`；`st_shaken` > 0 → 燈＋`UI_DEB_PREVIEW_SHAKEN`＋剩餘回合圓點；`st_tail` > 0 → `UI_TAIL`＋圓點；`st_flags`（最多三行）。全都沒有時顯示淡色「—」。其下 `BTN_DEB_NOTES`（合約沒有 port，只有外觀，不送事件）。`st_tail` > 0 時報頭列右端另掛「尾聲」大銅牌（設計說在兩錶之間）。
- **對決表**：右緣銅把手 `BTN_DEB_TABLE ▸`，點擊或 T 切換 `#table` 的 `Open` 狀態（UI 自己的狀態，不經 port）；展開為 4×3 的表（列 `BTN_DEB_*`、欄 `UI_TABLE_COL_*`、格 `UI_TABLE_*`，每格最多六行），疊在畫面中央之上；`tell_a`／`tell_b` 指到的欄（0／1 → 主張／猛攻、2 → 補強、3 → 設陷）表頭朱紅、格子淡黃；`st_shisshu` > 0 時反駁列淡出。不記住展開狀態。
- **揭示（`phase` 1～3）**：中段蓋上一條深墨帶；`reveal_seq` 變更時播 `reveal`：雙方黃銅邊大卡從兩側飛入（300 ms）、翻面（420～540 ms），我方卡顯示 `BTN_DEB_*`（`reveal_me` 1～4），對手卡顯示 `UI_ACT_*`（`reveal_opp` 0～3；4 垂死反撲顯示 `UI_TAIL` 與爪痕）；卡頂是 `SPK_SHEREFOX` 與 `opp_name`。`reveal_combo` 2：兩卡之間金色爆光＋`MSG_DEB_CLASH`；3：兩卡變淡（僵持）；0／1 外觀相同（演出順序由流圖計時）。`phase` 1 時帶子下緣顯示 `reveal_line`（760 ms 淡入），`phase` ≥ 2 時改顯示 `result_line`（朱筆底線）。揭示期間全畫面點擊、Enter、Space：`phase` 1 → `emit(skip)`，`phase` ≥ 2 → `emit(next)`。
- **鍵盤**（根元素持有焦點，同 vn）：1～4 行動、F 狐耳直覺、V 援護、T 對決表、Enter 鎖定（`can_lock`）／快轉／繼續、Space 快轉／繼續、Backspace 與右鍵 → `back`（`phase` 0 時）。
- **預設值**（截圖用）：Ch.2 主論戰第 3 回合：費奇（`valet`）70／100、我方 81／100，N1 亮起＋N2、N3，模糊預兆「主張／猛攻」與小動作「拉袖口、鞠躬」，推理鏈同 board 的樣本，破竹 1，已選反駁、選擇器兩張（E02_02、E02_04），確認列與預估列有字，手牌 1。
- 未做（合約沒有對應 port，或需要動畫素材）：立繪的小動作動畫（以字幕代替）、管線蒸汽流向亮起節點、論破時版面撕裂與齒輪撞擊主張鏈、鎖在 1 的「瀕死底線」紅燈、壓力錶玻璃碎裂、故事模式的推薦格與小動作標註、偽裝對手的常駐說明 `UI_DEB_DISGUISER`、看穿時台詞泡泡上的裂開面具、援護確認、方向鍵選節點／證物／鏈、滾輪捲動選擇器、Ctrl 長按快轉、對決表展開狀態的記憶、對手筆記畫面（只有按鈕）。

字串鍵：`UI_PAPER_MAST`、`UI_PAPER_EXTRA`、`UI_NODE_NORMAL`、`UI_NODE_LIT`、`UI_NODE_FRAGILE`、`UI_NODE_SECOND`、`UI_NODE_STURDY_SRC`、`UI_DEB_GOSSIP`（新增）、`BTN_DEB_INSTINCT`、`UI_DEB_TELL_CLEAR`、`UI_DEB_TELL_FUZZY`、`UI_DEB_TELL_SCRIPT`、`UI_ACT_CLAIM`、`UI_ACT_RUSH`、`UI_ACT_REINFORCE`、`UI_ACT_TRAP`、`UI_ACT_GROUP_ATK`、`UI_ACT_GROUP_DEF`、`MSG_DEB_SELECT_PARRY`、`UI_DEB_PREVIEW_LABEL`（新增）、`UI_DEB_PREVIEW_SHAKEN`、`UI_STATE_KONJU_TIP`、`UI_STATE_SHISSHU_TIP`、`BTN_BACK`、`BTN_DEB_LOCK`、`UI_DEB_LOCKED`、`UI_DEB_ASSIST_ARMED`、`BTN_DEB_SOLID`、`BTN_DEB_SOPH`、`BTN_DEB_PARRY`、`BTN_DEB_OBSERVE`、`BTN_DEB_ASSIST`、`UI_DEB_STATUS_LABEL`（新增）、`UI_DEB_STATUS_BREAK_TURN`、`UI_TAIL`、`BTN_DEB_NOTES`、`BTN_DEB_TABLE`、`UI_TABLE_TITLE`、`UI_TABLE_COL_*`、`UI_TABLE_*`、`SPK_SHEREFOX`、`MSG_DEB_CLASH`。新增的三個鍵只在 `ui/project/shared/strings/<lang>.csv`（`tools/build_data.py` 會保留並列為 UI-only），尚未進根目錄 `strings/`。

流圖側（`flows/debate_ui.xtflow`，`docs/flows.md` §4.8，M4c）：除了 `act_enabled`／`act_reason`（`atrium.ui.list` 只寫物件陣列：`list<bool>` 被拒、`list<string>` 顯示不出字，`docs/flows.md` §7.2 第 3 項；按不可用的行動時改在 `summary` 顯示原因）、`preview_vs` 與 `st_flags`（空字串）以外的 port 全部寫入。`summary`、`preview` 的具名佔位樣板填不了，以在地化片段加空白組成；`round_text`、`counter_text`、`tell_star_text`、`claim_preview` 用 `tools/build_data.py` 展開的 `<KEY>__<值>` 鍵。`skip`／`next` 在揭示中都是快轉，結算數字停留時 `next` 進下一回合（或結束）。

## cutin（書法大字與印章，覆蓋層，最上層，非 modal）

依據：系統規格 §4.7、§8.14；美術風格 §七。大字在兩種語言都是中文；英文模式下，若「大字譯名」開啟，字下方加小字譯名。

| port | 型別 | 方向 | 意義 |
|---|---|---|---|
| `big` | string | in | 全幕大書 id（`CUT_RONPA`、`CUT_SHAKEN`、`CUT_HACHIKU3`、`CUT_KONJU`、`CUT_SHISSHU`、`CUT_BRINK`、`CUT_REVERSE`、`CUT_DOUBLE`、`CUT_COUNTER`）。 |
| `big_seq` | number | in | 每播一次 +1（約 1.5 秒；論破約 4 秒）。 |
| `stamp` | string | in | 角落印章 id（`STAMP_PARRY`、`STAMP_TRAP`、`STAMP_WHIFF`、`STAMP_CLASH`、`STAMP_SEEN`、`STAMP_ASSIST`、`STAMP_HACHIKU`、`STAMP_HACHIKU_LOST`）。 |
| `stamp_seq` | number | in | 每蓋一次 +1（約 0.5 秒）。 |
| `stamp_n` | number | in | 破竹印章的層數（×n）。 |
| `subtitle` | string | in | 譯名小字（流圖依語言與設定決定；空字串不顯示）。 |
| `done` | event | out | 大字播完。 |

UI 側實作（板子 `ui/boards/project/Cutin.dc.html`）：

- **整個畫面透明、不吃輸入**（根元素 `pointer-events: none`，沒有背景），所以它在 `game.json` 是最後一個 surface、保持可見、非 modal；平時什麼都不畫，鍵盤輸入照常送到下層（宿主把輸入排給每個可見的 surface）。
- **全幕大書**：`big_seq` 變更時，`big` 為 `CUT_RONPA` 播 `ronpa`（4.0 秒），其他播 `big`（1.5 秒）：畫面變暗 70%（深墨）、中央一條新聞紙帶（雙線上下框，由中線展開 160 ms；黑墨大字在暗底上看不見，所以寫在紙帶上），大字由 1.3 倍縮入並由模糊轉清晰（420 ms；論破 1.45 倍、520 ms），落定時抖動四下（約 130 ms），停留到 1.1 秒（論破 3.5 秒），再放大、模糊、淡出（墨散）。圖檔：`CUT_RONPA`→`cut_ronpa.png`、`CUT_SHAKEN`→`cut_shaken.png`、`CUT_HACHIKU3`→`cut_hachiku.png`、`CUT_KONJU`→`cut_konju.png`、`CUT_SHISSHU`→`cut_shisshu.png`（900×430 contain）；沒有圖的 `CUT_BRINK`、`CUT_REVERSE`、`CUT_DOUBLE`、`CUT_COUNTER` 以 `@CUT_*`（兩種語言都是中文）朱紅大字代替。timeline 播完 → `emit(done)`（1.5／4.0 秒）。跳過、縮短、首播規則、震動強度由流圖決定（合約沒有對應 port）。
- **譯名**：`subtitle` 非空時，大字下方（紙帶外、暗底上）以新聞紙色大寫字距小字淡入（約 0.62 秒，論破 0.72 秒）；印章則在印章旁（右上的在印章下方、左下的在右側）顯示同一個 `subtitle`（0.15～0.68 秒）。只有一個 `subtitle` port：大字與印章同時播放時兩處顯示同一句。
- **角落印章**：`stamp_seq` 變更時播 `stamp`（168×168）：1.9 倍斜壓蓋下（150 ms）、回彈，停留到 0.5 秒，再縮成 0.55 倍留在角落到 2.7 秒，3.1 秒淡出。右上（對手側）：`STAMP_PARRY`、`STAMP_CLASH`、`STAMP_SEEN`；左下（我方側）：`STAMP_TRAP`、`STAMP_WHIFF`、`STAMP_ASSIST`、`STAMP_HACHIKU_LOST`（`stamp_lost.png`）、`STAMP_HACHIKU`（沒有圖：綠墨方框 `@STAMP_HACHIKU`「破竹」＋`format('×{0}', stamp_n)`）。
- 已知落差：系統規格 §4.7 規定落空印章蓋在「落空的那一方」，合約沒有方向 port，UI 一律蓋在左下（玩家反駁空過）；同一角落最多 3 枚並存、第 4 枚擠掉最舊一枚做不到（只有一個 `stamp` port，新印章直接重播）；大字的筆順寫入需要分筆素材，現為整張縮入。

字串鍵：`CUT_BRINK`、`CUT_REVERSE`、`CUT_DOUBLE`、`CUT_COUNTER`、`STAMP_HACHIKU`。

## result（結算，1280×720）

依據：系統規格 §4.2「SCR_RESULT」、§8.8。

| port | 型別 | 方向 | 意義 |
|---|---|---|---|
| `win` | number | in | 1 勝利、0 敗北、2 未達成（Ch.1）。 |
| `opp_line` | string | in | 對手的結局台詞。 |
| `stats` | list<struct{label: string, value: string}> | in | 統計列（回合數、讀對預兆、截斷次數…；已在地化與格式化）。 |
| `trust_from`、`trust_to` | number | in | 警督信任度變動；−1 隱藏。 |
| `comment` | string | in | 亞瑟評語（ART_RES_*）。 |
| `costs` | list<struct{text: string}> | in | 敗北時的「本案的代價」。 |
| `can_retry` | bool | in | 顯示「重新論戰」。 |
| `continue` | event | out | 繼續（進入報紙）。 |
| `retry` | event | out | 重新論戰。 |

UI 側實作（板子 `ui/boards/project/Result.dc.html`）：

- **整體**：桌面色（舊紙徑向漸層）上一張 1040×664 的剪報（新聞紙底、硬陰影、左右上角兩條斜貼的膠帶），放在以 `calc(50% - 640px)` 置中的 1280×720 `#sheet` 裡。剪報頂端是報名 `UI_PAPER_MAST` 與粗細雙線。
- **勝敗大字**（`win`）：三個元素依 `win | eq(1／0／2)` 只顯示一個：1 `UI_RES_WIN` 燈火金字＋深墨 3 px 硬陰影、0 `UI_RES_LOSE` 銅鏽色、2 `UI_RES_UNACHIEVED`（UI-only 鍵「未達成」）灰墨。中文 112 px、英文 84 px。顯示時與 `win` 變更時播 `verdict-in`（1.35 倍蓋下、回彈），`opp_line`（斜體置中，兩行，空字串隱藏）在 0.42 秒後淡入。勝利時剪報右下另蓋一枚 `UI_PAPER_STAMP_CLOSED` 朱紅印章（同 paper 的印章樣式，0.7 秒後蓋下）。
- **統計**（`stats`）：左欄 `<repeat>`，每筆一列「`item(label)` ⋯⋯ `item(value)`」（虛線導引、數值粗體右對齊、等寬數字）；列高 30 px，最多 9 列（超出截掉）。文字全由流圖在地化與格式化（`UI_RES_READS` 等含佔位的鍵由流圖代入後寫入）。
- **信任度**（`trust_from`、`trust_to`）：右欄頂端，`trust_from` < 0 時整列隱藏（Ch.2 沒有警督）。小標 `UI_RES_TRUST_LABEL`（UI-only 鍵「警督信任度」；`UI_RES_TRUST` 含 `{from}`／`{to}` 佔位，UI 無法填值），五枚警徽（同 vn 的 `.badge`）分兩層重疊：`trust_from` 層與 `trust_to` 層；顯示時與 `trust_to` 變更時播 `trust-in`：0.5～0.9 秒舊層淡出、新層淡入並由 1.18 倍縮回。右側 `format('{0} → {1}', trust_from, trust_to)`。
- **亞瑟評語**（`comment`）：亞瑟筆記本樣式（同 vn style 1：舊紙底、銅色頂線、`ui_ruled.png` 橫格線、銅色左邊線、`skewX(-6deg)` 斜體），頭像（`char_arthur.png` 裁頭部）＋`SPK_ARTHUR`；兩行，空字串隱藏。
- **本案的代價**（`costs`）：`win` = 0 時顯示，朱紅上下框、小標 `UI_RES_COST`，`<repeat>` 每筆一列（朱紅小方塊＋`item(text)`），可見 2～3 列。
- **按鈕**：右下 `BTN_RES_RETRY`（`can_retry` 為 false 時隱藏）→ `emit(retry)`；`BTN_RES_CONTINUE` → `emit(continue)`。鍵盤（根元素持有焦點，同 vn）：Enter／Space → `continue`，R → `retry`（`can_retry` 時）。
- **預設值**（截圖用）：Ch.2 勝利、費奇的結局台詞 `SCR_CH02_S05_L046`、9 列統計樣本、`trust_from`／`trust_to` = −1、`ART_RES_CLEAN`、沒有代價、不能重來。
- 未做（合約沒有對應 port）：敗北時先開對手筆記的回合紀錄、故事模式風評（`UI_RES_REPUTE`）、`BTN_RES_ACCEPT`。

字串鍵：`UI_PAPER_MAST`、`UI_RES_WIN`、`UI_RES_LOSE`、`UI_RES_UNACHIEVED`（新增，UI-only）、`UI_RES_TRUST_LABEL`（新增，UI-only）、`SPK_ARTHUR`、`UI_RES_COST`、`UI_PAPER_STAMP_CLOSED`、`BTN_RES_CONTINUE`、`BTN_RES_RETRY`。

流圖側（`flows/result.xtflow`，`docs/flows.md` §4.9，M4c）：全部 port 寫入；`stats` 的 `value` 是字串（數字以 `%.6g`），「讀對預兆」沒有資料不列；`continue` 之後畫面換成 vn 播結算場景的台詞，`retry` 回到論戰步驟。cutin 由 `debate_ui` 寫（`big`／`big_seq`、`stamp`／`stamp_seq`／`stamp_n`、英文時的 `subtitle`）；`done` 不讀。

## evbook（證物冊，覆蓋層，modal）

依據：系統規格 §4.2、§8.4（UI_EVBOOK_*）。

| port | 型別 | 方向 | 意義 |
|---|---|---|---|
| `tab` | number | in | 0 本案證物、1 黃金線索、2 私人收藏。 |
| `cards` | list<struct{id: string, name: string, grade: number, appraised: bool, isnew: bool}> | in | 目前分頁的卡。 |
| `sel_id`、`sel_name`、`sel_desc`、`sel_tags` | string | in | 詳情（同 board）。 |
| `sel_grade` | number | in | 等級。 |
| `sel_can_appraise` | bool | in | 「交給亞瑟」可按（蒐證中與線索板上）。 |
| `appraise_left` | number | in | 鑑定剩餘次數。 |
| `notes` | list<struct{text: string}> | in | 案件筆記（情報文字）。 |
| `select_tab` | number | out | 切換分頁。 |
| `select` | string | out | 選卡。 |
| `appraise` | event | out | 交給亞瑟。 |
| `close` | event | out | 關閉。 |

UI 側實作（板子 `ui/boards/project/Evbook.dc.html`）：

- **整體**：`game.json` 裡 `"modal": true` 的覆蓋層。全畫面深墨半透明遮罩（點一下 → `emit(close)`），中央一本攤開的剪貼簿（1120×640，以 `calc` 置中的 dock）：上方書名 `UI_EVBOOK_TITLE`、三個分頁、`BTN_CLOSE`、粗細雙線；左頁是卡片與案件筆記，中間書脊陰影，右頁是詳情。顯示時播 `open`（遮罩淡入、書本上移淡入）。
- **分頁**（`tab`、`select_tab`）：`UI_EVBOOK_TAB_CASE`／`UI_EVBOOK_TAB_GOLD`／`UI_EVBOOK_TAB_PLOT`，`tab | eq(n)` 的那一頁深墨底；點擊 → `set(select_tab, n)`。UI 不自己換頁，等流圖寫回 `tab` 與 `cards`。黃金線索分頁且 `cards` 第一筆 `id` 為空時顯示 `UI_EVBOOK_GOLD_EMPTY`。
- **卡片**（`cards`）：`<repeat>` 換行排列（每列 4 張、116×140）的剪報卡：頂端等級色條、膠帶、`item(id)`（小字編號）、卡名四行、`appraised` 為 false 時朱紅「?」、`isnew` 時右上朱紅圓點；等級框同 board／investigate（1 銀框、2 舊紙＋深墨 2 px 框、3 金框＋金光、4 虛線框舊紙）；`item(id) | eq(sel_id)` 時朱紅外框。點擊 → `set(select, item(id))`。卡片區 318 px 高、可捲動（約 2 列可見）。範本內沒有固定文字（範本裡的 `@key` 不會在地化）。
- **案件筆記**（`notes`）：左頁下方舊紙底、銅色頂線的框，小標 `UI_NOTES_TITLE`，`<repeat>` 每筆一段（銅色菱形＋`item(text)`，自動換行），可捲動。
- **詳情**（`sel_*`；`sel_id` 空字串隱藏）：同 board 的詳情面板：等級小標 `UI_GRADE_*`、頂端等級色條、右上 `sel_id`、`sel_name`、`sel_tags`、雙線、`sel_desc`（最多 9 行）；底部鑑定箱圖示＋`UI_INV_APPR`＋`format('×{0}', appraise_left)`，`BTN_APPRAISE`（`sel_can_appraise` 為 false 時灰色且不送）→ `emit(appraise)`。
- **鍵盤**（根元素持有焦點，同 vn）：Esc、Tab、Backspace → `close`；1／2／3 → `set(select_tab, 0／1／2)`；Q／E → `set(select_tab, tab ∓ 1)`（`offset` 後 `clamp(0, 2)`）。
- **預設值**（截圖用）：Ch.2 本案證物分頁 6 張（E02_01～E02_06；E02_01 為未鑑定的關鍵證物並選中，E02_05、E02_06 為新取得），案件筆記 2 則（`HS_CH02_09_NOTE`、`HS_CH02_11_NOTE`），鑑定 2 次。
- 未做（合約沒有對應 port）：卡片上的五大標籤圖示與已鑑定鋼印、方向鍵選卡、筆記分類。

字串鍵：`UI_EVBOOK_TITLE`、`UI_EVBOOK_TAB_CASE`、`UI_EVBOOK_TAB_GOLD`、`UI_EVBOOK_TAB_PLOT`、`UI_EVBOOK_GOLD_EMPTY`、`UI_NOTES_TITLE`、`BTN_CLOSE`、`UI_GRADE_*`、`UI_INV_APPR`、`BTN_APPRAISE`。
