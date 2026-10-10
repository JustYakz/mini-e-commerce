import sys
import os

# Auto-detect dan sertakan direktori site-packages
_extra_paths = [
    os.path.expanduser(r"~\AppData\Local\Programs\Python\Python314\Lib\site-packages"),
    r"C:\Python314\Lib\site-packages",
    os.path.join(os.path.dirname(__file__), "Lib", "site-packages"),
]
for _p in _extra_paths:
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import mysql.connector
from werkzeug.utils import secure_filename
from datetime import datetime
import io
import csv
import json

app = Flask(__name__)
app.secret_key = 'rahasia-proyek-ecommerce-flask'

# Konfigurasi folder upload gambar
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # Maksimal upload 5MB

# Pastikan folder upload selalu ada
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="db_miniecommerce"
    )

# Filter Jinja untuk format mata uang Rupiah
@app.template_filter('rupiah')
def rupiah_filter(val):
    try:
        val = float(val)
        return f"Rp {val:,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        return f"Rp {val}"

# Filter Jinja untuk format tanggal pesanan
@app.template_filter('format_tanggal')
def format_tanggal_filter(val):
    if not val:
        return '-'
    if isinstance(val, str):
        try:
            val = datetime.fromisoformat(val)
        except Exception:
            return val
    try:
        return val.strftime('%d %b %Y, %H:%M WIB')
    except Exception:
        return str(val)

# Context Processor agar jumlah keranjang, wishlist, dan avatar bisa diakses di semua template
@app.context_processor
def inject_cart_count():
    cart = session.get('keranjang', {})
    total_qty = sum(cart.values()) if isinstance(cart, dict) else 0
    wishlist_count = 0
    user_wishlist_ids = set()
    if session.get('user_id'):
        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)
            cursor.execute("SELECT produk_id FROM wishlist WHERE user_id = %s", (session['user_id'],))
            rows = cursor.fetchall()
            user_wishlist_ids = {r['produk_id'] for r in rows}
            wishlist_count = len(user_wishlist_ids)
            cursor.close()
            db.close()
        except Exception:
            pass
    return dict(
        cart_count=total_qty,
        wishlist_count=wishlist_count,
        user_wishlist_ids=user_wishlist_ids,
        user_foto=session.get('foto_profil', '')
    )

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    flash("Halaman yang Anda tuju tidak ditemukan.", "warning")
    return redirect(url_for('home'))

@app.errorhandler(413)
def request_entity_too_large(error):
    flash("Ukuran file gambar terlalu besar! Maksimal ukuran file adalah 5MB.", "danger")
    return redirect(request.referrer or url_for('home'))

@app.errorhandler(500)
def internal_error(error):
    flash("Terjadi kendala pada server. Silakan coba kembali beberapa saat lagi.", "danger")
    return redirect(url_for('home'))

# Decorator proteksi hak akses Administrator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            flash("Silakan masuk terlebih dahulu untuk mengakses halaman administrator.", "warning")
            return redirect(url_for('login', next=request.path))
        if session.get('role') != 'admin':
            flash("Akses ditolak! Halaman ini hanya untuk Administrator.", "danger")
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# Route Admin Dashboard Hub & Analisis Bisnis
@app.route('/admin')
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        # Total Pendapatan dari pesanan aktif (tidak dibatalkan)
        cursor.execute("SELECT COALESCE(SUM(total_harga), 0) AS total FROM pesanan WHERE status != 'dibatalkan'")
        total_pendapatan = float(cursor.fetchone()['total'])

        # Total Seluruh Pesanan
        cursor.execute("SELECT COUNT(*) AS total FROM pesanan")
        total_pesanan = cursor.fetchone()['total']

        # Total Pesanan Selesai
        cursor.execute("SELECT COUNT(*) AS total FROM pesanan WHERE status = 'selesai'")
        total_pesanan_selesai = cursor.fetchone()['total']

        # Total Produk
        cursor.execute("SELECT COUNT(*) AS total FROM produk")
        total_produk = cursor.fetchone()['total']

        # Total Pelanggan (Member)
        cursor.execute("SELECT COUNT(*) AS total FROM users WHERE role = 'user'")
        total_member = cursor.fetchone()['total']

        # Top 5 Produk Terlaris berdasarkan kuantitas & omset
        cursor.execute("""
            SELECT produk.id, produk.nama_produk, produk.gambar, produk.harga, produk.stok,
                   COALESCE(SUM(detail_pesanan.jumlah), 0) AS total_terjual,
                   COALESCE(SUM(detail_pesanan.subtotal), 0) AS total_omset
            FROM produk
            LEFT JOIN detail_pesanan ON produk.id = detail_pesanan.produk_id
            GROUP BY produk.id
            ORDER BY total_terjual DESC, total_omset DESC
            LIMIT 5
        """)
        produk_terlaris = cursor.fetchall()

        # Statistik Distribusi Status Pesanan
        cursor.execute("""
            SELECT status, COUNT(*) AS jumlah, COALESCE(SUM(total_harga), 0) AS omset
            FROM pesanan
            GROUP BY status
        """)
        status_distribusi = cursor.fetchall()

        # 10 Pesanan Terbaru
        cursor.execute("""
            SELECT pesanan.*, 
                   COALESCE(users.nama, 'Pelanggan') AS nama_pembeli,
                   COALESCE(users.email, '-') AS email_pembeli
            FROM pesanan
            LEFT JOIN users ON pesanan.user_id = users.id
            ORDER BY pesanan.id DESC
            LIMIT 10
        """)
        pesanan_terbaru = cursor.fetchall()

        # Data Grafik Penjualan Harian (7 - 14 Hari Terakhir)
        cursor.execute("""
            SELECT DATE(tanggal_pesanan) AS tgl, 
                   COALESCE(SUM(total_harga), 0) AS total_omset,
                   COUNT(id) AS jml_order
            FROM pesanan
            WHERE status != 'dibatalkan'
            GROUP BY DATE(tanggal_pesanan)
            ORDER BY tgl ASC
            LIMIT 14
        """)
        omset_harian = cursor.fetchall()

        chart_labels = [row['tgl'].strftime('%d %b') if hasattr(row['tgl'], 'strftime') else str(row['tgl']) for row in omset_harian]
        chart_omset = [float(row['total_omset']) for row in omset_harian]
        chart_orders = [int(row['jml_order']) for row in omset_harian]

        status_labels = [row['status'].replace('_', ' ').title() for row in status_distribusi]
        status_counts = [int(row['jumlah']) for row in status_distribusi]

        return render_template(
            'admin_dashboard.html',
            total_pendapatan=total_pendapatan,
            total_pesanan=total_pesanan,
            total_pesanan_selesai=total_pesanan_selesai,
            total_produk=total_produk,
            total_member=total_member,
            produk_terlaris=produk_terlaris,
            pesanan_terbaru=pesanan_terbaru,
            status_distribusi=status_distribusi,
            chart_labels=json.dumps(chart_labels),
            chart_omset=json.dumps(chart_omset),
            chart_orders=json.dumps(chart_orders),
            status_labels=json.dumps(status_labels),
            status_counts=json.dumps(status_counts)
        )
    finally:
        cursor.close()
        db.close()

# Unduh / Ekspor Laporan Penjualan (Excel / CSV Format dengan BOM UTF-8)
@app.route('/admin/laporan/export-csv')
@admin_required
def export_laporan_csv():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        query = """
            SELECT pesanan.*, 
                   COALESCE(users.nama, 'Pelanggan') AS nama_pembeli,
                   COALESCE(users.email, '-') AS email_pembeli,
                   COALESCE(NULLIF(pesanan.no_hp, ''), users.no_hp, '-') AS no_telepon,
                   COALESCE(NULLIF(pesanan.alamat_pengiriman, ''), users.alamat, '-') AS alamat_tujuan
            FROM pesanan
            LEFT JOIN users ON pesanan.user_id = users.id
            ORDER BY pesanan.id DESC
        """
        cursor.execute(query)
        daftar_pesanan = cursor.fetchall()

        for p in daftar_pesanan:
            cursor.execute("""
                SELECT detail_pesanan.*, COALESCE(produk.nama_produk, 'Produk') AS nama_produk
                FROM detail_pesanan
                LEFT JOIN produk ON detail_pesanan.produk_id = produk.id
                WHERE detail_pesanan.pesanan_id = %s
            """, (p['id'],))
            p['items'] = cursor.fetchall()

        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        writer.writerow([
            'ID Pesanan', 'Tanggal Pesanan', 'Nama Pelanggan', 'Email', 'No Telepon',
            'Alamat Pengiriman', 'Metode Pembayaran', 'Status Pesanan',
            'Kode Voucher', 'Diskon (Rp)', 'Total Tagihan (Rp)', 'Daftar Produk Dipesan'
        ])

        for p in daftar_pesanan:
            tgl_str = p['tanggal_pesanan'].strftime('%Y-%m-%d %H:%M:%S') if p.get('tanggal_pesanan') else '-'
            item_summary = ", ".join([f"{it['nama_produk']} ({it['jumlah']}x @ Rp {float(it['harga_satuan']):,.0f})" for it in p['items']])
            writer.writerow([
                f"#{p['id']}",
                tgl_str,
                p['nama_pembeli'],
                p['email_pembeli'],
                p['no_telepon'],
                p['alamat_tujuan'].replace('\n', ' ').replace('\r', ' '),
                p.get('metode_pembayaran', '-'),
                p.get('status', '-').capitalize(),
                p.get('kode_kupon') or '-',
                f"{float(p.get('diskon') or 0):.2f}",
                f"{float(p['total_harga']):.2f}",
                item_summary
            ])

        csv_content = '\ufeff' + output.getvalue()
        filename = f"laporan_penjualan_barokah_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(
            csv_content,
            mimetype='text/csv; charset=utf-8',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'}
        )
    finally:
        cursor.close()
        db.close()

