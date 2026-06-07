import psycopg2
from psycopg2 import sql
import os

# Read database connection details from environment variables or configuration
db_user = os.getenv("DB_USER", "postgres")
db_password = os.getenv("DB_PASSWORD", "postgres")
db_host = os.getenv("DB_HOST", "localhost")
db_name = os.getenv("DB_NAME", "stock")

# Define the name of the database to create
database_name = db_name

def create_database():
    try:
        # Connect to the default database
        connection = psycopg2.connect(
            dbname='postgres', 
            user=db_user, 
            password=db_password, 
            host=db_host
        )
        connection.autocommit = True  # Enable autocommit to create database
        cursor = connection.cursor()

        # Check if the database already exists
        cursor.execute(
            sql.SQL("SELECT 1 FROM pg_database WHERE datname = %s"),
            [database_name]
        )

        if cursor.fetchone():
            print(f"Database '{database_name}' already exists.")
        else:
            # Create the database
            cursor.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
            )
            print(f"Database '{database_name}' created successfully.")

    except Exception as e:
        print(f"Error creating database: {e}")
    finally:
        if connection:
            cursor.close()
            connection.close()

def create_user():
    try:
        # Connect to the specified database
        connection = psycopg2.connect(
            dbname=database_name, 
            user=db_user, 
            password=db_password, 
            host=db_host
        )
        cursor = connection.cursor()

        # Create the frontend_users table if it doesn't exist
        create_table_query = '''
        CREATE TABLE IF NOT EXISTS frontend_users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(255) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL
        );
        '''
        cursor.execute(create_table_query)
        connection.commit()
        print("Table created successfully.")

        # Insert the user record
        insert_user_query = '''
        INSERT INTO frontend_users (username, password)
        VALUES (%s, %s)
        ON CONFLICT (username) DO NOTHING;
        '''
        seed_user = os.getenv("FRONTEND_SEED_USER", "admin")
        seed_password = os.getenv("FRONTEND_SEED_PASSWORD", "changeme")
        cursor.execute(insert_user_query, (seed_user, seed_password))
        connection.commit()
        print("User inserted successfully.")

    except Exception as e:
        print(f"An error occurred: {e}")
        connection.rollback()
    finally:
        if connection:
            cursor.close()
            connection.close()

if __name__ == "__main__":
    create_database()
    create_user()
