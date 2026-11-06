# 流圖（M4c：Ch.1～3 全程可玩：劇情、蒐證、線索板、熱身、論戰、結算）

狀態：M5a 2026-11-06（XTAtrium 5aad137：AT-047 `atrium.ui.list` 的 `bare` 寫行動鈕的可用狀態，§4.8；AT-046 `atrium.ui.list` 的欄位參照取代組合鍵表、`atrium.textf` 取代展開的字串鍵，§5.2、§7.2；AT-043 跨圖脈衝同 tick，`debCmd*` 不再鎖住，§4.8；`debScript` 以 `columns` 宣告）。M4c 草案 2026-11-06（論戰 UI、書法大字、結算與後果接上論戰引擎，§4.8、§4.9；之前：M3 M2 第二輪之後：蒐證、證物冊、線索板接上 UI 並把板面交給論戰引擎；AT-040 `.emitted` 與 `find` 的 `from`／`filters`、AT-041 `atrium.gate`／`expr.truth` 已採用）。依據：`docs/architecture.md` §3、§8；`docs/ui-contracts.md`（title、vn、paper、investigate、board、evbook）；`docs/data-schema.md` §1～§5、§9、§13；`docs/debate-engine.md` §2.2；`docs/rulings.md`（C4、D2～D4、D11、F1、F3、F5、F6）；01-systems §1、§2、§3.1；XTAtrium docs 02 §2.3、04、05 §5.4、08 §8.1～§8.5a。

本文件說明 `flows/*.xtflow` 每一張圖做什麼、圖與圖之間經哪些 `world.*` 訊號與集合溝通、「步驟」的介面合約，以及已知限制。M3 範圍：標題 → 選章 → 開場報紙 → 逐行播放 vn 場景 → 蒐證（調查點、刻度、鑑定、提示、證物冊、保底、漏證）→ 線索板（放卡、理由、拉線判定、推理鏈、鑑定、進入論戰前檢查、交給論戰引擎的板面）→ 熱身（Ch.3）→ 論戰（布丁論戰、Ch.2、Ch.3）→ 結算（後果、重新論戰、結算場景台詞）→ 下一章。語言可即時切換。

## 1. 產生方式

全部由 `tools/gen_flows.py` 產生（論戰 UI 與結算圖在 `tools/gen_debui.py`，由 gen_flows 匯入；論戰引擎 `debate_engine`／`debate_warmup` 由 `tools/gen_debate.py` 產生；`uv run tools/gen_flows.py`；`--check` 只比對、不寫檔；`--stats` 印節點數）。產生器同時寫三樣東西，改任何一樣都改產生器再重產，不要手改：

- `flows/*.xtflow`：下表六張圖。
- `data/flow/*.json`：流圖用的輔助表（§5），全部由 `data/*.json` 推導。
- `game.json` 中流圖擁有的條目：`signals` 的 `trust`／`bookOpen`／`caseOutcome`、`collections`（§2.2）、`tables` 的 `flow*`（整組重寫：不再產生的表從 `game.json` 與 `data/flow/` 刪掉；`--check` 把多出來的檔案算成過期）與 `debScript`（物件形式，帶 `columns`）、`flows` 的清單與順序。其他條目原樣保留。

`flows` 依序載入 `main`、`dialogue`、`paper`、`investigate`、`board`、`debate_ui`、`debate_engine`、`debate_warmup`、`result`（`debate_ui` 在引擎之前：它寫的值與送的脈衝引擎同 tick 都收到；引擎寫的值 `debate_ui` 下一 tick 才讀到，`docs/debate-engine.md` §7.6）；載入順序就是同一 tick 內的執行順序（05 §5.4「跨圖可見性」）。

| 圖 | 節點／邊 | 職責 |
|---|---|---|
| `main` | 54／92 | 應用狀態機：語言切換、選章、步驟執行器（`steps` 表）、畫面可見性、證物冊覆蓋層、結尾卡 |
| `dialogue` | 52／95 | `vn` 步驟：依 `script` 表逐列把可播放的對白寫進 `ui#vn`；結算步驟的場景台詞（§4.9） |
| `paper` | 44／71 | `paper` 步驟：依 `papers` 表填 `ui#paper`，兩頁翻完即結束 |
| `investigate` | 497／819 | `investigate` 步驟（01-systems §1）與證物冊 `ui#evbook` |
| `board` | 1901／4100 | `board` 步驟（01-systems §2）：抽屜、板面、理由、拉線判定、推理鏈、鑑定、進入論戰、論戰引擎的板面輸入 |
| `debate_ui` | 1104／2156 | `debate`、`warmup` 步驟（§4.8）：引擎輸入、`ui#debate`、`ui#cutin`、玩家選擇、揭示播放 |
| `result` | 128／194 | `result` 步驟（§4.9）：`ui#result`、信任度、報紙側欄的結果、證物後果、重新論戰 |

### 1.1 寫法上的三條規則

1. **邊的順序**：一個節點依檔案順序沿各邊送出值或脈衝（05 §5.4）。需要看到「已結算」值的脈衝先經 `merge` 或閘（脈衝輸出在送出前結算）。條件效果一律走閘：運算式條件用 `atrium.gate`（`cond` ＝運算式的數值，08 §8.5a），布林條件用「脈衝閘」（`state` 的 `guard`）。
2. **不能回授**：Kahn 排序含所有節點邊（含脈衝邊），所以「一個值決定某脈衝能不能通過，而那個脈衝又改這個值」在圖裡是環。這類狀態一律放在 map 集合（`invState`、`boardState`、`caseNum`、`dlgState`）：寫入是效果、讀取是查詢，兩者之間沒有邊。代價是同一 tick 內讀不到新值（下一條）。
3. **集合在下一 tick 才讀得到**：效果立刻改變集合，但輸入沒變的查詢只在下一 tick 的第 (4) 步重算（08 §8.0、§8.3.2）。所以「先改再讀」的工作拆成兩個 tick：第二段掛在一個 1 ms、不重複的 `timer` 上（它在下一 tick 的第 (4) 步觸發）。產生器把所有 `timer` 宣告在最後，所以那一步裡每個查詢都已先重算（第 (4) 步依宣告順序執行）。`forEach` 是例外：它在觸發當下複製集合，迭代中鍵值改變的查詢會立即重算，所以「清空 → addAll → forEach」可以在同一個脈衝內完成。

