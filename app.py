import os
import io
import json
import sqlite3
import logging
from datetime import datetime, timezone
from functools import wraps

import numpy as np
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
import tensorflow as tf
from PIL import Image
from tensorflow.keras.applications.resnet50 import preprocess_input

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_PATH = os.path.join(BASE_DIR, 'resnet50_garbage_classifier_model.keras')
USERS_PATH = os.path.join(BASE_DIR, 'users.json')
DB_PATH = os.path.join(BASE_DIR, 'ecolovers.db')
IMG_SIZE = (384, 384)
LABELS = ['Cartón', 'Vidrio', 'Metal', 'Papel', 'Plástico', 'Basura General']
ICONS = ['📦', '🍶', '🔩', '📄', '🧴', '🗑️']
GUIDE_SLUGS = ['carton', 'vidrio', 'metal', 'papel', 'plastico', 'basura-general']
GUIDES_PATH = os.path.join(BASE_DIR, 'guides.json')

with open(GUIDES_PATH, 'r', encoding='utf-8') as _f:
    GUIDES = json.load(_f)

app = Flask(__name__, root_path=BASE_DIR)
CORS(app)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-me')

APP_USERNAME = os.environ.get('APP_USERNAME', 'admin')
APP_PASSWORD = os.environ.get('APP_PASSWORD', 'admin123')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        '''
    )
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT,
            predicted_label TEXT NOT NULL,
            predicted_slug TEXT NOT NULL,
            confidence REAL NOT NULL,
            all_scores_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        '''
    )
    cur.execute('CREATE INDEX IF NOT EXISTS idx_analyses_user_created ON analyses(user_id, created_at DESC)')
    conn.commit()

    if os.path.exists(USERS_PATH):
        try:
            with open(USERS_PATH, 'r', encoding='utf-8') as f:
                legacy_users = json.load(f)
            if isinstance(legacy_users, dict):
                for username, password_hash in legacy_users.items():
                    cur.execute('SELECT id FROM users WHERE username = ?', (username,))
                    exists = cur.fetchone()
                    if not exists:
                        cur.execute(
                            'INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)',
                            (username, password_hash, datetime.now(timezone.utc).isoformat())
                        )
                conn.commit()
        except Exception as e:
            log.warning('No se pudo migrar users.json a SQLite: %s', e)

    conn.close()


def get_user_by_username(username):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT id, username, password_hash FROM users WHERE username = ?', (username,))
    row = cur.fetchone()
    conn.close()
    return row


