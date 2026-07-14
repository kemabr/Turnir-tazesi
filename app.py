import os
import random
import string
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, g, session, flash
import requests

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'uc-market-gizli-anahtar-2026')

# Railway'de kalıcı veritabanı - proje dizininde
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'ucmarket.db')

# Telegram Bot
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')

# Admin şifresi
ADMIN_SIFRE = os.environ.get('ADMIN_SIFRE', 'admin2026')

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    """Veritabanını başlat - tablolar yoksa oluştur"""
    try:
        # Doğrudan bağlantı aç (app context olmadan da çalışsın)
        db = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        
        cursor = db.cursor()
        
        # Katilimcilar tablosu
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS katilimcilar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referans_kodu TEXT UNIQUE NOT NULL,
                ad TEXT NOT NULL,
                pubg_id TEXT NOT NULL UNIQUE,
                telefon TEXT NOT NULL,
                ulasim TEXT NOT NULL,
                takim_kodu TEXT,
                takim_lideri INTEGER DEFAULT 0,
                odeme_durumu INTEGER DEFAULT 0,
                admin_onay INTEGER DEFAULT 0,
                kayit_tarihi TEXT NOT NULL,
                odeme_tarihi TEXT,
                onay_tarihi TEXT
            )
        """)
        
        # Takimlar tablosu
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS takimlar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                takim_kodu TEXT UNIQUE NOT NULL,
                takim_adi TEXT,
                lider_referans TEXT NOT NULL,
                uye1_referans TEXT,
                uye2_referans TEXT,
                uye3_referans TEXT,
                durum INTEGER DEFAULT 0
            )
        """)
        
        # Admins tablosu
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                created_at TEXT
            )
        """)
        
        # Varsayılan admin
        cursor.execute("SELECT 1 FROM admins WHERE username = 'admin'")
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO admins (username, password, created_at) VALUES (?, ?, ?)",
                ('admin', ADMIN_SIFRE, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )
        
        db.commit()
        db.close()
        print("✅ Veritabanı başlatıldı:", DATABASE)
        return True
    except Exception as e:
        print("❌ Veritabanı hatası:", str(e))
        return False

def generate_ref_code():
    while True:
        code = 'UC-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        db = get_db()
        existing = db.execute('SELECT 1 FROM katilimcilar WHERE referans_kodu = ?', (code,)).fetchone()
        if not existing:
            return code

def send_telegram_message(message):
    if not BOT_TOKEN or not CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except:
        return False

def get_stats():
    db = get_db()
    try:
        stats = db.execute("""
            SELECT 
                COUNT(*) as toplam,
                SUM(CASE WHEN odeme_durumu = 1 THEN 1 ELSE 0 END) as odeme_yapan,
                SUM(CASE WHEN admin_onay = 1 THEN 1 ELSE 0 END) as onaylanan
            FROM katilimcilar
        """).fetchone()
        return {
            'toplam': stats['toplam'] or 0,
            'odeme_yapan': stats['odeme_yapan'] or 0,
            'onaylanan': stats['onaylanan'] or 0
        }
    except sqlite3.OperationalError:
        # Tablo yoksa init et ve tekrar dene
        init_db()
        return {'toplam': 0, 'odeme_yapan': 0, 'onaylanan': 0}

# ===================== MIDDLEWARE =====================
@app.before_request
def ensure_db():
    """Her istekten önce tabloların var olduğundan emin ol"""
    try:
        db = get_db()
        db.execute("SELECT 1 FROM katilimcilar LIMIT 1")
    except sqlite3.OperationalError:
        init_db()

# ===================== AUTH =====================
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_ref' not in session:
            return redirect(url_for('giris'))
        return f(*args, **kwargs)
    return decorated_function

# ===================== ROUTES =====================

@app.route('/')
def index():
    stats = get_stats()
    user = None
    if 'user_ref' in session:
        db = get_db()
        user = db.execute('SELECT * FROM katilimcilar WHERE referans_kodu = ?', 
                         (session['user_ref'],)).fetchone()
    return render_template('index.html', stats=stats, user=user)

@app.route('/giris')
def giris():
    if 'user_ref' in session:
        return redirect(url_for('profil', ref_code=session['user_ref']))
    return render_template('giris.html')

@app.route('/api/giris', methods=['POST'])
def api_giris():
    data = request.get_json()
    ref_code = data.get('referans_kodu', '').strip().upper()
    
    if not ref_code:
        return jsonify({'success': False, 'message': 'Referans kody giriziň!'})
    
    db = get_db()
    katilimci = db.execute('SELECT * FROM katilimcilar WHERE referans_kodu = ?', (ref_code,)).fetchone()
    
    if not katilimci:
        return jsonify({'success': False, 'message': 'Nädogry referans kody!'})
    
    session['user_ref'] = ref_code
    return jsonify({'success': True, 'message': 'Giriş üstünlikli!', 'redirect': '/profil/' + ref_code})

@app.route('/cikis')
def cikis():
    session.pop('user_ref', None)
    return redirect(url_for('index'))

@app.route('/kayit')
def kayit():
    if 'user_ref' in session:
        return redirect(url_for('profil', ref_code=session['user_ref']))
    return render_template('kayit.html')

@app.route('/api/kayit-ol', methods=['POST'])
def api_kayit_ol():
    data = request.get_json()
    ad = data.get('ad', '').strip()
    pubg_id = data.get('pubg_id', '').strip()
    telefon = data.get('telefon', '').strip()
    ulasim = data.get('ulasim', '').strip()

    if not all([ad, pubg_id, telefon, ulasim]):
        return jsonify({'success': False, 'message': 'Ähli maglumatlary dolduryň!'})

    db = get_db()
    
    # PUBG ID benzersiz mi kontrol et
    existing_pubg = db.execute('SELECT 1 FROM katilimcilar WHERE pubg_id = ?', (pubg_id,)).fetchone()
    if existing_pubg:
        return jsonify({'success': False, 'message': 'Bu PUBG ID eýýam hasaba alynan!'})

    ref_code = generate_ref_code()
    kayit_tarihi = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    db.execute("""
        INSERT INTO katilimcilar (referans_kodu, ad, pubg_id, telefon, ulasim, kayit_tarihi)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (ref_code, ad, pubg_id, telefon, ulasim, kayit_tarihi))
    db.commit()

    session['user_ref'] = ref_code

    msg = f"""🎮 <b>TÄZE KATYLYJY!</b>

👤 Ady: <b>{ad}</b>
🆔 PUBG ID: <code>{pubg_id}</code>
📞 Telefon: <code>{telefon}</code>
💬 Ulaşmak: {ulasim}
🔑 Referans kody: <code>{ref_code}</code>
📅 Sene: {kayit_tarihi}

⏳ <b>Töleg garaşylýar...</b>"""
    send_telegram_message(msg)

    return jsonify({
        'success': True,
        'referans_kodu': ref_code,
        'message': 'Üstünlikli hasaba alyndyňyz!'
    })

