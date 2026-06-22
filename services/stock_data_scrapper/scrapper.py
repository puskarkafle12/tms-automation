from datetime import datetime
from pathlib import Path
import logging
import re
from threading import local
import pandas as pd
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

REQUEST_TIMEOUT = 12
MAX_WORKERS = 8
_thread_local = local()
logger = logging.getLogger(__name__)

try:
    from utils.base_functions import get_function_time
except Exception:
    def get_function_time(func):
        def wrapper(*args, **kwargs):
            start = datetime.now()
            result = func(*args, **kwargs)
            elapsed = (datetime.now() - start).total_seconds()
            print(f"Function '{func.__name__}' executed in {elapsed:.6f} seconds")
            return result
        return wrapper

def convert_to_numeric(value):
    if value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    try:
        text = str(value).strip()
        if not text or text in {"-", "--"}:
            return value
        return float(text.replace('%', '').replace(',', ''))
    except (TypeError, ValueError):
        return value  
def extract_numeric_value(s):
    match = re.search(r'([-+]?\d*\.\d+|\d+)', str(s))
    if match:
        return float(match.group())
    else:
        return None

def _build_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(['GET']),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=MAX_WORKERS, pool_maxsize=MAX_WORKERS)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })
    return session

def _get_session():
    session = getattr(_thread_local, 'session', None)
    if session is None:
      session = _build_session()
      _thread_local.session = session
    return session

def get_stock_detail(url):
    url = "https://merolagani.com/" + url
    response = _get_session().get(url, timeout=REQUEST_TIMEOUT)
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')
        tables = soup.find_all('table', {'class': 'table-zeromargin'})
        if not tables:
            return {}
        table = tables[0]
        result_dict = {}
        for row in table.find_all('tr'):
            try:
                key = row.find('th').get_text(strip=True)
                value = row.find('td').get_text(strip=True)
                result_dict[key] = value
            except:
                pass
        return result_dict


def fetch_stock_details(row_data):
    link = row_data['link']
    try:
        stock_detail = get_stock_detail(link) or {}
    except Exception as exc:
        logger.warning("Merolagani detail fetch failed for %s: %s", link, exc)
        stock_detail = {}
    row_data.update(stock_detail)
    return row_data

def _parse_latest_market_table(soup):
    table = soup.find('table', {'class': 'live-trading'})
    if table is None:
        raise RuntimeError("Could not find live-trading table on latest market page")
    table_data = []
    table_header = []
    for index, row in enumerate(table.find_all('tr')):
        if index == 0:
            table_header = [cell.text.strip() for cell in row.find_all('th') if cell.text.strip()]
            continue
        anchor = row.find('a')
        row_data = {
            table_header[i]: cell.text.strip()
            for i, cell in enumerate(row.find_all('td'))
            if i < len(table_header) and cell.text.strip()
        }
        if anchor is not None:
            row_data['link'] = anchor.get('href')
        table_data.append(row_data)
    return table_header, table_data


def get_latest_market_rows():
    """Fetch Merolagani live-trading table only (no per-symbol detail pages)."""
    url = 'https://merolagani.com/latestmarket.aspx'
    response = _get_session().get(url, timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        raise RuntimeError(f"Failed to load latest market page: HTTP {response.status_code}")
    soup = BeautifulSoup(response.text, 'html.parser')
    _, table_data = _parse_latest_market_table(soup)
    return table_data


@get_function_time
def get_stock_details():
    url = 'https://merolagani.com/latestmarket.aspx'
    response = _get_session().get(url, timeout=REQUEST_TIMEOUT)

    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        stock_details = []
        _, table_data = _parse_latest_market_table(soup)

        worker_count = min(MAX_WORKERS, max(4, len(table_data) or 4))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(fetch_stock_details, row_data) for row_data in table_data]
            for future in as_completed(futures):
                stock_details.append(future.result())

        numeric_columns = ['LTP', '% Change', 'Open', 'High', 'Low', 'Qty.', 'Shares Outstanding', 'Market Price', '180 Day Average',
                       '120 Day Average', '1 Year Yield',
                       'EPS', 'P/E Ratio', 'Book Value', 'PBV', '% Bonus', 'Right Share',
                       '30-Day Avg Volume', 'Market Capitalization'
                       ]
        df = pd.DataFrame(stock_details)
        existing_numeric_columns = [column for column in numeric_columns if column in df.columns]
        if existing_numeric_columns:
            df[existing_numeric_columns] = df[existing_numeric_columns].map(convert_to_numeric)
        if 'EPS' in df.columns:
            df['EPS'] = df["EPS"].apply(extract_numeric_value)

        return df

    raise RuntimeError(f"Failed to load latest market page: HTTP {response.status_code}")

def main():
    project_root = Path(__file__).resolve().parents[2]
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    stock_df = get_stock_details()
    output_path = data_dir / f"share_data_{datetime.today().strftime('%Y-%m-%d')}.csv"
    stock_df.to_csv(output_path, index=False)
    print(f"Saved {len(stock_df)} rows to {output_path}")
    if 'Symbol' in stock_df.columns:
        czbil = stock_df[stock_df['Symbol'].astype(str).str.upper().eq('CZBIL')]
        if not czbil.empty:
            row = czbil.iloc[0]
            print(
                f"CZBIL => LTP={row.get('LTP')} Change={row.get('% Change')} "
                f"LastTraded={row.get('Last Traded On')}"
            )


if __name__ == "__main__":
    main()
