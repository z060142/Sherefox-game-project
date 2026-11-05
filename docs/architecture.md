# 狐耳摩斯 原型架構（Ch.1～3）

狀態：草案 2026-11-06。依據：設計文件（`docs/design/`）、XTAtrium docs 04／05／07／08。本文件決定「遊戲怎麼在 XTAtrium 上表達」；遊戲規則本身一律以設計文件為準。

## 1. 分層

| 層 | 放什麼 | 檔案 |
|---|---|---|
| 資料 | 劇本行、證物、調查點、主張節點、對手設定、預兆台詞、頭條、章節步驟 | `data/*.json`（由 `tools/` 產生）、`strings/<lang>.csv` |
| 遊戲邏輯 | 章節流程、對話執行、蒐證、線索板判定、論戰結算與對手 AI | `flows/*.xtflow`（Atrium Script） |
| 狀態 | 持有證物、理由選擇、板面與推理鏈、節點池、手牌、旗標、信任度、惡名 | `game.json` 的 `collections` 與 `world.*` 訊號 |
| 介面 | 每個畫面一個 XTFrame UI surface | `ui/boards/`（.dc.html 原稿）→ `ui/project/`（import 產物）→ `ui/bundle/`（pack 產物，不進版控） |
| 參考模型 | 論戰規則的 Python 實作，產生黃金軌跡 | `ref/` |

原則：
- 流圖只做規則與流程，不寫任何顯示文字；文字一律是字串鍵，經 `atrium.text` 或 UI 的 `@key` 解析。
- 同一條規則只有一份：論戰數值用 `atrium.expr` 寫成與數值總表同形的式子，參數來自資料表。
- 畫面間只經訊號溝通：UI 送出事件 port（流圖讀 `ui.<surface>.<port>`），流圖寫 UI 的 in port 或用 `atrium.ui.list` 填清單。

## 2. 畫面（surface）

全部 1280×720，疊放順序由下而上。

| surface | 用途 | 主要內容 |
|---|---|---|
| `title` | 標題、章節選擇、語言切換 | 報頭、選單、Ch.1～3 入口 |
| `vn` | 日常、事件、劇情對白 | 背景、最多 3 名立繪、名牌、對白框、選項、快捷列 |
| `paper` | 開場頭版、轉場報紙 | 報頭、頭條、副標、內文、第二版與側欄 |
| `investigate` | 蒐證 | 場景與區域切換、調查點、懷錶刻度、鑑定次數、亞瑟提示、結束蒐證 |
| `board` | 線索板 | 證物抽屜、板面 15 格、詳情與三選一理由、推理鏈列表、進入論戰 |
| `debate` | 熱身、布丁論戰、主論戰 | 對手主張鏈、預兆區、四個行動、鏈段與證物選擇、壓力錶、狀態圖示、對決表、對手筆記 |
| `result` | 結算 | 勝敗、統計、信任度、亞瑟評語 |
| `evbook` | 證物冊（覆蓋層） | 本案證物、黃金線索、私人收藏 |
| `cutin` | 書法大字與印章（最上層） | 全幕大書、角落印章、譯名小字 |

各 surface 的 port 合約（名稱、型別、方向）寫在 `docs/ui-contracts.md`，UI 與流圖兩邊照它做；改合約先改文件。

## 3. 流圖

| 流圖 | 職責 |
|---|---|
| `main` | 應用狀態機：title → chapter（依 `steps` 表逐步執行）→ 章末 → 下一章；決定哪個 surface 顯示 |
| `dialogue` | 對白執行器：依 `script` 表逐行推進、處理選項與跳轉、執行行內指令（換背景、立繪、給證物、旗標、大字） |
| `investigate` | 調查點、刻度、鑑定、權限、必需證物保底、漏證結算 |
| `board` | 放卡、理由、拉線判定（實證／詭辯／無效）、推理鏈組成、進入論戰前檢查 |
| `debate` | 回合流程（附錄 A-1）、對決表與傷害、節點、狀態、論破與尾聲、對手 AI 與預兆、熱身與布丁論戰的變體 |
| `settings` | 語言（寫 `world.language`）、文字速度等 |

流圖之間的介面：`world.*` 訊號（值與 pulse），在 `game.json` 的 `signals` 宣告。例：`world.step.done`（pulse）、`world.debate.start`（pulse）、`world.debate.case`（string）、`world.debate.won`（bool）。

## 4. 資料表（`game.json` 的 `tables`）