@app.route('/odeme/<ref_code>')
@login_required
def odeme(ref_code):
    db = get_db()
    katilimci = db.execute('SELECT * FROM katilimcilar WHERE referans_kodu = ?', (ref_code,)).fetchone()
    if not katilimci:
        return redirect(url_for('index'))
    if katilimci['referans_kodu'] != session.get('user_ref'):
        return redirect(url_for('index'))
    return render_template('odeme.html', katilimci=katilimci)

@app.route('/api/odeme-yapildi', methods=['POST'])
@login_required
def api_odeme_yapildi():
    data = request.get_json()
    ref_code = data.get('referans_kodu', '')
    
    if ref_code != session.get('user_ref'):
        return jsonify({'success': False, 'message': 'Rugsat ýok!'})

    db = get_db()
    katilimci = db.execute('SELECT * FROM katilimcilar WHERE referans_kodu = ?', (ref_code,)).fetchone()
    if not katilimci:
        return jsonify({'success': False, 'message': 'Katylyjy tapylmady!'})

    odeme_tarihi = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    db.execute("UPDATE katilimcilar SET odeme_durumu = 1, odeme_tarihi = ? WHERE referans_kodu = ?",
               (odeme_tarihi, ref_code))
    db.commit()

    msg = f"""💰 <b>TÖLEG BILDIRIMI!</b>

👤 Ady: <b>{katilimci['ad']}</b>
🔑 Referans kody: <code>{ref_code}</code>
📞 Telefon: <code>{katilimci['telefon']}</code>
📅 Töleg senesi: {odeme_tarihi}

✅ <b>Admin tassyklamasy garaşylýar!</b>"""
    send_telegram_message(msg)

    return jsonify({'success': True, 'message': 'Töleg bildirimi ugradyldy!'})

