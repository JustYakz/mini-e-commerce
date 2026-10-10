import mysql.connector

def run_migrations():
    try:
        db = mysql.connector.connect(host='localhost', user='root', password='', database='db_miniecommerce')
        c = db.cursor()

        # 1. Tabel users: foto_profil, latitude, longitude
        columns_users = [
            ("foto_profil", "VARCHAR(255) DEFAULT NULL"),
            ("latitude", "DECIMAL(10,7) DEFAULT NULL"),
            ("longitude", "DECIMAL(10,7) DEFAULT NULL"),
        ]
        for col, col_type in columns_users:
            try:
                c.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
                print(f"[OK] Added users.{col}")
            except Exception as e:
                print(f"[INFO] users.{col} exists or skipped: {e}")

        # 2. Tabel pesanan: metode_pembayaran, kurir_lat, kurir_lng, tujuan_lat, tujuan_lng
        columns_pesanan = [
            ("metode_pembayaran", "VARCHAR(50) DEFAULT 'Transfer Bank'"),
            ("kurir_lat", "DECIMAL(10,7) DEFAULT NULL"),
            ("kurir_lng", "DECIMAL(10,7) DEFAULT NULL"),
            ("tujuan_lat", "DECIMAL(10,7) DEFAULT NULL"),
            ("tujuan_lng", "DECIMAL(10,7) DEFAULT NULL"),
        ]
        for col, col_type in columns_pesanan:
            try:
                c.execute(f"ALTER TABLE pesanan ADD COLUMN {col} {col_type}")
                print(f"[OK] Added pesanan.{col}")
            except Exception as e:
                print(f"[INFO] pesanan.{col} exists or skipped: {e}")

        # 3. Tabel produk_gambar (Multi-Foto Galeri Produk)
        create_produk_gambar = """
        CREATE TABLE IF NOT EXISTS produk_gambar (
            id INT AUTO_INCREMENT PRIMARY KEY,
            produk_id INT NOT NULL,
            gambar VARCHAR(255) NOT NULL,
            is_primary TINYINT(1) DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (produk_id) REFERENCES produk(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        c.execute(create_produk_gambar)
        print("[OK] Table produk_gambar ready")

        # 4. Sinkronisasi foto produk utama yang belum tercatat di produk_gambar
        c.execute("""
            INSERT INTO produk_gambar (produk_id, gambar, is_primary)
            SELECT p.id, p.gambar, 1 
            FROM produk p
            LEFT JOIN produk_gambar pg ON p.id = pg.produk_id
            WHERE pg.id IS NULL AND p.gambar IS NOT NULL AND p.gambar != ''
        """)
        print(f"[OK] Synced {c.rowcount} existing product primary pictures into produk_gambar")

        db.commit()
        db.close()
        print("[SUCCESS] All database migrations completed successfully!")
    except Exception as e:
        print(f"[ERROR] Database migration failed: {e}")

if __name__ == '__main__':
    run_migrations()
