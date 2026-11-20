# v3：開機片頭（OP）

狀態：2026-11-20，分支 `v3-op`（由 `v2-demo` 15bcb58 分出；`main`、`v2-demo` 不動）。實驗性質：v2 的一切照舊，加一段開機片頭。發佈到 `E:/coding4/Sherefox-build-v3`（與 v1、v2 的建置分開）。

## 1. 做了什麼

- 開機先播片頭（59.3 秒，1920×1080，配樂 `audio/op/op_music.mp3`），播完出現標題與標題音樂。點一下或按 Enter／Space／Esc 立刻跳過：片頭音樂停、標題出現。
- 標題頂端列加「觀看片頭」（`UI_V3_WATCH_OP`，佔位字串「觀看片頭」／"Watch the Opening"，`source/localization/v3_placeholders.csv`），再播一次，播完（或跳過）回到標題。
- 到了標題之後，v1 三章、v2 示範關卡、設定、語言切換與 v2 相同（既有檢查全過；`tests/check_op.py` (d) 另外比對片頭播完與跳過之後的埠紀錄）。

## 2. 決定

1. **整合方式**：片頭是遊戲 UI 專案（`ui/project`）多一個 UI，不經板子轉換器。複製片頭專案的 `.xt`／`.xts`、`shared/fx/*.xtfx`（5 個）與它用到的 52 張圖；不複製 `.xtvc/`、`.xtcache/`、`*.xteditor.json`、片頭專案自己的 `.xtflow`。UI id 沿用 `sherefox-op`，圖檔路徑沿用 `../shared/img/`（檔名與遊戲的不重複）。碰撞與改動（只有兩處，詳見 ui-contracts）：
   - 片頭的 `shared/base.xts` 與遊戲的同路徑 → 複製成 `sherefox-op/sherefox-op.base.xts`，只由片頭連結（類別名稱本來就不重複；遊戲的 `shared/base.xts` 經專案的 `shared.styles` 也套到片頭，無衝突，只多兩則 `var(--copper)` 警告，和其他 UI 一樣）。
   - 根元素加 `ui-scale: clamp(1, 1)`（§5 缺口 2、3）。
2. **自己的 surface 尺寸**：`game.json` 的 `ui.surfaces` 加 `sherefox-op` 與跳過層 `opskip`，邏輯尺寸 1920×1080，排在最上層。宿主把每個 surface 各自依它的邏輯尺寸 fit 到渲染尺寸（等比、置中、留黑邊；`dpr ＝ 像素寬 ÷ 邏輯寬`，XTAtrium 09 §9.5）：1280×720 視窗時片頭以 dpr 2/3 直接畫在 1280×720 像素上，1920×1080 時 dpr 1；不是把 1280 寬的畫面放大，所以任何視窗大小都清晰。16:9 以外的視窗，片頭與其他畫面一樣上下或左右留黑邊（1600×1000 實測）。
3. **跳過的輸入**：片頭文件不加 port；改用一個透明的跳過層 `opskip`（手寫的小 UI，`skip` event port）。
4. **流程**：`flows/op.xtflow`（`tools/gen_op.py` 產生，`docs/flows.md` §4.16）。片頭的時間軸由片頭的 UI 流圖在顯示時播放；音樂播在自己的通道 `op`，跳過時能停，`music` 流圖的 bgm 通道在片頭期間不送指令。
5. **影像釋放**：`display.gpuTrim` 設為 `on-hide`（框架提供的宿主規則：surface 停止繪製後釋放閒置貼圖）。量測見 §4。

## 3. 測試機制

框架沒有「每次執行預設一個 world 訊號或設定」的通用方法（`run`／`trace`／`shot`／`play` 只有 `--seed`、`--lang`；§5 缺口 1）。所以用退而求其次的方式：**每個錄影在 tick 0 送一個跳過輸入**。

