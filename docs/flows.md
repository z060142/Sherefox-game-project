# 流圖（M3：Ch.1～3 劇情、蒐證、線索板可玩）

狀態：M3 草案 2026-11-06（M2 第二輪之後：蒐證、證物冊、線索板接上 UI 並把板面交給論戰引擎；AT-040 `.emitted` 與 `find` 的 `from`／`filters`、AT-041 `atrium.gate`／`expr.truth` 已採用）。依據：`docs/architecture.md` §3、§8；`docs/ui-contracts.md`（title、vn、paper、investigate、board、evbook）；`docs/data-schema.md` §1～§5、§9、§13；`docs/debate-engine.md` §2.2；`docs/rulings.md`（C4、D2～D4、D11、F1、F3、F5、F6）；01-systems §1、§2、§3.1；XTAtrium docs 02 §2.3、04、05 §5.4、08 §8.1～§8.5a。

本文件說明 `flows/*.xtflow` 每一張圖做什麼、圖與圖之間經哪些 `world.*` 訊號與集合溝通、「步驟」的介面合約，以及已知限制。M3 範圍：標題 → 選章 → 開場報紙 → 逐行播放 vn 場景 → 蒐證（調查點、刻度、鑑定、提示、證物冊、保底、漏證）→ 線索板（放卡、理由、拉線判定、推理鏈、鑑定、進入論戰前檢查、交給論戰引擎的板面）→ 論戰／熱身／結算（樁）→ 下一章。語言可即時切換。

## 1. 產生方式

全部由 `tools/gen_flows.py` 產生（`uv run tools/gen_flows.py`；`--check` 只比對、不寫檔；`--stats` 印節點數）。產生器同時寫三樣東西，改任何一樣都改產生器再重產，不要手改：

- `flows/*.xtflow`：下表六張圖。
- `data/flow/*.json`：流圖用的輔助表（§5），全部由 `data/*.json` 推導。
- `game.json` 中流圖擁有的條目：`signals` 的 `trust`／`bookOpen`／`caseOutcome`、`collections`（§2.2）、`tables` 的 `flow*`、`flows` 的清單與順序。其他條目原樣保留。

`flows` 依序載入 `main`、`dialogue`、`paper`、`investigate`、`board`、`stubs`；載入順序就是同一 tick 內的執行順序（05 §5.4「跨圖可見性」）。

| 圖 | 節點／邊 | 職責 |
|---|---|---|
| `main` | 46／77 | 應用狀態機：語言切換、選章、步驟執行器（`steps` 表）、畫面可見性、證物冊覆蓋層、結尾卡 |
| `dialogue` | 42／76 | `vn` 步驟：依 `script` 表逐列把可播放的對白寫進 `ui#vn` |
| `paper` | 32／51 | `paper` 步驟：依 `papers` 表填 `ui#paper`，兩頁翻完即結束 |
| `investigate` | 503／834 | `investigate` 步驟（01-systems §1）與證物冊 `ui#evbook` |
| `board` | 1873／3968 | `board` 步驟（01-systems §2）：抽屜、板面、理由、拉線判定、推理鏈、鑑定、進入論戰、論戰引擎的板面輸入 |
| `stubs` | 12／19 | `warmup`、`debate`、`result` 立即回報完成；`debate` 記下勝利 |

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
| `world.trust` | number | （尚無寫入者，初值 3） | `investigate`、`board` | 警督信任度永久值（01-systems §3.1，起始 3）。熱身是樁，本案修正尚未接上（§6）。 |
| `world.caseOutcome` | string | `stubs` | （之後的結算／報紙） | 本案論戰結果；論戰是樁，一律 `win`。 |

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
| `caseSpots`、`sceneSpots`、`bookList` | list string | `investigate` | 迭代用的暫存清單 |
| `row0`～`row2` | list string（5） | `board` | 三條推理鏈，卡一律從 pos 0 連續排放 |
| `reason` | map number | `board` | 卡 → 選的理由 1～3（顯示順序） |
| `caseCards`、`boardCards` | list string | `board` | 本章可上板的卡（`flowCase.cards`）；其中已持有或黃金線索的＝抽屜 |
| `boardState` | map number | `board` | `locked`、`armed`、`bouncing`、`placeMode`、`solidSaid`、`invalidSaid` |
| `slotList`、`linkMap`、`chainMap`、`drawerList` | | `board` | 四個清單 port 的來源（§5.2） |
| `debBoard`、`debBoardOk`、`debBoardLink` | list（24） | `board` | 論戰引擎的板面輸入（`docs/debate-engine.md` §2.2，宣告與 `tools/gen_debate.py` 相同） |
| `dlgState` | map number | `dialogue` | `row`：目前顯示的劇本列 |

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
- **畫面**：`screen` 狀態 `title`／`paper`／`vn`／`investigate`／`board`，由 `kind` 的 `compare.true` 切換；樁步驟（`warmup`、`debate`、`result`）不改畫面，所以線索板之後停在線索板，直到 `vn`（結案筆記）出現。
- **證物冊**：`book` 狀態（closed／open）：蒐證中 `ui#investigate.book` → open；`ui#evbook.close` → closed；每次步驟開始 → closed。寫 `ui#evbook.visible` 與 `world.bookOpen`。證物冊是 modal 覆蓋層，開著時下層收不到輸入。