## 2. world 訊號與集合

### 2.1 訊號

全部在 `game.json` 的 `signals` 宣告。值型訊號在一張圖內只有一個寫入邊（05 §5.3）；脈衝可由多張圖寫入。

| 訊號 | 型別 | 寫入者 | 讀取者 | 意義 |
|---|---|---|---|---|
| `world.language` | string | `main`（另：`--lang`） | 宿主、全部 `atrium.text`、`investigate`／`board`（重寫清單） | 目前語言（08 §8.1 自動宣告）。 |
| `world.chapter` | number | `main` | `dialogue`、`investigate`、`board` | 目前步驟所屬的章（`steps.chapter`）；尚未選章時 0。 |
| `world.stepRow` | number | `main` | （除錯用） | 目前步驟在 `steps` 表的列號；−1＝沒有步驟。 |
| `world.stepKind` | string | `main` | 各步驟圖 | 目前步驟的 `steps.kind`。 |
| `world.stepArg` | string | `main` | `paper` | 目前步驟的 `steps.arg`。 |
| `world.stepScene` | string | `main` | `dialogue` | 目前步驟的 `steps.scene`。 |
| `world.stepBegin` | pulse | `main` | 各步驟圖 | 每進入一個步驟發一次（值先寫好再發）；選章時若所選的列就是目前列，也再發一次（重玩同一章）。 |
| `world.stepDone` | pulse | 各步驟圖 | `main` | 目前步驟結束；`main` 在下一 tick 前進到下一列。 |
| `world.bookOpen` | bool | `main` | `investigate` | 證物冊覆蓋層開著。 |
| `world.trust` | number | `result` | `investigate`、`board`、`debate_ui`（`chapter_values`） | 警督信任度永久值（01-systems §3.1，起始 3）＝ 3 ＋ `progress.trustAdj`（結算圖讀不到自己寫的 world 值，所以永久值存在集合）。本案有效值＝永久值＋`caseMod.trust`（熱身），夾在 0～5。 |
| `world.caseOutcome` | string | `result` | `paper` | 上一案的結果：`win`／`notorious`／`lose`（§3.3 判定順序；Ch.1 未達成記 `lose`）；按結算的「繼續」時寫入。 |
| `world.resultLines`、`world.resultBranch` | pulse、string | `result` | `main`、`dialogue` | 結算畫面按「繼續」：播放結算場景（`steps.scene`）中 `script.branch` ＝ `win`／`lose` 的台詞。 |
| `world.debRetry` | pulse | `result` | `main` | 重新論戰（A-14）：步驟回到論戰（`cur.decrement`）。 |
| `deb*`、`dw*` | | `debate_ui`／引擎 | | 論戰引擎的介面（`docs/debate-engine.md` §2.1）；`debOppBonus`（漏證加成）由 `debate_ui` 寫。 |

### 2.2 集合

| 集合 | 種類 | 寫入者 | 內容 |
|---|---|---|---|
| `held` | list string | `investigate` | 本案已取得的卡（含劇情證物）；蒐證開始時清空 |
| `appraised` | list string | `investigate`、`board` | 已鑑定的卡 |
| `golden` | list string | `board` | 已取得的黃金線索；跨章保留（Ch.2 取得 G-01，Ch.3 使用），每次鎖板依該章結果加入或移除 |
| `oppHand` | list string | `investigate` | 漏證進對手手牌的卡（D4：每張手牌 +1、主導權 +10，由論戰接線時套用） |
| `caseNum` | map number | `investigate`、`board` | `appr`：本案剩餘鑑定次數 |
| `invState` | map number | `investigate` | `ticks` 剩餘刻度、`sc` 場景索引、`pop` 彈窗開著 |
| `spotSeen`、`spotsHere` | map number | `investigate` | 已調查的點；目前場景的點（id → 0 未調查／1 已調查），`spots` 清單的來源 |
| `toFind`、`needed` | list string | `investigate` | 調查點還能給的卡；其中的必需證物 |
| `notes`、`newCards` | list string | `investigate` | 案件筆記（檢視點的 `noteKey`）；證物冊打開後才取得的卡（紅點） |
| `caseSpots`、`sceneSpots` | list string | `investigate` | 迭代用的暫存清單 |
| `bookList` | map bool | `investigate` | `evbook.cards` 的來源：卡 → 已揭露（目前分頁的卡，依序） |
| `row0`～`row2` | list string（5） | `board` | 三條推理鏈，卡一律從 pos 0 連續排放 |
| `reason` | map number | `board` | 卡 → 選的理由 1～3（顯示順序） |
| `caseCards`、`boardCards` | list string | `board` | 本章可上板的卡（`flowCase.cards`）；其中已持有或黃金線索的＝抽屜 |
| `boardState` | map number | `board` | `locked`、`armed`、`bouncing`、`placeMode`、`solidSaid`、`invalidSaid` |
| `slotList`／`slotPos`、`linkMap`、`chainMap`／`chainCards`／`chainSolid`／`chainSoph`、`drawerList`／`drawRset`／`drawPlaced` | map | `board` | 四個清單 port 的來源與欄位（§5.2） |
| `debBoard`、`debBoardOk`、`debBoardLink` | list（24） | `board` | 論戰引擎的板面輸入（`docs/debate-engine.md` §2.2，宣告與 `tools/gen_debate.py` 相同） |
| `dlgState` | map number | `dialogue` | `row`：目前顯示的劇本列 |
| `dbui`、`dbuiS` | map number／string | `debate_ui`（`result` 讀 `maxd`／`maxc`，寫 `res`） | 論戰 UI 的狀態（§4.8） |
| `caseMod` | map number | `debate_ui` | `trust`：熱身給本案的信任度修正；每章的開場報紙步驟清空 |
| `progress` | map number | `result` | `trustAdj`：永久信任度相對 3 的增減（跨章） |
| `uiNodeIds`、`uiShat`、`uiCands`、`uiParryAll`、`uiParry`、`evF`、`evN` | list | `debate_ui` | 節點 id、反駁候選與事件紀錄的拆欄（§4.8） |
| `uiActOn`、`uiActWhy` | list bool／string（4） | `debate_ui` | `debate.act_enabled`／`act_reason` 的值陣列（`bare`，§4.8） |
| `uiNodes`；`uiChains`／`uiChPos`／`uiChLink`／`uiChSel` | map | `debate_ui` | `debate.nodes`（節點 → state）與 `debate.chains`（卡 → 鏈、位置、link、sel）的來源（§4.8） |
| `resStats`、`resCosts` | map string／list | `result` | 統計與代價兩個清單 port 的來源 |
| 引擎的集合 | | 引擎 | `debState`、`dwState`、`debOn`、`debEvents`、`debSnap`、`debAssisted`（`docs/debate-engine.md` §2.2） |