- `game.json` 宣告 `input.opSkip`（pulse）。SDL 宿主的鍵位表沒有它，玩家送不出來；只有錄影會送。它和跳過層的 `skip` 一樣是「跳過」，不是「這是回放」的判斷，遊戲不讀任何非決定性的東西。
- 共用的產生器（`tests/gen_playthrough.py` 的 `Recording`、`tests/gen_d1_play.py` 的 `Rec`）在標頭之後加 `{"t": 0, "w": [["input.opSkip", "p"]]}`（`OP_SKIP`）；所有錄影重新產生，差異只有這一行。測試副本（harness）沿用同一批錄影，不用另設初始值。
- tick 0 的跳過在同一個 tick 生效：`op` 是第一張圖，`main`、`music` 同 tick 讀到 `world.opOn` 為 false，標題可見性一直是 true（沒有變化、沒有 shown 事件），片頭從未顯示、沒有任何 `op` 通道的指令。實測 `ch1_playthrough` 的 `--ports` 紀錄（3000 tick）與 v2 逐行相同，只多兩個新 port 的初始值各一行（`title.watch_op`、`opskip.skip`）。
- 唯一的時間差：標題音樂 BGM01 的 play 由 tick 0 變成 tick 1（音樂流圖在 tick 0 的計時器步驟取樣到的是初始值，片頭的時機沒有音檔 → 不送；之後才看到標題）。指令的種類與順序不變，`check_music` 照原樣檢查。
- 片頭自己的測試：`tests/check_op.py`（開機播放、三種方式三個時間點的跳過、觀看片頭、片頭後 v1／v2 不受影響、決定性）。

## 4. 量測

| 項目 | v2 | v3 |
|---|---|---|
| 打包大小（`xtatrium pack`） | 148.5 MB | 213.6 MB |
| 估計顯示記憶體（pack 的估計：全部圖片常駐） | 133.4 MB（未壓縮 399.9） | 198.7 MB（未壓縮 592.9） |
| `display.gpuImageBudget` | 300 MiB | 300 MiB（未超過） |

- 實際 GPU 影像記憶體（`play --profile`，wgpu，1280×720，msaa 1）：圖片在第一次畫到時才上傳。片頭整段播完時 53 張貼圖、67.7 MB；`gpuTrim off` 時片頭結束後 52 張（65.6 MB）閒置留著；`on-hide` 時片頭隱藏後隨即（60 幀內）釋放，只剩標題的 1 張（2.1 MB）。片頭期間沒有掉幀：每 600 tick 的牆鐘時間 9.96～9.99 秒（60.1 tick/s），單幀最長 51 ms（< 8 步上限 133 ms）。開機第一幀（tick 0，片頭尚未顯示）約 1.1 秒。
- 工具訊息：pack 對片頭只有遊戲 `shared/base.xts` 的兩則 `var(--copper)` 警告（各 UI 都有）；`xtatrium check` 0 錯誤。
- 決定性：時間軸、粒子、shader 時間都由固定步長推進。`check_op` (e)：同一輸入兩次的狀態雜湊相同；兩次軟體算圖的同 tick 畫面逐位元組相同。
- 畫面比對：13 個鏡頭各一格（1280×720 與 1920×1080，wgpu）對片頭專案以 SDK 的 `xtframe-view` 單獨算的同一時間點：RMSE 0.4～1.4%，差異只在移動中物件的邊緣（次像素位置與遊戲打包的 DDS 壓縮），粒子、光暈、掃光、漸層遮罩、色彩調整與五個自訂 shader（作者寫的 filmlook、speedlines、spotlight、beamshape 與內建範例 ripple）都與參考相同。時間對應：遊戲 tick N ＝ 片頭時間 (N−1)/60 ＝ `xtframe-view` 第 N 格。

### 音樂同步

- 綁法：開機的 tick 1（或「觀看片頭」的下一 tick）同一個脈衝送音樂指令並顯示片頭；片頭在同一 tick 的 ui 步驟顯示，UI 流圖在顯示當下播放時間軸。兩者同一 tick 開始，之後時間軸跟著模擬的固定步長走，音樂跟著音訊裝置走。
- 最壞偏差（推算，未以錄音實測）：宿主一幀內批次跑完到期的 tick，再算圖呈現，所以畫面比指令晚約一幀（60 Hz 16.7 ms，加上合成器的呈現延遲）；音訊從下一個混音週期開始（miniaudio 約 10 ms）。起點偏差約在 ±30 ms 內，通常是畫面略晚。之後不會累積：模擬依牆鐘補步（每幀最多 8 步），只有單幀超過 133 ms 才會丟時間，片頭期間量到最長 51 ms。時間軸不能跟隨音訊時鐘（片頭作者的回報；框架也沒有），所以若宿主卡頓超過 133 ms，畫面會永久落後音樂該段時間。
- 片頭音樂 59.298 秒，時間軸 59.3 秒：結束時音樂已自然結束，`stop` 只是收尾。

## 5. 缺口（通用請求，附證據）

