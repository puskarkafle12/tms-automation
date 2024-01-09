import pandas as pd

# Load the CSV file into a DataFrame
df = pd.read_csv("share_data2024-01-09.csv")

# Convert the "% Change" column to numeric (remove "%" sign and convert to float)

# Filter low cap stocks (assuming Market Capitalization is the cap)
low_cap_stocks = df[df["Market Capitalization"] < 2000000]

# Filter high percentage change stocks
high_percentage_change_stocks = df[df["% Change"] > 8]

# Display the results
print("Low Cap Stocks:")
print(low_cap_stocks[["Symbol", "Market Capitalization", "% Change"]])

print("\nHigh Percentage Change Stocks:")
print(high_percentage_change_stocks[["Symbol", "Market Capitalization", "% Change"]])