## 3. 步驟合約

一個步驟流圖：

- **接收**：`world.stepKind`、`world.stepArg`、`world.stepScene`、`world.chapter`（值）與 `world.stepBegin`（脈衝）。同一 tick 內 `main` 先執行，所以步驟流圖在 `stepBegin` 到達時看到的值已是新步驟的值。
- **啟動**：只在 `world.stepKind` 等於自己的種類時回應 `world.stepBegin`（脈衝閘）。
- **結束**：發一次 `world.stepDone`。
- **畫面**：步驟流圖不寫 `ui#<id>.visible`；可見性只由 `main` 決定（§4.1）。
- **UI 輸入**：只在自己的步驟進行中處理（以種類相符的閘擋住）。值型 out port 的點擊一律接 `ui#<surface>.<port>.emitted`（AT-040），同一項連點兩次也會反應；值本身在第 (5) 步先到，脈衝在第 (8) 步。

## 4. 各圖細節

### 4.1 `main`

- **語言**、**結尾卡**：同 M2。
- **選章**：`ui#title.chapter` → `find(steps, chapter, idx = "0")`；每次 `ui#title.chapter.emitted` 以 `filter(sample)` 把列號送進計數器 `cur`。若所選的列就是 `cur`（例如結尾卡關掉後連點同一章時值不變），另由一個以「相等」為 guard 的閘直接發 `world.stepBegin`。
- **步驟前進**：`world.stepDone` → `cur.increment`（同 M2）。
- **畫面**：`screen` 狀態 `title`／`paper`／`vn`／`investigate`／`board`／`debate`／`result`，由 `kind` 的 `compare.true` 切換（`warmup` 與 `debate` → debate）；`world.resultLines` → vn（結算場景的台詞）。
- **重新論戰**：`world.debRetry` → `cur.decrement`（結算步驟的前一列就是論戰步驟），步驟重新開始。
- **證物冊**：`book` 狀態（closed／open）：蒐證中 `ui#investigate.book` → open；`ui#evbook.close` → closed；每次步驟開始 → closed。寫 `ui#evbook.visible` 與 `world.bookOpen`。證物冊是 modal 覆蓋層，開著時下層收不到輸入。

### 4.2 `dialogue`

- `sceneKey` ＝ `format("CH0{a}_{b}", world.chapter, 場景)`（＝`script.sceneKey`）。
- 游標放在 `dlgState["row"]`。`first` ＝ `find(script, sceneKey, filters {"playable": "true"})`；`next` ＝ 同一個 find 加 `from = row + 1`（AT-040），所以場景中不可播放的列會被跳過，不再假設可播放列連續、也不假設標題在第一列。
- 步驟開始顯示 `first`；每個 `ui#vn.advance` 顯示 `next`；`next` 為 −1（場景結束）時發 `world.stepDone`。`atBegin` toggle 選 first／next，經 `merge` 結算後由 `atrium.gate`（`pick >= 0`／`pick < 0`）分流。顯示列以 `filter(sample)` 鎖住並寫回 `dlgState`；`line_seq` 在文字之後 +1。
- 顯示列 → `ui#vn` 各 port、章名、選項、`trust` 同 M2。
- **結算步驟的台詞**（D6）：`result` 步驟裡 `world.resultLines` 是第二個入口；兩個 find 多一個條件 `branch` ＝（結算步驟時）`world.resultBranch`、（vn 步驟時）空字串（vn 場景沒有 branch 列）。播完發 `world.stepDone`。

### 4.3 `paper`

同 M2。結果條依 `world.caseOutcome` 選 `sideLose*`（`lose`）／`sideNoto*`（`notorious`）／`sideWin*`（其他，含從標題直接選章時的空字串）。

### 4.4 `investigate`（01-systems §1；ui-contracts investigate、evbook）

**開始**（`stepBegin` 且種類為 investigate）：清空本案集合與 `invState`；`held` 加入本章 `obtain = event` 的卡（Ch.3：E03_02、E03_05）；警察參與章且 `world.trust ≥ 3` 時加入警方報告的卡（`flowCase.policeCards`，Ch.3 E03_01，其隱藏標籤全部算揭露，01-systems §3.1、F6）；`invState.ticks` ＝ `chapters.ticks`（−1 不限）；`caseNum.appr` ＝ `chapters.appraisals`；開場台詞 `ART_OPEN_CH0n`（警察章而沒有報告時 `ART_NO_REPORT`）。下一 tick：逐一檢查本章的調查點（`flowCase.spots`，不含 `phase = postDebate` 與 `auto` 的點；條件點 `requires = missing:G-01` 只在 `golden` 沒有 G-01 時算）：會產出卡且該卡尚未持有 → 加入 `toFind`，必需的再加入 `needed`；然後建第一個場景。

**場景**：`flowScene`（章、索引）給背景與點清單；`spotsHere` 以 forEach 重建（條件點依 `golden` 決定出現與否），`atrium.ui.list` 寫 `ui#investigate.spots`（欄位參照 `table:flowSpot[id].*`、`name` 在地化，§5.2）。左右箭頭（`nav`）改 `invState.sc`，下一 tick 重建（只有 Ch.3 有三個場景；切換不花刻度）。`area_name` 沒有字串鍵，寫空字串（§7）。

**點一個調查點**（`spot.emitted`；彈窗與證物冊沒開、刻度未用完）：

