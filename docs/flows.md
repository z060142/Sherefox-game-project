# 流圖（M2：Ch.1～3 劇情可玩）

狀態：M2 草案 2026-11-06（第二輪：`papers`／`script` 新欄位、結尾卡 `end_dismiss`）。依據：`docs/architecture.md` §3、§8；`docs/ui-contracts.md`（title、vn、paper）；`docs/data-schema.md` §1、§2、§3、§9；裁決 D5、D6、E1；XTAtrium docs 04、05 §5.4、02 §2.3、03 §3.4、08 §8.1、§8.2、§8.5。

本文件說明 `flows/*.xtflow` 每一張圖做什麼、圖與圖之間經哪些 `world.*` 訊號溝通、「步驟」的介面合約，以及已知限制。M2 範圍：標題 → 選章 → 開場報紙 → 逐行播放每個 vn 場景 → 下一章，語言可即時切換。蒐證、線索板、熱身、論戰、結算都是樁（stub），流程直接跳過。

## 1. 產生方式

四張圖都由 `tools/gen_flows.py` 產生（`uv run tools/gen_flows.py`；`--check` 只比對、不寫檔）。改流圖請改產生器再重產，不要手改 `.xtflow`。`game.json` 的 `flows` 依序載入 `main`、`dialogue`、`paper`、`stubs`；載入順序就是同一 tick 內的執行順序（05 §5.4「跨圖可見性」）。

| 圖 | 節點／邊 | 職責 |
|---|---|---|
| `main` | 33／51 | 應用狀態機：語言切換、選章、步驟執行器（`steps` 表）、畫面可見性、結尾卡 |
| `dialogue` | 40／75 | `vn` 步驟：依 `script` 表逐行把對白寫進 `ui#vn` |
| `paper` | 32／51 | `paper` 步驟：依 `papers` 表填 `ui#paper`，兩頁翻完即結束 |
| `stubs` | 16／26 | 其他步驟種類（`warmup`、`investigate`、`board`、`debate`、`result`）立即回報完成 |

## 2. world 訊號

全部在 `game.json` 的 `signals` 宣告。值型訊號在一張圖內只有一個寫入邊（05 §5.3）；脈衝可由多張圖寫入。

| 訊號 | 型別 | 寫入者 | 讀取者 | 意義 |
|---|---|---|---|---|
| `world.language` | string | `main`（另：`--lang`） | 宿主（UI 語言）、全部 `atrium.text` | 目前語言（08 §8.1 自動宣告）。`main` 的語言狀態跟隨它：外部寫入（`--lang`、日後的設定畫面）會同步到切換鈕。 |
| `world.chapter` | number | `main` | `dialogue` | 目前步驟所屬的章（`steps.chapter`）；尚未選章時 0。Ch.3 末尾的最終報紙與 `end` 步驟仍是 3。 |
| `world.stepRow` | number | `main` | （除錯用） | 目前步驟在 `steps` 表的列號；−1＝沒有步驟（標題）。 |
| `world.stepKind` | string | `main` | `dialogue`、`paper`、`stubs` | 目前步驟的 `steps.kind`；沒有步驟時空字串。 |
| `world.stepArg` | string | `main` | `paper` | 目前步驟的 `steps.arg`（paper → `papers.group`）。 |
| `world.stepScene` | string | `main` | `dialogue` | 目前步驟的 `steps.scene`（vn → `script.scene`）。 |
| `world.stepBegin` | pulse | `main` | `dialogue`、`paper`、`stubs` | 每進入一個步驟發一次（`world.stepRow` 改變時；值先寫好再發脈衝）。載入時也會發一次（`stepKind` 為空，沒有人回應）。 |
| `world.stepDone` | pulse | `dialogue`、`paper`、`stubs` | `main` | 目前步驟結束；`main` 在下一 tick 前進到下一列。 |

## 3. 步驟合約

一個步驟流圖（現有 `dialogue`、`paper`、`stubs`，日後的 `investigate`、`board`、`debate`、`result`）：

