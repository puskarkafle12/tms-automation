# Project Name

## Installation

To run this project, follow these steps:

1. Clone the repository to your local machine:
    ```bash
    git clone https://github.com/your_username/your_repository.git
    cd your_repository
    ```

2. Install the required dependencies:
    ```bash
    pip install -r requirements.txt
    ```


## Usage

3. create .env file 
DB_USER=pk
DB_PASSWORD=
DB_HOST=localhost
DB_NAME=stock

4. alembic is used as orm so go to alembic .ini and env file configure to make sure its working 
    in alembic env add these 
    from models import user
    target_metadata = user.Base.metadata
    in alembic.ini file add database configuration
    sqlalchemy.url = postgresql://pk:@localhost/stock

### Configuring Login Details

Create a `users.txt` file in the project folder with the following format:

```plaintext
username = PK479690
password = 
stock_symbol = prvu
broker_no = 35
previous_ltp = 400
request_per_sec = 3
order_quantity = 10
end

username = AnotherUsername
password = AnotherPassword
stock_symbol = prvu
broker_no = 42
previous_ltp = 300
request_per_sec = 2
order_quantity = 15
end

### Running the main file 
'''
python main.py

'''