| 情況 | 刻度 | 彈窗 | 其他 |
|---|---|---|---|
| 第一次調查（任何類型） | −1（刻度有限時） | — | `spotSeen`、`spotsHere` 標 1，清單重寫 |
| 檢視點 | 同上 | 1：`nameKey`／`noteKey` | `noteKey` 加入案件筆記 |
| 證物點、卡未持有 | 同上 | 2（證詞點 3）：卡名、說明、等級 | 卡加入 `held`，移出 `toFind`／`needed`，證物冊紅點 +1 |
| 證物點、卡已持有（事件中已取得、警方報告、再訪） | 同上 | 1：卡名、說明 | — |
| 已調查過 | 不扣 | 同上重播 | — |

已調查過的點免費重播（01-systems §1.2）；`revisit` 點與信任度 ≥3 時的 `HS_CH03_01` 第一次也扣 1 刻度並只顯示情報（F5、F6）。點擊後亞瑟的一句（Ch.1 沒有，亞瑟還不是助手，§1.11）：刻度用完 `ART_TIME_OUT`、剩 3 格 `ART_TIME_LOW`，否則取得關鍵證物 `ART_FOUND_KEY`、劇情證物 `ART_FOUND_PLOT`、替代證物 `ART_SUB_FOUND`。

**彈窗關閉**（`dismiss`）：刻度已用完時，若還缺必需證物 → 亞瑟補撿（§1.7）：缺的卡全部加入 `held`，彈窗以取得卡的樣式顯示第一張，提示 `ART_RESCUE`；下一次關閉（或沒有缺卡時這一次）→ 結束蒐證。

**結束蒐證**（`end`，只在 `can_end` ＝ `needed` 為空時；或上述刻度用完）：`toFind` 中 `obtainable` 的卡在 `chapters.missToHand` 時進 `oppHand`（§1.8、D3、D4）；發 `world.stepDone`。`WARN_INV_END` 的確認與 `MSG_INV_MISSED`（漏證張數）原型不顯示：`atrium.textf` 已能填佔位，但結束蒐證後立刻換步驟，沒有顯示它們的時機與 port（§7.1 第 4 項）。

**提示**（`ask_hint`）：`toFind` 的張數 ≥4 `ART_REMAIN_MANY`、1～3 `ART_REMAIN_FEW`、0 `ART_REMAIN_NONE`；Ch.1 為 Sherefox 的 `SHF_C1_REMAIN`（還有）／`SHF_C1_IDLE`（沒有了；設計只有這兩句 SHF_）。

**證物冊**：打開時與換分頁、選卡、鑑定、換語言後（下一 tick）重寫 `cards`：0 本案證物（`held` 中非劇情證物）、1 黃金線索（`golden`）、2 私人收藏（`held` 中的劇情證物）；`notes` 寫案件筆記。詳情：`sel_name`／`sel_desc`／`sel_tags`（§4.6）／`sel_grade`；`sel_can_appraise` ＝ 已解鎖、有隱藏標籤且未揭露、剩餘次數夠。關閉時清空 `newCards`。

**鑑定**（§4.6）在證物冊與線索板共用同一套規則。台詞寫在 `investigate.hint`（證物冊沒有台詞 port）。

### 4.5 `board`（01-systems §2；ui-contracts board）

**開始**：清空板面、理由、`boardState`；下一 tick 由 `caseCards`（`flowCase.cards`：`usable` 含本章且 `onBoard` 的卡，證物表順序）挑出已持有或在 `golden` 中的卡成為抽屜 `boardCards`（G-01 在 Ch.3、S-01 只有取得時），再刷新。

**板面**：三條鏈各是一個清單 `row0`～`row2`，卡一律從 pos 0 連續排放（不留空格），所以「一列＝一條鏈」、第 c 列第 i 張就在格 5c + i。

- **放卡**（`place` ＝ chain × 5 + pos，已選卡時）：卡插到該列的 pos；該列較短時接在尾端（`coll.insert` 夾住索引）。若卡原本在別的列先移出；已在同一列不動（重排請先收回）；列滿 5 張 → `MSG_CHAIN_MAX`。
- **收回**（`unplace`）：移出，同列後面的卡往前補。若補上之後相鄰的兩張沒有共同標籤（無效），缺口右邊的卡全部退回抽屜。
- **理由**（`reason` 1～3，非黃金／替代證物）：寫 `reason`，相連的連結隨之重判（實證與詭辯互換，不會變無效，§2.3）。沒選理由的卡不能連結（M4c 照設計 §2.3 修正，M3 照 ref 視為理由錯誤）：它與左右鄰的連結為 0（不畫線，鏈在那裡斷開），不算進銅牌的張數；沒有共同標籤時照樣是無效（放下時彈回）。

**連結判定**（格 s 與 s+1，裁決 C4、ref `rules.link_kind`；全部是純查詢，每 tick 依板面重算）：對左卡的每個標籤 t（`flowCard.tag0..3`）：右卡也有 t（`table.has`），且兩邊都揭露它（不是隱藏標籤、或該卡已鑑定、或警方報告揭露）→ 共享；共享且兩邊都沒有把它標為擦邊 → 堅實。沒有共享 → 3 無效；任一張沒選理由 → 0；有堅實、兩邊理由都正確、都不是替代證物 → 1 實證（有黃金線索時 4）；其他 → 2 詭辯。

**刷新**（每次變動的下一 tick；這時每個查詢都已重算）：
1. 剛放下的卡（`placeMode`）旁有無效連結 → 亞瑟 `ART_INVALID`（每章一次），0.35 秒後卡退回抽屜（`bouncing` 期間不收輸入），再重寫清單；無效連結在這 0.35 秒內以 kind 3（剪刀）顯示。
2. 收回造成的無效相鄰 → 缺口右邊退回（上述），再重寫清單。
3. 剛放下的卡的新連結：含替代證物 `ART_SUB_LINK`；詭辯 `ART_SOPH_1`～`4` 輪流；本章第一條實證 `ART_SOLID`。
4. 寫四個清單（§5.2）：`slots`、`links`、`chain_info`（鏈序 0、1、2；預估傷害 `atrium.expr` `14 * (10 + 5 * 實證 + 8 * 詭辯) / 10`，與 ref `chain_damage_breakdown` 同形，2 張以上才有）、`drawer`。