- **接收**：`world.stepKind`、`world.stepArg`、`world.stepScene`、`world.chapter`（值），以及 `world.stepBegin`（脈衝）。同一 tick 內 `main` 先執行，所以步驟流圖在 `stepBegin` 到達時看到的值已是新步驟的值（05 §5.4 第 5 步先於第 8 步）。
- **啟動**：只在 `world.stepKind` 等於自己的種類時回應 `world.stepBegin`。慣用寫法是「脈衝閘」：一個兩狀態互轉的 `state` 節點（`a ⇄ b`，事件 `go`），`guard` 接「種類相符」的 `compare`，`stepBegin` 接 `go`，`changed` 就是「本種類的步驟開始了」（53 §53.4.15：`guard` 為 false 時吞掉事件）。
- **結束**：發一次 `world.stepDone`。同一步驟只能發一次（多發會跳過下一步）：`dialogue` 與 `paper` 用 `compare` 的 `true` 脈衝（只在結果改變時發），`stubs` 每次 `stepBegin` 只發一次。
- **畫面**：步驟流圖不寫 `ui#<id>.visible`；可見性只由 `main` 決定（§4.3）。新增一種有畫面的步驟時，在 `main` 的 `screen` 狀態機加一個狀態與它的 `lookup`。
- **UI 輸入**：只在自己的步驟進行中計數（以種類相符的閘擋住），這樣隱藏中的畫面殘留的事件不會影響別的步驟。

把某個種類從樁換成真正的流圖：刪掉 `tools/gen_flows.py` 裡 `STUB_KINDS` 的那一項（`<kind>Tag`、`<kind>Is`、`<kind>Gate` 三個節點與它們的邊），再加上該種類的流圖並列進 `game.json` 的 `flows`。

## 4. 各圖細節

### 4.1 `main`

- **語言**（M0 行為）：`ui#title.lang_toggle` 翻轉 `lang` 狀態（`zh`／`en`），`lookup` 轉成 `zh-TW`／`en` 寫入 `world.language`；`ui#title.lang_en` 由 `lang` 的 index 推出。`world.language` 被別人寫入時，以 `lang.set` 讓狀態跟上（自己寫入的值不會回送給自己，05 §5.4，所以沒有回授）。
- **選章**：`ui#title.chapter`（1～3）→ `atrium.table.find(steps, chapter, filterColumn idx = "0")` → 計數器 `cur.set`。
- **步驟前進**：`world.stepDone` → `cur.increment`。`steps` 的列依章、idx 排序（data-schema §2），所以一章的最後一步之後就是下一章的第一步，Ch.3 之後是最終報紙 `CH04_OPEN` 與 `end`；不需要查 `chapters.next`。
- **輸出**：`cur` → `atrium.table.get` → `world.stepKind`／`stepArg`／`stepScene`／`chapter`、`world.stepRow`。`cur.value` 的最後一條邊接 `filter(deadband, 0)`，它的 `passed` 就是 `world.stepBegin`：`filter` 在 `cur` 的值送完前面所有邊之後才收到，送出脈衝前先結算，因此 world 值一定先寫好（邊依檔案順序投遞，05 §5.4）。
- **畫面**（§8 的「一個 state 節點」）：`screen` 狀態 `title`／`paper`／`vn`，事件來自 `compare(stepKind == end／paper／vn)` 的 `true` 脈衝；每個 surface 一個 `lookup` 把 `screen.index` 轉成 `ui#title.visible`、`ui#paper.visible`、`ui#vn.visible`。樁步驟不改畫面（停在上一個畫面），所以 vn → 樁 → vn 不會閃一下。`investigate`、`board`、`debate`、`result` 在 M2 一直隱藏（`game.json` 初值）。
- **待續**：`ui#title.ended` ＝ `stepKind == "end"` 且結尾卡狀態 `card` 為 `open`。`card`（`open`／`closed`）：`ui#title.end_dismiss` → `closed`；進入 `end` 步驟時（`isEnd` 的 `true` 脈衝）→ `open`。`end` 步驟不回報完成；關掉結尾卡後步驟仍是 `end`、畫面仍是 title，目錄可以再選章（選章改寫 `cur`，`stepKind` 離開 `end`）。

