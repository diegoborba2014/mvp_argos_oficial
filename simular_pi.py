"""
Simula o equipamento ARGOS enviando telemetria para o QG local.
Uso: python simular_pi.py
"""
import time
import random
import requests
from datetime import datetime, timezone

QG_URL    = "http://localhost:5000/api/argos/telemetry"
API_KEY   = "argos-secret-2026"
VIATURA   = "VTR-TATICA-01"
HEADERS   = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

# Hotlist simulada (algumas placas que vão gerar alerta)
HOTLIST = {"ABC1234", "XYZ9999", "DEF5678"}

MARCAS  = ["Toyota", "Honda", "Volkswagen", "Chevrolet", "Ford", "Hyundai", "Fiat"]
MODELOS = ["Corolla", "Civic", "Gol", "Onix", "Ka", "HB20", "Uno"]
CORES   = ["Preto", "Branco", "Prata", "Vermelho", "Azul", "Cinza"]

# Coordenadas ao redor de Florianópolis (ajuste para a cidade do projeto)
LAT_BASE = -27.5954
LON_BASE = -48.5480

def placa_aleatoria():
    import string
    letras = "".join(random.choices(string.ascii_uppercase, k=3))
    # 50% Mercosul, 50% antiga
    if random.random() > 0.5:
        num = f"{random.randint(0,9)}{random.choice(string.ascii_uppercase)}{random.randint(10,99)}"
    else:
        num = str(random.randint(1000, 9999))
    return letras + num

def enviar(payload):
    try:
        r = requests.post(QG_URL, json=payload, headers=HEADERS, timeout=5)
        return r.status_code
    except Exception as e:
        print(f"  ERRO: {e}")
        return None

def heartbeat():
    lat = LAT_BASE + random.uniform(-0.05, 0.05)
    lon = LON_BASE + random.uniform(-0.05, 0.05)
    payload = {
        "tipo": "heartbeat",
        "viatura_id": VIATURA,
        "timestamp": time.time(),
        "lpr_health": round(random.uniform(85, 100), 1),
        "lpr_fps":    round(random.uniform(8, 15), 1),
        "cpu_temp_c": round(random.uniform(52, 72), 1),
        "buffer_pendente": 0,
        "gps": {
            "latitude":  lat,
            "longitude": lon,
            "altitude":  round(random.uniform(5, 30), 1),
            "speed":     round(random.uniform(0, 80), 1),
            "satellites": random.randint(6, 12),
            "status": "3D_FIX",
        }
    }
    status = enviar(payload)
    print(f"[{_hora()}] HEARTBEAT → {status} | temp={payload['cpu_temp_c']}°C "
          f"| lpr={payload['lpr_health']}% | gps=({lat:.4f},{lon:.4f})")

def deteccao():
    placa = random.choice(list(HOTLIST)) if random.random() < 0.15 else placa_aleatoria()
    alerta = placa in HOTLIST
    lat = LAT_BASE + random.uniform(-0.05, 0.05)
    lon = LON_BASE + random.uniform(-0.05, 0.05)
    score = round(random.uniform(0.75, 0.99), 3)
    payload = {
        "tipo": "deteccao",
        "viatura_id": VIATURA,
        "timestamp": time.time(),
        "placa": placa,
        "score": score,
        "dscore": round(score - random.uniform(0, 0.05), 3),
        "marca": random.choice(MARCAS),
        "modelo": random.choice(MODELOS),
        "cor": random.choice(CORES),
        "tipo_veiculo": "car",
        "velocidade": round(random.uniform(20, 110), 1),
        "direcao": round(random.uniform(0, 360), 1),
        "regiao": "br",
        "alerta_tatico": alerta,
        "camera_id": "cam0",
        "latitude": lat,
        "longitude": lon,
        "altitude": round(random.uniform(5, 30), 1),
        "gps_satellites": random.randint(6, 12),
        "gps_status": "3D_FIX",
    }
    status = enviar(payload)
    tag = " *** ALERTA ***" if alerta else ""
    print(f"[{_hora()}] DETECCAO  → {status} | {placa} | {payload['score']:.0%}{tag}")

def _hora():
    return datetime.now().strftime("%H:%M:%S")

def main():
    print("=" * 55)
    print("  ARGOS — Simulador de Pi")
    print(f"  Destino: {QG_URL}")
    print(f"  Viatura: {VIATURA}")
    print(f"  Hotlist: {HOTLIST}")
    print("  Ctrl+C para parar")
    print("=" * 55)

    # Teste de conexão
    try:
        r = requests.get("http://localhost:5000/api/argos/status", timeout=3)
        print(f"  QG online: {r.json()}\n")
    except Exception:
        print("  AVISO: QG não responde em localhost:5000 — inicie o Flask antes.\n")
        return

    ciclo = 0
    while True:
        ciclo += 1
        # Heartbeat a cada 5 iterações (~30s)
        if ciclo % 5 == 1:
            heartbeat()

        # 1 a 3 detecções por ciclo
        for _ in range(random.randint(1, 3)):
            deteccao()
            time.sleep(random.uniform(0.5, 1.5))

        time.sleep(random.uniform(4, 8))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSimulador encerrado.")