@app.route('/profil/<ref_code>')
@login_required
def profil(ref_code):
    if ref_code != session.get('user_ref'):
        return redirect(url_for('profil', ref_code=session['user_ref']))
    
    db = get_db()
    katilimci = db.execute("""
        SELECT k.*, t.takim_adi, t.takim_kodu as t_kod
        FROM katilimcilar k
        LEFT JOIN takimlar t ON k.takim_kodu = t.takim_kodu
        WHERE k.referans_kodu = ?
    """, (ref_code,)).fetchone()

    if not katilimci:
        return redirect(url_for('index'))

    takim_arkadaslari = []
    if katilimci['takim_kodu']:
        takim_arkadaslari = db.execute("""
            SELECT ad, pubg_id, referans_kodu, admin_onay 
            FROM katilimcilar 
            WHERE takim_kodu = ? AND referans_kodu != ?
        """, (katilimci['takim_kodu'], ref_code)).fetchall()

    return render_template('profil.html', katilimci=katilimci, takim_arkadaslari=takim_arkadaslari)

@app.route('/takim/<ref_code>')
@login_required
def takim(ref_code):
    if ref_code != session.get('user_ref'):
        return redirect(url_for('takim', ref_code=session['user_ref']))
    
    db = get_db()
    katilimci = db.execute('SELECT * FROM katilimcilar WHERE referans_kodu = ?', (ref_code,)).fetchone()
    if not katilimci:
        return redirect(url_for('index'))
    return render_template('takim.html', katilimci=katilimci)

@app.route('/api/takim-olustur', methods=['POST'])
@login_required
def api_takim_olustur():
    data = request.get_json()
    lider_ref = data.get('lider_ref', '')
    takim_adi = data.get('takim_adi', '').strip()

    if lider_ref != session.get('user_ref'):
        return jsonify({'success': False, 'message': 'Rugsat ýok!'})

    db = get_db()
    lider = db.execute('SELECT * FROM katilimcilar WHERE referans_kodu = ?', (lider_ref,)).fetchone()
    if not lider:
        return jsonify({'success': False, 'message': 'Katylyjy tapylmady!'})
    if lider['takim_kodu']:
        return jsonify({'success': False, 'message': 'Siz eýýam topar bolduňyz!'})

    takim_kodu = 'TEAM-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    db.execute("INSERT INTO takimlar (takim_kodu, takim_adi, lider_referans) VALUES (?, ?, ?)",
               (takim_kodu, takim_adi, lider_ref))
    db.execute("UPDATE katilimcilar SET takim_kodu = ?, takim_lideri = 1 WHERE referans_kodu = ?",
               (takim_kodu, lider_ref))
    db.commit()

    return jsonify({'success': True, 'takim_kodu': takim_kodu, 'message': 'Topar üstünlikli döredildi!'})

