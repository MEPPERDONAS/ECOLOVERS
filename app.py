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
GUIDES = {
    'carton': {
        'title': 'Cartón',
        'bin': 'Caneca blanca (aprovechables limpios y secos).',
        'how_to': [
            'Dobla y compacta cajas para ahorrar espacio.',
            'Retira cintas plásticas y restos de comida.',
            'Mantén el material seco antes de depositarlo.',
        ],
        'tips': [
            'Separa cartón corrugado de otros residuos.',
            'Si está húmedo o con grasa, no va en reciclaje.',
            'Usa bolsas o contenedores secos para almacenarlo.',
        ],
        'dont': [
            'No mezclar con servilletas usadas o papel sanitario.',
            'No botar cartón con aceite, grasa o moho.',
            'No incluir cartón plastificado muy contaminado.',
        ],
    },
    'vidrio': {
        'title': 'Vidrio',
        'bin': 'Caneca blanca (aprovechables), limpio y sin tapas.',
        'how_to': [
            'Enjuaga botellas y frascos para quitar residuos.',
            'Separa tapas metálicas o plásticas.',
            'Deposita con cuidado para evitar rupturas.',
        ],
        'tips': [
            'Agrupa por tipo: botellas y frascos de alimentos.',
            'Si se rompe, envuelve y marca como cortopunzante.',
            'Prioriza reuso de frascos antes de reciclar.',
        ],
        'dont': [
            'No mezclar vidrio con cerámica o espejo.',
            'No depositar bombillos comunes o tubos fluorescentes.',
            'No enviar vidrio contaminado con quí­micos peligrosos.',
        ],
    },
    'metal': {
        'title': 'Metal',
        'bin': 'Caneca blanca, limpio y sin residuos orgánicos.',
        'how_to': [
            'Enjuaga latas de bebidas o conservas.',
            'Aplasta latas para reducir volumen.',
            'Separa piezas metálicas de otros materiales.',
        ],
        'tips': [
            'Junta aluminio y hojalata en un mismo flujo limpio.',
            'Revisa bordes filosos antes de manipular.',
            'Entrega chatarra grande a gestores autorizados.',
        ],
        'dont': [
            'No mezclar con residuos de comida.',
            'No incluir aerosoles con contenido restante.',
            'No botar pilas o baterías como si fueran metal común.',
        ],
    },
    'papel': {
        'title': 'Papel',
        'bin': 'Caneca blanca, papel limpio y seco.',
        'how_to': [
            'Separa hojas, periódicos y cuadernos sin espiral.',
            'Mantén el papel lejos de humedad.',
            'Retira plásticos o grapas cuando sea posible.',
        ],
        'tips': [
            'Reutiliza hojas por ambas caras antes de reciclar.',
            'Compacta papel en paquetes para facilitar recolección.',
            'Clasifica papel blanco y mixto si tu operador lo pide.',
        ],
        'dont': [
            'No incluir papel sanitario o servilletas usadas.',
            'No reciclar papel con grasa o restos de comida.',
            'No mezclar con papel plastificado contaminado.',
        ],
    },
    'plastico': {
        'title': 'Plástico',
        'bin': 'Caneca blanca, envases limpios y secos.',
        'how_to': [
            'Enjuaga envases y deja escurrir.',
            'Aplasta botellas PET y cierra con tapa.',
            'Separa plásticos flexibles si el operador lo exige.',
        ],
        'tips': [
            'Prioriza reducir y reutilizar antes de reciclar.',
            'Identifica código de resina cuando sea visible.',
            'Acumula en bolsa limpia para evitar contaminación.',
        ],
        'dont': [
            'No mezclar con empaques sucios de comida.',
            'No incluir icopor sucio o residuos peligrosos.',
            'No quemar plásticos a cielo abierto.',
        ],
    },
    'basura-general': {
        'title': 'Basura General',
        'bin': 'Caneca negra (no aprovechables).',
        'how_to': [
            'Deposita residuos que no se pueden reciclar.',
            'Usa bolsas cerradas para evitar derrames.',
            'Separa siempre de reciclables y orgÃ¡nicos.',
        ],
        'tips': [
            'Revisa antes si algÃºn material puede recuperarse.',
            'Reduce el volumen de residuos en casa.',
            'Gestiona aparte residuos peligrosos y especiales.',
        ],
        'dont': [
            'No mezclar reciclables limpios en caneca negra.',
            'No botar pilas, medicamentos o electrónicos aquí.',
            'No dejar residuos sueltos en vía pública.',
        ],
    },
}


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

# ── Cargar modelo ──────────────────────────────────────────
log.info("⏳  Cargando modelo…")
if not os.path.exists(MODEL_PATH):
    raise FileNotFoundError(
        f"\n❌  Modelo no encontrado: '{MODEL_PATH}'\n"
        f"    Coloca el archivo .keras en la misma carpeta que app.py\n"
    )

model = tf.keras.models.load_model(MODEL_PATH)

# ── Info del modelo al arrancar ────────────────────────────
log.info(f"✅  Modelo cargado: {MODEL_PATH}")
log.info(f"    Input shape esperado : {model.input_shape}")
log.info(f"    Output shape         : {model.output_shape}")
log.info(f"    Número de clases     : {model.output_shape[-1]}")

if model.output_shape[-1] != len(LABELS):
    log.warning(
        f"⚠️  DESAJUSTE: el modelo tiene {model.output_shape[-1]} salidas "
        f"pero LABELS tiene {len(LABELS)} entradas."
    )


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
    log.info(f"{'â”€'*50}")
    log.info(f"ðŸ“¥  Imagen recibida: '{filename}'")

    img_bytes = file.read()
    
    # ── Abrir y preprocesar ────────────────────────────────
    try:
        img = Image.open(io.BytesIO(img_bytes))
        log.debug(f"    Modo original: {img.mode} | Tamaño: {img.size}")
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
        
        log.debug(f"    Preprocesamiento ResNet50 aplicado.")
        log.debug(f"    Rango valores: min={img_array.min():.1f} max={img_array.max():.1f}")
        
    except Exception as e:
        log.error(f"âŒ  Error procesando imagen: {e}")
        return jsonify({'error': f'No se pudo procesar la imagen: {e}'}), 400

    preds = model.predict(img_array, verbose=0)[0]
    
    log.info(f"ðŸ“Š  Predicciones brutas (softmax):")
    for i, (label, prob) in enumerate(zip(LABELS, preds)):
        bar = 'â–ˆ' * int(prob * 30)
        log.info(f"    [{i}] {label:<18} {prob:.6f}  {bar}")

    idx        = int(np.argmax(preds))
    confidence = float(round(float(preds[idx]) * 100, 2))
    log.info(f"ðŸ†  Resultado: '{LABELS[idx]}'  ({confidence}%)")

    # Alerta si siempre gana la misma clase
    if idx == len(LABELS) - 1 and confidence > 95:
        log.warning("âš ï¸  Resultado recurrente: Basura General. Verifica el dataset original.")

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
    log.info("ðŸš€  Servidor iniciado â†’ http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)

