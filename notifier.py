"""
Envío de alertas por email cuando aparecen oportunidades con score >= SCORE_ALERTA.
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from config import (
    FROM_EMAIL, SCORE_ALERTA, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER
)
from database import Licitacion, Oportunidad, Proveedor, SessionLocal

log = logging.getLogger(__name__)


def _formato_monto(monto: float | None) -> str:
    if monto is None:
        return "No informado"
    return f"$ {monto:,.0f} CLP".replace(",", ".")


def _html_oportunidad(lic: Licitacion, score: float) -> str:
    fecha = lic.fecha_cierre.strftime("%d/%m/%Y %H:%M") if lic.fecha_cierre else "—"
    monto = _formato_monto(lic.monto_estimado)
    color = "#c8a951" if score >= 80 else "#4a90d9"
    return f"""
    <tr>
      <td style="padding:12px;border-bottom:1px solid #2a3450;">
        <strong style="color:#f0f0f0;">{lic.nombre}</strong><br>
        <span style="color:#aaa;font-size:12px;">{lic.organismo} · {lic.region or '—'}</span>
      </td>
      <td style="padding:12px;border-bottom:1px solid #2a3450;color:#aaa;">{monto}</td>
      <td style="padding:12px;border-bottom:1px solid #2a3450;color:#aaa;">{fecha}</td>
      <td style="padding:12px;border-bottom:1px solid #2a3450;">
        <span style="background:{color};color:#000;padding:4px 10px;border-radius:12px;font-weight:bold;">
          {score:.0f}
        </span>
      </td>
      <td style="padding:12px;border-bottom:1px solid #2a3450;">
        <a href="https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?qs=OQ4BE/fkDuGM8WQlQM9nkQ=="
           style="color:#c8a951;">Ver licitación →</a>
      </td>
    </tr>"""


def _construir_html(proveedor: Proveedor, oportunidades: list[tuple]) -> str:
    filas = "".join(_html_oportunidad(lic, score) for lic, score in oportunidades)
    return f"""
    <html><body style="background:#0d1117;color:#f0f0f0;font-family:Georgia,serif;padding:32px;">
      <h1 style="color:#c8a951;border-bottom:1px solid #2a3450;padding-bottom:16px;">
        Radar de Oportunidades
      </h1>
      <p>Hola <strong>{proveedor.nombre}</strong>,</p>
      <p>Encontramos <strong>{len(oportunidades)} licitaciones</strong> con alta coincidencia para tu perfil:</p>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="background:#161b2e;border-radius:8px;overflow:hidden;margin-top:16px;">
        <thead>
          <tr style="background:#1e2640;">
            <th style="padding:12px;text-align:left;color:#c8a951;">Licitación</th>
            <th style="padding:12px;text-align:left;color:#c8a951;">Monto</th>
            <th style="padding:12px;text-align:left;color:#c8a951;">Cierre</th>
            <th style="padding:12px;text-align:left;color:#c8a951;">Score</th>
            <th style="padding:12px;text-align:left;color:#c8a951;">Enlace</th>
          </tr>
        </thead>
        <tbody>{filas}</tbody>
      </table>
      <p style="margin-top:24px;color:#666;font-size:12px;">
        Radar Mercado Público · Ríos & Ríos Asociados
      </p>
    </body></html>"""


def enviar_alertas():
    """Envía email a proveedores con oportunidades nuevas >= SCORE_ALERTA."""
    if not SMTP_HOST or not SMTP_USER:
        log.warning("SMTP no configurado — saltando notificaciones.")
        return

    db: Session = SessionLocal()
    try:
        pendientes = (
            db.query(Oportunidad)
            .filter(Oportunidad.notificado == False, Oportunidad.score >= SCORE_ALERTA)
            .all()
        )
        if not pendientes:
            return

        # Agrupar por proveedor
        por_proveedor: dict[str, list[Oportunidad]] = {}
        for op in pendientes:
            por_proveedor.setdefault(op.proveedor_id, []).append(op)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)

            for proveedor_id, ops in por_proveedor.items():
                proveedor = db.get(Proveedor, proveedor_id)
                if not proveedor or not proveedor.email:
                    continue

                pares = []
                for op in ops:
                    lic = db.get(Licitacion, op.licitacion_id)
                    if lic:
                        pares.append((lic, op.score))

                if not pares:
                    continue

                msg = MIMEMultipart("alternative")
                msg["Subject"] = f"🎯 {len(pares)} licitaciones para {proveedor.nombre}"
                msg["From"]    = FROM_EMAIL
                msg["To"]      = proveedor.email
                msg.attach(MIMEText(_construir_html(proveedor, pares), "html"))

                server.sendmail(FROM_EMAIL, proveedor.email, msg.as_string())
                log.info("Email enviado a %s con %d oportunidades", proveedor.email, len(pares))

                for op in ops:
                    op.notificado = True
                db.commit()

    except Exception as e:
        log.error("Error enviando alertas: %s", e)
    finally:
        db.close()