**詳情面板**：選卡（`select.emitted`）後顯示名稱、說明、標籤（§4.6）、等級、三個理由（資料的顯示順序 `reason0Key`～`reason2Key`）、已選理由、`sel_fixed`（黃金／替代）、`sel_can_appraise`。`opponent_name` ＝ 對手 `speaker`；`threshold_text` ＝ `UI_BOARD_COND_EARLY`（`chapters.phase`；Ch.1～3 都是前期）；設計的 `UI_BOARD_THRESHOLD`（`{stage}論破：{condition}`）沒有 `{stage}` 的字串鍵（前期／中期／後期），所以不用（§7.3 第 2 項）。

**鑑定**：同證物冊（§4.6），台詞寫在 `remark`。

**進入論戰**（`to_debate`，§2.7）：沒有任何 2 張以上的鏈 → `MSG_BOARD_NOCHAIN`，不進入。板上有沒選理由的卡、或還有可鑑定的卡且有剩餘次數 → 第一次按下只顯示 `WARN_BOARD_NOREASON`／`WARN_BOARD_UNAPPR`，再按一次才進入；之後任何板面變動都重新要求確認。警告以 `atrium.textf` 填 `{n}`（沒選理由的張數／可鑑定的張數）與 `{left}`（剩餘鑑定次數），值在警告的脈衝上鎖住。通過後：
1. 寫 `debBoard`／`debBoardOk`／`debBoardLink`（`docs/debate-engine.md` §2.2）：格 0～14 ＝ 板面（空格與沒選理由的卡 `-`〔不參戰，§2.7〕、ok 1、link 0；link 1 實證〔含黃金〕、2 詭辯、鏈尾 0；ok ＝ 理由正確或固定），之後是不在板上的抽屜卡，從 15 起依抽屜順序（ok 依理由，未選為 0），`-` 補到 24 格。
2. 黃金線索（§2.3，默默收進）：`evidence.golden` 有值的卡，在抽屜中且理由正確 → 加入 `golden`，否則移除（Ch.2 E02_01 → G-01）。
3. 鎖定（之後不收輸入），發 `world.stepDone`。

### 4.6 共用：揭露、鑑定、標籤文字

- **揭露**：卡沒有隱藏標籤、或在 `appraised`、或（警察章、信任度 ≥3 且 `flowCard.policeFull`）。產生器要求 `policeTags` 為空或等於 `hiddenTags`（目前只有 E03_01）。
- **鑑定**（01-systems §1.5）：未解鎖（Ch.1）或沒有選卡 → 無反應；`appraiseCost` 0 或已揭露 → `ART_APPR_NONE`；剩餘次數不足 → `ART_APPR_EMPTY`；否則加入 `appraised`、`caseNum.appr` 扣掉次數，台詞依類型 `ART_APPR_MED_DONE`／`ART_APPR_MECH_DONE`／`ART_APPR_DUAL`。
- **標籤文字**（`sel_tags`）：每個標籤的 `tags.nameKey` 文字，未揭露的隱藏標籤寫 `UI_TAG_HIDDEN`（「？」），以空白隔開（字串表沒有分隔符號鍵，§7）。

### 4.7 （M3 的 `stubs` 已移除：熱身、論戰、結算由 §4.8、§4.9 接手）

### 4.8 `debate_ui`（`debate`、`warmup` 步驟；01-systems §4.4、§4.7、A-13；ui-contracts debate、cutin）

**節拍**：圖是無環的（Kahn 排序含脈衝邊），所以「一個階段結束後觸發下一個階段」不能接成脈衝鏈（那會回到自己的條件）。每一 tick 由 `clock` 的變化產生一個節拍脈衝；每個階段是一個 `atrium.gate`（節拍 ＋ 只讀 `dbui` 的條件），只寫下一階段的旗標或時間（`rsAt`、`r2`、`r3`、`sel`、`instAt`、`lockAt`、`pb`／`pbAt`、`holdAt`、`finAt`，時間以 `clock.seconds` 計）。

**開始**（`stepBegin`，種類 debate／warmup）：鎖住 `steps.arg` → `world.debCase`（`debScript` 恆為空字串＝用 `debCase`，表見 `docs/debate-engine.md` §2.4）；`world.debOppBonus` ＝ 主論戰時 `oppHand` 張數 × `opponents.hpPerMissed`（D4；手牌 port `hand` ＝ 張數 × `handPerMissed`）；清空 `dbui`／`dbuiS`；反駁候選 `uiCands` ＝ 主論戰：`debBoard` 的卡（板上與抽屜）、熱身：`opponents.hand`（事件中取得的 E03_05、E03_02）；發 `world.debStart`；0.1 秒後開始第 1 回合。

**一回合的畫面**（`rs`）：選擇重設（行動、鏈段、卡、目標、援護、訊息）、`hpO`／`hpM` ＝ 引擎值；**把引擎的輸出鎖住**（`snap`：回合、預兆各欄、動搖、尾聲、破竹、困獸、失守、矛盾、直覺、援護、失效次數、上限、脆弱數、熱身的回合／失誤／說法），所以揭示期間引擎已經寫好的下一回合預兆不會提早出現；`uiNodeIds` ＝ `debOn`（熱身：`dwClaim`）。下一拍（`r2`）重寫三個清單：

| port | 來源（列鍵） | 欄位 | 內容 |
|---|---|---|---|
| `nodes` | `uiNodes`（節點 id → state） | `text`、`src` ＝ `table:flowNodeView[id].*` | state：4 粉碎中（`uiShat`）＞3 第二說詞＞1 亮起＞2 脆弱（不在 `debNode`）＞0 |
| `chains` | `uiChains`（卡 → 鏈） | `pos`、`link`、`sel` ＝ `map:uiChPos`／`uiChLink`／`uiChSel`；`name` ＝ `table:flowCard[id].nameKey` | 鏈的格依序；link ＝ `debBoardLink`，本回合被設陷斷開（`debSnap` ≥ 回合）6、已援護（`debAssisted`）5；sel ＝ 在選中的鏈段內 |
| `parry_cards` | `uiParry`（卡） | `name` ＝ `table:flowCard[id].nameKey` | 選了反駁時＝`uiParryAll`：候選中破解亮起節點（`debCard` r1～r3／rT）且已揭露（熱身不要求）的卡 |

