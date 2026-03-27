import os
import io
import json
import sqlite3
import logging
from datetime import datetime, timezone
from functools import wraps
from datetime import timedelta

from dotenv import load_dotenv
import numpy as np
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS

# --- IA: GEMINI (nuevo SDK google-genai) ---
from google import genai

# Cargar variables de entorno 
load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
genai_client = genai.Client(api_key=GOOGLE_API_KEY)

app = Flask(__name__, root_path=BASE_DIR)
CORS(app)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-change-me')

# Rutas de Archivos
DB_PATH = os.path.join(BASE_DIR, 'ecolovers.db')
GUIDES_PATH = os.path.join(BASE_DIR, 'guides.json')

# Configuración de Etiquetas
LABELS = ['Cartón', 'Vidrio', 'Metal', 'Papel', 'Plástico', 'Basura General']
ICONS = ['📦', '🍶', '🔩', '📄', '🧴', '🗑️']
GUIDE_SLUGS = ['carton', 'vidrio', 'metal', 'papel', 'plastico', 'basura-general']

# Credenciales de administrador por defecto
APP_USERNAME = os.getenv('APP_USERNAME', 'admin')
APP_PASSWORD = os.getenv('APP_PASSWORD', 'admin123')

# Cargar Guías
if os.path.exists(GUIDES_PATH):
    with open(GUIDES_PATH, 'r', encoding='utf-8') as _f:
        GUIDES = json.load(_f)
else:
    GUIDES = {}