@app.route('/api/takima-katil', methods=['POST'])
@login_required
def api_takima_katil():
    data = request.get_json()
    uye_ref = data.get('uye_ref', '')
    takim_kodu = data.get('takim_kodu', '').strip().upper()

    if uye_ref != session.get('user_ref'):
        return jsonify({'success': False, 'message': 'Rugsat ýok!'})

    db = get_db()
    uye = db.execute('SELECT * FROM katilimcilar WHERE referans_kodu = ?', (uye_ref,)).fetchone()
    if not uye:
        return jsonify({'success': False, 'message': 'Katylyjy tapylmady!'})
    if uye['takim_kodu']:
        return jsonify({'success': False, 'message': 'Siz eýýam topar bolduňyz!'})

    takim = db.execute('SELECT * FROM takimlar WHERE takim_kodu = ?', (takim_kodu,)).fetchone()
    if not takim:
        return jsonify({'success': False, 'message': 'Topar kody nädogry!'})

    uye_sayisi = db.execute('SELECT COUNT(*) as say FROM katilimcilar WHERE takim_kodu = ?', 
                           (takim_kodu,)).fetchone()['say']
    if uye_sayisi >= 4:
        return jsonify({'success': False, 'message': 'Bu topar eýýam doly (4 kişi)!'})

    db.execute("UPDATE katilimcilar SET takim_kodu = ? WHERE referans_kodu = ?", (takim_kodu, uye_ref))
    if not takim['uye1_referans']:
        db.execute('UPDATE takimlar SET uye1_referans = ? WHERE takim_kodu = ?', (uye_ref, takim_kodu))
    elif not takim['uye2_referans']:
        db.execute('UPDATE takimlar SET uye2_referans = ? WHERE takim_kodu = ?', (uye_ref, takim_kodu))
    elif not takim['uye3_referans']:
        db.execute('UPDATE takimlar SET uye3_referans = ? WHERE takim_kodu = ?', (uye_ref, takim_kodu))
    db.commit()

    msg = f"""👥 <b>TOPARA TÄZE AGZA!</b>

Topar: <b>{takim['takim_adi']}</b>
Kody: <code>{takim_kodu}</code>

Täze agza: <b>{uye['ad']}</b>
PUBG ID: <code>{uye['pubg_id']}</code>

Topardaky agza sany: {uye_sayisi + 1}/4"""
    send_telegram_message(msg)

    return jsonify({'success': True, 'message': f'Topara üstünlikli goşuldyňyz! ({uye_sayisi + 1}/4)'})

# ===================== KATEGORIYALAR =====================
@app.route('/duzgunler')
def duzgunler():
    stats = get_stats()
    user = None
    if 'user_ref' in session:
        db = get_db()
        user = db.execute('SELECT * FROM katilimcilar WHERE referans_kodu = ?', 
                         (session['user_ref'],)).fetchone()
    return render_template('duzgunler.html', stats=stats, user=user)

@app.route('/bayraklar')
def bayraklar():
    stats = get_stats()
    user = None
    if 'user_ref' in session:
        db = get_db()
        user = db.execute('SELECT * FROM katilimcilar WHERE referans_kodu = ?', 
                         (session['user_ref'],)).fetchone()
    return render_template('bayraklar.html', stats=stats, user=user)

@app.route('/turnir-maglumatlary')
def turnir_maglumatlary():
    stats = get_stats()
    user = None
    if 'user_ref' in session:
        db = get_db()
        user = db.execute('SELECT * FROM katilimcilar WHERE referans_kodu = ?', 
                         (session['user_ref'],)).fetchone()
    return render_template('turnir_maglumatlary.html', stats=stats, user=user)

# ===================== ADMIN PANEL =====================
@app.route('/admin')
def admin_login():
    return render_template('admin_login.html')

@app.route('/admin/giris', methods=['POST'])
def admin_giris():
    username = request.form.get('username', '')
    password = request.form.get('password', '')
    
    db = get_db()
    admin = db.execute('SELECT * FROM admins WHERE username = ? AND password = ?', 
                      (username, password)).fetchone()
    
    if admin:
        session['admin'] = True
        return redirect(url_for('admin_panel'))
    flash('Nädogry ulanyjy ady ýa-da parol!')
    return redirect(url_for('admin_login'))

