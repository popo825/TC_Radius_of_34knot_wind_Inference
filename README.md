# R34

https://popo825.github.io/TC_Radius_of_34knot_wind_Inference/

## 檔案與 API

```text
backend/model.py       原始架構、權重載入、固定正規化與推論
backend/storms.py      全球清單解析、NHC 有限範圍備援
backend/imagery.py     原始衛星資料、對中裁切、校準與重採樣
backend/centers.py     影像時刻中心內插／外推（WGS84）
backend/position_sources.py NHC/CPHC、JTWC、TCVitals 定位與移動向量
backend/app.py         FastAPI、背景下載工作、圖片與推論 API
backend/batch.py       每小時推論、失敗隔離與靜態結果產出
backend/fetch_model.py Release 下載與 SHA-256 核對
frontend/              純靜態介面與本地 Leaflet／海岸線
.github/workflows/     排程推論與 Pages 發布
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
