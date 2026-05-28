# ==============================================================================
# webhook_handler.py — Recebe e processa os webhooks do Plate Recognizer
# ==============================================================================
import base64
import json
import logging
import time as _time
from flask import Blueprint, jsonify, request

from config.settings import TEMPO_TRAVA_ALERTA_S, VIATURA_ID
from src.state import lock_estado, ultima_leitura
import src.state as app_state
from src.gps_reader import gps
from src.offline_buffer import buffer
from src.hotlist_manager import hotlist_manager
from src.gpio_controller import GpioController

logger = logging.getLogger("argos.webhook")
webhook_bp = Blueprint("webhook", __name__)

# Tamanho máximo do crop de placa enviado ao QG (em pixels de largura)
_PLACA_MAX_LARGURA_PX = 300
_PLACA_MAX_BYTES = 60_000

# Tamanho máximo do frame completo enviado ao QG em alertas (em pixels de largura)
_FRAME_MAX_LARGURA_PX = 800
_FRAME_MAX_BYTES = 150_000


def _thumbnail_placa_b64(raw_bytes: bytes) -> str:
    """
    Redimensiona o crop da placa para no máximo _PLACA_MAX_LARGURA_PX de largura
    e retorna como string base64. Usa Pillow se disponível; caso contrário, envia
    o original se for pequeno o suficiente (< _PLACA_MAX_BYTES).
    """
    try:
        from PIL import Image
        import io as _io
        img = Image.open(_io.BytesIO(raw_bytes)).convert("RGB")
        w, h = img.size
        if w > _PLACA_MAX_LARGURA_PX:
            ratio = _PLACA_MAX_LARGURA_PX / w
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=75, optimize=True)
        resultado = buf.getvalue()
        if len(resultado) > _PLACA_MAX_BYTES:
            logger.warning(f"[WEBHOOK] Imagem da placa ainda grande após resize ({len(resultado)} bytes) — descartando")
            return ""
        return base64.b64encode(resultado).decode("utf-8")
    except ImportError:
        # Pillow não disponível — envia raw se for pequeno o suficiente
        if len(raw_bytes) <= _PLACA_MAX_BYTES:
            return base64.b64encode(raw_bytes).decode("utf-8")
        logger.warning(f"[WEBHOOK] Imagem da placa grande ({len(raw_bytes)} bytes) e Pillow indisponível — descartando")
        return ""
    except Exception as exc:
        logger.warning(f"[WEBHOOK] Erro ao processar thumbnail da placa: {exc}")
        return ""


def _thumbnail_frame_b64(raw_bytes: bytes) -> str:
    """
    Redimensiona o frame completo da câmera para no máximo _FRAME_MAX_LARGURA_PX de largura
    e retorna como string base64 para envio ao QG em alertas táticos.
    """
    try:
        from PIL import Image
        import io as _io
        img = Image.open(_io.BytesIO(raw_bytes)).convert("RGB")
        w, h = img.size
        if w > _FRAME_MAX_LARGURA_PX:
            ratio = _FRAME_MAX_LARGURA_PX / w
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=65, optimize=True)
        resultado = buf.getvalue()
        if len(resultado) > _FRAME_MAX_BYTES:
            logger.warning(f"[WEBHOOK] Frame ainda grande após resize ({len(resultado)} bytes) — descartando")
            return ""
        return base64.b64encode(resultado).decode("utf-8")
    except ImportError:
        if len(raw_bytes) <= _FRAME_MAX_BYTES:
            return base64.b64encode(raw_bytes).decode("utf-8")
        logger.warning(f"[WEBHOOK] Frame grande ({len(raw_bytes)} bytes) e Pillow indisponível — descartando")
        return ""
    except Exception as exc:
        logger.warning(f"[WEBHOOK] Erro ao processar thumbnail do frame: {exc}")
        return ""


# Referência global ao GPIO (será injetada pelo main.py se necessário,
# mas para simplificar, usamos uma instância que aponta para a mesma lib lgpio)
gpio = GpioController()