1. **XTAtrium：沒有逐次執行的預設值**。測試需要「預設關掉某功能、玩家預設開啟」時，只能在每個錄影加輸入。建議 `run`／`trace`／`shot`／`play --set world.<name>=<value>`，或錄影標頭帶初始訊號值（像 `seed`、`lang`）。
2. **XTAtrium：邏輯圖不能播 UI 的時間軸，也讀不到它的結束**。`timeline` 節點的 `ui` 只能用在全域流圖（XF077），`ui#<ui>.timeline.<name>.end` 不是端點（XF054）。現做法：片頭的 UI 流圖在 `lifecycle.shown` 播放、`hidden` 停止；結束用一個同長度的邏輯計時器。建議：邏輯圖的 `timeline` 接受 `ui`，或開放 `ui#<ui>.timeline.<name>.end` 端點。
3. **XTFrame：設計高是整個專案共用的**。`spec.logicalHeight` 720 與 `uiscaleRule: fit` 套到專案裡每個 UI，1080 設計的 UI 放進來會被放大 1.5 倍（`v3/gap-project-uiscale-crop.png`：左 1280×720、右 1920×1080，都只看得到左上 2/3）。建議每個 UI 可覆寫設計高（`.xtui` 的 `uis[]`）。現做法：根元素 `ui-scale` 夾在 1。
4. **XTFrame v0.19.0：`ui-scale: none` 在 dpr ≠ 1 時把 dpr 乘了兩次**。1920×1080 的 surface 在 1280×720 視窗（dpr 2/3）只畫在左上 853×480（＝×(2/3)²），dpr 1 時正確；`clamp(1, 1)` 兩種尺寸都正確（`v3/gap-uiscale-none-dpr.png`：none@1280、none@1920、clamp@1280）。
5. **框架：一張圖的計時器（第 4 步）在讀本 tick 的輸入之前**，所以「依 tick 0 的輸入決定 tick 0 的事」做不到；片頭因此從 tick 1 開始（tick 0 一格黑畫面），音樂流圖開機的取樣看到初始值（BGM01 晚一 tick）。若要 tick 0 就顯示，需要一個「本 tick 輸入讀完之後」的開機脈衝。
6. **隱藏的 surface 仍每 tick update**（XTAtrium 03 §3.4）：片頭隱藏後沒有畫面、沒有事件、貼圖已釋放，但 headless 看不出 `autoplay` 粒子在隱藏時是否仍在模擬；沒有「卸載一個 surface」的方法。
7. 片頭作者回報的項目在遊戲裡的情形：一之 3（不自動播放時全部鏡頭疊在一起）不影響：片頭只在播放時顯示，tick 0 也不顯示；一之 12（自訂 shader 的座標是畫面空間）：遊戲以 dpr 縮放整個 surface，探照燈的位置在 1280×720 與 1920×1080 都與參考相同；音樂同步見 §4。

## 6. 未做

- 片頭的配樂沒有實際聽過（headless 與 `--no-audio`）；同步偏差是推算值。
- 跳過層只涵蓋 16:9 的畫面範圍；非 16:9 視窗的黑邊上點擊不會跳過（按鍵可以）。

## 框架後續（2026-11-20，XTAtrium 的回覆）

- **每次執行預設訊號**：框架正在做 `--set world.<名稱>=<值>`（run／trace／shot／play，可重複；寫在 game.json `signals` 裡的值型訊號，載入後、第 0 tick 之前寫入一次；錄製時存進 `.atrec` 檔頭，舊錄製檔也可在重播時加 `--set`）。出貨後可以把「每個錄製檔第 0 tick 的 `opSkip`」換成一個宣告的訊號（例如 `world.skipOpening`）加上測試時的 `--set`，錄製檔就不必帶那一行。要改的地方：`tools/gen_op.py`（開場邏輯在開始時讀這個訊號）、共用產生器的 `OP_SKIP`、`tests/xt_cli.py`。
- **邏輯流圖讀 UI 時間軸的結束**：框架打算讓 `end`／`marker` 可以從邏輯流圖讀（端點寫法待定）。出貨後拿掉「與時間軸等長的計時器」，OP 的長度就只寫在一處。播放仍由 UI 自己的流圖負責（顯示時播），不會改。
- **tick 內的順序**：照設計不改。可被當 tick 輸入取消的動作從第 1 tick 開始是正確做法。
- **隱藏的畫面**：照規格仍會每 tick 更新、不能卸載；`display.gpuTrim: on-hide` 已解決貼圖記憶體。若剖析顯示隱藏的 OP 佔 CPU，再把數字給框架。
- **`ui-scale: none` 在 dpr≠1 時縮兩次**（XTFrame）：最小重現案例在 `E:\coding4\sherefox-repro\uiscale-none\`，主線確認後預計 0.19.1 修。**每個 UI 自己的設計尺寸**：XTFrame 那邊待使用者決定。
