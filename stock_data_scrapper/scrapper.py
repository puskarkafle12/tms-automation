import pandas as pd
import requests
from bs4 import BeautifulSoup
import json



def get_stock_detail(url):
    url ="https://merolagani.com/"+url
    response = requests.get(url)
    # Check if the request was successful (status code 200)
    if response.status_code == 200:
        # Parse the HTML content of the page
        soup = BeautifulSoup(response.content, 'html.parser')

        # Find all tables with the specified class
        tables = soup.find_all('table', {'class': 'table-zeromargin'})[0]
        # Iterate over each row in the table
        result_dict={}
        for row in tables.find_all('tr'):
            # Extract the key (th) and value (td) from each row
            try:
                key = row.find('th').get_text(strip=True)
                value = row.find('td').get_text(strip=True)

                # Add the key-value pair to the dictionary
                result_dict[key] = value
            except:
                pass
        return result_dict

# Specify the URL of the website


def get_stock_details():
    url = 'https://merolagani.com/latestmarket.aspx'

    # Send a GET request to the website
    response = requests.get(url)

    if response.status_code == 200:
        # Parse the HTML content of the page using BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')

        # Locate the table on the webpage using appropriate HTML tags and classes
        table = soup.find('table', {'class': 'live-trading'})

        # Create a list to store the table data
        stock_details= {}
        table_data=[]
        for index, row in enumerate(table.find_all('tr')):
            if index == 0:
                table_header = [cell.text.strip() for cell in row.find_all('th') if cell.text.strip()]
            else:
                row_data = {table_header[i]: cell.text.strip() for i, cell in enumerate(row.find_all('td')) if cell.text.strip()}
                row_data['link']=row.find('a').get('href')
                row_data.update(get_stock_detail(row_data['link']))
                table_data.append(row_data)

    