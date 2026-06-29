import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import Config

SMTP_SERVER = Config.SMTP_SERVER
SMTP_PORT = Config.SMTP_PORT
SMTP_USER = Config.SMTP_USER
SMTP_PASSWORD = Config.SMTP_PASSWORD
FROM_EMAIL = Config.FROM_EMAIL

def send_reset_email(to_email, reset_link):

    message = MIMEMultipart()

    message["From"] = FROM_EMAIL
    message["To"] = to_email
    message["Subject"] = "Réinitialisation de votre mot de passe"

    html = f"""
    <html>
    <body style="font-family:Arial;background:#f4f4f4;padding:30px;">
        <div style="max-width:650px;margin:auto;background:white;padding:30px;border-radius:10px;">
            <div style="text-align:center;">
                <img
                src="https://logiciel.copawotko-cajou.com/static/images/logo.png"
                width="120">
            </div>
            <h2 style="color:#2e7d32; text-align:center;">
                Coopérative COPAWOTKO CAJOU
            </h2>

            <p>Bonjour,</p>

            <p>
            Vous avez demandé la réinitialisation de votre mot de passe.
            </p>

            <p>
            Cliquez sur le bouton ci-dessous :
            </p>

            <p style="text-align:center;">

                <a href="{reset_link}"
                   style="
                   background:#2e7d32;
                   color:white;
                   padding:14px 25px;
                   text-decoration:none;
                   border-radius:6px;
                   font-weight:bold;">

                   Réinitialiser mon mot de passe

                </a>

            </p>

            <p>
            Ce lien est valable pendant <b>1 heure</b>.
            </p>

            <hr>

            <p style="font-size:12px;color:gray;">
            Si vous n'êtes pas à l'origine de cette demande,
            ignorez simplement cet email.
            </p>

        </div>
    </body>
    </html>
    """

    message.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(
            FROM_EMAIL,
            to_email,
            message.as_string()
        )
        server.quit()