# 1. Halaman Utama (Katalog Produk dengan Pencarian & Filter Kategori)
@app.route('/')
def home():
    kategori_id = request.args.get('kategori', type=int)
    if kategori_id and kategori_id <= 0:
        kategori_id = None
    search_query = request.args.get('q', '').strip()
    page = max(1, request.args.get('page', 1, type=int))
    per_page = 12
    
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        # Ambil daftar kategori beserta jumlah produk untuk sidebar
        query_kat = """
            SELECT kategori.*, COUNT(produk.id) AS total_produk
            FROM kategori
            LEFT JOIN produk ON kategori.id = produk.kategori_id
            GROUP BY kategori.id, kategori.nama_kategori
            ORDER BY kategori.nama_kategori ASC
        """
        cursor.execute(query_kat)
        daftar_kategori = cursor.fetchall()

        # Total seluruh produk di database
        cursor.execute("SELECT COUNT(*) AS total FROM produk")
        total_semua_produk = cursor.fetchone()['total']

        # Hitung total produk sesuai filter (kategori & search)
        count_query = """
            SELECT COUNT(*) AS total 
            FROM produk 
            LEFT JOIN kategori ON produk.kategori_id = kategori.id 
            WHERE 1=1
        """
        params = []
        if kategori_id:
            count_query += " AND produk.kategori_id = %s"
            params.append(kategori_id)
        if search_query:
            count_query += " AND (produk.nama_produk LIKE %s OR produk.deskripsi LIKE %s)"
            params.extend([f"%{search_query}%", f"%{search_query}%"])

        cursor.execute(count_query, tuple(params))
        total_filtered_produk = cursor.fetchone()['total']
        total_pages = max(1, (total_filtered_produk + per_page - 1) // per_page)

        if page > total_pages:
            page = total_pages

        offset = (page - 1) * per_page

        # Query produk dengan JOIN kategori, rating ulasan, dan Pagination LIMIT OFFSET
        query = """
            SELECT produk.*, kategori.nama_kategori,
                   ROUND(COALESCE(AVG(ulasan.rating), 0.0), 1) AS rating_avg,
                   COUNT(ulasan.id) AS total_ulasan
            FROM produk 
            LEFT JOIN kategori ON produk.kategori_id = kategori.id 
            LEFT JOIN ulasan ON produk.id = ulasan.produk_id
            WHERE 1=1
        """
        if kategori_id:
            query += " AND produk.kategori_id = %s"
        if search_query:
            query += " AND (produk.nama_produk LIKE %s OR produk.deskripsi LIKE %s)"
            
        query += " GROUP BY produk.id ORDER BY produk.id DESC LIMIT %s OFFSET %s"
        query_params = list(params) + [per_page, offset]
        cursor.execute(query, tuple(query_params))
        daftar_produk = cursor.fetchall()

        return render_template(
            'index.html',
            produk_list=daftar_produk,
            kategori_list=daftar_kategori,
            total_semua_produk=total_semua_produk,
            total_filtered_produk=total_filtered_produk,
            selected_kategori=kategori_id,
            search_query=search_query,
            current_page=page,
            total_pages=total_pages
        )
    except Exception as e:
        flash(f"Terjadi kesalahan saat memuat katalog: {e}", "danger")
        return render_template(
            'index.html',
            produk_list=[],
            kategori_list=[],
            total_semua_produk=0,
            total_filtered_produk=0,
            selected_kategori=None,
            search_query='',
            current_page=1,
            total_pages=1
        )
    finally:
        cursor.close()
        db.close()

# 2. Halaman & Proses Tambah Produk (Admin)
@app.route('/tambah-produk', methods=['GET', 'POST'])
@admin_required
def tambah_produk():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        if request.method == 'POST':
            nama = request.form.get('nama_produk', '').strip()
            kategori_id = request.form.get('kategori_id')
            deskripsi = request.form.get('deskripsi', '').strip()
            varian = request.form.get('varian', '').strip()
            
            if not nama or not kategori_id:
                flash("Nama produk dan kategori wajib diisi!", "warning")
                return redirect(url_for('tambah_produk'))

            try:
                kategori_id = int(kategori_id)
                cursor.execute("SELECT id FROM kategori WHERE id = %s", (kategori_id,))
                if not cursor.fetchone():
                    flash("Kategori yang dipilih tidak valid!", "warning")
                    return redirect(url_for('tambah_produk'))
            except (ValueError, TypeError):
                flash("Kategori tidak valid!", "warning")
                return redirect(url_for('tambah_produk'))

            try:
                harga = float(request.form.get('harga') or 0)
                stok = int(request.form.get('stok') or 0)
                if harga < 0 or stok < 0:
                    raise ValueError
            except (ValueError, TypeError):
                flash("Harga dan stok harus berupa angka valid (minimal 0)!", "warning")
                return redirect(url_for('tambah_produk'))

            # Proses Upload Gambar Tunggal / Galeri Multi-Foto
            files_galeri = request.files.getlist('foto_galeri')
            single_file = request.files.get('gambar')
            
            all_files = []
            if files_galeri and any(f.filename for f in files_galeri):
                all_files.extend([f for f in files_galeri if f and f.filename])
            if single_file and single_file.filename:
                all_files.append(single_file)

            uploaded_images = []
            for idx, f in enumerate(all_files):
                if allowed_file(f.filename):
                    filename = secure_filename(f.filename)
                    unique_filename = f"{int(datetime.now().timestamp())}_{idx}_{filename}"
                    f.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                    uploaded_images.append(unique_filename)

            nama_gambar = uploaded_images[0] if uploaded_images else 'default.jpg'

            # Simpan ke Database
            query = """
                INSERT INTO produk (kategori_id, nama_produk, deskripsi, harga, stok, gambar, varian)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query, (kategori_id, nama, deskripsi, harga, stok, nama_gambar, varian))
            produk_id = cursor.lastrowid

            # Simpan foto ke tabel produk_gambar
            if uploaded_images:
                for idx, img_name in enumerate(uploaded_images):
                    is_prim = 1 if idx == 0 else 0
                    cursor.execute("INSERT INTO produk_gambar (produk_id, gambar, is_primary) VALUES (%s, %s, %s)", (produk_id, img_name, is_prim))
            else:
                cursor.execute("INSERT INTO produk_gambar (produk_id, gambar, is_primary) VALUES (%s, 'default.jpg', 1)", (produk_id,))

            db.commit()
            flash(f"Produk '{nama}' beserta galeri foto berhasil ditambahkan!", "success")
            return redirect(url_for('home'))

        # Method GET: ambil daftar kategori
        cursor.execute("SELECT * FROM kategori ORDER BY nama_kategori ASC")
        daftar_kategori = cursor.fetchall()
        return render_template('tambah_produk.html', kategori_list=daftar_kategori)
    except Exception as e:
        flash(f"Gagal menambahkan produk: {e}", "danger")
        return redirect(url_for('home'))
    finally:
        cursor.close()
        db.close()

# 3. Halaman & Proses Edit Produk (Admin)
@app.route('/edit-produk/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_produk(id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        # Cek produk yang akan diedit
        cursor.execute("SELECT * FROM produk WHERE id = %s", (id,))
        produk = cursor.fetchone()
        if not produk:
            flash("Produk tidak ditemukan!", "danger")
            return redirect(url_for('home'))

        if request.method == 'POST':
            nama = request.form.get('nama_produk', '').strip()
            kategori_id = request.form.get('kategori_id')
            deskripsi = request.form.get('deskripsi', '').strip()
            varian = request.form.get('varian', '').strip()
            
            if not nama or not kategori_id:
                flash("Nama produk dan kategori wajib diisi!", "warning")
                return redirect(url_for('edit_produk', id=id))

            try:
                kategori_id = int(kategori_id)
                cursor.execute("SELECT id FROM kategori WHERE id = %s", (kategori_id,))
                if not cursor.fetchone():
                    flash("Kategori yang dipilih tidak valid!", "warning")
                    return redirect(url_for('edit_produk', id=id))
            except (ValueError, TypeError):
                flash("Kategori tidak valid!", "warning")
                return redirect(url_for('edit_produk', id=id))

            try:
                harga = float(request.form.get('harga') or 0)
                stok = int(request.form.get('stok') or 0)
                if harga < 0 or stok < 0:
                    raise ValueError
            except (ValueError, TypeError):
                flash("Harga dan stok harus berupa angka valid (minimal 0)!", "warning")
                return redirect(url_for('edit_produk', id=id))
            
            nama_gambar = produk['gambar'] or 'default.jpg'

            # Upload Foto Galeri Baru (Multiple / Single)
            files_galeri = request.files.getlist('foto_galeri')
            single_file = request.files.get('gambar')

            new_files = []
            if files_galeri and any(f.filename for f in files_galeri):
                new_files.extend([f for f in files_galeri if f and f.filename])
            if single_file and single_file.filename:
                new_files.append(single_file)

            for idx, f in enumerate(new_files):
                if allowed_file(f.filename):
                    filename = secure_filename(f.filename)
                    unique_filename = f"{int(datetime.now().timestamp())}_{idx}_{filename}"
                    f.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                    cursor.execute("INSERT INTO produk_gambar (produk_id, gambar, is_primary) VALUES (%s, %s, 0)", (id, unique_filename))
                    if nama_gambar == 'default.jpg':
                        nama_gambar = unique_filename

            # Cek foto utama dari galeri
            cursor.execute("SELECT gambar FROM produk_gambar WHERE produk_id = %s ORDER BY is_primary DESC, id ASC LIMIT 1", (id,))
            prim = cursor.fetchone()
            if prim:
                nama_gambar = prim['gambar']

            # Update data ke database
            query = """
                UPDATE produk 
                SET kategori_id = %s, nama_produk = %s, deskripsi = %s, harga = %s, stok = %s, gambar = %s, varian = %s
                WHERE id = %s
            """
            cursor.execute(query, (kategori_id, nama, deskripsi, harga, stok, nama_gambar, varian, id))
            db.commit()
            flash(f"Produk '{nama}' berhasil diperbarui!", "success")
            return redirect(url_for('edit_produk', id=id))

        # Method GET
        cursor.execute("SELECT * FROM kategori ORDER BY nama_kategori ASC")
        daftar_kategori = cursor.fetchall()
        cursor.execute("SELECT * FROM produk_gambar WHERE produk_id = %s ORDER BY is_primary DESC, id ASC", (id,))
        galeri_foto = cursor.fetchall()
        return render_template('edit_produk.html', produk=produk, kategori_list=daftar_kategori, galeri_foto=galeri_foto)
    except Exception as e:
        flash(f"Gagal mengedit produk: {e}", "danger")
        return redirect(url_for('home'))
    finally:
        cursor.close()
        db.close()

# 3b. Hapus Foto Individual dari Galeri Produk (Admin)
@app.route('/hapus-foto-produk/<int:foto_id>', methods=['POST', 'GET'])
@admin_required
def hapus_foto_produk(foto_id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM produk_gambar WHERE id = %s", (foto_id,))
        foto = cursor.fetchone()
        if not foto:
            flash("Foto tidak ditemukan!", "warning")
            return redirect(url_for('home'))

        produk_id = foto['produk_id']
        nama_file = foto['gambar']

        cursor.execute("DELETE FROM produk_gambar WHERE id = %s", (foto_id,))
        db.commit()

        if nama_file and nama_file != 'default.jpg':
            path_foto = os.path.join(app.config['UPLOAD_FOLDER'], nama_file)
            if os.path.exists(path_foto):
                try:
                    os.remove(path_foto)
                except Exception:
                    pass

        # Update thumbnail utama produk jika foto yang dihapus adalah foto utama
        cursor.execute("SELECT gambar FROM produk_gambar WHERE produk_id = %s ORDER BY is_primary DESC, id ASC LIMIT 1", (produk_id,))
        next_foto = cursor.fetchone()
        new_thumb = next_foto['gambar'] if next_foto else 'default.jpg'
        cursor.execute("UPDATE produk SET gambar = %s WHERE id = %s", (new_thumb, produk_id))
        db.commit()

        flash("Foto berhasil dihapus dari galeri produk!", "success")
        return redirect(url_for('edit_produk', id=produk_id))
    finally:
        cursor.close()
        db.close()

# 4. Proses Hapus Produk (Admin)
@app.route('/hapus-produk/<int:id>')
@admin_required
def hapus_produk(id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT gambar, nama_produk FROM produk WHERE id = %s", (id,))
        produk = cursor.fetchone()
        if not produk:
            flash("Produk tidak ditemukan!", "warning")
            return redirect(url_for('home'))

        # Cek apakah produk memiliki riwayat transaksi di pesanan
        cursor.execute("SELECT COUNT(*) AS total FROM detail_pesanan WHERE produk_id = %s", (id,))
        if cursor.fetchone()['total'] > 0:
            flash("Produk ini tidak bisa dihapus karena tersimpan dalam riwayat transaksi pesanan! Anda dapat mengubah stoknya menjadi 0 via Edit Produk.", "warning")
            return redirect(url_for('home'))

        cursor.execute("DELETE FROM produk WHERE id = %s", (id,))
        db.commit()

        # Hapus berkas gambar dari server jika bukan default.jpg
        if produk['gambar'] and produk['gambar'] != 'default.jpg':
            path_gambar = os.path.join(app.config['UPLOAD_FOLDER'], produk['gambar'])
            if os.path.exists(path_gambar):
                try:
                    os.remove(path_gambar)
                except Exception:
                    pass

        flash(f"Produk '{produk['nama_produk']}' berhasil dihapus!", "success")
    except mysql.connector.Error as err:
        db.rollback()
        if err.errno == 1451:
            flash("Produk ini tidak bisa dihapus karena tersimpan dalam riwayat transaksi pesanan! Anda dapat mengubah stoknya menjadi 0 via Edit Produk.", "warning")
        else:
            flash(f"Gagal menghapus produk: {err}", "danger")
    finally:
        cursor.close()
        db.close()

    return redirect(url_for('home'))

# 4b. Halaman & Modal Detail Produk (Beserta Rating & Ulasan)
@app.route('/produk/<int:id>')
def detail_produk(id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT produk.*, kategori.nama_kategori,
                   ROUND(COALESCE(AVG(ulasan.rating), 0.0), 1) AS rating_avg,
                   COUNT(ulasan.id) AS total_ulasan
            FROM produk
            LEFT JOIN kategori ON produk.kategori_id = kategori.id
            LEFT JOIN ulasan ON produk.id = ulasan.produk_id
            WHERE produk.id = %s
            GROUP BY produk.id
        """, (id,))
        produk = cursor.fetchone()
        if not produk:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json':
                return {'error': 'Produk tidak ditemukan'}, 404
            flash("Produk tidak ditemukan!", "danger")
            return redirect(url_for('home'))

        # Ambil daftar ulasan pembeli
        cursor.execute("""
            SELECT ulasan.*, users.nama AS nama_user
            FROM ulasan
            JOIN users ON ulasan.user_id = users.id
            WHERE ulasan.produk_id = %s
            ORDER BY ulasan.id DESC
        """, (id,))
        daftar_ulasan = cursor.fetchall()

        # Format JSON jika dipanggil secara dinamis oleh modal pop-up AJAX
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json':
            return {
                'produk': {
                    'id': produk['id'],
                    'nama_produk': produk['nama_produk'],
                    'kategori': produk['nama_kategori'] or 'Umum',
                    'harga': float(produk['harga']),
                    'harga_format': f"Rp {float(produk['harga']):,.0f}".replace(",", "."),
                    'stok': produk['stok'],
                    'deskripsi': produk['deskripsi'] or 'Deskripsi produk belum ditambahkan.',
                    'gambar': produk['gambar'] or 'default.jpg',
                    'rating_avg': float(produk['rating_avg']),
                    'total_ulasan': produk['total_ulasan']
                },
                'ulasan': [{
                    'id': u['id'],
                    'nama_user': u['nama_user'],
                    'rating': u['rating'],
                    'komentar': u['komentar'],
                    'tanggal': u['created_at'].strftime('%d %b %Y') if u.get('created_at') else '-'
                } for u in daftar_ulasan]
            }

        # Ambil galeri multi-foto produk
        cursor.execute("SELECT * FROM produk_gambar WHERE produk_id = %s ORDER BY is_primary DESC, id ASC", (id,))
        galeri_foto = cursor.fetchall()

        return render_template('detail_produk.html', produk=produk, ulasan_list=daftar_ulasan, galeri_foto=galeri_foto)
    finally:
        cursor.close()
        db.close()