def create_user(username, password):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            'INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)',
            (username, generate_password_hash(password), datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
    finally:
        conn.close()


def ensure_admin_in_db():
    if not get_user_by_username(APP_USERNAME):
        create_user(APP_USERNAME, APP_PASSWORD)


def save_analysis(username, filename, label, slug, confidence, all_scores):
    user = get_user_by_username(username)
    if not user and username == APP_USERNAME:
        ensure_admin_in_db()
        user = get_user_by_username(username)
    if not user:
        return

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        INSERT INTO analyses (user_id, filename, predicted_label, predicted_slug, confidence, all_scores_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            user['id'],
            filename,
            label,
            slug,
            float(confidence),
            json.dumps(all_scores, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
        )
    )
    conn.commit()
    conn.close()


def get_user_analyses(username, limit=50):
    user = get_user_by_username(username)
    if not user and username == APP_USERNAME:
        ensure_admin_in_db()
        user = get_user_by_username(username)
    if not user:
        return []

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT id, filename, predicted_label, predicted_slug, confidence, all_scores_json, created_at
        FROM analyses
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        ''',
        (user['id'], int(limit))
    )
    rows = cur.fetchall()
    conn.close()

    output = []
    for r in rows:
        output.append(
            {
                'id': r['id'],
                'filename': r['filename'],
                'label': r['predicted_label'],
                'slug': r['predicted_slug'],
                'confidence': float(r['confidence']),
                'all_scores': json.loads(r['all_scores_json']),
                'created_at': r['created_at'],
            }
        )
    return output



def compute_user_stats(username):
    user = get_user_by_username(username)
    if not user and username == APP_USERNAME:
        ensure_admin_in_db()
        user = get_user_by_username(username)
    if not user:
        return {
            'total': 0,
            'first_at': None,
            'last_at': None,
            'by_category': [
                {
                    'label': label,
                    'slug': slug,
                    'count': 0,
                    'percentage': 0.0,
                    'first_at': None,
                    'last_at': None,
                }
                for label, slug in zip(LABELS, GUIDE_SLUGS)
            ],
            'timeline': [],
        }

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        '''
        SELECT COUNT(*) AS total, MIN(created_at) AS first_at, MAX(created_at) AS last_at
        FROM analyses
        WHERE user_id = ?
        ''',
        (user['id'],)
    )
    totals = cur.fetchone()
    total = int(totals['total'] or 0)

    cur.execute(
        '''
        SELECT
            predicted_label AS label,
            predicted_slug AS slug,
            COUNT(*) AS count,
            MIN(created_at) AS first_at,
            MAX(created_at) AS last_at
        FROM analyses
        WHERE user_id = ?
        GROUP BY predicted_label, predicted_slug
        ''',
        (user['id'],)
    )
    grouped_rows = cur.fetchall()
    grouped = {
        r['label']: {
            'slug': r['slug'],
            'count': int(r['count']),
            'first_at': r['first_at'],
            'last_at': r['last_at'],
        }
        for r in grouped_rows
    }

    by_category = []
    for label, slug in zip(LABELS, GUIDE_SLUGS):
        item = grouped.get(label, {})
        count = int(item.get('count', 0))
        percentage = round((count * 100.0 / total), 2) if total else 0.0
        by_category.append(
            {
                'label': label,
                'slug': item.get('slug', slug),
                'count': count,
                'percentage': percentage,
                'first_at': item.get('first_at'),
                'last_at': item.get('last_at'),
            }
        )

    cur.execute(
        '''
        SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS count
        FROM analyses
        WHERE user_id = ?
        GROUP BY day
        ORDER BY day DESC
        LIMIT 30
        ''',
        (user['id'],)
    )
    timeline_rows = cur.fetchall()
    timeline = [
        {'date': r['day'], 'count': int(r['count'])}
        for r in reversed(timeline_rows)
    ]

    conn.close()

    return {
        'total': total,
        'first_at': totals['first_at'],
        'last_at': totals['last_at'],
        'by_category': by_category,
        'timeline': timeline,
    }
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user'):
            if request.method == 'POST' or request.path.startswith('/predict'):
                return jsonify({'error': 'No autenticado'}), 401
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)

    return wrapped


init_db()
model = None
MODEL_AVAILABLE = False
MODEL_ERROR = None
try:
    model = tf.keras.models.load_model(MODEL_PATH)
    MODEL_AVAILABLE = True
except Exception as e:
    MODEL_ERROR = str(e)
    log.warning('Modelo no disponible. Se inicia en modo navegacion sin analisis: %s', e)


@app.route('/')
@login_required
def index():
    username = session.get('user')
    stats = compute_user_stats(username)
    return render_template('index.html', model_name=MODEL_PATH, labels=LABELS, user=username, stats=stats, model_available=MODEL_AVAILABLE)


@app.route('/predict', methods=['POST'])
@login_required
def predict():
    if not MODEL_AVAILABLE:
        return jsonify({'error': 'Analisis no disponible en este momento: modelo .keras no cargado.'}), 503

    if 'image' not in request.files:
        return jsonify({'error': 'No se recibió ninguna imagen (campo: image)'}), 400

    file = request.files['image']
    filename = file.filename
    img_bytes = file.read()

    try:
        img = Image.open(io.BytesIO(img_bytes))
        img = img.convert('RGB')
        img = img.resize(IMG_SIZE)
        img_array = np.array(img, dtype=np.float32)
        img_array = np.expand_dims(img_array, axis=0)
        img_array = preprocess_input(img_array)
    except Exception as e:
        log.error('Error procesando imagen: %s', e)
        return jsonify({'error': f'No se pudo procesar la imagen: {e}'}), 400

    preds = model.predict(img_array, verbose=0)[0]
    idx = int(np.argmax(preds))
    confidence = float(round(float(preds[idx]) * 100, 2))

    all_scores = sorted(
        [
            {
                'label': LABELS[i],
                'icon': ICONS[i],
                'slug': GUIDE_SLUGS[i],
                'probability': float(round(float(preds[i]) * 100, 2)),
            }
            for i in range(len(LABELS))
        ],
        key=lambda x: x['probability'],
        reverse=True,
    )

    try:
        save_analysis(
            username=session.get('user'),
            filename=filename,
            label=LABELS[idx],
            slug=GUIDE_SLUGS[idx],
            confidence=confidence,
            all_scores=all_scores,
        )
    except Exception as e:
        log.warning('No se pudo guardar el análisis en DB: %s', e)

    return jsonify(
        {
            'label': LABELS[idx],
            'icon': ICONS[idx],
            'slug': GUIDE_SLUGS[idx],
            'confidence': confidence,
            'all_scores': all_scores,
        }
    )


@app.route('/api/analyses')
@login_required
def analyses_api():
    limit = request.args.get('limit', default=50, type=int)
    limit = max(1, min(limit, 200))
    data = get_user_analyses(session.get('user'), limit=limit)
    return jsonify({'items': data, 'count': len(data)})


@app.route('/health')
@login_required
def health():
    return jsonify({
        'status': 'ok',
        'model_available': MODEL_AVAILABLE,
        'model_error': MODEL_ERROR,
        'input_shape': str(model.input_shape) if MODEL_AVAILABLE else None,
        'labels_count': len(LABELS)
    })


@app.route('/guia/<slug>')
@login_required
def guide(slug):
    guide_data = GUIDES.get(slug)
    if not guide_data:
        return redirect(url_for('index'))
    return render_template('guide.html', guide=guide_data, slug=slug, user=session.get('user'))


@app.route('/lugares')
@login_required
def places():
    places_data = [
        {
            'name': 'Punto Limpio Municipal',
            'desc': 'Recibe carton, papel, vidrio, metal y plastico limpio.',
            'hours': 'Lunes a sabado, 8:00 a.m. - 5:00 p.m.',
        },
        {
            'name': 'Centro de Acopio de Barrio',
            'desc': 'Recepcion de reciclables separados y secos.',
            'hours': 'Lunes a viernes, 9:00 a.m. - 4:00 p.m.',
        },
        {
            'name': 'Jornada Movil de Reciclaje',
            'desc': 'Punto itinerante para residuos aprovechables y especiales.',
            'hours': 'Consulta el calendario local de tu alcaldia.',
        },
    ]
    return render_template('places.html', places=places_data, user=session.get('user'))


@app.route('/tips')
@login_required
def tips():
    tips_by_category = []
    for slug in GUIDE_SLUGS:
        guide_data = GUIDES[slug]
        tips_by_category.append({'slug': slug, 'title': guide_data['title'], 'tips': guide_data['tips']})
    return render_template('tips.html', tips_by_category=tips_by_category, user=session.get('user'))



@app.route('/historial')
@login_required
def history():
    username = session.get('user')
    items = get_user_analyses(username, limit=200)
    stats = compute_user_stats(username)
    return render_template('history.html', items=items, stats=stats, user=username)
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''

        if username == APP_USERNAME and password == APP_PASSWORD:
            ensure_admin_in_db()
            session['user'] = username
            next_url = request.args.get('next') or url_for('index')
            if not str(next_url).startswith('/'):
                next_url = url_for('index')
            return redirect(next_url)

        db_user = get_user_by_username(username)
        if db_user and check_password_hash(db_user['password_hash'], password):
            session['user'] = username
            next_url = request.args.get('next') or url_for('index')
            if not str(next_url).startswith('/'):
                next_url = url_for('index')
            return redirect(next_url)

        error = 'Usuario o contraseña incorrectos.'

    return render_template('login.html', error=error)


@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        confirm = request.form.get('confirm') or ''

        if len(username) < 3:
            error = 'El usuario debe tener al menos 3 caracteres.'
        elif len(password) < 6:
            error = 'La contraseña debe tener al menos 6 caracteres.'
        elif password != confirm:
            error = 'Las contraseñas no coinciden.'
        elif username == APP_USERNAME:
            error = 'Ese usuario ya existe.'
        elif get_user_by_username(username):
            error = 'Ese usuario ya existe.'
        else:
            try:
                create_user(username, password)
                session['user'] = username
                return redirect(url_for('index'))
            except sqlite3.IntegrityError:
                error = 'Ese usuario ya existe.'

    return render_template('register.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)