@app.route('/admin/panel')
def admin_panel():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    db = get_db()
    stats = db.execute("""
        SELECT 
            COUNT(*) as toplam,
            SUM(CASE WHEN odeme_durumu = 1 THEN 1 ELSE 0 END) as odeme_yapan,
            SUM(CASE WHEN admin_onay = 1 THEN 1 ELSE 0 END) as onaylanan
        FROM katilimcilar
    """).fetchone()

    katilimcilar = db.execute("""
        SELECT k.*, t.takim_adi 
        FROM katilimcilar k
        LEFT JOIN takimlar t ON k.takim_kodu = t.takim_kodu
        ORDER BY k.kayit_tarihi DESC
    """).fetchall()

    takimlar = db.execute("""
        SELECT t.*, k.ad as lider_ady
        FROM takimlar t
        JOIN katilimcilar k ON t.lider_referans = k.referans_kodu
        ORDER BY t.id DESC
    """).fetchall()

    return render_template('admin_panel.html', stats=stats, katilimcilar=katilimcilar, takimlar=takimlar)

@app.route('/api/admin-onayla', methods=['POST'])
def api_admin_onayla():
    if not session.get('admin'):
        return jsonify({'success': False, 'message': 'Rugsat ýok!'})
    
    data = request.get_json()
    ref_code = data.get('referans_kodu', '')

    db = get_db()
    katilimci = db.execute('SELECT * FROM katilimcilar WHERE referans_kodu = ?', (ref_code,)).fetchone()
    if not katilimci:
        return jsonify({'success': False, 'message': 'Katylyjy tapylmady!'})

    onay_tarihi = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    db.execute("UPDATE katilimcilar SET admin_onay = 1, onay_tarihi = ? WHERE referans_kodu = ?",
               (onay_tarihi, ref_code))
    db.commit()

    msg = f"""✅ <b>TASSYKLANDY!</b>

👤 Ady: <b>{katilimci['ad']}</b>
🔑 Referans kody: <code>{ref_code}</code>
📅 Tassyklama senesi: {onay_tarihi}

✅ <b>Katylyjy üstünlikli tassyklandy!</b>"""
    send_telegram_message(msg)

    return jsonify({'success': True, 'message': 'Katylyjy tassyklandy!'})

@app.route('/api/admin-reddet', methods=['POST'])
def api_admin_reddet():
    if not session.get('admin'):
        return jsonify({'success': False, 'message': 'Rugsat ýok!'})
    
    data = request.get_json()
    ref_code = data.get('referans_kodu', '')

    db = get_db()
    db.execute('UPDATE katilimcilar SET admin_onay = 2 WHERE referans_kodu = ?', (ref_code,))
    db.commit()
    return jsonify({'success': True, 'message': 'Katylyjy ret edildi!'})

@app.route('/api/admin-sil', methods=['POST'])
def api_admin_sil():
    if not session.get('admin'):
        return jsonify({'success': False, 'message': 'Rugsat ýok!'})
    
    data = request.get_json()
    ref_code = data.get('referans_kodu', '')

    db = get_db()
    katilimci = db.execute('SELECT * FROM katilimcilar WHERE referans_kodu = ?', (ref_code,)).fetchone()
    if not katilimci:
        return jsonify({'success': False, 'message': 'Katylyjy tapylmady!'})
    
    # Takım lideri ise takımı da sil
    if katilimci['takim_lideri'] == 1 and katilimci['takim_kodu']:
        db.execute('DELETE FROM takimlar WHERE takim_kodu = ?', (katilimci['takim_kodu'],))
        db.execute('UPDATE katilimcilar SET takim_kodu = NULL, takim_lideri = 0 WHERE takim_kodu = ?',
                   (katilimci['takim_kodu'],))
    
    db.execute(