# 4c. Fitur Beli Sekarang (Direct Checkout tanpa lewat keranjang)
@app.route('/beli-sekarang/<int:id>', methods=['GET', 'POST'])
@app.route('/beli-langsung/<int:id>', methods=['GET', 'POST'])
def beli_sekarang(id):
    if 'user_id' not in session:
        flash("Silakan login terlebih dahulu untuk melakukan transaksi pembelian.", "warning")
        return redirect(url_for('login', next=f'/beli-sekarang/{id}'))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, nama_produk, stok, harga FROM produk WHERE id = %s", (id,))
        produk = cursor.fetchone()
        if not produk:
            flash("Produk tidak ditemukan!", "danger")
            return redirect(url_for('home'))

        if produk['stok'] < 1:
            flash(f"Maaf, stok produk '{produk['nama_produk']}' sedang habis!", "danger")
            return redirect(url_for('detail_produk', id=id))

        jumlah = 1
        if request.method == 'POST':
            try:
                jumlah = int(request.form.get('jumlah', 1))
            except (ValueError, TypeError):
                jumlah = 1
        elif request.args.get('jumlah'):
            try:
                jumlah = int(request.args.get('jumlah', 1))
            except (ValueError, TypeError):
                jumlah = 1

        jumlah = max(1, min(jumlah, produk['stok']))

        # Simpan varian jika dipilih
        varian = request.values.get('varian', '').strip()
        if 'item_varian' not in session:
            session['item_varian'] = {}
        if varian:
            session['item_varian'][str(id)] = varian

        # Langsung set produk ini ke sesi transaksi checkout (bypass keranjang standar)
        session['keranjang'] = {str(id): jumlah}
        session.modified = True
        return redirect(url_for('checkout'))
    finally:
        cursor.close()
        db.close()

