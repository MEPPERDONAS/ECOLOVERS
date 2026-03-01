import os
import io
import json
import logging
from functools import wraps

import numpy as np
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
import tensorflow as tf
from PIL import Image
# Importamos el preprocesador oficial de ResNet50
from tensorflow.keras.applications.resnet50 import preprocess_input

# â”€â”€ Logging 
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_PATH = os.path.join(BASE_DIR, 'resnet50_garbage_classifier_model.keras')
USERS_PATH = os.path.join(BASE_DIR, 'users.json')
IMG_SIZE   = (384, 384)
LABELS     = ['Cartón', 'Vidrio', 'Metal', 'Papel', 'Plástico', 'Basura General']
ICONS      = ['📦',      '🍶',    '🔩',   '📄',    '🧴',       '🗑️']
GUIDE_SLUGS = ['carton', 'vidrio', 'metal', 'papel', 'plastico', 'basura-general']
GUIDES_PATH = os.path.join(BASE_DIR, 'guides.json')
with open(GUIDES_PATH, 'r', encoding='utf-8') as _f:
    GUIDES = json.load(_f)


app = Flask(__name__, root_path=BASE_DIR)
CORS(app) # Habilitamos CORS para evitar bloqueos del navegador
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-me')

APP_USERNAME = os.environ.get('APP_USERNAME', 'admin')
APP_PASSWORD = os.environ.get('APP_PASSWORD', 'admin123')

def load_users():
    if not os.path.exists(USERS_PATH):
        return {}
    try:
        with open(USERS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_users(users):
    with open(USERS_PATH, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user'):
            if request.method == 'POST' or request.path.startswith('/predict'):
                return jsonify({'error': 'No autenticado'}), 401
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped

model = tf.keras.models.load_model(MODEL_PATH)

@app.route('/')
@login_required
def index():
    return render_template('index.html', model_name=MODEL_PATH, labels=LABELS, user=session.get('user'))

@app.route('/predict', methods=['POST'])
@login_required
def predict():
    if 'image' not in request.files:
        return jsonify({'error': 'No se recibió ninguna imagen (campo: image)'}), 400

    file      = request.files['image']
    filename  = file.filename

    img_bytes = file.read()
    
    # ── Abrir y preprocesar ────────────────────────────────
    try:
        img = Image.open(io.BytesIO(img_bytes))
        img = img.convert('RGB')
        img = img.resize(IMG_SIZE)
        
        # Convertir a array de numpy
        img_array = np.array(img, dtype=np.float32)
        
        # IMPORTANTE: No dividimos por 255.0 manualmente.
        # Expandimos dimensiÃ³n para el batch (1, 384, 384, 3)
        img_array = np.expand_dims(img_array, axis=0)
        
        # Aplicamos el preprocesamiento especÃ­fico de ResNet50
        # Esto ajusta los colores y resta la media de ImageNet
        img_array = preprocess_input(img_array)
        
    except Exception as e:
        log.error(f"âŒ  Error procesando imagen: {e}")
        return jsonify({'error': f'No se pudo procesar la imagen: {e}'}), 400

    preds = model.predict(img_array, verbose=0)[0]
    idx        = int(np.argmax(preds))
    confidence = float(round(float(preds[idx]) * 100, 2))
    log.info(f"ðŸ†  Resultado: '{LABELS[idx]}'  ({confidence}%)")

    all_scores = sorted(
        [
            {
                'label':       LABELS[i],
                'icon':        ICONS[i],
                'slug':        GUIDE_SLUGS[i],
                'probability': float(round(float(preds[i]) * 100, 2))
            }
            for i in range(len(LABELS))
        ],
        key=lambda x: x['probability'],
        reverse=True
    )

    return jsonify({
        'label':      LABELS[idx],
        'icon':       ICONS[idx],
        'slug':       GUIDE_SLUGS[idx],
        'confidence': confidence,
        'all_scores': all_scores
    })

@app.route('/health')
@login_required
def health():
    return jsonify({
        'status':        'ok',
        'input_shape':   str(model.input_shape),
        'labels_count':  len(LABELS)
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
        tips_by_category.append({
            'slug': slug,
            'title': guide_data['title'],
            'tips': guide_data['tips'],
        })
    return render_template('tips.html', tips_by_category=tips_by_category, user=session.get('user'))
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        users = load_users()

        if username == APP_USERNAME and password == APP_PASSWORD:
            session['user'] = username
            next_url = request.args.get('next') or url_for('index')
            if not str(next_url).startswith('/'):
                next_url = url_for('index')
            return redirect(next_url)

        if username in users and check_password_hash(users[username], password):
            session['user'] = username
            next_url = request.args.get('next') or url_for('index')
            if not str(next_url).startswith('/'):
                next_url = url_for('index')
            return redirect(next_url)

        error = 'Usuario o contraseÃ±a incorrectos.'
    return render_template('login.html', error=error)

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        confirm  = request.form.get('confirm') or ''

        if len(username) < 3:
            error = 'El usuario debe tener al menos 3 caracteres.'
        elif len(password) < 6:
            error = 'La contraseÃ±a debe tener al menos 6 caracteres.'
        elif password != confirm:
            error = 'Las contraseÃ±as no coinciden.'
        else:
            users = load_users()
            if username in users or username == APP_USERNAME:
                error = 'Ese usuario ya existe.'
            else:
                users[username] = generate_password_hash(password)
                save_users(users)
                session['user'] = username
                return redirect(url_for('index'))

    return render_template('register.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)