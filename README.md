# R34 Observatory · 熱帶氣旋觀測台

本機可執行的研究展示網站：全球氣旋地圖 → 選取系統 → 原始 11.2 µm IR 亮溫 → 既有 PyTorch 權重推論 → 59-bin 機率曲線與 mean。

目前保留在本機，未發布 GitHub 或任何公開網站。沒有更動或重新訓練模型。需要 **Python / PyTorch 後端**；GitHub Pages 本身不能執行 `.pth`。

## 目前電腦啟動

專案位於 `C:\Users\cwycw\OneDrive\2026_Research\R34_website`，原本的 Notebook、權重均保留。

雙擊 `start.cmd`，等待終端顯示 `Uvicorn running`，然後開啟 **http://127.0.0.1:8000**。啟動後請保留終端視窗；按 Ctrl+C 停止服務。需要可對外連線的網路來更新氣旋與衛星資料。

也可從 PowerShell 執行：

```powershell
cd 'C:\Users\cwycw\OneDrive\2026_Research\R34_website'
.\start.ps1
```

此機已準備 `.runtime` 本地套件，使用現有 Miniconda Python 3.12 / PyTorch CPU；不改動原本的全域套件。首次載入與衛星下載可能需要數十秒到數分鐘。原始衛星檔案暫存在 `.cache`，最多保留最近 30 個原始檔；小型裁切與來源紀錄保留以便追溯。

## 新電腦安裝

建議 Python 3.12，先放入自己的可信任模型檔，再執行：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

預設讀取根目錄的 `TCR34_reference_DNN_test1_25MAE.pth`。更換模型時設定 `$env:R34_MODEL_PATH='C:/path/model.pth'` 並重啟服務；新權重需維持相同架構與 bins。`.env.example` 只說明設定，不會自動載入。模型以 `weights_only=True` 與必要的 NumPy 型別白名單讀取，禁止退回任意 pickle 執行。

## 使用

1. 網站啟動後載入活躍清單，從地圖或側欄選氣旋。橘色為北大西洋以外的跨域實驗，灰色代表定位過期。
2. 後端依位置選擇 GOES-19、GOES-18 或 Himawari-9，下載校準所需的原始資料並裁切。
3. IR 顯示完成後按 **開始 R34 辨識**。輸出 59 個 bin 的 Softmax 機率與 `mean = Σ pᵢrᵢ`，單位為海浬。
4. **CSV ↓** 匯出機率、mean、中心、影像與定位時間、衛星頻道與模型 SHA-256。

即時案例沒有 Ground Truth，因此不畫真值、軟標籤或 MAE。`25MAE` 只是既有模型檔名，不是本網站已驗證的即時準確度。沒有示範或隨機預測混入實時清單。

## 科學規格與限制

- 原始架構：`HurricaneAlexNet_ReferenceDNN`，依 `Sep_LDL_test.ipynb` 重建並嚴格載入 `model_state_dict`。輸出 bins 從 checkpoint 讀取，驗證為 `10, 15, …, 300 n mi`，共 59 個。
- GOES：ABI Level-2 CMIP Full Disk 的 **C14 / 11.2 µm**。IR CMI 已為 Kelvin，保留 DQF 0/1，雙線性重採樣。GOES-16 訓練資料與現行 GOES-19/18 同頻段仍可能存在感測器差異。
- Himawari：AHI HSD **B14 / 11.2 µm**，由 Satpy 使用檔案校準係數解碼為 Kelvin，最近鄰重採樣。顯示的彩色 PNG 不參與推論。
- 空間：採 **8 km/pixel**，156 個像素的外緣寬度為 **1,248 km ≈ 673.87 n mi**。局地 WGS84 等距方位投影，北朝上，中心位於四個中央像素之間。像素中心間距 8 km，首尾中心相距 1,240 km。
- **仍需核對訓練時的實際格網**：約 `0.078°` 並不嚴格等於 8 km；經向寬度也隨緯度改變。本版選擇固定物理範圍。若原始 GridSat 裁切使用固定經緯間距，必須調整 adapter 才能精確一致。此差異與重採樣方式可能影響辨識結果，尚未量化。
- 正規化嚴格為 `(img_K - 236.54854) / 26.703743`，shape `[1,1,156,156]`，float32。缺值少於或等於 2% 以 245 K 補值；超過 2% 拒絕辨識。不做每張影像的 min-max normalization。
- 限定有限亮溫 100–350 K；影像須在 90 分鐘內、定位 12 小時內，影像與定位時間差不超過 6 小時。即時中心沿用來源的最近定位，**沒有外插中心位置**；風暴移動可能造成偏心。
- 全球清單來自 Tropical Tidbits 的 ATCF 位置摘要；失敗時只回退 NOAA NHC 海盆並顯示範圍縮限。來源失效與真正的空清單分開處理。全球清單不保證涵蓋各機構尚未列出的系統或全部擾動。
- **全球顯示不等於全球 IR 已接通**。GOES 與 Himawari 以距星下點較近者選擇，超過 65° 的區域停止自動擷取，且另檢查整片裁切的資料覆蓋。印度洋的部分區域需要 Meteosat／IODC；NOAA CPC 公開全球 IR 約延遲兩天，所以本版不把它作為即時備援。
- 模型主要以北大西洋資料訓練，其他海盆未驗證。模型輸出單一半徑分布，不表示四象限風圈。Softmax 曲線不是已校準的信賴區間。

