import json
from datetime import datetime, timedelta, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

db = SQLAlchemy()


class Cliente(db.Model):
    __tablename__ = "clientes"

    id        = db.Column(db.Integer, primary_key=True)
    nome      = db.Column(db.String(128), nullable=False, unique=True)
    cnpj_cpf  = db.Column(db.String(20), default="")
    contato   = db.Column(db.String(128), default="")
    ativo     = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=_utcnow)

    viaturas = db.relationship("Viatura", backref="cliente", lazy="select")
    usuarios = db.relationship("Usuario", backref="cliente", lazy="select")

    def __repr__(self):
        return f"<Cliente {self.nome}>"


class Viatura(db.Model):
    __tablename__ = "viaturas"

    id = db.Column(db.Integer, primary_key=True)
    viatura_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    descricao = db.Column(db.String(128), default="")
    ativa = db.Column(db.Boolean, default=True)
    # "hibrido": Pi OU QG fazem match | "nuvem": apenas QG | "local": apenas Pi
    hotlist_mode = db.Column(db.String(16), default="hibrido")
    config_json = db.Column(db.Text, nullable=True)
    config_pendente = db.Column(db.Boolean, default=False)
    hotlist_pendente = db.Column(db.Boolean, default=False)
    hotlist_hash = db.Column(db.String(32), nullable=True)
    ultima_sync_hotlist = db.Column(db.DateTime, nullable=True)
    comando_pendente = db.Column(db.String(32), nullable=True)
    comando_pendente_at = db.Column(db.DateTime, nullable=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=True, index=True)
    criado_em = db.Column(db.DateTime, default=_utcnow)

    deteccoes = db.relationship("Deteccao", backref="viatura_ref", lazy="select")
    heartbeats = db.relationship("Heartbeat", backref="viatura_ref", lazy="select")

    def get_config(self):
        if self.config_json:
            try:
                return json.loads(self.config_json)
            except Exception:
                return {}
        return {}

    def set_config(self, config_dict):
        self.config_json = json.dumps(config_dict, ensure_ascii=False)
        self.config_pendente = True

    def ultimo_heartbeat(self):
        return Heartbeat.query.filter_by(viatura_id=self.viatura_id).order_by(
            Heartbeat.recebido_em.desc()
        ).first()

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
    __table_args__ = (
        db.Index("ix_deteccoes_alerta_recebido", "alerta_tatico", "recebido_em"),
        db.Index("ix_deteccoes_viatura_recebido", "viatura_id", "recebido_em"),
    )

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
    imagem_placa = db.Column(db.LargeBinary, nullable=True)    # Crop da placa (JPEG), todas as detecções
    imagem_veiculo = db.Column(db.LargeBinary, nullable=True)  # Frame completo (JPEG), apenas alertas táticos
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
            "tem_imagem": self.imagem_placa is not None,
            "tem_imagem_veiculo": self.imagem_veiculo is not None,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "recebido_em": (self.recebido_em - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M:%S"),
        }


class Heartbeat(db.Model):
    __tablename__ = "heartbeats"
    __table_args__ = (
        db.Index("ix_heartbeats_viatura_recebido", "viatura_id", "recebido_em"),
    )

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
    motivo = db.Column(db.String(64), default="")
    prioridade = db.Column(db.Integer, default=2)  # 1=Alta 2=Média 3=Baixa
    observacao = db.Column(db.Text, default="")
    ativa = db.Column(db.Boolean, default=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=True, index=True)
    criado_em = db.Column(db.DateTime, default=_utcnow)


class EventoSistema(db.Model):
    """Eventos operacionais do sistema: Pi offline, LPR degradado, GPS sem sinal, etc."""
    __tablename__ = "eventos_sistema"
    __table_args__ = (
        db.Index("ix_eventos_viatura_resolvido", "viatura_id", "resolvido"),
        db.Index("ix_eventos_viatura_tipo_resolvido", "viatura_id", "tipo", "resolvido"),
    )

    id = db.Column(db.Integer, primary_key=True)
    viatura_id = db.Column(db.String(64), nullable=False, index=True)
    # Tipos: pi_offline | pi_reconectado | lpr_offline | lpr_degradado |
    #        gps_sem_sinal | gps_restaurado | buffer_crescendo | cpu_quente | camera_erro
    tipo = db.Column(db.String(32), nullable=False, index=True)
    severidade = db.Column(db.String(8), nullable=False)  # "critico" | "aviso" | "info"
    detalhe = db.Column(db.Text, default="")
    resolvido = db.Column(db.Boolean, default=False, index=True)
    resolvido_em = db.Column(db.DateTime, nullable=True)
    criado_em = db.Column(db.DateTime, default=_utcnow, index=True)

    def __repr__(self):
        return f"<EventoSistema {self.tipo} {self.viatura_id} {'OK' if self.resolvido else 'ATIVO'}>"


class LogAuditoria(db.Model):
    """Trilha de auditoria: registra ações operacionais de cada usuário."""
    __tablename__ = "log_auditoria"
    __table_args__ = (
        db.Index("ix_log_auditoria_criado", "criado_em"),
        db.Index("ix_log_auditoria_usuario", "usuario"),
    )

    id        = db.Column(db.Integer, primary_key=True)
    usuario   = db.Column(db.String(64), nullable=False)
    acao      = db.Column(db.String(128), nullable=False)  # "hotlist:adicionar:ABC1234"
    detalhe   = db.Column(db.Text, default="")
    criado_em = db.Column(db.DateTime, default=_utcnow, index=True)

    def __repr__(self):
        return f"<LogAuditoria {self.usuario} {self.acao}>"


class MotivoHotlist(db.Model):
    """Motivos cadastráveis pelo admin para uso na Hotlist."""
    __tablename__ = "motivos_hotlist"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(64), unique=True, nullable=False)
    criado_em = db.Column(db.DateTime, default=_utcnow)

    def __repr__(self):
        return f"<MotivoHotlist {self.nome}>"


class Usuario(UserMixin, db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    # perfil: "superadmin" | "admin_cliente" | "operador_cliente" | legado: "admin" | "operador"
    perfil = db.Column(db.String(16), default="operador")
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=True, index=True)
    criado_em = db.Column(db.DateTime, default=_utcnow)

    def set_password(self, senha):
        self.password_hash = generate_password_hash(senha)

    def check_password(self, senha):
        return check_password_hash(self.password_hash, senha)

    def is_admin(self):
        return self.perfil in ("admin", "superadmin")

    def is_superadmin(self):
        return self.perfil in ("admin", "superadmin")

    def is_admin_cliente(self):
        return self.perfil == "admin_cliente"

    def can_edit_hotlist(self):
        return self.perfil in ("admin", "superadmin", "admin_cliente")

    def can_manage_equipment(self):
        return self.is_superadmin()

    def get_cliente_id(self):
        """None para superadmin (sem filtro); int para usuários de cliente."""
        return None if self.is_superadmin() else self.cliente_id