@webhook_bp.route("/alpr-webhook", methods=["POST"])
def handle_alpr_webhook():
    # Leitura do JSON (multipart ou JSON puro)
    dados = None
    if request.form and "json" in request.form:
        try:
            dados = json.loads(request.form["json"])
        except (json.JSONDecodeError, TypeError):
            pass
    if dados is None:
        try:
            dados = request.get_json(force=True)
        except Exception:
            pass
    if not dados:
        return jsonify({"status": "erro_leitura"}), 400

    bloco_data = dados.get("data", dados)
    resultados = bloco_data.get("results", [])
    if not resultados:
        return jsonify({"status": "sem_resultados"}), 200

    # Hotlist check em TODOS os resultados — alerta se qualquer placa estiver na lista
    agora = _time.time()
    e_alerta = False
    for r in resultados:
        if hotlist_manager.is_alert(r.get("plate", "").upper()):
            e_alerta = True
            break

    # Resultado principal: maior score (ou primeiro se empate)
    resultado = max(resultados, key=lambda r: r.get("score", 0.0))
    placa_lida = resultado.get("plate", "").upper()
    if not placa_lida:
        return jsonify({"status": "placa_vazia"}), 200

    # Trava tática
    with lock_estado:
        if agora < app_state.timestamp_trava_ate:
            return jsonify({"status": "trava_ativa", "placa_ignorada": placa_lida}), 200
        if e_alerta:
            app_state.timestamp_trava_ate = agora + TEMPO_TRAVA_ALERTA_S

    # MMC
    mmc_lista = resultado.get("model_make", [])
    marca  = mmc_lista[0].get("make", "N/D").upper() if mmc_lista else "N/D"
    modelo = mmc_lista[0].get("model", "N/D").upper() if mmc_lista else "N/D"

    cores_lista = resultado.get("color", [])
    cor = cores_lista[0].get("color", "N/D").upper() if cores_lista else "N/D"

    veiculo_dados = resultado.get("vehicle", {})
    tipo_veiculo = veiculo_dados.get("type", "N/D").upper()
    velocidade   = veiculo_dados.get("speed", 0.0)
    direcao      = veiculo_dados.get("direction", 0)
    regiao = resultado.get("region", {}).get("code", "N/D").upper()

    # Frame da câmera — UI local usa versão full quality; QG recebe versão redimensionada (só alertas)
    imagem_veiculo_b64 = ""
    imagem_veiculo_qg_b64 = ""
    for chave_img in ["upload", "vehicle"]:
        if chave_img in request.files:
            try:
                raw_frame = request.files[chave_img].read()
                imagem_veiculo_b64 = base64.b64encode(raw_frame).decode("utf-8")
                if e_alerta:
                    imagem_veiculo_qg_b64 = _thumbnail_frame_b64(raw_frame)
                break
            except Exception:
                pass
    if not imagem_veiculo_b64:
        imagem_veiculo_b64 = resultado.get("imagem_b64", "")

    # Recorte da placa — thumbnail compacto, enviado ao QG em todas as detecções
    imagem_placa_b64 = ""
    if "plate_img" in request.files:
        try:
            raw = request.files["plate_img"].read()
            imagem_placa_b64 = _thumbnail_placa_b64(raw)
        except Exception:
            pass

    camera_id = bloco_data.get("camera_id", dados.get("hook", {}).get("id", "N/D"))

    # Captura coordenadas GPS atuais
    pos_gps = gps.get_position()

    # Atualiza estado em RAM
    novo_estado = {
        "placa":         placa_lida,
        "score":         resultado.get("score", 0.0),
        "dscore":        resultado.get("dscore", 0.0),
        "marca":         marca,
        "modelo":        modelo,
        "cor":           cor,
        "tipo_veiculo":  tipo_veiculo,
        "velocidade":    velocidade,
        "direcao":       direcao,
        "regiao":        regiao,
        "alerta_tatico": e_alerta,
        "imagem_veiculo": imagem_veiculo_b64,
        "imagem_placa":   imagem_placa_b64,
        "camera_id":     camera_id,
        "timestamp":     str(agora),
        "latitude":      pos_gps.get("latitude"),
        "longitude":     pos_gps.get("longitude"),
        "altitude":      pos_gps.get("altitude"),
        "gps_satellites": pos_gps.get("satellites"),
        "gps_status":    pos_gps.get("status"),
        "bbox_placa":    resultado.get("box"),
        "bbox_veiculo":  resultado.get("vehicle", {}).get("box"),
        "deteccoes":     [
            {"placa": r.get("plate", "").upper(), "score": r.get("score", 0.0), "box": r.get("box")}
            for r in resultados if r.get("box")
        ],
    }

    with lock_estado:
        # Importante: Atualizando os valores do dicionário no state em vez de reatribuir a variável global
        # pois `ultima_leitura` foi importada e reatribuí-la localmente não modificaria o dicionário de state.py
        app_state.ultima_leitura.update(novo_estado)

    # Enfileira para envio ao QG
    # imagem_veiculo (full quality): apenas para UI local, excluída do buffer
    # imagem_placa:                  enviada em todas as detecções
    # imagem_veiculo (QG, resized):  enviada apenas em alertas táticos
    excluir_buffer = {"imagem_veiculo"}
    evento_buffer = {k: v for k, v in novo_estado.items() if k not in excluir_buffer}
    evento_buffer["viatura_id"] = VIATURA_ID
    if imagem_veiculo_qg_b64:
        evento_buffer["imagem_veiculo"] = imagem_veiculo_qg_b64
    buffer.enqueue(evento_buffer)

    # Feedback tático físico
    if e_alerta:
        gpio.alerta_placa(duracao_s=TEMPO_TRAVA_ALERTA_S)

    tag = "🚨 ALERTA" if e_alerta else "✅ OK"
    gps_info = f"GPS: {pos_gps.get('latitude', '?'):.5f}, {pos_gps.get('longitude', '?'):.5f}" if pos_gps.get("latitude") else "GPS: SEM FIX"
    logger.info(f"[WEBHOOK] {placa_lida} | {marca} {modelo} | {tag} | {gps_info}")

    return jsonify({"status": "sucesso", "alerta": e_alerta}), 200
