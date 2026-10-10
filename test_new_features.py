import sys
import os
import unittest
import io

_extra_paths = [
    os.path.expanduser(r"~\AppData\Local\Programs\Python\Python314\Lib\site-packages"),
    r"C:\Python314\Lib\site-packages",
    os.path.join(os.path.dirname(__file__), "Lib", "site-packages"),
]
for _p in _extra_paths:
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from app import app, get_db_connection

class TestNewFeatures(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        # Dapatkan ID admin dan user pembeli dari database
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE role = 'admin' LIMIT 1")
        self.admin_user = cursor.fetchone()
        cursor.execute("SELECT * FROM users WHERE role = 'user' LIMIT 1")
        self.regular_user = cursor.fetchone()
        if not self.regular_user:
            cursor.execute("SELECT * FROM users WHERE role != 'admin' LIMIT 1")
            self.regular_user = cursor.fetchone()
        if not self.regular_user:
            # Buat user pembeli dummy untuk testing
            cursor.execute("INSERT INTO users (nama, email, password, role) VALUES ('Pembeli Barokah', 'pembeli@barokah.com', '1234', 'user')")
            db.commit()
            cursor.execute("SELECT * FROM users WHERE email = 'pembeli@barokah.com'")
            self.regular_user = cursor.fetchone()
        cursor.execute("SELECT * FROM produk LIMIT 1")
        self.sample_product = cursor.fetchone()
        cursor.close()
        db.close()

    def test_01_cek_kupon_api(self):
        print("\n--- TEST 1: API Cek Kupon Diskon ---")
        # 1. Invalid coupon
        res = self.client.post('/cek-kupon', json={'kode': 'INVALIDCODE123', 'total': 100000})
        data = res.get_json()
        self.assertFalse(data['valid'])
        print("  [PASS] Kupon tidak valid ditolak dengan pesan:", data['pesan'])

        # 2. Min belanja tidak cukup (HEMAT50K butuh minimal 200.000)
        res = self.client.post('/cek-kupon', json={'kode': 'HEMAT50K', 'total': 50000})
        data = res.get_json()
        self.assertFalse(data['valid'])
        print("  [PASS] Kupon dengan syarat belanja tidak cukup ditolak:", data['pesan'])

        # 3. Valid coupon persen (BAROKAH10: 10% min 50.000)
        res = self.client.post('/cek-kupon', json={'kode': 'BAROKAH10', 'total': 100000})
        data = res.get_json()
        self.assertTrue(data['valid'])
        self.assertEqual(data['diskon'], 10000.0)
        self.assertEqual(data['total_akhir'], 90000.0)
        print("  [PASS] Kupon BAROKAH10 valid! Diskon:", data['diskon_format'], "Total Akhir:", data['total_format'])

        # 4. Valid coupon nominal (DISKON20K: Rp 20.000 min 100.000)
        res = self.client.post('/cek-kupon', json={'kode': 'DISKON20K', 'total': 150000})
        data = res.get_json()
        self.assertTrue(data['valid'])
        self.assertEqual(data['diskon'], 20000.0)
        self.assertEqual(data['total_akhir'], 130000.0)
        print("  [PASS] Kupon DISKON20K valid! Diskon:", data['diskon_format'], "Total Akhir:", data['total_format'])

    def test_02_wishlist_functionality(self):
        print("\n--- TEST 2: Fitur Wishlist (Produk Favorit) ---")
        prod_id = self.sample_product['id']

        # 1. Unauthorized toggle
        res = self.client.post(f'/toggle-wishlist/{prod_id}', headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(res.status_code, 401)
        print("  [PASS] Tamu tanpa login ditolak saat toggle wishlist")

        # 2. Login user and toggle add
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.regular_user['id']
            sess['nama'] = self.regular_user['nama']
            sess['role'] = 'user'

        res = self.client.post(f'/toggle-wishlist/{prod_id}', headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['is_wishlist'])
        self.assertEqual(data['action'], 'added')
        print("  [PASS] Berhasil menambahkan produk ke wishlist:", data['pesan'])

        # 3. View Wishlist page
        res = self.client.get('/wishlist')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Wishlist Produk Favorit", res.data)
        self.assertIn(self.sample_product['nama_produk'].encode('utf-8', 'ignore'), res.data)
        print("  [PASS] Halaman /wishlist menampilkan produk yang difavoritkan")

        # 4. Toggle remove
        res = self.client.post(f'/toggle-wishlist/{prod_id}', headers={'X-Requested-With': 'XMLHttpRequest'})
        data = res.get_json()
        self.assertFalse(data['is_wishlist'])
        self.assertEqual(data['action'], 'removed')
        print("  [PASS] Berhasil menghapus produk dari wishlist:", data['pesan'])

    def test_03_review_with_photo(self):
        print("\n--- TEST 3: Ulasan Bergambar ---")
        prod_id = self.sample_product['id']

        with self.client.session_transaction() as sess:
            sess['user_id'] = self.regular_user['id']
            sess['nama'] = self.regular_user['nama']
            sess['role'] = 'user'

        # Buat dummy photo file
        fake_image = (io.BytesIO(b"dummy image data for review"), "test_review_photo.jpg")
        res = self.client.post(
            f'/tambah-ulasan/{prod_id}',
            data={
                'rating': '5',
                'komentar': 'Produk mantap berkualitas, pengiriman cepat!',
                'foto_ulasan': fake_image
            },
            content_type='multipart/form-data',
            follow_redirects=True
        )
        self.assertEqual(res.status_code, 200)

        # Verifikasi data tersimpan di database
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM ulasan WHERE produk_id = %s AND user_id = %s ORDER BY id DESC LIMIT 1", (prod_id, self.regular_user['id']))
        latest_rev = cursor.fetchone()
        self.assertIsNotNone(latest_rev)
        self.assertIsNotNone(latest_rev['foto'])
        self.assertTrue(latest_rev['foto'].startswith(f"ulasan_{prod_id}"))
        print("  [PASS] Ulasan bergambar berhasil disimpan ke DB dengan foto:", latest_rev['foto'])

        # Cek apakah file fisik tersimpan di static/uploads/
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], latest_rev['foto'])
        self.assertTrue(os.path.exists(file_path))
        print("  [PASS] Berkas foto tersimpan fisik di:", file_path)

        # Cleanup file test
        try:
            os.remove(file_path)
            cursor.execute("DELETE FROM ulasan WHERE id = %s", (latest_rev['id'],))
            db.commit()
        except Exception:
            pass
        cursor.close()
        db.close()

    def test_04_admin_dashboard_and_export(self):
        print("\n--- TEST 4: Admin Dashboard & Ekspor Laporan CSV ---")
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.admin_user['id']
            sess['nama'] = self.admin_user['nama']
            sess['role'] = 'admin'

        # 1. Dashboard UI
        res = self.client.get('/admin/dashboard')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Dashboard Analisis Toko", res.data)
        self.assertIn(b"salesTrendChart", res.data)
        self.assertIn(b"statusPieChart", res.data)
        self.assertIn(b"Top 5 Produk Terlaris", res.data)
        self.assertIn(b"/admin/laporan/export-csv", res.data)
        print("  [PASS] Dashboard admin (/admin/dashboard) berhasil dimuat lengkap dengan Chart.js & KPI")

        # 2. CSV Export
        res_csv = self.client.get('/admin/laporan/export-csv')
        self.assertEqual(res_csv.status_code, 200)
        self.assertIn('text/csv', res_csv.content_type)
        content_text = res_csv.data.decode('utf-8')
        self.assertTrue(content_text.startswith('\ufeff'))
        self.assertIn('ID Pesanan;Tanggal Pesanan;Nama Pelanggan', content_text)
        print("  [PASS] Ekspor laporan CSV (/admin/laporan/export-csv) berhasil dengan format Excel UTF-8 BOM!")

    def test_05_checkout_with_coupon(self):
        print("\n--- TEST 5: Checkout dengan Kupon Diskon ---")
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM produk WHERE stok >= 5 AND harga >= 50000 LIMIT 1")
        test_prod = cursor.fetchone()
        cursor.close()
        db.close()

        self.assertIsNotNone(test_prod, "Harus ada produk dengan stok >= 5 dan harga >= 50000")
        prod_id = test_prod['id']
        prod_harga = float(test_prod['harga'])
        qty = 1

        with self.client.session_transaction() as sess:
            sess['user_id'] = self.regular_user['id']
            sess['nama'] = self.regular_user['nama']
            sess['role'] = 'user'
            sess['keranjang'] = {str(prod_id): qty}

        # 1. GET Checkout page (cek kupon list hadir)
        res_get = self.client.get('/checkout')
        self.assertEqual(res_get.status_code, 200)
        self.assertIn(b"Punya Kode Voucher Diskon?", res_get.data)
        self.assertIn(b"BAROKAH10", res_get.data)
        print("  [PASS] Halaman checkout menampilkan input kupon & daftar voucher tersedia")

        # 2. POST Checkout dengan Kupon BAROKAH10
        # BAROKAH10: 10% diskon
        res_post = self.client.post(
            '/checkout',
            data={
                'nama_penerima': 'Pembeli Barokah Test',
                'no_hp': '081299998888',
                'alamat_pengiriman': 'Jl. Barokah No. 123, Banjarmasin',
                'metode_pembayaran': 'Transfer Bank',
                'kode_kupon': 'BAROKAH10'
            },
            follow_redirects=True
        )
        self.assertEqual(res_post.status_code, 200)

        # Cek database pesanan
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM pesanan WHERE user_id = %s ORDER BY id DESC LIMIT 1", (self.regular_user['id'],))
        order = cursor.fetchone()
        self.assertIsNotNone(order)
        self.assertEqual(order['kode_kupon'], 'BAROKAH10')
        expected_diskon = (prod_harga * 10.0) / 100.0
        self.assertAlmostEqual(float(order['diskon']), expected_diskon, places=2)
        print("  [PASS] Pesanan tercatat dengan kupon:", order['kode_kupon'], "Diskon:", order['diskon'], "Total:", order['total_harga'])

        # Restore stok & cleanup pesanan test
        cursor.execute("UPDATE produk SET stok = stok + %s WHERE id = %s", (qty, prod_id))
        cursor.execute("DELETE FROM detail_pesanan WHERE pesanan_id = %s", (order['id'],))
        cursor.execute("DELETE FROM pesanan WHERE id = %s", (order['id'],))
        db.commit()
        cursor.close()
        db.close()

if __name__ == '__main__':
    unittest.main()
