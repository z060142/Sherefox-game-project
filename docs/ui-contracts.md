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

UI 側實作（板子 `ui/boards/project/Vn.dc.html`）：

- **背景切換**：每個已知背景 id 各有一張 `<img id="bg-<id>">`，以 `bind:display="bg | eq('<id>')"` 只顯示相符的那一張；其他值（含空字串、未知 id）全部隱藏，露出新聞紙底色（下方墨色漸層也一併隱藏）。`bg` 變更時播 `bg-in`（360 ms 淡入）。已知 id：`office_night`、`office_day`、`kitchen_morning`、`clockshop`、`dock_fog`、`barge_deck`、`boiler_room`、`debate`；圖檔 `ui/boards/_blob/bg_<id>.png`（1280×720）。
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
| `next` | event | out | 翻頁／看完（左鍵、Enter、→）。 |
| `prev` | event | out | 回上一頁（←）。 |

UI 側實作（板子 `ui/boards/project/Paper.dc.html`）：

- **page**：1 顯示頭版（`#p1`），2 顯示第二版（`#p2`），其他值兩頁都不顯示；變更時播 `flip`（280 ms 淡入並右移收回）。頁尾中央的頁碼直接顯示 `page`。
- **頭版**：報頭圖（與 title 共用同一檔）居中，左右耳框；雙線；`dateline` 置中；`headline` 大標兩行（中文 52 px、英文 40 px，以 `:lang(en)` 切換），顯示與變更時播 `intro`（活字落下）；`subhead` 斜體兩行；內文五欄。
- **五欄內文的做法**：五欄各放一份同樣綁 `body` 的文字，欄寬相同所以斷行相同；第 k 欄把文字往上位移 (k−1) × 欄高（264 px），外層 `overflow: hidden`，看起來就是同一段文字由第一欄接到第五欄。超出五欄（約每欄 14 字 × 12 行）的部分被截掉。第二版內文三欄同法（250 px 寬、462 px 高）。
- **mast**：0 平常版（左耳「倫敦提燈報」、右耳「頭版」）；1 號外（兩耳改為銅底「號外」）；2 滲透版（報頭粗線改狼影紫 `#3b2a4a`；token 表尚無此色）。
- **第二版**：頁眉（左「第二版」、中報名、右 `dateline`）；`page2_head` 標題與三欄 `page2_body`；右側欄「城市短訊」（`side`）與「廣告」雙框（`ad`）。
- **stamp**：1 結案、2 更正；朱紅印章（雙框、旋轉 −9°）疊在內文第二欄上，約占畫面 3%，兩頁都顯示；變更時播 `stamp-in`（180 ms 蓋印）。
- **輸入**：左鍵（畫面任一處）、Enter、Space、→、PageDown → `next`；←、PageUp → `prev`。鍵盤同 vn，根元素持有焦點。
- 已知落差：美術風格 §五「章節開場」要求鋼版畫主圖，合約沒有圖片 port；Ch.1 開場內文（`SCR_CH01_S01_L003`，約 170 字）只填滿五欄中的一欄多。「收入剪報簿」提示（系統規格 §4.2）沒有對應 port，未做。

字串鍵：`UI_PAPER_MAST`、`UI_PAPER_PAGE1`、`UI_PAPER_PAGE2`、`UI_PAPER_SIDE`、`UI_PAPER_ADS`、`UI_PAPER_EXTRA`、`UI_PAPER_STAMP_CLOSED`、`UI_PAPER_STAMP_FIX`。

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