| 表 | 一列 | 主要欄 |
|---|---|---|
| `steps` | 章節的一步 | chapter, idx, kind（paper／vn／warmup／investigate／board／debate／result）, arg |
| `script` | 一行劇本 | id, chapter, scene, seq, speaker, expr, bg, cmd, arg, next |
| `evidence` | 一張證物卡 | id, chapter, grade, tags, hiddenTags, grazingTags, appraise, reason0..2（字串鍵）, correct, flags, refutes, golden, obtainable, required |
| `hotspots` | 一個調查點 | 欄位見 `docs/data-schema.md` §5 |
| `nodes` | 一個主張節點 | case, id, textKey, tags, truth |
| `opponents` | 一場論戰的對手 | case, type, hp, nodeCap, base, w_claim, w_rush, w_reinforce, w_trap, clear, fuzzy, disguise, rules |
| `tells` | 對手的一種行動 | case, action, gestureKey, lines（字串鍵，以 `|` 分隔） |
| `scripted` | 劇本覆蓋的回合 | case, round, action, node, clarity, lineKey |
| `papers` | 一份報紙（每個章節交界一份） | 欄位見 `docs/data-schema.md` §9 |
| `difficulty` | 一個難度（系統規格 6.1） | id, instinct, assist, tailRounds, …；原型只用 `standard`，但流圖一律從此表讀，日後開故事模式／名偵探不改流圖 |

標籤以 `類別:值` 字串存（例 `place:boiler_room`），多值以 `,` 分隔；「共享非擦邊已揭露標籤」由集合 `intersects` 計算（先 `addAll` 再求交集）。

## 5. 驗證

- 規則：`ref/` 的 Python 模型重現各章設計「推薦路線」與「常見失誤」表的每個數字（pytest）。
- 流圖：以 headless `xtatrium run` 加錄好的 `.atrec` 輸入重播一場論戰，讀 port 軌跡，與 `ref/` 對同一串行動產生的軌跡比對（對手行動用劇本覆蓋固定）。
- UI：xtui 的 lint／compile／headless screenshot；最後由人在 `xtatrium play` 中實際遊玩。

## 6. 里程碑

| 編號 | 內容 | 完成條件 |
|---|---|---|
| M0 | 專案骨架 | `xtatrium play --game E:\coding4\Sherefox` 開出 title，語言可切換 |
| M1 | 資料管線 | `tools/` 由在地化表與設計快照產生 `data/*.json` 與 `strings/*.csv`，載入無錯 |
| M2 | Ch.1 劇情 | 開場報紙 → 日常 → 事件，可逐行推進、選項可選 |
| M3 | Ch.1 蒐證與線索板 | 調查 6 處證物、選理由、拉線、組鏈、進入論戰 |
| M4 | 論戰 | 布丁論戰（Ch.1）、正式論戰（Ch.2）、熱身與困獸／失守（Ch.3）；流圖軌跡與 `ref/` 一致 |
| M5 | Ch.2、Ch.3 完整 | 結算、轉場報紙、信任度、惡名、黃金線索 G-01 回收、章節選擇 |

## 7. 原型範圍（不做或簡化）

- 不做：語音、存檔／讀檔（以章節選擇代替）、二週目流程圖、剪報簿、成就、難度切換（固定「標準」）、手把重新指定、論戰委託。
- 簡化：音樂與音效先只列需求清單（`docs/audio-requests.md`），由使用者準備素材；背景、證物插圖、CG 先用佔位圖，立繪用設計 session 提供的去背圖。
- 線索板的拉線支援「點卡 A 再點卡 B」（設計文件的手把流程）；拖曳拉線視 XTFrame 能力再加。

## 8. 畫面切換（XTAtrium AT-039）

- 每個 surface 有匯流排訊號 `ui.<id>.visible`（bool）；`main` 流圖以一個 `state` 節點寫入各 surface 的 `ui#<id>.visible`。宿主把變化轉成 request_show／request_hide，intro／outro 照播，`ui#<id>.shown`／`hidden` 照常發。
- `game.json` 的 `ui.surfaces[]`：`title` 可見，其餘 `"visible": false`；覆蓋層（`evbook`、`cutin`）放在陣列最後，需要擋住下層輸入的設 `"modal": true`。繪製順序＝陣列順序，後者在上。
- 隱藏的 surface 不更新、不繪製、不收輸入；輸入由上而下只經可見 surface，遇到第一個可見的 modal 即停。