### 4.2 `dialogue`

- `sceneKey` ＝ `format("CH0{a}_{b}", world.chapter, 場景)`（＝`script.sceneKey`）。
- 游標放在 `dlgState["row"]`。`first` ＝ `find(script, sceneKey, filters {"playable": "true"})`；`next` ＝ 同一個 find 加 `from = row + 1`（AT-040），所以場景中不可播放的列會被跳過，不再假設可播放列連續、也不假設標題在第一列。
- 步驟開始顯示 `first`；每個 `ui#vn.advance` 顯示 `next`；`next` 為 −1（場景結束）時發 `world.stepDone`。`atBegin` toggle 選 first／next，經 `merge` 結算後由 `atrium.gate`（`pick >= 0`／`pick < 0`）分流。顯示列以 `filter(sample)` 鎖住並寫回 `dlgState`；`line_seq` 在文字之後 +1。
- 顯示列 → `ui#vn` 各 port、章名、選項、`trust` 同 M2。

### 4.3 `paper`

同 M2。結果條仍固定勝利版（論戰是樁，`world.caseOutcome` 恆為 `win`）。

### 4.4 `investigate`（01-systems §1；ui-contracts investigate、evbook）

**開始**（`stepBegin` 且種類為 investigate）：清空本案集合與 `invState`；`held` 加入本章 `obtain = event` 的卡（Ch.3：E03_02、E03_05）；警察參與章且 `world.trust ≥ 3` 時加入警方報告的卡（`flowCase.policeCards`，Ch.3 E03_01，其隱藏標籤全部算揭露，01-systems §3.1、F6）；`invState.ticks` ＝ `chapters.ticks`（−1 不限）；`caseNum.appr` ＝ `chapters.appraisals`；開場台詞 `ART_OPEN_CH0n`（警察章而沒有報告時 `ART_NO_REPORT`）。下一 tick：逐一檢查本章的調查點（`flowCase.spots`，不含 `phase = postDebate` 與 `auto` 的點；條件點 `requires = missing:G-01` 只在 `golden` 沒有 G-01 時算）：會產出卡且該卡尚未持有 → 加入 `toFind`，必需的再加入 `needed`；然後建第一個場景。

**場景**：`flowScene`（章、索引）給背景與點清單；`spotsHere` 以 forEach 重建（條件點依 `golden` 決定出現與否），`atrium.ui.list` 寫 `ui#investigate.spots`（join `flowSpot`、`name` 在地化）。左右箭頭（`nav`）改 `invState.sc`，下一 tick 重建（只有 Ch.3 有三個場景；切換不花刻度）。`area_name` 沒有字串鍵，寫空字串（§7）。

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

**結束蒐證**（`end`，只在 `can_end` ＝ `needed` 為空時；或上述刻度用完）：`toFind` 中 `obtainable` 的卡在 `chapters.missToHand` 時進 `oppHand`（§1.8、D3、D4）；發 `world.stepDone`。`WARN_INV_END` 的確認與 `MSG_INV_MISSED` 的張數需要佔位字串（§7），原型不顯示。

**提示**（`ask_hint`）：`toFind` 的張數 ≥4 `ART_REMAIN_MANY`、1～3 `ART_REMAIN_FEW`、0 `ART_REMAIN_NONE`；Ch.1 為 Sherefox 的 `SHF_C1_REMAIN`（還有）／`SHF_C1_IDLE`（沒有了；設計只有這兩句 SHF_）。

**證物冊**：打開時與換分頁、選卡、鑑定、換語言後（下一 tick）重寫 `cards`：0 本案證物（`held` 中非劇情證物）、1 黃金線索（`golden`）、2 私人收藏（`held` 中的劇情證物）；`notes` 寫案件筆記。詳情：`sel_name`／`sel_desc`／`sel_tags`（§4.6）／`sel_grade`；`sel_can_appraise` ＝ 已解鎖、有隱藏標籤且未揭露、剩餘次數夠。關閉時清空 `newCards`。