# 4d. Proses Tambah Ulasan Produk
@app.route('/tambah-ulasan/<int:produk_id>', methods=['POST'])
def tambah_ulasan(produk_id):
    if 'user_id' not in session:
        flash("Silakan login terlebih dahulu untuk memberikan rating dan ulasan.", "warning")
        return redirect(url_for('login'))

    rating = int(request.form.get('rating', 5))
    rating = max(1, min(5, rating))
    komentar = request.form.get('komentar', '').strip()

    if not komentar:
        flash("Ulasan atau komentar tidak boleh kosong!", "warning")
        return redirect(request.referrer or url_for('detail_produk', id=produk_id))

    db = get_db_connection()
    cursor = db.cursor()
    try:
        # Upload Foto Ulasan Produk (Opsional)
        foto_nama = None
        if 'foto_ulasan' in request.files:
            file_foto = request.files['foto_ulasan']
            if file_foto and file_foto.filename and allowed_file(file_foto.filename):
                ext = file_foto.filename.rsplit('.', 1)[1].lower()
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                foto_nama = f"ulasan_{produk_id}_{session['user_id']}_{timestamp}.{ext}"
                file_foto.save(os.path.join(app.config['UPLOAD_FOLDER'], foto_nama))

        cursor.execute("""
            INSERT INTO ulasan (produk_id, user_id, rating, komentar, foto)
            VALUES (%s, %s, %s, %s, %s)
        """, (produk_id, session['user_id'], rating, komentar, foto_nama))
        db.commit()
        flash("Terima kasih! Ulasan dan rating Anda berhasil disimpan.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Gagal mengirim ulasan: {e}", "danger")
    finally:
        cursor.close()
        db.close()

    return redirect(request.referrer or url_for('detail_produk', id=produk_id))

# 5. Tambah Produk ke Keranjang (Dengan Validasi Stok & Varian)
@app.route('/tambah-keranjang/<int:id>', methods=['GET', 'POST'])
def tambah_keranjang(id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM produk WHERE id = %s", (id,))
        produk = cursor.fetchone()
        if not produk:
            flash("Produk tidak ditemukan!", "danger")
            return redirect(url_for('home'))

        if produk['stok'] <= 0:
            flash(f"Maaf, stok untuk '{produk['nama_produk']}' sedang habis!", "warning")
            return redirect(request.referrer or url_for('home'))

        if 'keranjang' not in session:
            session['keranjang'] = {}

        if 'item_varian' not in session:
            session['item_varian'] = {}

        varian = request.values.get('varian', '').strip()
        if varian:
            session['item_varian'][str(id)] = varian

        keranjang = session['keranjang']
        str_id = str(id)
        current_qty = keranjang.get(str_id, 0)

        tambah_qty = 1
        if request.values.get('jumlah'):
            try:
                tambah_qty = max(1, int(request.values.get('jumlah', 1)))
            except (ValueError, TypeError):
                tambah_qty = 1

        if current_qty + tambah_qty > produk['stok']:
            flash(f"Jumlah di keranjang sudah mencapai batas stok yang tersedia ({produk['stok']} pcs)!", "warning")
        else:
            keranjang[str_id] = current_qty + tambah_qty
            session.modified = True
            msg = f"'{produk['nama_produk']}'"
            if varian:
                msg += f" (Varian: {varian})"
            msg += " berhasil dimasukkan ke keranjang!"
            flash(msg, "success")

    except Exception as e:
        flash(f"Gagal menambahkan ke keranjang: {e}", "danger")
    finally:
        cursor.close()
        db.close()

    return redirect(request.referrer or url_for('home'))

# 6. Kurangi Item dari Keranjang
@app.route('/kurang-keranjang/<int:id>')
def kurang_keranjang(id):
    str_id = str(id)
    if 'keranjang' in session and str_id in session['keranjang']:
        if session['keranjang'][str_id] > 1:
            session['keranjang'][str_id] -= 1
            flash("Jumlah item berhasil dikurangi.", "info")
        else:
            del session['keranjang'][str_id]
            if 'item_varian' in session and str_id in session['item_varian']:
                del session['item_varian'][str_id]
            flash("Item dihapus dari keranjang belanja.", "info")
        session.modified = True
    return redirect(url_for('lihat_keranjang'))

# 7. Halaman Lihat Keranjang Belanja
@app.route('/keranjang')
def lihat_keranjang():
    if 'keranjang' not in session or not session['keranjang']:
        return render_template('keranjang.html', items=[], total=0)

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    items = []
    total = 0
    items_to_remove = []
    item_varian_dict = session.get('item_varian', {})

    try:
        for prod_id, jumlah in list(session['keranjang'].items()):
            cursor.execute("SELECT * FROM produk WHERE id = %s", (prod_id,))
            produk = cursor.fetchone()
            if produk:
                subtotal = produk['harga'] * jumlah
                total += subtotal
                items.append({
                    'produk': produk,
                    'jumlah': jumlah,
                    'subtotal': subtotal,
                    'varian': item_varian_dict.get(str(prod_id), '')
                })
            else:
                items_to_remove.append(prod_id)

        # Hapus item dari keranjang jika produk sudah tidak ada di database
        if items_to_remove:
            for pid in items_to_remove:
                del session['keranjang'][pid]
                if pid in item_varian_dict:
                    del item_varian_dict[pid]
            session.modified = True

    finally:
        cursor.close()
        db.close()

    return render_template('keranjang.html', items=items, total=total)

# 8. Hapus Seluruh Kuantitas Item dari Keranjang
@app.route('/hapus-keranjang/<int:id>')
def hapus_keranjang(id):
    str_id = str(id)
    if 'keranjang' in session and str_id in session['keranjang']:
        del session['keranjang'][str_id]
        if 'item_varian' in session and str_id in session['item_varian']:
            del session['item_varian'][str_id]
        session.modified = True
        flash("Item telah dihapus dari keranjang belanja.", "info")
    return redirect(url_for('lihat_keranjang'))


# 8b. API Cek & Validasi Kupon Diskon (AJAX)
@app.route('/cek-kupon', methods=['POST'])
def cek_kupon():
    data = request.get_json(silent=True) or request.form
    kode = data.get('kode', '').strip().upper()
    try:
        total = float(data.get('total', 0))
    except (ValueError, TypeError):
        total = 0.0

    if not kode:
        return jsonify({'valid': False, 'pesan': 'Silakan masukkan kode voucher diskon!'}), 400

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM kupon WHERE UPPER(kode) = %s AND status_aktif = 1", (kode,))
        kupon = cursor.fetchone()
        if not kupon:
            return jsonify({
                'valid': False,
                'pesan': f"Kode kupon '{kode}' tidak valid atau sudah tidak aktif."
            })

        min_belanja = float(kupon['minimal_belanja'])
        if total < min_belanja:
            min_fmt = f"Rp {min_belanja:,.0f}".replace(',', '.')
            return jsonify({
                'valid': False,
                'pesan': f"Kupon {kupon['kode']} memerlukan minimal belanja {min_fmt} (Total belanja Anda saat ini: {f'Rp {total:,.0f}'.replace(',', '.')})."
            })

        if kupon['tipe_diskon'] == 'persen':
            diskon = (total * float(kupon['nilai_diskon'])) / 100.0
        else:
            diskon = float(kupon['nilai_diskon'])

        diskon = min(diskon, total)
        total_akhir = max(0.0, total - diskon)
        diskon_fmt = f"Rp {diskon:,.0f}".replace(',', '.')
        total_fmt = f"Rp {total_akhir:,.0f}".replace(',', '.')

        return jsonify({
            'valid': True,
            'kode': kupon['kode'],
            'tipe_diskon': kupon['tipe_diskon'],
            'nilai_diskon': float(kupon['nilai_diskon']),
            'diskon': diskon,
            'diskon_format': diskon_fmt,
            'total_akhir': total_akhir,
            'total_format': total_fmt,
            'pesan': f"Kupon {kupon['kode']} berhasil diterapkan! Hemat {diskon_fmt}."
        })
    finally:
        cursor.close()
        db.close()

# 9. Halaman & Proses Checkout Pesanan (Dengan Kupon & Diskon)
@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    # Pastikan user sudah login sebelum checkout
    if 'user_id' not in session:
        flash("Silakan login terlebih dahulu untuk melakukan checkout pesanan.", "warning")
        return redirect(url_for('login'))

    if 'keranjang' not in session or not session['keranjang']:
        flash("Keranjang belanja kamu masih kosong!", "warning")
        return redirect(url_for('home'))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:
        # Validasi apakah user benar-benar ada di database
        cursor.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()
        if not user:
            session.clear()
            flash("Sesi akun Anda tidak valid atau telah dihapus. Silakan login kembali.", "warning")
            return redirect(url_for('login'))

        total_harga = 0
        items_checkout = []
        item_varian_dict = session.get('item_varian', {})

        for prod_id, jumlah in session['keranjang'].items():
            cursor.execute("SELECT * FROM produk WHERE id = %s", (prod_id,))
            produk = cursor.fetchone()
            if not produk:
                flash("Ada produk di keranjang yang sudah tidak tersedia.", "danger")
                return redirect(url_for('lihat_keranjang'))

            # Cek ketersediaan stok
            if produk['stok'] < jumlah:
                flash(f"Stok produk '{produk['nama_produk']}' tidak mencukupi! (Tersedia: {produk['stok']})", "danger")
                return redirect(url_for('lihat_keranjang'))
            
            subtotal = produk['harga'] * jumlah
            total_harga += subtotal
            items_checkout.append({
                'produk_id': produk['id'],
                'nama_produk': produk['nama_produk'],
                'gambar': produk['gambar'] or 'default.jpg',
                'jumlah': jumlah,
                'harga_satuan': produk['harga'],
                'subtotal': subtotal,
                'varian': item_varian_dict.get(str(prod_id), '')
            })

        if not items_checkout:
            flash("Tidak ada barang valid untuk di-checkout.", "warning")
            return redirect(url_for('home'))

        # GET Request: Tampilkan halaman review checkout beserta opsi kupon aktif
        if request.method == 'GET':
            cursor.execute("SELECT * FROM kupon WHERE status_aktif = 1 ORDER BY minimal_belanja ASC")
            daftar_kupon = cursor.fetchall()
            return render_template(
                'checkout.html',
                items=items_checkout,
                total=total_harga,
                user=user,
                daftar_kupon=daftar_kupon
            )

        # POST Request: Proses Pembayaran, Verifikasi Kupon, & Buat Pesanan
        nama_penerima = request.form.get('nama_penerima', user['nama']).strip()
        no_hp = request.form.get('no_hp', user.get('no_hp', '')).strip()
        alamat_pengiriman = request.form.get('alamat_pengiriman', user.get('alamat', '')).strip()
        metode_pembayaran = request.form.get('metode_pembayaran', '').strip()
        catatan = request.form.get('catatan', '').strip()
        kode_kupon = request.form.get('kode_kupon', '').strip().upper()

        # Validasi Kupon di Sisi Server
        diskon = 0.0
        valid_kode_kupon = None
        float_total = float(total_harga)
        if kode_kupon:
            cursor.execute("SELECT * FROM kupon WHERE UPPER(kode) = %s AND status_aktif = 1", (kode_kupon,))
            kp = cursor.fetchone()
            if kp and float_total >= float(kp['minimal_belanja']):
                if kp['tipe_diskon'] == 'persen':
                    diskon = (float_total * float(kp['nilai_diskon'])) / 100.0
                else:
                    diskon = float(kp['nilai_diskon'])
                diskon = min(diskon, float_total)
                valid_kode_kupon = kp['kode']

        total_harga_final = max(0.0, float_total - diskon)

        # Validasi Wajib Pilih Metode Pembayaran
        if not metode_pembayaran:
            flash("Silakan pilih salah satu metode pembayaran terlebih dahulu sebelum membuat pesanan!", "warning")
            cursor.execute("SELECT * FROM kupon WHERE status_aktif = 1 ORDER BY minimal_belanja ASC")
            daftar_kupon = cursor.fetchall()
            return render_template('checkout.html', items=items_checkout, total=total_harga, user=user, daftar_kupon=daftar_kupon)

        if not no_hp or not alamat_pengiriman:
            flash("Nomor HP dan Alamat Pengiriman lengkap wajib diisi untuk pengiriman pesanan!", "warning")
            cursor.execute("SELECT * FROM kupon WHERE status_aktif = 1 ORDER BY minimal_belanja ASC")
            daftar_kupon = cursor.fetchall()
            return render_template('checkout.html', items=items_checkout, total=total_harga, user=user, daftar_kupon=daftar_kupon)

        # Update profil user jika sebelumnya belum ada nomor HP atau alamat
        if not user.get('no_hp') or not user.get('alamat'):
            cursor.execute("""
                UPDATE users SET no_hp = COALESCE(NULLIF(%s, ''), no_hp), alamat = COALESCE(NULLIF(%s, ''), alamat)
                WHERE id = %s
            """, (no_hp, alamat_pengiriman, user['id']))

        # Tentukan status awal berdasarkan metode pembayaran
        status_awal = 'diproses' if 'COD' in metode_pembayaran.upper() else 'menunggu_pembayaran'

        # Koordinat kurir & tujuan
        kurir_lat = -6.175392
        kurir_lng = 106.827153
        
        req_lat = request.form.get('latitude', '').strip()
        req_lng = request.form.get('longitude', '').strip()
        tujuan_lat = -6.208763
        tujuan_lng = 106.845599

        if req_lat and req_lng:
            try:
                tujuan_lat = float(req_lat)
                tujuan_lng = float(req_lng)
                if not user.get('latitude') or not user.get('longitude'):
                    cursor.execute("UPDATE users SET latitude = %s, longitude = %s WHERE id = %s", (tujuan_lat, tujuan_lng, user['id']))
            except (ValueError, TypeError):
                pass
        elif user.get('latitude') and user.get('longitude'):
            try:
                tujuan_lat = float(user['latitude'])
                tujuan_lng = float(user['longitude'])
            except (ValueError, TypeError):
                pass

        # Simpan Header Pesanan Beserta Diskon & Kupon
        query_pesanan = """
            INSERT INTO pesanan 
            (user_id, total_harga, status, metode_pembayaran, alamat_pengiriman, no_hp, kurir_lat, kurir_lng, tujuan_lat, tujuan_lng, kode_kupon, diskon) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query_pesanan, (
            session['user_id'], total_harga_final, status_awal, metode_pembayaran, alamat_pengiriman, no_hp,
            kurir_lat, kurir_lng, tujuan_lat, tujuan_lng, valid_kode_kupon, diskon
        ))
        pesanan_id = cursor.lastrowid

        # Simpan Detail Pesanan & Kurangi Stok Produk
        for item in items_checkout:
            query_detail = """
                INSERT INTO detail_pesanan (pesanan_id, produk_id, jumlah, harga_satuan, subtotal, varian)
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query_detail, (
                pesanan_id, 
                item['produk_id'], 
                item['jumlah'], 
                item['harga_satuan'], 
                item['subtotal'],
                item.get('varian', '')
            ))

            # Kurangi stok produk secara atomik dengan proteksi stok negatif
            cursor.execute(
                "UPDATE produk SET stok = stok - %s WHERE id = %s AND stok >= %s", 
                (item['jumlah'], item['produk_id'], item['jumlah'])
            )
            if cursor.rowcount == 0:
                raise Exception(f"Stok produk '{item['nama_produk']}' tidak mencukupi saat proses finalisasi transaksi.")

        db.commit()

        # Kosongkan keranjang belanja di session
        session.pop('keranjang', None)
        session.pop('item_varian', None)
        nama_produk_ringkasan = ", ".join([it['nama_produk'] for it in items_checkout])
        return render_template(
            'checkout_sukses.html',
            pesanan_id=pesanan_id,
            total=total_harga_final,
            diskon=diskon,
            kode_kupon=valid_kode_kupon,
            status=status_awal,
            metode_pembayaran=metode_pembayaran,
            alamat_pengiriman=alamat_pengiriman,
            nama_produk_ringkasan=nama_produk_ringkasan,
            items=items_checkout
        )

    except Exception as e:
        db.rollback()
        flash(f"Terjadi kesalahan saat memproses checkout: {e}", "danger")
        return redirect(url_for('lihat_keranjang'))
    finally:
        cursor.close()
        db.close()

