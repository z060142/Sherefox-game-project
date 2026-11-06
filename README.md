# 狐耳摩斯（Sherefox）遊戲專案

蒸氣龐克偵探 AVG《狐耳摩斯》Ch.1～3 可玩原型。遊戲邏輯以 [XTAtrium](https://github.com/z060142/XTAtrium) 執行（Atrium Script 流程圖、資料表、集合），全部畫面用 XTFrame UI；中英雙語，可在遊戲中切換。

設計文件：線上主文件 https://claude.ai/artifact/LQDVV6KG7qX32iaqWw4Pv2 ；設計資料包（含在地化來源）在 https://github.com/z060142/research-prototype-2 。

## 目錄

| 路徑 | 內容 |
| --- | --- |
| `game.json` | 專案根（XTAtrium 0.4） |
| `flows/` | 流程圖（由 `tools/gen_flows.py`、`tools/gen_debui.py`、`tools/gen_debate.py` 產生，不要手改） |
| `data/`、`strings/` | 資料表與遊戲字串（由 `tools/build_data.py` 產生） |
| `source/` | 資料管線的輸入：在地化表、標籤值、演出（站位） |
| `ui/boards/` → `ui/project/` | UI 原稿（.dc.html）與 XTFrame UI 專案；`ui/bundle/` 為打包產物，不進版控 |
| `ref/` | 論戰規則的 Python 參考模型（黃金軌跡） |
| `tests/` | 錄製重播與比對檢查 |
| `docs/` | 實作文件：`architecture.md`、`flows.md`、`debate-engine.md`、`ui-contracts.md`、`data-schema.md`、`rulings.md`、`audio-requests.md`、`todo.md`；`design/` 為設計文件快照 |

## 執行

先用 XTAtrium 的 `tools/install-sdk.ps1` 建好 SDK，然後：

```
xtatrium pack --game .
xtatrium play --game .
xtatrium publish --game . --out <輸出目錄>
```

資料與檢查：`uv run tools/build_data.py`；檢查見 `tests/README.md`（`check_debate`、`check_policy`、`check_case`、`check_playthrough`、`check_debate_play`）。