## 檔案與 API

```text
backend/model.py       原始架構、權重載入、固定正規化與推論
backend/storms.py      全球清單解析、NHC 有限範圍備援
backend/imagery.py     原始衛星資料、對中裁切、校準與重採樣
backend/app.py         FastAPI、背景下載工作、圖片與推論 API
frontend/              無需 Node build 的靜態介面與本地 Leaflet／海岸線
tests/                 科學與 API 不變量檢查
artifacts/             本次真實案例輸出（預設不提交版本控制）
```

- `GET /api/health`：服務與模型檔案存在狀態。
- `GET /api/storms`：清單、資料範圍、取得時間與警示，快取 5 分鐘。
- `POST /api/imagery`：`{"storm_id":"31W"}`，回傳工作 ID。
- `GET /api/jobs/{id}`：下載與裁切進度、失敗原因或觀測 metadata。
- `GET /api/patches/{id}/image`：顯示用 PNG。
- `POST /api/patches/{id}/infer`：以同一份 Kelvin 裁切推論。
- `/docs`：FastAPI 互動 API 說明。

## 驗證

```powershell
# 此機使用本地套件
$env:PYTHONPATH="$PWD/.runtime"
python -m unittest discover -s tests -v
node --check frontend/app.js
```

測試包含格網方向及實距、南北／東西半球定位、資料來源格式變更、缺值與單位拒絕、正規化與 mean、過期推論阻擋及真實 checkpoint 形狀。另有下載當日 GOES 與 Himawari 真實觀測的端到端實測，詳見 `artifacts/validation.md`。測試通過不代表氣象準確度已驗證。

新電腦若要執行測試，請另安裝 `python -m pip install -r requirements-dev.txt`（TestClient 需要 HTTPX）。

## 未來 GitHub／部署

已提供 `.gitignore`，忽略 `.pth`（原檔約 115 MB，超過一般 GitHub 單檔限制）、Notebook、套件與快取。尚未建立或推送遠端 repository。未來上傳時把此專案的原始碼提交即可；權重另存伺服器、受控儲存或 Git LFS。

最直接的部署是讓 Python 服務同時供應前端與 API，避免跨網域問題。可在支援 Python 的 VM／容器服務使用 `Dockerfile`：

```sh
docker build -t r34-observatory .
docker run --rm -p 8000:8000 -v /absolute/path/model.pth:/models/model.pth:ro -e R34_MODEL_PATH=/models/model.pth r34-observatory
```

若使用 GitHub Pages 放前端，需先增加可設定 API origin、後端 CORS 與 HTTPS；本版採同源設計，不能直接把靜態目錄推上 Pages 就期待 `.pth` 可執行。公開上線前另需加入適當的工作佇列、使用量限制與監控。

## 資料與第三方元件

- [NOAA GOES Open Data](https://registry.opendata.aws/noaa-goes/)、[JMA Himawari Open Data](https://registry.opendata.aws/noaa-himawari/)
- [Tropical Tidbits 氣旋位置摘要](https://www.tropicaltidbits.com/storminfo/)、[NOAA NHC current storms](https://www.nhc.noaa.gov/CurrentStorms.json)。只解析定位摘要，不使用其彩色 IR 當模型輸入；若未來大量公開提供服務，需再確認其使用規範。
- [CPC 資料格式與延遲說明](https://www.cpc.ncep.noaa.gov/products/global_precip/html/README)（僅調查，未用於實時推論）。
- [Leaflet 1.9.4](https://leafletjs.com/)（BSD-2-Clause，附 `frontend/vendor/LEAFLET-LICENSE`）；[Natural Earth 1:110m land](https://www.naturalearthdata.com/about/terms-of-use/)（public domain）。
- 介面需求參考使用者提供的 [Typhoon-Forecast](https://github.com/lkt0713/Typhoon-Forecast)，此處為自行撰寫的網站程式，未複製該專案程式碼。

自有程式與模型的授權由專案擁有者決定；本版未替模型或研究程式指定公開授權。
