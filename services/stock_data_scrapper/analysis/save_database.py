import pandas as pd
import pymysql
from sqlalchemy import create_engine

# Assuming df is your DataFrame with the specified column names
data_path="/Users/pkafle/tms-automation/data/share_data_2024-04-24.csv"
# Connection parameters
host = 'localhost'
database = 'stock_details'
username = 'root'
password = ''

# Create a MySQL connection using pymysql
connection = pymysql.connect(
    host=host,
    user=username,
    password=password,
    database=database,
    cursorclass=pymysql.cursors.DictCursor
)

# Create a SQLAlchemy engine
engine = create_engine(f"mysql+pymysql://{username}:{password}@{host}/{database}")

# Save DataFrame to MySQL table
table_name = data_path.split('/')[-1].split('.')[0]
df = pd.read_csv(data_path)

df.to_sql(table_name, con=engine, index=False, if_exists='replace')

# Close the connections
connection.close()
engine.dispose()

print(f"DataFrame successfully written to MySQL table: {table_name}")
