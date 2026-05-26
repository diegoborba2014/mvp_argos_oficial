from datetime import datetime, timedelta, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

db = SQLAlchemy()


class Viatura(db.Model):
    __tablename__ = "viaturas"

    id = db.Column(db.Integer, primary_key=True)
    viatura_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    descricao = db.Column(db.String(128), default="")
    ativa = db.Column(db.Boolean, default=True)
    # "hibrido": Pi OU QG fazem match | "nuvem": apenas QG | "local": apenas Pi
    hotlist_mode = db.Column(db.String(16), default="hibrido")
    criado_em = db.Column(db.DateTime, default=_utcnow)

    deteccoes = db.relationship("Deteccao", backref="viatura_ref", lazy="dynamic")
    heartbeats = db.relationship("Heartbeat", backref="viatura_ref", lazy="dynamic")

    def ultimo_heartbeat(self):
        return self.heartbeats.order_by(Heartbeat.recebido_em.desc()).first()

    def online(self):
        hb = self.ultimo_heartbeat()
        if not hb:
            return False
        delta = (_utcnow() - hb.recebido_em).total_seconds()
        return delta < 300  # offline se sem heartbeat > 5 min

    def __repr__(self):
        return f"<Viatura {self.viatura_id}>"


class Deteccao(db.Model):
    __tablename__ = "deteccoes"

    id = db.Column(db.Integer, primary_key=True)
    viatura_id = db.Column(db.String(64), db.ForeignKey("viaturas.viatura_id"), nullable=False, index=True)
    placa = db.Column(db.String(16), nullable=False, index=True)
    score = db.Column(db.Float, default=0.0)
    dscore = db.Column(db.Float, default=0.0)
    marca = db.Column(db.String(64), default="")
    modelo = db.Column(db.String(64), default="")
    cor = db.Column(db.String(32), default="")
    tipo_veiculo = db.Column(db.String(32), default="")
    velocidade = db.Column(db.Float, default=0.0)
    direcao = db.Column(db.Float, default=0.0)
    regiao = db.Column(db.String(16), default="")
    alerta_tatico = db.Column(db.Boolean, default=False, index=True)
    camera_id = db.Column(db.String(32), default="")
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    altitude = db.Column(db.Float, nullable=True)
    gps_satellites = db.Column(db.Integer, nullable=True)
    gps_status = db.Column(db.String(16), default="")
    timestamp = db.Column(db.Float, nullable=True)
    recebido_em = db.Column(db.DateTime, default=_utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "viatura_id": self.viatura_id,
            "placa": self.placa,
            "score": self.score,
            "marca": self.marca,
            "modelo": self.modelo,
            "cor": self.cor,
            "tipo_veiculo": self.tipo_veiculo,
            "velocidade": self.velocidade,
            "alerta_tatico": self.alerta_tatico,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "recebido_em": (self.recebido_em - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M:%S"),
        }


class Heartbeat(db.Model):
    __tablename__ = "heartbeats"

    id = db.Column(db.Integer, primary_key=True)
    viatura_id = db.Column(db.String(64), db.ForeignKey("viaturas.viatura_id"), nullable=False, index=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    altitude = db.Column(db.Float, nullable=True)
    speed = db.Column(db.Float, nullable=True)
    satellites = db.Column(db.Integer, nullable=True)
    gps_status = db.Column(db.String(16), default="")
    lpr_health = db.Column(db.Float, nullable=True)
    lpr_fps = db.Column(db.Float, nullable=True)
    cpu_temp_c = db.Column(db.Float, nullable=True)
    buffer_pendente = db.Column(db.Integer, default=0)
    timestamp = db.Column(db.Float, nullable=True)
    recebido_em = db.Column(db.DateTime, default=_utcnow, index=True)


class Hotlist(db.Model):
    __tablename__ = "hotlist"

    id = db.Column(db.Integer, primary_key=True)
    placa = db.Column(db.String(16), unique=True, nullable=False, index=True)
    descricao = db.Column(db.String(256), default="")
    ativa = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=_utcnow)


class Usuario(UserMixin, db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    perfil = db.Column(db.String(16), default="operador")  # "admin" ou "operador"
    criado_em = db.Column(db.DateTime, default=_utcnow)

    def set_password(self, senha):
        self.password_hash = generate_password_hash(senha)

    def check_password(self, senha):
        return check_password_hash(self.password_hash, senha)

    def is_admin(self):
        return self.perfil == "admin"
