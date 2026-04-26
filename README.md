# Stock Intelligence Dashboard

This is a stock intelligence dashboard that shows NSE stock prices, charts, market breadth, comparison data, and a basic prediction line using a FastAPI backend with a HTML/CSS/JavaScript frontend.
Deployed on Railway.com.

It shows some NSE stock data, charts, comparison, market breadth and a small prediction line. The prediction is very basic, so it should not be used for real trading.

## Tech Used

- Python
- FastAPI
- SQLite
- Pandas
- HTML, CSS, JavaScript
- Chart.js

## Main Things

- Shows stock list and latest price
- Shows chart for selected stock
- Supports 30D and 90D view
- Has compare option
- Shows market breadth
- Has a profile page

## Data

The project has a small sample CSV here:

```text
data/bhavcopy/dashboard_training_sample.csv
```

The app mainly reads from:

```text
backend/stocks.db
```

If more data is needed, the backend can try yfinance or Alpha Vantage.

## How To Run

Create virtual environment:

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install packages:

```powershell
pip install -r requirements.txt
```

Run backend:

```powershell
uvicorn backend.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/
```

## API Routes

```text
GET /health
GET /companies
GET /data/{symbol}
GET /summary/{symbol}
GET /compare
```

FastAPI docs:

```text
http://127.0.0.1:8000/docs
```

## Note

This is just a learning project. Some sidebar features are only prototype buttons for now.