**鑑定**（§4.6）在證物冊與線索板共用同一套規則。台詞寫在 `investigate.hint`（證物冊沒有台詞 port）。

### 4.5 `board`（01-systems §2；ui-contracts board）

**開始**：清空板面、理由、`boardState`；下一 tick 由 `caseCards`（`flowCase.cards`：`usable` 含本章且 `onBoard` 的卡，證物表順序）挑出已持有或在 `golden` 中的卡成為抽屜 `boardCards`（G-01 在 Ch.3、S-01 只有取得時），再刷新。

**板面**：三條鏈各是一個清單 `row0`～`row2`，卡一律從 pos 0 連續排放（不留空格），所以「一列＝一條鏈」、第 c 列第 i 張就在格 5c + i。

- **放卡**（`place` ＝ chain × 5 + pos，已選卡時）：卡插到該列的 pos；該列較短時接在尾端（`coll.insert` 夾住索引）。若卡原本在別的列先移出；已在同一列不動（重排請先收回）；列滿 5 張 → `MSG_CHAIN_MAX`。
- **收回**（`unplace`）：移出，同列後面的卡往前補。若補上之後相鄰的兩張沒有共同標籤（無效），缺口右邊的卡全部退回抽屜。
- **理由**（`reason` 1～3，非黃金／替代證物）：寫 `reason`，相連的連結隨之重判（實證與詭辯互換，不會變無效，§2.3）。沒選理由的卡照常相連，判定時視為理由不正確（只能接成詭辯；設計 §2.3 說「不能連結」，見 §6）。

**連結判定**（格 s 與 s+1，裁決 C4、ref `rules.link_kind`；全部是純查詢，每 tick 依板面重算）：對左卡的每個標籤 t（`flowCard.tag0..3`）：右卡也有 t（`table.has`），且兩邊都揭露它（不是隱藏標籤、或該卡已鑑定、或警方報告揭露）→ 共享；共享且兩邊都沒有把它標為擦邊 → 堅實。沒有共享 → 3 無效；有堅實、兩邊理由都正確、都不是替代證物 → 1 實證（有黃金線索時 4）；其他 → 2 詭辯。

**刷新**（每次變動的下一 tick；這時每個查詢都已重算）：
1. 剛放下的卡（`placeMode`）旁有無效連結 → 亞瑟 `ART_INVALID`（每章一次），0.35 秒後卡退回抽屜（`bouncing` 期間不收輸入），再重寫清單；無效連結在這 0.35 秒內以 kind 3（剪刀）顯示。
2. 收回造成的無效相鄰 → 缺口右邊退回（上述），再重寫清單。
3. 剛放下的卡的新連結：含替代證物 `ART_SUB_LINK`；詭辯 `ART_SOPH_1`～`4` 輪流；本章第一條實證 `ART_SOLID`。
4. 寫四個清單（§5.2）：`slots`、`links`、`chain_info`（鏈序 0、1、2；預估傷害 `atrium.expr` `14 * (10 + 5 * 實證 + 8 * 詭辯) / 10`，與 ref `chain_damage_breakdown` 同形，2 張以上才有）、`drawer`。

**詳情面板**：選卡（`select.emitted`）後顯示名稱、說明、標籤（§4.6）、等級、三個理由（資料的顯示順序 `reason0Key`～`reason2Key`）、已選理由、`sel_fixed`（黃金／替代）、`sel_can_appraise`。`opponent_name` ＝ 對手 `speaker`；`threshold_text` ＝ `UI_BOARD_COND_EARLY`（`chapters.phase`；Ch.1～3 都是前期）。

**鑑定**：同證物冊（§4.6），台詞寫在 `remark`。

**進入論戰**（`to_debate`，§2.7）：沒有任何 2 張以上的鏈 → `MSG_BOARD_NOCHAIN`，不進入。板上有沒選理由的卡、或還有可鑑定的卡且有剩餘次數 → 第一次按下只顯示 `WARN_BOARD_NOREASON`／`WARN_BOARD_UNAPPR`（佔位 `{n}` 填不了，§7），再按一次才進入；之後任何板面變動都重新要求確認。通過後：
1. 寫 `debBoard`／`debBoardOk`／`debBoardLink`（`docs/debate-engine.md` §2.2）：格 0～14 ＝ 板面（空格 `-`、ok 1、link 0；link 1 實證〔含黃金〕、2 詭辯、鏈尾 0；ok ＝ 理由正確或固定），之後是不在板上的抽屜卡，從 15 起依抽屜順序（ok 依理由，未選為 0），`-` 補到 24 格。
2. 黃金線索（§2.3，默默收進）：`evidence.golden` 有值的卡，在抽屜中且理由正確 → 加入 `golden`，否則移除（Ch.2 E02_01 → G-01）。
3. 鎖定（之後不收輸入），發 `world.stepDone`。