# --- FUNCIONES DE BASE DE DATOS ---

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        filename TEXT,
        predicted_label TEXT NOT NULL,
        predicted_slug TEXT NOT NULL,
        confidence REAL NOT NULL,
        all_scores_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id))''')
    conn.commit()
    conn.close()

def get_user_by_username(username):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT id, username, password_hash FROM users WHERE username = ?', (username,))
    row = cur.fetchone()
    conn.close()
    return row

def save_analysis(username, filename, label, slug, confidence, all_scores):
    user = get_user_by_username(username)
    if not user: return
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''INSERT INTO analyses (user_id, filename, predicted_label, predicted_slug, confidence, all_scores_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (user['id'], filename, label, slug, float(confidence), json.dumps(all_scores, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()

def compute_user_stats(username):
    user = get_user_by_username(username)
    if not user: return {'total': 0, 'by_category': []}
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) as total, MIN(created_at) as first_at, MAX(created_at) as last_at FROM analyses WHERE user_id = ?', (user['id'],))
    res = cur.fetchone()
    total = res['total'] or 0
    
    by_category = []
    for label, slug in zip(LABELS, GUIDE_SLUGS):
        cur.execute('SELECT COUNT(*) FROM analyses WHERE user_id = ? AND predicted_label = ?', (user['id'], label))
        count = cur.fetchone()[0]
        perc = round((count * 100 / total), 2) if total > 0 else 0
        by_category.append({'label': label, 'slug': slug, 'count': count, 'percentage': perc})
    
    conn.close()
    return {'total': total, 'by_category': by_category, 'first_at': res['first_at'], 'last_at': res['last_at']}

def get_user_analyses(username, limit=50):
    user = get_user_by_username(username)
    if not user: return []
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM analyses WHERE user_id = ? ORDER BY id DESC LIMIT ?', (user['id'], limit))
    rows = cur.fetchall()
    conn.close()
    return [{'id': r['id'], 'filename': r['filename'], 'label': r['predicted_label'], 'slug': r['predicted_slug'], 
             'confidence': r['confidence'], 'all_scores': json.loads(r['all_scores_json']), 'created_at': r['created_at']} for r in rows]

#RACHAS

def compute_user_stats(username):
    user = get_user_by_username(username)
    if not user: return {'total': 0, 'by_category': []}
    
    conn = get_db()
    cur = conn.cursor()
    
    # 1. Definir 'res' y 'total' (Esto faltaba)
    cur.execute('''SELECT COUNT(*) as total, 
                          MIN(created_at) as first_at, 
                          MAX(created_at) as last_at 
                   FROM analyses WHERE user_id = ?''', (user['id'],))
    res = cur.fetchone() #
    total = res['total'] or 0 #
    
    # 2. Definir 'by_category' (Esto también faltaba)
    by_category = []
    for label, slug in zip(LABELS, GUIDE_SLUGS):
        cur.execute('SELECT COUNT(*) FROM analyses WHERE user_id = ? AND predicted_label = ?', (user['id'], label))
        count = cur.fetchone()[0]
        perc = round((count * 100 / total), 2) if total > 0 else 0
        by_category.append({'label': label, 'slug': slug, 'count': count, 'percentage': perc})
    
    # 3. Lógica de la racha semanal
    hoy = datetime.now(timezone.utc).date()
    lunes = hoy - timedelta(days=hoy.weekday())
    
    semana_stats = []
    nombres_dias = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
    
    for i in range(7):
        fecha_dia = lunes + timedelta(days=i)
        cur.execute('''SELECT COUNT(*) FROM analyses 
                       WHERE user_id = ? AND date(created_at) = date(?)''', 
                    (user['id'], fecha_dia.isoformat()))
        count = cur.fetchone()[0]
        
        semana_stats.append({
            'nombre': nombres_dias[i],
            'activo': count > 0,
            'es_hoy': fecha_dia == hoy
        })
    
    conn.close()
    
    # Devolver todo correctamente definido
    return {
        'total': total,
        'by_category': by_category,
        'first_at': res['first_at'], #
        'last_at': res['last_at'],   #
        'semana': semana_stats
    }
# --- DECORADORES ---

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user'):
            if request.path.startswith('/predict'): return jsonify({'error': 'No autenticado'}), 401
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped

# --- RUTAS DE LA APLICACIÓN ---

init_db()

@app.route('/')
@login_required
def index():
    username = session.get('user')
    stats = compute_user_stats(username)
    return render_template('index.html', labels=LABELS, user=username, stats=stats, model_available=True)

@app.route('/predict', methods=['POST'])
@login_required
def predict():
    if 'image' not in request.files: return jsonify({'error': 'No image'}), 400
    file = request.files['image']
    img_bytes = file.read()
    
    try:
        import base64
        img_b64 = base64.standard_b64encode(img_bytes).decode('utf-8')

        prompt = f"""
        Analiza esta imagen de un residuo y clasifícala en una de estas categorías: {', '.join(LABELS)}.
        Responde estrictamente en formato JSON con solo estos dos campos:
        {{"label": "nombre_de_la_categoria", "confidence": 0.95}}
        """

        response = genai_client.models.generate_content(
            model='gemini-2.0-flash',
            contents=[
                prompt,
                {'inline_data': {'mime_type': 'image/jpeg', 'data': img_b64}}
            ]
        )
        
        # Limpiar la respuesta de posibles bloques de código Markdown
        res_text = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(res_text)
        
        label = data.get('label', 'Basura General')
        if label not in LABELS: label = 'Basura General'
        idx = LABELS.index(label)
        conf = data.get('confidence', 0.8) * 100

        all_scores = [{'label': LABELS[i], 'icon': ICONS[i], 'slug': GUIDE_SLUGS[i], 
                       'probability': conf if i == idx else (100-conf)/5} for i in range(len(LABELS))]

        save_analysis(session.get('user'), file.filename, label, GUIDE_SLUGS[idx], conf, all_scores)
        return jsonify({
            'label': label, 
            'icon': ICONS[idx], 
            'slug': GUIDE_SLUGS[idx], 
            'confidence': round(conf, 2), 
            'all_scores': all_scores
        })
    except Exception as e:
        log.error(f"Error IA: {e}")
        # Si el error es de modelo no encontrado, intentamos dar una pista
        return jsonify({'error': 'El modelo de IA no está respondiendo. Verifica tu API Key o el nombre del modelo.'}), 500

@app.route('/historial')
@login_required
def history():
    username = session.get('user')
    items = get_user_analyses(username, limit=100)
    stats = compute_user_stats(username)
    return render_template('history.html', items=items, stats=stats, user=username)

# --- NUEVA RUTA: REGISTER (Soluciona tu error) ---
@app.route('/registro', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password')
        
        if get_user_by_username(username):
            return render_template('register.html', error="El usuario ya existe")
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute('INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)',
                    (username, generate_password_hash(password), datetime.now(timezone.utc).isoformat()))
        conn.commit()
        conn.close()
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/guia/<slug>')
@login_required
def guide(slug):
    guide_data = GUIDES.get(slug)
    if not guide_data: return redirect(url_for('index'))
    return render_template('guide.html', guide=guide_data, slug=slug, user=session.get('user'))

@app.route('/lugares')
@login_required
def places():
    places_data = [
        {'name': 'Punto Limpio Municipal', 'desc': 'Recibe todo tipo de reciclables.', 'hours': '8:00 - 17:00'},
        {'name': 'Centro de Acopio Barrio', 'desc': 'Papel y plástico seco.', 'hours': '9:00 - 16:00'}
    ]
    return render_template('places.html', places=places_data, user=session.get('user'))

@app.route('/tips')
@login_required
def tips():
    tips_list = [{'slug': s, 'title': GUIDES[s]['title'], 'tips': GUIDES[s]['tips']} for s in GUIDE_SLUGS if s in GUIDES]
    return render_template('tips.html', tips_by_category=tips_list, user=session.get('user'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user, pwd = request.form.get('username'), request.form.get('password')
        if user == APP_USERNAME and pwd == APP_PASSWORD:
            session['user'] = user
            return redirect(url_for('index'))
        u = get_user_by_username(user)
        if u and check_password_hash(u['password_hash'], pwd):
            session['user'] = user
            return redirect(url_for('index'))
        return render_template('login.html', error="Credenciales incorrectas")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)