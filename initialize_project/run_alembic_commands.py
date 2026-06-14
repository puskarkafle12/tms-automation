import os
import shutil
import subprocess

# Set your database URL here
DATABASE_URL = "postgresql+psycopg2://username:password@localhost/dbname"

def delete_alembic_versions_folder():
    alembic_versions_path = os.path.join(os.getcwd(), 'alembic', 'versions')
    if os.path.exists(alembic_versions_path):
        shutil.rmtree(alembic_versions_path)
        print(f"Deleted Alembic versions folder: {alembic_versions_path}")
    else:
        print(f"Alembic versions folder does not exist: {alembic_versions_path}")
def run_alembic_commands():
    try:
        # Generate the initial migration script
        print("Generating initial migration...")
        result = subprocess.run(
            ['alembic', 'revision', '--autogenerate', '-m', 'Initial migration'],
            check=True,
            text=True,
            capture_output=True
        )
        print("Initial migration generated.")
        print(result.stdout)
        
        # Apply the migration
        print("Applying migration...")
        result = subprocess.run(
            ['alembic', 'upgrade', 'head'],
            check=True,
            text=True,
            capture_output=True
        )
        print("Migration applied successfully.")
        print(result.stdout)
        
    except subprocess.CalledProcessError as e:
        print("Migration failed.")
        print(f"Error: {e}")
        print(f"Output: {e.output}")

if __name__ == "__main__":
    # Delete the existing Alembic versions
    # delete_alembic_versions_folder()
    
    # Run the Alembic commands
    run_alembic_commands()