**顯示**（都是純查詢）：`mode`、立繪（`flowDebCase.char`：該講者在劇本中最常用的立繪）、名牌與類型、壓力錶（`dbui` 的 `hpO`／`hpM` 與鎖住的上限）、`round_text`／`counter_text`／`tell_star_text`／`claim_preview`（`atrium.textf`：`UI_DEB_ROUND` `{n}`、`UI_CH1_CONTRA` `{n}`／`{r}`、`UI_WARMUP_MISS`、`UI_DEB_TELL_LIKELY`、`UI_DEB_COUNTER_PREVIEW(_RUSH)` `{base}`／`{n}`／`{dmg}`，`dmg` 照引擎的 `base + per × n`、猛攻 ×`rushN`／`rushD`；依據小銅牌 `UI_DEB_TELL_BASIS_RULE` 的 `{n}` ＝ `flowWord.code`）、預兆（台詞、小動作、清晰度、依據銅牌 `flowWord`、候選 A／B 與 ★；尾聲的玉石俱焚以猛攻圖示顯示）、狀態、直覺與援護燈、`phase`、`float_*`、`result_line`。

**可按的行動**（§4.4、A-5、A-13）：實證連鎖＝板上有卡；詭辯＝本章開放（`playerActions`）且板上有未斷開的詭辯連結（不做臨場硬接）；反駁＝有亮起節點、不在失守，且有候選卡（或論破回合／尾聲可改出示鏈段）；觀察＝主論戰。熱身只有反駁。按了不可按的行動：不選取，確認列顯示原因（`MSG_DEB_NO_TARGET`、`MSG_DEB_NOSOPH`、`MSG_DEB_NOPARRY_SHISSHU`／`_NOCARD`）。`act_enabled`（四個行動依序可按與否）／`act_reason`（同一句原因的字串鍵，在地化；熱身的實證／詭辯／觀察與未開放的詭辯沒有原因）以 `atrium.ui.list` 的 `bare` 寫成值陣列（`uiActOn`／`uiActWhy`），每回合按鈕設定時（`r3`）與換語言時重寫，所以不可按的按鈕變灰並印出原因。

**選擇**（只在 phase 0；值型 port 經 `.emitted`）：`act`；`seg`：第一下＝起點，第二下＝終點（同一條鏈、中間的連結都在且沒斷開；否則重選起點）；`target`：可見的非脆弱節點（攻擊時）；`card`：反駁選擇器（清掉鏈段）；`back`：先退卡／鏈段，再退行動；`assist`：切換；`instinct`：發 `world.debInstinct`，0.1 秒後重新鎖住預兆，同時蓋 `STAMP_SEEN`。

**能否鎖定**：實證＝鏈段只有實證連結、目標可見、至少一張卡與目標共享標籤（A-2）；詭辯＝鏈段含詭辯連結、同上；反駁＝不在失守、有亮起節點，且（單張：破解亮起節點、已揭露）或（鏈段：論破回合或尾聲、含破解證物、全部已揭露、論破回合要過門檻：Ch.1 E01_03 理由正確；否則強攻卡＋失效次數 − 破竹 3 的減免，或 2 張以上全實證，ref `break_threshold_met`）；觀察一律可以。單張反駁在論破回合本身就是論破時（Ch.1 E01_03、門檻 1 張時的強攻卡）以「一張卡的鏈段」送出（引擎只在鏈段上判論破）。確認列：可鎖時是 `UI_DEB_LOCK_SUMMARY_ATK`（`{action}` 行動鈕文字、`{node}` 目標、`{cards}` 鏈段「起 → 訖」）／`_PARRY`（`{node}` 亮起節點、`{card}` 出示的卡或鏈段）／`_OBSERVE`，不可鎖時是提示（`MSG_DEB_SELECT_CHAIN`／`NOSOLID`／`NOSOPH`／`NOTAG`／`SELECT_PARRY`）；預估列：攻擊的鏈傷害（含動搖 ×1.5 與破竹）＋「可以論破／動搖」、反駁 `UI_DEB_PREVIEW_PARRY`（設計的 `UI_DEB_PREVIEW` `{mult}` 沒定義是哪個倍率，沒用，§7.1 第 9 項）。

**鎖定**：`debCmd*` 直接跟著選擇（行動、鏈段、卡、目標、援護）寫到匯流排，鎖定時已是結算好的值；發 `world.debLock`（引擎在同一 tick 收到值與脈衝，AT-043，`docs/debate-engine.md` §7.6；M4c 在鎖定脈衝上以 `filter(sample)` 鎖住的寫法已拿掉）；phase 1。

**揭示播放**（0.1 秒後；`dbui.pb`：1 取下一筆 → 以 `|` 拆進 `evF`／`evN` → 2 播放 → 3 等到 `pbAt`）：

| 紀錄 | 演出 | 停留 |
|---|---|---|
| `reveal`、`wReveal` | `reveal_me`／`reveal_opp`／`reveal_combo`／`reveal_seq`；`reveal_line`：我攻對手守＝Sherefox 的 `sfAction` 台詞、我守對手攻＝對手的 `action` 台詞、交鋒／僵持＝`reaction`，玉石俱焚＝`cornered`（G3，回合數輪流）；熱身＝警督的說法 | 1.4 秒 |
| `cutin` | 播放全幕者 → `cutin.big`＋`big_seq`；印章與降級的破竹 3 → `stamp`＋`stamp_seq`（`stamp_n` 層數）；英文時 `subtitle` ＝ `<id>_SUB`（大字譯名預設開，沒有設定畫面；破竹印章 `STAMP_HACHIKU_SUB` 以 `atrium.textf` 填層數 `{n}`） | 1.6／4.0（論破）／0.6 秒 |
| `dmgOpp`、`dmgPlayer`、`heal` | `float_*` 「−n」「+n」；壓力錶跟著紀錄的「後」值 | 0.6 秒 |
| `nodeRemoved`、`nodeAdded` | 節點粉碎（state 4）／加入，清單重寫 | 有台詞時 0.6 秒 |
| 其他 | `flowEvLine`（`case|種類|欄`）有台詞的寫進 `result_line`（截斷：`MSG_DEB_PARRY`）；台詞以 `atrium.textf` 填 `{name}`（對手）與 `{n}`（反擊量、矛盾數、尾聲反撲 `debCase.tw`），鍵與 `{n}` 存在 `dbuiS.rl`／`dbui.rln` | 0.6 秒或 0 |