### 4.2 `dialogue`

- `vnScene` ＝ 種類為 `vn` 時的 `world.stepScene`，否則空字串；`sceneKey` ＝ `format("CH0{a}_{b}", world.chapter, vnScene)`（＝`script.sceneKey`，例 `CH01_S02`；只適用 Ch.1～9）。`first` ＝ `find(script, sceneKey = sceneKey, playable = "true")`，即該場景第一個可播放列（不再假設標題在第一列）。
- 游標：`row = first + off`（`atrium.expr`），`off` 是計數器：`stepBegin` 歸零，每個 `ui#vn.advance`（只在 vn 步驟中）＋1。
- `inScene` ＝ 種類為 vn 且 `script[row].sceneKey == sceneKey` 且 `script[row].playable`。游標逐列前進，遇到第一個不可播放列（或下一個場景）就結束，所以假設一個 vn 場景的可播放列是連續的（§6 第 1 項）。`inScene` 由 true 變 false（游標走出場景）時，`compare` 的 `true` 脈衝就是 `world.stepDone`。
- 顯示：`stepBegin` 與 `advance` 經一個 `merge`（脈衝送出前先結算，游標與 `inScene` 已是新值）進脈衝閘（`guard` ＝ `inScene`），通過時 `filter(sample)` 取樣目前的 `row` 成為「顯示列」，再經第二個 `merge` 讓 `line_seq` ＋1（先寫文字、後寫 `line_seq`）。走出場景那一下閘不通過，畫面停在最後一句直到下一步驟。
- 顯示列 → `ui#vn`：`bg`、`slot_l`／`slot_c`／`slot_r`、`focus`、`style` 直接寫；`line` ＝ `atrium.text(text)`；`speaker` ＝ `focus ≠ 0` 時 `atrium.text(speaker)`，否則空字串（旁白、系統、報紙的 `focus` 都是 0，data-schema §3.1）。文字經 `atrium.text` 解析，切換語言時即時重算。
- 其他：`chapter_title` ＝ `atrium.text(chapters.titleKey)`；`choice_count` ＝ 0，`choice1～4` 空字串、`choice_locked1～4` false；`trust` ＝ −1。

### 4.3 `paper`

- 進入 paper 步驟時（脈衝閘）以 `filter(sample)` 鎖住 `world.stepArg` 作為報紙 id，`find(papers, group)` 取列。鎖住是為了在畫面淡出時內容不變。
- 欄位對應（一個 port 一欄，data-schema §9；文字欄經 `atrium.text`，空鍵＝空字串＝該部分隱藏）：`headline` ← `headlineKey`；`subhead` ← `subKey`；`body` ← `bodyKey`；`page2_head`／`page2_body` ← `page2HeadKey`／`page2BodyKey`（原型全空白）；`side` ← `sideKey`（Ch.1 是開場城市新聞 `NEWS_00_OPEN`）；`ad` ← `adKey`（只有 `CH01_OPEN` 有值）；`picture` ← `pictureId`（不經 `atrium.text`）。
- 「上一案結果」條：`result_head`／`result_sub` ← `sideWinKey`／`sideWinSubKey`；Ch.1 這兩欄是空白，條隱藏，不需特判 `resultChapter`。**M2 沒有結算，一律用勝利版**；日後由結算流圖提供勝敗與惡名，依 01-systems §3.3 的判定順序選 `sideLoseKey`／`sideNotoKey`／`sideWinKey`。
- 沒有資料的 port：`mast` 0、`stamp` 0、`dateline` 空字串（字串表沒有各期日期／天氣，data-schema 待確認 Q28）。
- 翻頁：計數器 `pg`（1～3）在 paper 步驟開始時歸 1；`next` ＋1、`prev` −1（只在 paper 步驟中）；`page` ＝ `min(pg, 2)`；`pg` 到 3 時 `compare` 的 `true` 脈衝即 `world.stepDone`。

