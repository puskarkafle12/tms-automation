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
    from models import frontend_user, logged_in_user, order_status_log, scheduled_order, user
    target_metadata = logged_in_user.Base.metadata
    target_metadata = scheduled_order.Base.metadata
    target_metadata = order_status_log.Base.metadata
    target_metadata = user.Base.metadata
    target_metadata = frontend_user.Base.metadata
in alembic.ini configuration
    sqlalchemy.url = postgresql://pk:@localhost/stock