第一筆之後 phase 2（結算數字，`result_line` 可見）。`skip`／`next`（播放中）＝快轉：其餘紀錄每拍一筆、不播大字。播完：壓力錶＝引擎值、節點與清單重寫、停 1.5 秒（或 `next`）；沒結束 → 下一回合；結束（`debOver`／`dwOver`）→ phase 3，1.2 秒（或 `next`）後：熱身把 `dwTrustDelta` 寫進 `caseMod.trust`，發 `world.stepDone`。

### 4.9 `result`（`result` 步驟；01-systems §4.2 SCR_RESULT、§3.1～3.3、§8.8、A-14；ui-contracts result）

引擎的輸出在論戰結束後保留，結算圖直接讀。

- `win`：`debOutcome` win 1／unachieved 2／其他 0；`opp_line`：勝利或未達成時，論戰場景最後一回合對手的第一句無標記台詞（`flowDebCase.winLine`：Ch.1 L028、Ch.2 L046、Ch.3 L045），敗北空白。
- `stats`（`resStats`，依序）：回合數、截斷次數、最大單次傷害（`dbui.maxd`）、最長連鎖（`dbui.maxc`）、論破次數（`dbui.brks`：播放到的 `break|1` 紀錄）、援護使用、狐耳直覺使用、剩餘主導權（沒有主導權的論戰不列傷害、援護與主導權）。「讀對預兆」沒有資料（引擎不記），不列。
- 信任度（§3.1）：永久值 `perm` ＝ 3 ＋ `progress.trustAdj`；變動 ＝ `chapters.trustDebate` 時勝 +1／敗 −1，加 `trustNotoriety` 且惡名 ≥3 時 −1（設計是下一案開始時套用，數值相同）；`trust_from`／`to` 只在 `chapters.trustShown`（Ch.3）顯示。
- `comment`：勝利 惡名 0 `ART_RES_CLEAN`、1～2 `MID`、≥3 `NOTORIOUS`；敗北（含未達成）`LOSE`、惡名 ≥3 `LOSE_NOTO`。
- `costs`（敗北）：信任度下降時 `UI_RES_COST_TRUST`，再加本案的扣押（10-cases：Ch.2 E02_01、Ch.3 E03_04，`flowDebCase.seize`；`UI_RES_COST_SEIZE` 以 `atrium.textf` 填卡名 `{name}`）。清單寫的是已在地化的文字（寫入當下的語言；清單本來就只在結算開始時寫一次）。`can_retry` ＝ 敗北。
- **繼續**：寫 `progress.trustAdj`、`world.caseOutcome`（§3.3：敗北 `lose`、勝利且惡名 ≥3 `notorious`、否則 `win`）；勝利時加入本章 `obtain = afterDebate` 的卡（F3：E02_08 進私人收藏 `held`）；Ch.2 敗北移除 G-01（10-cases：Ch.3 改由 S-01 取代）；`world.resultBranch`（win／lose）後發 `world.resultLines`，`dialogue` 播放結算場景的那一支，播完結束步驟。
- **重新論戰**（A-14）：發 `world.debRetry`。所有後果都在「繼續」時才套用，所以重來時沒有東西要還原；板面（`debBoard*`）不變，引擎由 `debStart` 重設。

## 5. 輔助表 `data/flow/`

`tools/gen_flows.py` 由 `data/*.json` 推導，`game.json` 以 `flow*` 名稱載入。

### 5.1 資料重整

| 表 | 一列 | 內容 |
|---|---|---|
| `flowCard` | 一張證物卡 | 數字化的 `grade`（0 一般、1 關鍵、2 劇情、3 黃金、4 替代，＝ UI 的 grade）與 `appraise`（0～3）、`story`／`goldenCard`／`sub`／`fixed`／`hidden`／`policeFull` 旗標、`reason1..3`（＝`reason0..2Key`）、`tags`／`hiddenTags`／`grazingTags` 與拆開的 `tag0..3` |
| `flowSpot` | 一個蒐證階段的調查點 | 數字化的 `type`（0 檢視、1 證物、2 證詞）、`yield`（產出的卡，最多一張，產生器驗證）、`reqMissing`（`requires = missing:X` 的 X）、名稱與筆記鍵、矩形 |
| `flowScene` | 章 × 場景 | 鍵 `章:索引`；`bg`（`hotspots.scene` → vn 背景 id）、該場景的點 |
| `flowCase` | 一章 | 場景數、全部點、事件中取得的卡、警方報告的卡、可上板的卡 |

### 5.2 清單 port 的來源

`atrium.ui.list` 的 `fields` 以列鍵（list 元素／map 鍵）引用其他來源（08 §8.4，AT-046）：`table:<表>[<鍵欄>].<欄>`、`coll:<名>.contains`、`map:<名>`。每列會變的欄位各放一個以卡（或格、鏈）為鍵的 map，取代 M4c 的組合鍵表（`flowBook`、`flowDrawer`、`flowSlot`、`flowChain`、`flowChainView`，已刪）。寫清單的那串效果先清空、再依序寫好這些 map，最後才寫清單。

| port | 來源（列鍵 → 值） | 其他欄位 |
|---|---|---|
| `investigate.spots` | `spotsHere`（調查點 → 狀態） | `name`、`x`～`h`、`type` ＝ `table:flowSpot[id].*` |
| `evbook.cards` | `bookList`（卡 → 已揭露） | `name`、`grade` ＝ `table:flowCard[id].*`；`isnew` ＝ `coll:newCards.contains` |
| `evbook.notes` | `notes`（筆記鍵，在地化） | — |
| `board.drawer` | `drawerList`（卡 → 已揭露） | `reason_set`、`placed` ＝ `map:drawRset`／`map:drawPlaced`；`name`、`grade` ＝ `table:flowCard[id].*` |
| `board.slots` | `slotList`（卡 → 鏈，依格序） | `pos` ＝ `map:slotPos`；`name`、`grade` ＝ `table:flowCard[id].*` |
| `board.links` | `linkMap`（格 → kind） | `chain`、`pos` ＝ `table:flowLink[key].*`（`flowLink`：連結格 → 鏈、位置，12 列） |
| `board.chain_info` | `chainMap`（鏈 → 預估傷害，依鏈序寫入） | `chain` ＝ `index`；`cards`、`solid`、`soph` ＝ `map:chainCards`／`chainSolid`／`chainSoph` |
| `debate.nodes`、`debate.chains`、`debate.parry_cards` | §4.8 | `flowNodeView`：節點 id（含脆弱節點 F1～F12）→ `textKey`、`src`（恆空） |

