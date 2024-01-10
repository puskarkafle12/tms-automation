from datetime import datetime
import re
import pandas as pd
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

def convert_to_numeric(value):
    try:
        return float(value.replace('%', '').replace(',', ''))
    except ValueError:
        return value  # If conversion is not possible, return the original value
def extract_numeric_value(s):
    match = re.search(r'([-+]?\d*\.\d+|\d+)', str(s))
    if match:
        return float(match.group())
    else:
        return None
def get_stock_detail(url):
    url = "https://merolagani.com/" + url
    response = requests.get(url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')
        tables = soup.find_all('table', {'class': 'table-zeromargin'})[0]
        result_dict = {}
        for row in tables.find_all('tr'):
            try:
                key = row.find('th').get_text(strip=True)
                value = row.find('td').get_text(strip=True)
                result_dict[key] = value
            except:
                pass
        return result_dict


def fetch_stock_details(row_data):
    link = row_data['link']
    stock_detail = get_stock_detail(link)
    print(link)
    row_data.update(stock_detail)
    return row_data


def get_stock_details():
    url = 'https://merolagani.com/latestmarket.aspx'
    response = requests.get(url)

    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table', {'class': 'live-trading'})
        stock_details = []
        table_data = []

        for index, row in enumerate(table.find_all('tr')):
            if index == 0:
                table_header = [cell.text.strip()
                                for cell in row.find_all('th') if cell.text.strip()]
            else:
                row_data = {table_header[i]: cell.text.strip() for i, cell in enumerate(
                    row.find_all('td')) if cell.text.strip()}
                row_data['link'] = row.find('a').get('href')
                table_data.append(row_data)

        # Use ThreadPoolExecutor to fetch stock details concurrently
        with ThreadPoolExecutor(max_workers=15) as executor:
            futures = [executor.submit(fetch_stock_details, row_data)
                       for row_data in table_data]

            for future in futures:
                stock_details.append(future.result())

        # Convert the list of dictionaries to a Pandas DataFrame
        numeric_columns = ['LTP', '% Change', 'Open', 'High', 'Low', 'Qty.', 'Shares Outstanding', 'Market Price', '180 Day Average',
                       '120 Day Average', '1 Year Yield',
                       'EPS', 'P/E Ratio', 'Book Value', 'PBV', '% Bonus', 'Right Share',
                       '30-Day Avg Volume', 'Market Capitalization'
                       ]
        df = pd.DataFrame(stock_details)
        df[numeric_columns] = df[numeric_columns].applymap(convert_to_numeric)
        df['EPS'] = df["EPS"].apply(extract_numeric_value)

        return df


# Call the function to fetch stock details
stock_df=get_stock_details()
stock_df.to_csv('data/'+"share_data_"+datetime.today().strftime("%Y-%m-%d")+'.csv', index=False)