### 4.4 `stubs`

`warmup`、`investigate`、`board`、`debate`、`result` 各一個脈衝閘：種類相符時 `stepBegin` 直接成為 `world.stepDone`（同一 tick 發出，`main` 下一 tick 前進），所以一個樁步驟佔 1 tick。

## 5. 驗證

`tests/README.md`。`uv run tests/check_playthrough.py` 重產錄影並以 headless 回放：Ch.1 的 21 行（zh-TW 與 en）、Ch.1～3 全部 54 行依序各顯示一次、四份報紙的每個有欄位的 port（含結果條、側欄、廣告、鋼版畫 id）、畫面可見性、待續卡、點擊與 Enter 關掉待續卡後目錄可再選章（Ch.3 重玩到第二次待續卡、再選 Ch.2）、語言切換鈕。

## 6. 已知限制

1. **不跳過不可播放列**：`dialogue` 從場景第一個可播放列（`script.playable`）起逐列前進，遇到第一個不可播放列就結束場景，所以假設一個 vn 場景的可播放列連續。Ch.1～3 的 vn 場景成立（`check_playthrough.py` 驗證）；結算場景（`subheading`、`branch`）與論戰場景（`staging`）不成立，屆時需要「跳過不可播放列」，Flow 沒有無環的寫法（見 §7 第 2 項）。`sceneKey` 由 `format("CH0{a}_{b}")` 拼成，只適用 Ch.1～9。
2. **同一章不能重選**：`ui#title.chapter` 是 number 值型 out port；同值再次送出時匯流排值不變，邏輯流圖看不到（見 §7 第 1 項）。例如 Ch.1 開始、玩到待續卡、關掉後再點 Ch.1 不會有反應（點別章可以）。
3. **同一 tick 的重複輸入**：步驟結束那一 tick 若又收到一次 `prev`＋`next`（paper）會再發一次 `stepDone`。`advance` 不受影響（`compare` 只在改變時發）。實際操作中（每 tick 最多一次點擊）不會發生。
4. 結果條固定勝利版；`dateline`、`mast`、`stamp` 沒有資料；第二版文章與 Ch.2 起的廣告在資料裡是空白。

## 7. 對框架與資料管線的請求

1. **XTAtrium：值型 out port 的每次送出**。XTFrame 27 §27.13 規定值型 out port 每次 `set` 都 emit（同值也發），但 `UiSystem` 只把值寫進 `ui.<id>.<port>` 訊號；同值不改變匯流排，邏輯流圖（05 §5.4 第 5 步比較上次看到的值）收不到。重現：title 的 `click:set(chapter, 1)` 點兩次，邏輯圖 `ui#title.chapter → counter.set` 只觸發一次。期望：每次 emit 另有一個可讀的脈衝（例如 `ui#title.chapter.emitted`，或以 `ui.<id>.<port>` 的寫入序號驅動），讓邏輯圖對每次點擊反應。
2. **XTAtrium：「從某列起找下一個符合的列」**。`atrium.table.find` 只取第一個符合列、最多兩欄條件；逐列前進並跳過不符的列在 Flow 裡必然成環（游標 → 判斷 → 游標）。請求：`find` 加可省輸入 `from`（number，從該列起找），並允許多個 filter 欄（或資料端提供複合鍵）。有了它，「場景內下一個可播放列」＝ `find(script, sceneKey = …, playable = true, from = row + 1)`。
3. **資料管線（`tools/build_data.py`）**：2026-11-06 第二輪已完成 `papers.pictureId`／`adKey`／`page2HeadKey`／`page2BodyKey`、Ch.1 開場城市新聞移到 `sideKey`、`script.playable`／`sceneKey`；在地化包也刪掉了 `_SUB` 文字裡的「第二版：」「內文：」標籤。仍缺：每期報紙的日期與天氣字串（配 `UI_PAPER_DATE`，data-schema 待確認 Q28），有了之後再加 `dateKey`／`weatherKey`。