## 6. 驗證

`tests/README.md`。

- `uv run tests/check_playthrough.py`：story 流程（M2 的檢查），蒐證與線索板以最短路線通過（`tests/gen_case.py` 的 `MINIMAL`，第一次按「進入論戰」只顯示警告、第二次進入）；結尾卡關掉後連點同一章（值不變，經 `.emitted`）也會重新開始。
- `uv run tests/check_case.py [--frames DIR]`：Ch.1 調查全部 10 點、不鑑定、組推薦鏈 E01_01→E01_04 並選對全部理由；Ch.2 用 3 次鑑定（1 次在證物冊）、漏 E02_05、一條詭辯（E02_04 理由錯）、一次無效彈回、兩條鏈。比對刻度、彈窗種類、提示與亞瑟台詞序列、清單 port 的 JSON（點、抽屜、格、連結、銅牌）、`oppHand`、`appraised`、`golden`，以及 `debBoard*` 與 ref 對同一路線的板面（`fixtures.ch1_board`；Ch.2 為 `ch2_case` 改 E02_04 理由錯、兩條鏈）逐格相等。

## 7. 已知限制與請求

### 7.1 已知限制

1. 調查時不播放 `hotspots.lines`（證物描述與反應台詞）：investigate 沒有對白 port；彈窗只顯示卡名與說明。鑑定台詞 `evidence.appraisalKey` 同樣沒有出口。
2. ~~「理由未定的卡不能連結」與「未選理由的卡不參戰」~~：M4c 照設計修正（§4.5）。
3. 放卡一律接成連續的鏈；不能在同一列內直接移動（先收回再放）；拖曳與自由擺放不做（ui-contracts board 原型簡化）。
4. 刻度歸零時在關閉彈窗後結束（設計：3 秒後自動結束）；「全部調查完畢」的確認、`WARN_INV_END`、漏證結算 `MSG_INV_MISSED`／`MSG_INV_MISSED_NONE`、`WARN_BOARD_LOCK` 確認、閒置台詞（`ART_IDLE_*`、30 秒）都沒做。
5. 熱身的本案信任度修正已接上（§4.8）；鑑定在熱身中用掉次數（F5）沒做（熱身不開放鑑定）。
6. 每個調查點最多產出 1 張卡（Ch.1～3 成立，產生器驗證）。
7. `area_name` 空白；Ch.1 板面的亞瑟台詞照用（Ch.1 沒有 SHF_ 版的線索板台詞）。
8. 同 M2：`sceneKey` 只適用 Ch.1～9；`dateline`、`mast`、`stamp` 沒有資料。
9. 論戰（§4.8）：論戰場景（`steps.scene` S05／S06）的台詞是推薦路線的逐字稿，不播放（含 Ch.1 論破後亞瑟招認的 L027～L035）；開場陳述、對手筆記、對決表的推薦、讀對預兆統計、`st_flags`（不能補強、必定攻擊、聽眾不耐）、預估列的 `preview_vs` 與 `UI_DEB_PREVIEW` 樣板（`{mult}`）、臨場硬接、首次大字必定完整播放、印章「落空的那一方」都沒做；跳過時不播大字。
10. 尾聲反撲的揭示台詞用 `cornered` 組（G3 沒有指定組）；脆弱節點沒有文字（只有 `UI_NODE_FRAGILE` 小標）；`src`（來自漏證的節點）恆空（引擎未實作手牌補入，`docs/debate-engine.md` §7.4）。

### 7.2 對 XTAtrium 的請求

1. ~~**`atrium.ui.list` 的多個變動欄位**~~：AT-046 的欄位參照落地（§5.2），組合鍵表已刪。
2. ~~**字串的具名佔位**~~：AT-046 `atrium.textf` 落地。`tools/build_data.py` 不再展開 `<KEY>__<值>` 鍵，改為驗證流圖填的佔位（`TEXTF_KEYS`：每個語言的樣板只能用流圖會填的名字）；UI 專案字串表裡 M4c 留下的展開鍵在同步時刪掉（`ui/bundle/` 要重新 pack 才會跟著少）。還沒用到的：`MSG_INV_MISSED`、`MSG_INV_RESCUE`、`WARN_INV_END`（沒有顯示時機，§4.4）、`UI_BOARD_THRESHOLD`（沒有 `{stage}` 鍵，§7.3）、`UI_DEB_PREVIEW`（`{mult}` 未定義，§4.8）。

3. ~~**`atrium.ui.list` 寫不了基本型別的 list port**~~（AT-047 `bare` 落地，`act_enabled`／`act_reason` 已寫入，§4.8）：它一律寫物件陣列；`debate.act_enabled`（`list<bool>`）以 `xt_surface_port_set_text` 寫入時被拒（kInvalidArgument），`act_reason`（`list<string>`）收下物件但顯示不出字。請求：`ui.list` 加「值」模式（例如 `fields` 只有一個欄位且 param `bare: true` 時寫 `[v, …]`）。原型不寫這兩個 port（按鈕不會變灰；按下不可用的行動時確認列說明原因）。
4. ~~**跨圖脈衝晚一 tick**~~：AT-043 查明是派送內重算節點的髒標記錯誤並修正；值與脈衝同 tick 送達（M5a 以探針確認），`debCmd*` 的鎖住已拿掉（§4.8）。

### 7.3 對資料管線的請求（`tools/build_data.py`）

1. 把 §5.1 的欄位收進正式表：`evidence.gradeNum`（或 UI 改吃字串）、`hotspots.typeNum`、`hotspots.sceneBg`、每章的場景表。
2. 字串：標籤分隔符號（例 `UI_TAG_SEP` ＝「・」／「 · 」）、區域／場景名稱鍵（`area_name`）、`UI_BOARD_THRESHOLD` 的 `{stage}`（前期／中期／後期論破的名稱鍵）、`HS_CH03_01` 在信任度 ≥3 時的筆記句（設計表的「驗屍報告已由警方提供，這裡只看得到現場」）、G-01／S-01 的說明與固定理由鍵（目前空白）。
