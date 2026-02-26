import numpy as np
import tensorflow as tf
from tensorflow.keras.preprocessing import image
from tensorflow.keras.applications.resnet50 import preprocess_input

# Cargar modelo
model = tf.keras.models.load_model('resnet50_garbage_classifier_model.keras')

def auditar(ruta_imagen):
    img = image.load_img(ruta_imagen, target_size=(384, 384))
    x = image.img_to_array(img)
    x = np.expand_dims(x, axis=0)
    x = preprocess_input(x)
    
    preds = model.predict(x, verbose=0)[0]
    idx = np.argmax(preds)
    confianza = preds[idx]
    
    print(f"Probando: {ruta_imagen}")
    print(f"Índice ganador: {idx}")
    print(f"Confianza: {confianza:.2%}")
    print("-" * 30)

# BUSCA 3 IMÁGENES EN GOOGLE Y PONLAS EN TU CARPETA:
# 1. Una caja de cartón (debería dar 0)
# 2. Una botella de plástico (debería dar 4)
# 3. Una lata de soda (debería dar 2)

auditar('caja.jpg')
auditar('botella.jpg')
auditar('lata.jpg')