### 4.6 共用：揭露、鑑定、標籤文字

- **揭露**：卡沒有隱藏標籤、或在 `appraised`、或（警察章、信任度 ≥3 且 `flowCard.policeFull`）。產生器要求 `policeTags` 為空或等於 `hiddenTags`（目前只有 E03_01）。
- **鑑定**（01-systems §1.5）：未解鎖（Ch.1）或沒有選卡 → 無反應；`appraiseCost` 0 或已揭露 → `ART_APPR_NONE`；剩餘次數不足 → `ART_APPR_EMPTY`；否則加入 `appraised`、`caseNum.appr` 扣掉次數，台詞依類型 `ART_APPR_MED_DONE`／`ART_APPR_MECH_DONE`／`ART_APPR_DUAL`。
- **標籤文字**（`sel_tags`）：每個標籤的 `tags.nameKey` 文字，未揭露的隱藏標籤寫 `UI_TAG_HIDDEN`（「？」），以空白隔開（字串表沒有分隔符號鍵，§7）。

### 4.7 `stubs`

`warmup`、`debate`、`result` 各一個脈衝閘：種類相符時 `stepBegin` 直接成為 `world.stepDone`。`debate` 另把 `world.caseOutcome` 設為 `win`。**M4c 待做**：Ch.2 主論戰結束時自動給 E02_08（裁決 F3，`hotspots.auto`），熱身的本案信任度修正（`dwTrustDelta`），對手手牌與主導權加成（`oppHand` × `opponents.handPerMissed`／`hpPerMissed`）。

## 5. 輔助表 `data/flow/`

`tools/gen_flows.py` 由 `data/*.json` 推導，`game.json` 以 `flow*` 名稱載入。

### 5.1 資料重整

| 表 | 一列 | 內容 |
|---|---|---|
| `flowCard` | 一張證物卡 | 數字化的 `grade`（0 一般、1 關鍵、2 劇情、3 黃金、4 替代，＝ UI 的 grade）與 `appraise`（0～3）、`story`／`goldenCard`／`sub`／`fixed`／`hidden`／`policeFull` 旗標、`reason1..3`（＝`reason0..2Key`）、`tags`／`hiddenTags`／`grazingTags` 與拆開的 `tag0..3` |
| `flowSpot` | 一個蒐證階段的調查點 | 數字化的 `type`（0 檢視、1 證物、2 證詞）、`yield`（產出的卡，最多一張，產生器驗證）、`reqMissing`（`requires = missing:X` 的 X）、名稱與筆記鍵、矩形 |
| `flowScene` | 章 × 場景 | 鍵 `章:索引`；`bg`（`hotspots.scene` → vn 背景 id）、該場景的點 |
| `flowCase` | 一章 | 場景數、全部點、事件中取得的卡、警方報告的卡、可上板的卡 |

### 5.2 清單 port 的組合鍵表

`atrium.ui.list` 一列只能有一個 join 與一個集合值（08 §8.4），清單裡每列有兩個以上會變的欄位時，改用「組合鍵」：集合元素是 `欄|欄|…` 字串，join 一張列出所有組合的表（§7 第 1 項的框架請求落地後刪除）。

| port | 來源集合 | join 表（列數） | 鍵 |
|---|---|---|---|
| `investigate.spots` | `spotsHere`（map：id → 狀態） | `flowSpot` | 調查點 id（狀態＝值） |
| `evbook.cards` | `bookList` | `flowBook`（104） | `id|已揭露|新取得` |
| `evbook.notes` | `notes` | — | 筆記鍵（在地化） |
| `board.drawer` | `drawerList` | `flowDrawer`（184） | `id|已揭露|理由已選|在板上` |
| `board.slots` | `slotList` | `flowSlot`（345） | `格|id` |
| `board.links` | `linkMap`（格 → kind） | `flowLink`（12） | 格 |
| `board.chain_info` | `chainMap`（鍵 → 預估傷害） | `flowChain`（108） | `鏈|張數|實證|詭辯` |

## 6. 驗證

`tests/README.md`。

