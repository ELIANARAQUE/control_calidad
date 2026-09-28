import cv2
import mediapipe as mp
import os
import urllib.request

from mediapipe.tasks import python
from mediapipe.tasks.python import vision


# ============================================================
# CONFIGURACIÓN
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_DIR = os.path.join(BASE_DIR, "models")

MODEL_PATH = os.path.join(
    MODEL_DIR,
    "face_landmarker.task"
)

MODEL_URL = (
    "https://storage.googleapis.com/"
    "mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/"
    "face_landmarker.task"
)


# ============================================================
# DESCARGAR MODELO AUTOMÁTICAMENTE
# ============================================================

def download_model():

    if os.path.exists(MODEL_PATH):

        size = os.path.getsize(MODEL_PATH)

        if size > 1000000:
            print("Modelo encontrado.")
            print(f"Ubicación: {MODEL_PATH}")
            print(f"Tamaño: {size / 1024 / 1024:.2f} MB")
            return

        else:
            print("El modelo parece estar incompleto.")
            os.remove(MODEL_PATH)

    print()
    print("==========================================")
    print("DESCARGANDO MODELO DE FACE LANDMARKER")
    print("==========================================")
    print()

    os.makedirs(MODEL_DIR, exist_ok=True)

    try:

        urllib.request.urlretrieve(
            MODEL_URL,
            MODEL_PATH
        )

        print()
        print("Modelo descargado correctamente.")
        print(f"Ubicación: {MODEL_PATH}")

    except Exception as error:

        print()
        print("ERROR AL DESCARGAR EL MODELO")
        print(error)

        if os.path.exists(MODEL_PATH):
            os.remove(MODEL_PATH)

        exit()


# Descargar modelo
download_model()


# ============================================================
# CONFIGURAR MEDIAPIPE
# ============================================================

print()
print("Inicializando MediaPipe...")

base_options = python.BaseOptions(
    model_asset_path=MODEL_PATH
)

options = vision.FaceLandmarkerOptions(

    base_options=base_options,

    running_mode=vision.RunningMode.VIDEO,

    num_faces=5,

    min_face_detection_confidence=0.5,

    min_face_presence_confidence=0.5,

    min_tracking_confidence=0.5,

    output_face_blendshapes=False,

    output_facial_transformation_matrixes=False
)


# Crear detector
detector = vision.FaceLandmarker.create_from_options(
    options
)

print("MediaPipe iniciado correctamente.")


# ============================================================
# CÁMARA
# ============================================================

camera = cv2.VideoCapture(0)

if not camera.isOpened():

    print("ERROR: No se pudo abrir la cámara.")

    detector.close()

    exit()


print("Cámara iniciada.")
print()
print("==========================================")
print("FACE LANDMARKER ACTIVO")
print("==========================================")
print("Presiona Q para salir.")
print()


# ============================================================
# FUNCIÓN PARA DIBUJAR LOS PUNTOS
# ============================================================
admin
def draw_landmarks(frame, landmarks):

    height, width, _ = frame.shape

    for index, landmark in enumerate(landmarks):

        x = int(landmark.x * width)

        y = int(landmark.y * height)

        if 0 <= x < width and 0 <= y < height:

            cv2.circle(
                frame,
                (x, y),
                1,
                (0, 255, 0),
                -1
            )


# ============================================================
# LOOP PRINCIPAL
# ============================================================

timestamp = 0

while True:

    success, frame = camera.read()

    if not success:

        print("No se pudo obtener imagen de la cámara.")

        break


    # Efecto espejo
    frame = cv2.flip(frame, 1)


    # BGR -> RGB
    rgb_frame = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2RGB
    )


    # Crear imagen de MediaPipe
    mp_image = mp.Image(
        image_format=mp.ImageFormat.SRGB,
        data=rgb_frame
    )


    # Timestamp
    timestamp += 1


    # Detectar rostro
    result = detector.detect_for_video(
        mp_image,
        timestamp
    )


    # Cantidad de rostros
    face_count = len(result.face_landmarks)


    # ========================================================
    # DIBUJAR PUNTOS
    # ========================================================

    for face_landmarks in result.face_landmarks:

        draw_landmarks(
            frame,
            face_landmarks
        )


        # Mostrar algunos datos
        number_points = len(face_landmarks)

        cv2.putText(
            frame,
            f"Landmarks: {number_points}",
            (20, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2
        )


    # ========================================================
    # INFORMACIÓN EN PANTALLA
    # ========================================================

    cv2.putText(
        frame,
        f"Rostros: {face_count}",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 0),
        2
    )


    cv2.putText(
        frame,
        "Face Landmarker",
        (20, 115),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2
    )


    cv2.putText(
        frame,
        "Q = Salir",
        (20, 150),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2
    )


    # ========================================================
    # MOSTRAR
    # ========================================================

    cv2.imshow(
        "Face Recognition Project",
        frame
    )


    # Salir con Q
    if cv2.waitKey(1) & 0xFF == ord("q"):

        break


# ============================================================
# CERRAR
# ============================================================

camera.release()

cv2.destroyAllWindows()

detector.close()

print()
print("Programa finalizado.")