# 9b. Halaman & Manajemen Wishlist (Produk Favorit)
@app.route('/wishlist')
def wishlist():
    if 'user_id' not in session:
        flash("Silakan login terlebih dahulu untuk mengakses daftar wishlist Anda.", "warning")
        return redirect(url_for('login', next='/wishlist'))

    user_id = session['user_id']
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT produk.*, kategori.nama_kategori,
                   ROUND(COALESCE(AVG(ulasan.rating), 0.0), 1) AS rating_avg,
                   COUNT(ulasan.id) AS total_ulasan,
                   wishlist.created_at AS tgl_wishlist
            FROM wishlist
            JOIN produk ON wishlist.produk_id = produk.id
            LEFT JOIN kategori ON produk.kategori_id = kategori.id
            LEFT JOIN ulasan ON produk.id = ulasan.produk_id
            WHERE wishlist.user_id = %s
            GROUP BY produk.id
            ORDER BY wishlist.id DESC
        """, (user_id,))
        produk_list = cursor.fetchall()
        return render_template('wishlist.html', produk_list=produk_list)
    finally:
        cursor.close()
        db.close()

# 9c. Toggle Wishlist (Tambah / Hapus Produk dari Favorit - AJAX & Standard)
@app.route('/toggle-wishlist/<int:produk_id>', methods=['GET', 'POST'])
def toggle_wishlist(produk_id):
    if 'user_id' not in session:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'status': 'unauthorized', 'pesan': 'Silakan masuk akun terlebih dahulu.'}), 401
        flash("Silakan login terlebih dahulu untuk menambahkan produk ke wishlist.", "warning")
        return redirect(url_for('login', next=request.referrer or url_for('home')))

    user_id = session['user_id']
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM wishlist WHERE user_id = %s AND produk_id = %s", (user_id, produk_id))
        ada = cursor.fetchone()
        if ada:
            cursor.execute("DELETE FROM wishlist WHERE id = %s", (ada['id'],))
            db.commit()
            action = 'removed'
            is_wishlist = False
            pesan = "Produk dihapus dari Wishlist."
        else:
            cursor.execute("INSERT INTO wishlist (user_id, produk_id) VALUES (%s, %s)", (user_id, produk_id))
            db.commit()
            action = 'added'
            is_wishlist = True
            pesan = "Produk berhasil ditambahkan ke Wishlist!"

        cursor.execute("SELECT COUNT(*) AS total FROM wishlist WHERE user_id = %s", (user_id,))
        total_wishlist = cursor.fetchone()['total']

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({
                'status': 'success',
                'action': action,
                'is_wishlist': is_wishlist,
                'total_wishlist': total_wishlist,
                'pesan': pesan
            })

        flash(pesan, "success" if action == 'added' else "info")
        return redirect(request.referrer or url_for('wishlist'))
    except Exception as e:
        db.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'status': 'error', 'pesan': str(e)}), 500
        flash(f"Gagal memproses wishlist: {e}", "danger")
        return redirect(request.referrer or url_for('home'))
    finally:
        cursor.close()
        db.close()

# 10. Registrasi Akun Baru
@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        nama = request.form.get('nama', '').strip()
        email = request.form.get('email', '').strip().lower()
        no_hp = request.form.get('no_hp', '').strip()
        password = request.form.get('password', '').strip()
        
        # Validasi: Nama, Password, serta salah satu dari Email atau Nomor HP wajib ada
        if not nama or (not email and not no_hp) or not password:
            flash("Nama, Password, dan salah satu dari Email atau Nomor HP wajib diisi!", "warning")
            return redirect(url_for('register'))

        if email and ('@' not in email or '.' not in email):
            flash("Format email tidak valid!", "warning")
            return redirect(url_for('register'))

        if len(password) < 4:
            flash("Password minimal harus 4 karakter!", "warning")
            return redirect(url_for('register'))

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        try:
            # Cek apakah email sudah dipakai (jika email diisi)
            if email:
                cursor.execute("SELECT * FROM users WHERE LOWER(email) = %s", (email,))
                if cursor.fetchone():
                    flash("Email sudah terdaftar! Silakan login atau gunakan email lain.", "danger")
                    return redirect(url_for('register'))
            
            # Cek apakah no_hp sudah dipakai (jika no_hp diisi)
            if no_hp:
                cursor.execute("SELECT * FROM users WHERE no_hp = %s", (no_hp,))
                if cursor.fetchone():
                    flash("Nomor HP sudah terdaftar! Silakan login dengan akun Anda.", "danger")
                    return redirect(url_for('register'))
            
            hashed_password = generate_password_hash(password)
            query = "INSERT INTO users (nama, email, password, role, no_hp, alamat) VALUES (%s, %s, %s, %s, %s, '')"
            cursor.execute(query, (nama, email, hashed_password, 'pembeli', no_hp))
            db.commit()

            flash("Akun berhasil dibuat! Silakan masuk dengan akun Anda.", "success")
            return redirect(url_for('login'))
        except Exception as e:
            flash(f"Gagal melakukan pendaftaran: {e}", "danger")
            return redirect(url_for('register'))
        finally:
            cursor.close()
            db.close()
        
    return render_template('register.html')

# 11. Login Pengguna
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM users WHERE LOWER(email) = %s", (email,))
            user = cursor.fetchone()
            
            is_valid = False
            if user:
                try:
                    is_valid = check_password_hash(user['password'], password)
                except Exception:
                    is_valid = (user['password'] == password)
                
                # Mendukung migrasi jika database diedit langsung dengan plain-text
                if not is_valid and user['password'] == password:
                    is_valid = True
                    try:
                        new_hash = generate_password_hash(password)
                        cursor.execute("UPDATE users SET password = %s WHERE id = %s", (new_hash, user['id']))
                        db.commit()
                    except Exception:
                        pass

            if is_valid:
                session['user_id'] = user['id']
                session['nama'] = user['nama']
                session['role'] = user['role']
                session['foto_profil'] = user.get('foto_profil') or ''
                flash(f"Selamat datang, {user['nama']}!", "success")

                next_url = request.args.get('next') or request.form.get('next')
                if next_url and next_url.startswith('/'):
                    return redirect(next_url)

                # Jika pembeli memiliki keranjang aktif, arahkan ke keranjang; selain itu (termasuk admin) ke katalog utama (home)
                if user['role'] != 'admin' and session.get('keranjang'):
                    return redirect(url_for('lihat_keranjang'))
                return redirect(url_for('home'))
            else:
                flash("Email atau password salah! Periksa kembali data Anda.", "danger")
                return redirect(url_for('login'))
        finally:
            cursor.close()
            db.close()
            
    return render_template('login.html')

# 12. Logout
@app.route('/logout')
def logout():
    session.clear()
    flash("Anda telah berhasil keluar (logout).", "info")
    return redirect(url_for('home'))

# 12b. Profil Pengguna & Kelola Alamat Lengkap
@app.route('/profil', methods=['GET', 'POST'])
def profil():
    if 'user_id' not in session:
        flash("Silakan login untuk mengakses profil dan alamat Anda.", "warning")
        return redirect(url_for('login'))

    user_id = session['user_id']
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            session.clear()
            flash("Sesi akun tidak valid. Silakan login kembali.", "warning")
            return redirect(url_for('login'))

        if request.method == 'POST':
            nama = request.form.get('nama', '').strip()
            email = request.form.get('email', '').strip().lower()
            no_hp = request.form.get('no_hp', '').strip()
            alamat = request.form.get('alamat', '').strip()

            # Validasi akun: Email atau No HP tidak boleh kosong
            if not email and not no_hp:
                flash("Email atau Nomor HP tidak boleh kosong!", "warning")
                return redirect(url_for('profil'))

            if email and ('@' not in email or '.' not in email):
                flash("Format email tidak valid!", "warning")
                return redirect(url_for('profil'))

            # Cek duplikasi email jika diubah
            if email and email != (user['email'] or '').lower():
                cursor.execute("SELECT id FROM users WHERE LOWER(email) = %s AND id != %s", (email, user_id))
                if cursor.fetchone():
                    flash("Email tersebut sudah digunakan oleh akun lain!", "danger")
                    return redirect(url_for('profil'))

            # Koordinat Lokasi Pin Peta
            lat_raw = request.form.get('latitude', '').strip()
            lng_raw = request.form.get('longitude', '').strip()
            latitude = user.get('latitude')
            longitude = user.get('longitude')
            if lat_raw and lng_raw:
                try:
                    latitude = float(lat_raw)
                    longitude = float(lng_raw)
                except (ValueError, TypeError):
                    pass

            # Upload Foto Profil
            foto_filename = user.get('foto_profil')
            if 'foto_profil' in request.files:
                file_foto = request.files['foto_profil']
                if file_foto and file_foto.filename and allowed_file(file_foto.filename):
                    ext = file_foto.filename.rsplit('.', 1)[1].lower()
                    foto_filename = f"avatar_{user_id}_{int(datetime.now().timestamp())}.{ext}"
                    file_foto.save(os.path.join(app.config['UPLOAD_FOLDER'], foto_filename))
                    session['foto_profil'] = foto_filename

            cursor.execute("""
                UPDATE users 
                SET nama = %s, email = %s, no_hp = %s, alamat = %s, latitude = %s, longitude = %s, foto_profil = %s 
                WHERE id = %s
            """, (nama, email, no_hp, alamat, latitude, longitude, foto_filename, user_id))
            db.commit()
            session['nama'] = nama
            if foto_filename:
                session['foto_profil'] = foto_filename
            flash("Data profil, foto, dan titik lokasi berhasil diperbarui!", "success")
            return redirect(url_for('profil'))

        # Data statistik belanja pengguna
        cursor.execute("""
            SELECT COUNT(*) AS total_pesanan,
                   COALESCE(SUM(CASE WHEN status='selesai' THEN 1 ELSE 0 END), 0) AS pesanan_selesai,
                   COALESCE(SUM(CASE WHEN status IN ('pending','menunggu_pembayaran','dibayar','diproses','dikirim') THEN 1 ELSE 0 END), 0) AS pesanan_aktif
            FROM pesanan WHERE user_id = %s
        """, (user_id,))
        stats = cursor.fetchone()

        recent_orders = []
        admin_stats = {}

        if user['role'] == 'admin':
            # Data statistik sistem untuk akun Admin
            cursor.execute("SELECT COUNT(*) AS total FROM produk")
            admin_stats['total_produk'] = cursor.fetchone()['total']

            cursor.execute("SELECT COUNT(*) AS total FROM pesanan")
            admin_stats['total_pesanan'] = cursor.fetchone()['total']

            cursor.execute("SELECT COUNT(*) AS total FROM kategori")
            admin_stats['total_kategori'] = cursor.fetchone()['total']

            cursor.execute("SELECT COUNT(*) AS total FROM users WHERE role != 'admin'")
            admin_stats['total_pembeli'] = cursor.fetchone()['total']

            cursor.execute("SELECT COUNT(*) AS total FROM pesanan WHERE status IN ('diproses', 'menunggu_pembayaran')")
            admin_stats['pesanan_perlu_proses'] = cursor.fetchone()['total']
        else:
            # Riwayat pesanan terbaru untuk akun Pembeli
            cursor.execute("""
                SELECT pesanan.*,
                       (SELECT COUNT(*) FROM detail_pesanan WHERE pesanan_id = pesanan.id) AS jumlah_item
                FROM pesanan
                WHERE user_id = %s
                ORDER BY id DESC LIMIT 5
            """, (user_id,))
            recent_orders = cursor.fetchall()

        return render_template(
            'profil.html',
            user=user,
            stats=stats,
            admin_stats=admin_stats,
            recent_orders=recent_orders
        )
    finally:
        cursor.close()
        db.close()

# 12b. Hapus Foto Profil Pengguna (Kembalikan ke Default Avatar)
@app.route('/hapus-foto-profil', methods=['POST', 'GET'])
def hapus_foto_profil():
    if 'user_id' not in session:
        flash("Silakan login terlebih dahulu.", "warning")
        return redirect(url_for('login'))

    user_id = session['user_id']
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT foto_profil FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if user and user.get('foto_profil'):
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], user['foto_profil'])
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
            cursor.execute("UPDATE users SET foto_profil = NULL WHERE id = %s", (user_id,))
            db.commit()
            session['foto_profil'] = ''
            flash("Foto profil berhasil dihapus dan dikembalikan ke avatar default.", "success")
        else:
            flash("Tidak ada foto profil kustom yang tersimpan.", "info")
    finally:
        cursor.close()
        db.close()

    return redirect(url_for('profil'))

# 12c. Ubah Password Pengguna (Keamanan & Autentikasi dengan Werkzeug)
@app.route('/ubah-password', methods=['POST'])
def ubah_password():
    if 'user_id' not in session:
        flash("Silakan login terlebih dahulu untuk mengubah password.", "warning")
        return redirect(url_for('login'))

    user_id = session['user_id']
    password_lama = request.form.get('password_lama', '').strip()
    password_baru = request.form.get('password_baru', '').strip()
    konfirmasi = request.form.get('konfirmasi_password', '').strip()

    if not password_lama or not password_baru or not konfirmasi:
        flash("Semua kolom password wajib diisi!", "warning")
        return redirect(url_for('profil'))

    if len(password_baru) < 4:
        flash("Password baru minimal harus 4 karakter!", "warning")
        return redirect(url_for('profil'))

    if password_baru != konfirmasi:
        flash("Konfirmasi password baru tidak cocok!", "warning")
        return redirect(url_for('profil'))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT password FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            flash("Data akun pengguna tidak ditemukan.", "danger")
            return redirect(url_for('login'))

        is_valid = False
        try:
            is_valid = check_password_hash(user['password'], password_lama)
        except Exception:
            is_valid = (user['password'] == password_lama)

        if not is_valid:
            flash("Password saat ini yang Anda masukkan salah!", "danger")
            return redirect(url_for('profil'))

        new_hash = generate_password_hash(password_baru)
        cursor.execute("UPDATE users SET password = %s WHERE id = %s", (new_hash, user_id))
        db.commit()
        flash("Password akun Anda berhasil diperbarui dengan aman!", "success")
        return redirect(url_for('profil'))
    except Exception as e:
        db.rollback()
        flash(f"Gagal mengubah password: {e}", "danger")
        return redirect(url_for('profil'))
    finally:
        cursor.close()
        db.close()

# 13. Riwayat Pesanan Pembeli (Customer)
@app.route('/pesanan-saya')
def pesanan_saya():
    if 'user_id' not in session:
        flash("Silakan login untuk melihat riwayat pesanan Anda.", "warning")
        return redirect(url_for('login'))

    user_id = session['user_id']
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        # Cek apakah akun pengguna masih ada di database
        cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        if not cursor.fetchone():
            session.clear()
            flash("Sesi login Anda telah kedaluwarsa. Silakan masuk kembali.", "warning")
            return redirect(url_for('login'))

        cursor.execute("SELECT * FROM pesanan WHERE user_id = %s ORDER BY id DESC", (user_id,))
        daftar_pesanan = cursor.fetchall()

        for pesanan in daftar_pesanan:
            query_detail = """
                SELECT detail_pesanan.*, 
                       COALESCE(produk.nama_produk, 'Produk telah dihapus') AS nama_produk, 
                       COALESCE(produk.gambar, 'default.jpg') AS gambar
                FROM detail_pesanan
                LEFT JOIN produk ON detail_pesanan.produk_id = produk.id
                WHERE detail_pesanan.pesanan_id = %s
            """
            cursor.execute(query_detail, (pesanan['id'],))
            pesanan['rincian'] = cursor.fetchall()

        return render_template('pesanan_saya.html', pesanan_list=daftar_pesanan)
    finally:
        cursor.close()
        db.close()

# 13c. Unduh & Cetak Invoice Resmi (PDF / Printable)
@app.route('/invoice/<int:id>')
@app.route('/cetak-invoice/<int:id>')
def cetak_invoice(id):
    if 'user_id' not in session:
        flash("Silakan login untuk melihat invoice pesanan.", "warning")
        return redirect(url_for('login', next=f'/invoice/{id}'))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        query_pesanan = """
            SELECT pesanan.*, 
                   pesanan.tanggal_pesanan AS tanggal,
                   COALESCE(users.nama, 'Pelanggan') AS nama_pembeli,
                   COALESCE(users.email, '-') AS email_pembeli,
                   COALESCE(NULLIF(pesanan.no_hp, ''), users.no_hp, '-') AS telepon_pembeli,
                   COALESCE(NULLIF(pesanan.alamat_pengiriman, ''), users.alamat, '-') AS alamat_tujuan
            FROM pesanan
            LEFT JOIN users ON pesanan.user_id = users.id
            WHERE pesanan.id = %s
        """
        cursor.execute(query_pesanan, (id,))
        pesanan = cursor.fetchone()

        if not pesanan:
            flash("Pesanan tidak ditemukan!", "danger")
            return redirect(url_for('pesanan_saya'))

        # Proteksi hak akses: pembeli hanya bisa lihat pesanan miliknya, admin bisa lihat semua
        if session.get('role') != 'admin' and pesanan['user_id'] != session.get('user_id'):
            flash("Akses ditolak! Anda tidak memiliki izin untuk melihat invoice ini.", "danger")
            return redirect(url_for('pesanan_saya'))

        query_detail = """
            SELECT detail_pesanan.*,
                   COALESCE(produk.nama_produk, 'Produk') AS nama_produk,
                   COALESCE(produk.gambar, 'default.jpg') AS gambar
            FROM detail_pesanan
            LEFT JOIN produk ON detail_pesanan.produk_id = produk.id
            WHERE detail_pesanan.pesanan_id = %s
        """
        cursor.execute(query_detail, (id,))
        items = cursor.fetchall()

        return render_template('invoice.html', pesanan=pesanan, items=items)
    finally:
        cursor.close()
        db.close()

# 13b. Pelacakan Pesanan & Visualisasi Peta (Leaflet.js)
@app.route('/lacak-pesanan/<int:id>')
@app.route('/lacak-pesanan')
@app.route('/tracking/<int:id>')
@app.route('/tracking')
@app.route('/tracking.html')
@app.route('/lacak/<int:id>')
@app.route('/lacak')
@app.route('/track/<int:id>')
@app.route('/track')
def lacak_pesanan(id=None):
    # 1. Ambil ID pesanan dari query string jika tidak ada di path URL
    if id is None:
        raw_id = request.args.get('id') or request.args.get('order_id') or request.args.get('pesanan_id')
        if raw_id:
            try:
                id = int(raw_id)
            except (ValueError, TypeError):
                id = None

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        # 2. Jika ID masih belum ada, coba cari pesanan terakhir milik user atau pesanan terbaru sistem
        if id is None:
            if 'user_id' in session:
                cursor.execute("SELECT id FROM pesanan WHERE user_id = %s ORDER BY id DESC LIMIT 1", (session['user_id'],))
            else:
                cursor.execute("SELECT id FROM pesanan ORDER BY id DESC LIMIT 1")
            row_latest = cursor.fetchone()
            if row_latest:
                id = row_latest['id']
            else:
                flash("Belum ada data pesanan untuk dilacak. Silakan belanja terlebih dahulu.", "info")
                return redirect(url_for('home'))

        # 3. Query data pesanan beserta data pemesan & alamat
        cursor.execute("""
            SELECT pesanan.*, 
                   COALESCE(users.nama, 'Pelanggan') AS nama_pembeli,
                   COALESCE(users.email, '-') AS email_pembeli,
                   COALESCE(NULLIF(pesanan.no_hp, ''), users.no_hp, '-') AS telepon_pembeli,
                   COALESCE(NULLIF(pesanan.alamat_pengiriman, ''), users.alamat, 'Alamat belum diatur') AS alamat_tujuan
            FROM pesanan
            LEFT JOIN users ON pesanan.user_id = users.id
            WHERE pesanan.id = %s
        """, (id,))
        pesanan = cursor.fetchone()
        if not pesanan:
            if request.args.get('format') == 'json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return {'error': f'Pesanan #{id} tidak ditemukan'}, 404
            flash(f"Pesanan #{id} tidak ditemukan!", "warning")
            return redirect(url_for('pesanan_saya' if 'user_id' in session else 'home'))

        # 4. Ambil detail produk yang dipesan
        cursor.execute("""
            SELECT detail_pesanan.*, 
                   COALESCE(produk.nama_produk, 'Produk telah dihapus') AS nama_produk, 
                   COALESCE(produk.gambar, 'default.jpg') AS gambar
            FROM detail_pesanan
            LEFT JOIN produk ON detail_pesanan.produk_id = produk.id
            WHERE detail_pesanan.pesanan_id = %s
        """, (id,))
        pesanan['rincian'] = cursor.fetchall()

        # 5. Format JSON jika dipanggil secara dinamis oleh modal pop-up pelacakan AJAX
        if request.args.get('format') == 'json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {
                'id': pesanan['id'],
                'status': pesanan['status'],
                'tanggal': pesanan['tanggal'].strftime('%d %B %Y, %H:%M') if pesanan.get('tanggal') else '-',
                'metode_pembayaran': pesanan.get('metode_pembayaran') or 'Transfer Bank',
                'nama_pembeli': pesanan.get('nama_pembeli', 'Pelanggan'),
                'telepon_pembeli': pesanan.get('telepon_pembeli', '-'),
                'alamat_tujuan': pesanan.get('alamat_tujuan', '-'),
                'total_harga': float(pesanan['total_harga']),
                'total_harga_format': f"Rp {float(pesanan['total_harga']):,.0f}".replace(",", "."),
                'kurir_lat': float(pesanan.get('kurir_lat') or -6.175392),
                'kurir_lng': float(pesanan.get('kurir_lng') or 106.827153),
                'tujuan_lat': float(pesanan.get('tujuan_lat') or -6.208763),
                'tujuan_lng': float(pesanan.get('tujuan_lng') or 106.845599),
                'rincian': [{
                    'nama_produk': item['nama_produk'],
                    'gambar': item['gambar'],
                    'jumlah': item['jumlah'],
                    'harga_satuan': float(item['harga_satuan']),
                    'subtotal': float(item['subtotal'])
                } for item in pesanan['rincian']]
            }

        return render_template('lacak_pesanan.html', pesanan=pesanan)
    finally:
        cursor.close()
        db.close()

# 13c. Konfirmasi Pembayaran oleh Customer
@app.route('/bayar-pesanan/<int:id>', methods=['GET', 'POST'])
def bayar_pesanan(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT user_id, status FROM pesanan WHERE id = %s", (id,))
        pesanan = cursor.fetchone()
        if pesanan and (session.get('role') == 'admin' or pesanan['user_id'] == session['user_id']):
            cursor.execute("UPDATE pesanan SET status = 'diproses' WHERE id = %s", (id,))
            db.commit()
            flash(f"Pembayaran untuk pesanan #{id} berhasil dikonfirmasi! Pesanan kini sedang dipersiapkan oleh toko.", "success")
        else:
            flash("Pesanan tidak ditemukan atau akses ditolak.", "warning")
    finally:
        cursor.close()
        db.close()
    return redirect(url_for('lacak_pesanan', id=id))

# 13d. Konfirmasi Pesanan Diterima oleh Customer
@app.route('/terima-pesanan/<int:id>', methods=['GET', 'POST'])
def terima_pesanan(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT user_id, status FROM pesanan WHERE id = %s", (id,))
        pesanan = cursor.fetchone()
        if pesanan and (session.get('role') == 'admin' or pesanan['user_id'] == session['user_id']):
            cursor.execute("UPDATE pesanan SET status = 'selesai' WHERE id = %s", (id,))
            db.commit()
            flash(f"Pesanan #{id} telah dikonfirmasi selesai dan diterima. Terima kasih telah berbelanja!", "success")
        else:
            flash("Pesanan tidak ditemukan atau akses ditolak.", "warning")
    finally:
        cursor.close()
        db.close()
    return redirect(url_for('lacak_pesanan', id=id))

# 14. Kelola Pesanan Masuk (Admin)
@app.route('/kelola-pesanan')
@admin_required
def kelola_pesanan():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        query = """
            SELECT pesanan.*, 
                   COALESCE(users.nama, 'Pengguna Tidak Ditemukan') AS nama_pembeli, 
                   COALESCE(users.email, '-') AS email_pembeli,
                   COALESCE(NULLIF(pesanan.no_hp, ''), users.no_hp, '-') AS telepon_pembeli,
                   COALESCE(NULLIF(pesanan.alamat_pengiriman, ''), users.alamat, 'Alamat belum diatur') AS alamat_tujuan
            FROM pesanan
            LEFT JOIN users ON pesanan.user_id = users.id
            ORDER BY pesanan.id DESC
        """
        cursor.execute(query)
        daftar_pesanan = cursor.fetchall()

        for pesanan in daftar_pesanan:
            query_detail = """
                SELECT detail_pesanan.*, 
                       COALESCE(produk.nama_produk, 'Produk telah dihapus') AS nama_produk, 
                       COALESCE(produk.gambar, 'default.jpg') AS gambar
                FROM detail_pesanan
                LEFT JOIN produk ON detail_pesanan.produk_id = produk.id
                WHERE detail_pesanan.pesanan_id = %s
            """
            cursor.execute(query_detail, (pesanan['id'],))
            pesanan['rincian'] = cursor.fetchall()

        return render_template('kelola_pesanan.html', pesanan_list=daftar_pesanan)
    finally:
        cursor.close()
        db.close()

# 15. Update Status Pesanan & Koordinat Kurir (Admin)
@app.route('/update-status/<int:id>', methods=['POST'])
@app.route('/update-status-pesanan/<int:id>', methods=['POST'])
@admin_required
def update_status(id):
    status_baru = request.form.get('status')
    STATUS_VALID = ['menunggu_pembayaran', 'pending', 'dibayar', 'diproses', 'dikirim', 'selesai', 'dibatalkan']

    if status_baru not in STATUS_VALID:
        flash(f"Status '{status_baru}' tidak valid!", "danger")
        return redirect(url_for('kelola_pesanan'))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM pesanan WHERE id = %s", (id,))
        pesanan = cursor.fetchone()
        if not pesanan:
            flash(f"Pesanan #{id} tidak ditemukan!", "warning")
            return redirect(url_for('kelola_pesanan'))

        # Koordinat custom dari form admin jika ada
        kurir_lat = request.form.get('kurir_lat')
        kurir_lng = request.form.get('kurir_lng')

        # Logika posisi kurir otomatis bila status diubah
        if kurir_lat and kurir_lng:
            try:
                k_lat = float(kurir_lat)
                k_lng = float(kurir_lng)
            except ValueError:
                k_lat = float(pesanan['kurir_lat'] or -6.175392)
                k_lng = float(pesanan['kurir_lng'] or 106.827153)
        elif status_baru == 'dikirim':
            # Posisi tengah antara gudang (-6.175392, 106.827153) dan alamat pembeli (-6.208763, 106.845599)
            k_lat = -6.192078
            k_lng = 106.836376
        elif status_baru == 'selesai':
            k_lat = float(pesanan['tujuan_lat'] or -6.208763)
            k_lng = float(pesanan['tujuan_lng'] or 106.845599)
        elif status_baru in ('menunggu_pembayaran', 'pending', 'diproses'):
            k_lat = -6.175392
            k_lng = 106.827153
        else:
            k_lat = float(pesanan['kurir_lat'] or -6.175392)
            k_lng = float(pesanan['kurir_lng'] or 106.827153)

        cursor.execute("""
            UPDATE pesanan 
            SET status = %s, kurir_lat = %s, kurir_lng = %s 
            WHERE id = %s
        """, (status_baru, k_lat, k_lng, id))
        db.commit()
        flash(f"Status pesanan #{id} berhasil diubah menjadi '{status_baru.capitalize()}'!", "success")
    except Exception as e:
        flash(f"Gagal memperbarui status: {e}", "danger")
    finally:
        cursor.close()
        db.close()

    return redirect(url_for('kelola_pesanan'))

# 16. Hapus Pesanan (Khusus Admin)
@app.route('/hapus-pesanan/<int:id>')
@admin_required
def hapus_pesanan(id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM pesanan WHERE id = %s", (id,))
        if not cursor.fetchone():
            flash(f"Pesanan #{id} tidak ditemukan!", "warning")
            return redirect(url_for('kelola_pesanan'))

        # Hapus detail pesanan terlebih dahulu karena foreign key
        cursor.execute("DELETE FROM detail_pesanan WHERE pesanan_id = %s", (id,))
        # Hapus pesanan
        cursor.execute("DELETE FROM pesanan WHERE id = %s", (id,))
        db.commit()
        flash(f"Pesanan #{id} berhasil dihapus dari sistem.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Gagal menghapus pesanan #{id}: {e}", "danger")
    finally:
        cursor.close()
        db.close()

    return redirect(url_for('kelola_pesanan'))

# 17. Kelola Kategori (Khusus Admin)
@app.route('/kelola-kategori', methods=['GET', 'POST'])
@admin_required
def kelola_kategori():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        if request.method == 'POST':
            nama_kategori = request.form.get('nama_kategori', '').strip()
            if not nama_kategori:
                flash("Nama kategori tidak boleh kosong!", "warning")
                return redirect(url_for('kelola_kategori'))

            # Cek apakah nama kategori sudah ada
            cursor.execute("SELECT id FROM kategori WHERE LOWER(nama_kategori) = LOWER(%s)", (nama_kategori,))
            if cursor.fetchone():
                flash(f"Kategori '{nama_kategori}' sudah ada!", "warning")
                return redirect(url_for('kelola_kategori'))

            cursor.execute("INSERT INTO kategori (nama_kategori) VALUES (%s)", (nama_kategori,))
            db.commit()
            flash(f"Kategori '{nama_kategori}' berhasil ditambahkan!", "success")
            return redirect(url_for('kelola_kategori'))

        # GET: Ambil daftar kategori beserta jumlah produknya
        query = """
            SELECT kategori.*, COUNT(produk.id) AS total_produk
            FROM kategori
            LEFT JOIN produk ON kategori.id = produk.kategori_id
            GROUP BY kategori.id, kategori.nama_kategori
            ORDER BY kategori.id ASC
        """
        cursor.execute(query)
        kategori_list = cursor.fetchall()
        return render_template('kelola_kategori.html', kategori_list=kategori_list)
    except Exception as e:
        flash(f"Terjadi kesalahan saat memuat kategori: {e}", "danger")
        return redirect(url_for('home'))
    finally:
        cursor.close()
        db.close()

# 18. Hapus Kategori (Khusus Admin)
@app.route('/hapus-kategori/<int:id>')
@admin_required
def hapus_kategori(id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, nama_kategori FROM kategori WHERE id = %s", (id,))
        kat = cursor.fetchone()
        if not kat:
            flash("Kategori tidak ditemukan!", "warning")
            return redirect(url_for('kelola_kategori'))

        # Cek apakah kategori sedang digunakan oleh produk
        cursor.execute("SELECT COUNT(*) AS total FROM produk WHERE kategori_id = %s", (id,))
        count = cursor.fetchone()['total']
        if count > 0:
            flash(f"Kategori tidak bisa dihapus karena masih digunakan oleh {count} produk! Pindahkan produk ke kategori lain terlebih dahulu.", "warning")
            return redirect(url_for('kelola_kategori'))

        cursor.execute("DELETE FROM kategori WHERE id = %s", (id,))
        db.commit()
        flash("Kategori berhasil dihapus!", "success")
    except Exception as e:
        db.rollback()
        flash(f"Gagal menghapus kategori: {e}", "danger")
    finally:
        cursor.close()
        db.close()

    return redirect(url_for('kelola_kategori'))

if __name__ == '__main__':
    app.run(debug=True)