- `uv run tests/check_playthrough.py`：story 流程（M2 的檢查），蒐證與線索板以最短路線通過（`tests/gen_case.py` 的 `MINIMAL`，第一次按「進入論戰」只顯示警告、第二次進入）；結尾卡關掉後連點同一章（值不變，經 `.emitted`）也會重新開始。
- `uv run tests/check_case.py [--frames DIR]`：Ch.1 調查全部 10 點、不鑑定、組推薦鏈 E01_01→E01_04 並選對全部理由；Ch.2 用 3 次鑑定（1 次在證物冊）、漏 E02_05、一條詭辯（E02_04 理由錯）、一次無效彈回、兩條鏈。比對刻度、彈窗種類、提示與亞瑟台詞序列、清單 port 的 JSON（點、抽屜、格、連結、銅牌）、`oppHand`、`appraised`、`golden`，以及 `debBoard*` 與 ref 對同一路線的板面（`fixtures.ch1_board`；Ch.2 為 `ch2_case` 改 E02_04 理由錯、兩條鏈）逐格相等。

## 7. 已知限制與請求

### 7.1 已知限制

1. 調查時不播放 `hotspots.lines`（證物描述與反應台詞）：investigate 沒有對白 port；彈窗只顯示卡名與說明。鑑定台詞 `evidence.appraisalKey` 同樣沒有出口。
2. 「理由未定的卡不能連結」（§2.3）與「未選理由的卡不參戰」（§2.7）：原型照 ref 的模型，把未選理由視為理由錯誤（詭辯、ok 0），卡照常參戰。待設計確認。
3. 放卡一律接成連續的鏈；不能在同一列內直接移動（先收回再放）；拖曳與自由擺放不做（ui-contracts board 原型簡化）。
4. 刻度歸零時在關閉彈窗後結束（設計：3 秒後自動結束）；「全部調查完畢」的確認、`WARN_INV_END`、`WARN_BOARD_LOCK` 確認、閒置台詞（`ART_IDLE_*`、30 秒）都沒做。
5. 熱身是樁：本案有效信任度＝永久值 `world.trust`（3）；Ch.3 信任度 ≥3 時一定有警方報告。
6. 每個調查點最多產出 1 張卡（Ch.1～3 成立，產生器驗證）。
7. `area_name` 空白；Ch.1 板面的亞瑟台詞照用（Ch.1 沒有 SHF_ 版的線索板台詞）。
8. 同 M2：`sceneKey` 只適用 Ch.1～9；結果條固定勝利版；`dateline`、`mast`、`stamp` 沒有資料。

### 7.2 對 XTAtrium 的請求

1. **`atrium.ui.list` 的多個變動欄位**：一列只有一個集合值（map 的 `value`）與一個 join，所以抽屜（已揭露、理由已選、在板上）、板面格（鏈、位置＋卡名、等級）、銅牌（四個數）、證物冊卡片（已揭露、新取得）只能用組合鍵表（§5.2）。請求：`fields` 的值可以引用「以本列鍵查另一個集合」，例如 `"placed": "@has:row0"`（list：是否包含）、`"chain": "@map:slotChain"`（map：該鍵的值），或允許多個 `join`。
2. **字串的具名佔位**：`MSG_INV_MISSED`（`{n}`）、`MSG_INV_RESCUE`（`{name}`）、`WARN_BOARD_NOREASON`（`{n}`）、`WARN_BOARD_UNAPPR`（`{n}`、`{left}`）、`WARN_INV_END`（`{left}`）、`UI_BOARD_THRESHOLD`（`{stage}`、`{condition}`）都帶具名佔位，`format` 的樣式是靜態參數且只認 `{a}`～`{d}`，填不進在地化的樣式。請求：`atrium.text` 加可選輸入（例如 `args`，或 `a`～`d` 依鍵名對應），或 `format` 接受樣式作為輸入。原型的警告台詞因此原樣顯示 `{n}`。

### 7.3 對資料管線的請求（`tools/build_data.py`）

1. 把 §5.1 的欄位收進正式表：`evidence.gradeNum`（或 UI 改吃字串）、`hotspots.typeNum`、`hotspots.sceneBg`、每章的場景表。
2. 字串：標籤分隔符號（例 `UI_TAG_SEP` ＝「・」／「 · 」）、區域／場景名稱鍵（`area_name`）、`HS_CH03_01` 在信任度 ≥3 時的筆記句（設計表的「驗屍報告已由警方提供，這裡只看得到現場」）、G-01／S-01 的說明與固定理由鍵（目前空白）。
