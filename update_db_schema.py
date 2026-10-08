import mysql.connector

try:
    db = mysql.connector.connect(host='localhost', user='root', password='', database='db_miniecommerce')
    c = db.cursor()

    # Add foto_profil column to users if not exists
    try:
        c.execute('ALTER TABLE users ADD COLUMN foto_profil VARCHAR(255) DEFAULT NULL')
        print('Added foto_profil column')
    except Exception as e:
        print(f'foto_profil already exists or error: {e}')

    # Add latitude/longitude columns to users if not exists
    try:
        c.execute('ALTER TABLE users ADD COLUMN latitude DECIMAL(10,7) DEFAULT NULL')
        print('Added latitude column')
    except Exception as e:
        print(f'latitude already exists or error: {e}')

    try:
        c.execute('ALTER TABLE users ADD COLUMN longitude DECIMAL(10,7) DEFAULT NULL')
        print('Added longitude column')
    except Exception as e:
        print(f'longitude already exists or error: {e}')

    db.commit()
    print('Current users table columns:')
    c.execute('DESCRIBE users')
    for row in c.fetchall():
        print(row)
    db.close()
except Exception as e:
    print(f'Database connection/execution failed: {e}')
