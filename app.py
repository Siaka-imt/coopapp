from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file
import mysql.connector
import json
import hashlib
import pandas as pd
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors
from reportlab.platypus import Image, Spacer, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from datetime import datetime
from reportlab.lib.pagesizes import letter, landscape
import secrets
from datetime import datetime, timedelta
from mail import send_reset_email
from config import Config

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY

#       Charger config.json
with open("config.json") as f:
    config = json.load(f)

DB_HOST = Config.DB_HOST
DB_NAME = Config.DB_NAME
DB_USER = Config.DB_USER
DB_PASSWORD = Config.DB_PASSWORD
#       Connexion DB
def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )
#       charger logo
import os
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads","logos")
PROFILE_UPLOAD_FOLDER = "static/uploads/profiles"

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config["PROFILE_UPLOAD_FOLDER"] = PROFILE_UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROFILE_UPLOAD_FOLDER, exist_ok=True)
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def clean_number(value):
    if value is None:
        return 0
    value = str(value).strip()
    if value == "":
        return 0
    if value == None or value == "None":
        return 0
    
    return int(float(str(value).replace(" ", "")))
def format_number_after(value):
        if value is None or str(value).strip() == "":
            return ""
        if value == 'None':
            return ""
        return "{:,}".format(int(str(value).replace(" ", ""))).replace(",", " ")

def recalculate_fiche_pisteur(pisteur, campagne):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)
    # 🔥 récupérer toutes les lignes
    cursor.execute("""
        SELECT * FROM fiche_pisteur
        WHERE pisteur = %s AND campagne = %s
        ORDER BY id ASC
    """, (pisteur, campagne))

    rows = cursor.fetchall()

    # =========================
    # VARIABLES CUMULATIVES
    # =========================

    poids_cumul = 0
    debit_cumul = 0
    credit_cumul = 0
    sac_restant = 0

    # =========================
    # RECALCUL
    # =========================

    for row in rows:

        poids_net = row["poids_net"] or 0
        debit = row["debit"] or 0
        credit = row["credit"] or 0
        sac_recu = row["sac_reçu"] or 0
        sac_livre = row["sac_livre"] or 0

        # cumul poids
        poids_cumul += clean_number(poids_net)

        # cumul débit
        debit_cumul += clean_number(debit)

        # cumul crédit
        credit_cumul += clean_number(credit)

        # solde
        solde = clean_number(debit_cumul) - clean_number(credit_cumul)

        # sacs
        sac_restant += clean_number(sac_recu) - clean_number(sac_livre)

        # 🔥 UPDATE
        cursor.execute("""
            UPDATE fiche_pisteur
            SET
                poids_cumul = %s,
                debit_cumul = %s,
                credit_cumul = %s,
                solde = %s,
                sac_restant = %s
            WHERE id = %s
        """, (
            poids_cumul,
            debit_cumul,
            credit_cumul,
            solde,
            sac_restant,
            row["id"]
        ))

    conn.commit()

def recalculate_fiche_client(client, campagne):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    # 🔥 récupérer toutes les lignes du client
    cursor.execute("""
        SELECT *
        FROM fiche_client
        WHERE client = %s AND campagne = %s
        ORDER BY id ASC
    """, (client, campagne))

    rows = cursor.fetchall()

    # =========================
    # VARIABLES CUMULATIVES
    # =========================

    cumul = 0
    cumul_poids_net = 0
    cumul_montant_livraison = 0
    resultat_livraison = 0
    sac_restant = 0

    # =========================
    # RECALCUL
    # =========================

    for row in rows:

        montant = row["montant"] or 0
        poids_net = row["poids_net"] or 0
        montant_livraison = row["montant_livraison"] or 0

        sac_recu = row["sac_reçu"] or 0
        sac_livre = row["sac_livre"] or 0

        # =========================
        # CUMULS
        # =========================

        cumul += clean_number(montant)

        cumul_poids_net += clean_number(poids_net)

        cumul_montant_livraison += clean_number(montant_livraison)

        resultat_livraison = cumul - cumul_montant_livraison

        sac_restant += clean_number(sac_recu) - clean_number(sac_livre)

        # =========================
        # UPDATE
        # =========================

        cursor.execute("""
            UPDATE fiche_client
            SET
                cumul = %s,
                cumul_poids_net = %s,
                cumul_montant_livraison = %s,
                resultat_livraison = %s,
                sac_restant = %s
            WHERE id = %s
        """, (
            cumul,
            cumul_poids_net,
            cumul_montant_livraison,
            resultat_livraison,
            sac_restant,
            row["id"]
        ))

    conn.commit()

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True, buffered=True)

        cursor.execute("SELECT * FROM utilisateur WHERE email = %s", (email,))
        user = cursor.fetchone()

        if user:
            if hash_password(password) == user["password"]:
                session["user"] = user["username"]
                session["role"] = user["role"]
                return redirect("/dashboard")
        
        return "Identifiants incorrects ❌"

    return render_template("login.html")
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    
    if request.method == "POST":

        email = request.form["email"]

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True, buffered=True)

        cursor.execute(
            "SELECT * FROM utilisateur WHERE email=%s",
            (email,)
        )

        user = cursor.fetchone()

        if not user:
            flash("Aucun compte trouvé avec cette adresse email ❌", "danger")
            return redirect("/forgot-password")

        # Suppression des anciens tokens
        cursor.execute(
            "DELETE FROM password_reset WHERE email=%s",
            (email,)
        )

        token = secrets.token_urlsafe(32)

        expiration = datetime.now() + timedelta(hours=1)

        cursor.execute("""
            INSERT INTO password_reset
            (email, token, expiration)
            VALUES (%s, %s, %s)
        """, (email, token, expiration))

        conn.commit()

        reset_link = url_for(
            "reset_password",
            token=token,
            _external=True
        )

        send_reset_email(email, reset_link)

        return redirect("/")

    return render_template("forgot_password.html")
@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute("""
        SELECT *
        FROM password_reset
        WHERE token = %s
        AND expiration > NOW()
    """, (token,))

    reset = cursor.fetchone()

    if not reset:
        flash("Lien expiré ou invalide ❌", "danger")
        return redirect("/")

    if request.method == "POST":

        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if password != confirm_password:
            flash("Les mots de passe ne correspondent pas ❌", "danger")
            return redirect(request.url)

        #from werkzeug.security import generate_password_hash

        #hashed_password = generate_password_hash(password)
        hashed = hashlib.sha256(password.encode()).hexdigest()

        cursor.execute("""
            UPDATE utilisateur
            SET password = %s
            WHERE email = %s
        """, (hashed, reset["email"]))

        cursor.execute("""
            DELETE FROM password_reset
            WHERE token = %s
        """, (token,))

        conn.commit()

        flash(
            "Mot de passe modifié avec succès ✅",
            "success"
        )

        return redirect("/")

    return render_template(
        "reset_password.html",
        token=token
    )
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/")

    conn = get_db_connection()
    cursor = conn.cursor(buffered = True)

    cursor.execute("SELECT photo FROM utilisateur WHERE username=%s", (session["user"],))
    user_photo = cursor.fetchone()
    # Comptage des données
    cursor.execute("SELECT COUNT(*) FROM client")
    nb_clients = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM pisteur")
    nb_pisteurs = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM zone")
    nb_zones = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM mission_camion WHERE etat = 'LIVRE'")
    nb_livraisons = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM campagne")
    nb_campagnes = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM produit")
    nb_produits = cursor.fetchone()[0]

    cursor.execute("SELECT DISTINCT produit FROM mouvement_stock")
    produit_stock = cursor.fetchall()
    nb_produit_stock = len(produit_stock)

    # ======================================
    # Répartition des pisteurs par zone
    # ======================================

    cursor.execute("""
        SELECT nom, nombre_pisteur
        FROM zone
        ORDER BY nombre_pisteur DESC
    """)

    pisteurs_zone = cursor.fetchall()

    zones_labels = [row[0] for row in pisteurs_zone]
    zones_values = [row[1] for row in pisteurs_zone]

    # ======================================
    # Répartition des clients par ville
    # ======================================

    cursor.execute("""
        SELECT localisation, COUNT(*)
        FROM client
        GROUP BY localisation
        ORDER BY COUNT(*) DESC
    """)

    clients_ville = cursor.fetchall()

    villes_labels = [row[0] for row in clients_ville]
    villes_values = [row[1] for row in clients_ville]

    # =============================================
    # comparaison des performances entre campagnes
    # =============================================

    cursor.execute("""
        SELECT
            campagne,
            SUM(CAST(REPLACE(cumul,' ','') AS UNSIGNED)) AS total_cumul
        FROM fiche_client
        WHERE id IN (
            SELECT MAX(id)
            FROM fiche_client
            GROUP BY client, campagne
        )
        GROUP BY campagne
        ORDER BY campagne
        """)

    campagnes_data = cursor.fetchall()

    campagnes_labels = [row[0] for row in campagnes_data]
    campagnes_values = [int(row[1]) for row in campagnes_data]

    cursor.execute("""
        SELECT
            produit,

            SUM(
                CASE
                    WHEN type_mouvement='ENTREE'
                    THEN quantite_poids
                    ELSE -quantite_poids
                END
            ) AS poids,

            SUM(
                CASE
                    WHEN type_mouvement='ENTREE'
                    THEN nombre_sacs
                    ELSE -nombre_sacs
                END
            ) AS sacs

        FROM mouvement_stock
        GROUP BY produit
        ORDER BY produit
    """)

    stocks = cursor.fetchall()

    cursor.execute("""
        SELECT
            campagne,
            client,
            destination,

            COUNT(*) AS nombre_livraisons,

            SUM(quantite_poids) AS poids_total,

            SUM(nombre_sacs) AS sacs_total

        FROM mission_camion

        WHERE etat = 'LIVRE'
        GROUP BY campagne, client, destination
        ORDER BY campagne DESC, client, destination
    """)
    livraisons = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template(
        "dashboard.html",
        user=session["user"],
        role=session["role"],
        photo = user_photo[0],
        stocks = stocks,
        nb_clients=nb_clients,
        nb_pisteurs=nb_pisteurs,
        nb_zones=nb_zones,
        nb_livraisons=nb_livraisons,
        nb_campagnes=nb_campagnes,
        nb_produits=nb_produits,
        format_number = clean_number,
        format_number_after = format_number_after,

        zones_labels=zones_labels,
        zones_values=zones_values,

        villes_labels=villes_labels,
        villes_values=villes_values,

        campagnes_labels=campagnes_labels,
        campagnes_values=campagnes_values,

        nb_produit_stock = nb_produit_stock,

        livraisons = livraisons
    )
#----------------------------------------------------------------
# Routes clients
#----------------------------------------------------------------
@app.route("/clients")
def clients():
    if "user" not in session:
        return redirect("/")
    search = request.args.get("search", "").strip()
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary = True, buffered=True)

    cursor.execute("SELECT DISTINCT campagne FROM client")
    campagnes = cursor.fetchall()

    campagne = request.args.get("campagne")

    if search:
        cursor.execute("""
            SELECT *
            FROM client
            WHERE nom LIKE %s
            ORDER BY nom
        """, (f"%{search}%",))
    elif campagne:
        cursor.execute("""
            SELECT *
            FROM client
            WHERE campagne = %s
            ORDER BY nom
        """, (campagne,))
    else:
        query = """
            SELECT * from client
            ORDER BY nom
        """
        cursor.execute(query,)
    
    clients = cursor.fetchall()

    cursor.execute("SELECT photo FROM utilisateur WHERE username = %s", (session["user"],))
    user_photo = cursor.fetchone()
    return render_template("clients.html",clients = clients,user = session["user"], campagnes = campagnes,
        role = session["role"], photo = user_photo["photo"] if user_photo else None)
@app.route("/clients/add", methods = ["POST"])
def add_client():
    
    nom = request.form["nom"]
    contact = request.form["contact"]
    localisation = request.form["localisation"]
    campagne = request.form["campagne"]
    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute(
        "INSERT INTO client (contact, nom, localisation, campagne) VALUES (%s, %s, %s, %s)",
        (contact, nom, localisation, campagne)
    )

    conn.commit()
    return redirect("/clients")
@app.route("/clients/delete/<int:id>", methods=["POST"])
def delete_client(id):
    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("DELETE FROM client WHERE id = %s", (id,))

    conn.commit()
    flash("Client supprimé avec succès ✅", "success")
    return redirect("/clients")
@app.route("/clients/edit/<int:id>", methods=["GET"])
def edit_client(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute("SELECT * FROM client WHERE id = %s", (id,))
    client = cursor.fetchone()

    return render_template("edit_client.html", client = client)
@app.route("/clients/update/<int:id>", methods = ["POST"])
def update_client(id):
    nom = request.form["nom"]
    contact = request.form["contact"]
    localisation = request.form["localisation"]
    campagne = request.form["campagne"]

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("""
        UPDATE client 
        SET nom = %s, contact = %s, localisation = %s, campagne = %s
        WHERE id = %s
    """, (nom, contact, localisation, campagne, id))

    conn.commit()
    flash("Client modifié avec succès ✅", "success")
    return redirect("/clients")
@app.route("/clients/select/<string:nom>", methods = ["GET"])
def select_client(nom):
    if "user" not in session:
        return redirect("/")
    search = request.args.get("search", "").strip()
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered= True)

    # =========================================================
    # 1. Récupérer les campagnes disponibles pour CE client
    # =========================================================
    cursor.execute("""
    SELECT DISTINCT campagne
    FROM fiche_client
    WHERE client = %s 
    ORDER BY campagne DESC""", 
    (nom,))

    campagnes = cursor.fetchall()

    # ==========================================================
    # 2. INFORMATIONS GÉNÉRALES DU CLIENT
    # ==========================================================
    campagne_selected = request.args.get("campagne")

    # Si aucune campagne n'est sélectionnée,
    # prendre la première campagne disponible
    if not campagne_selected and campagnes:
        campagne_selected = campagnes[0]["campagne"]
    # =========================================================
    # 3. Récupérer les dernières données du client
    #    pour la campagne sélectionnée
    # =========================================================
    client_fiche = []

    if campagne_selected:

        if search :
            cursor.execute("""
                SELECT * 
                FROM fiche_client
                WHERE client = %s
                AND campagne = %s
                AND date LIKE %s
                ORDER BY date DESC
                """, (nom, campagne_selected, f"%{search}%"))

        else:
            cursor.execute("""
                SELECT *
                FROM fiche_client
                WHERE client = %s
                AND campagne = %s
                ORDER BY date ASC
                """, (nom, campagne_selected))

        client_fiche = cursor.fetchall()

    # =========================================================
    # 4. Calculer les statistiques de la campagne
    # =========================================================
    totals = {
                "cumul": 0,
                "poids": 0,
                "livraison": 0,
                "resultat": 0,
                "sac": 0
            }
    def format_number(value):
        if value is None or str(value).strip() == "":
            return ""
        if value == 'None':
            return ""
        return "{:,}".format(int(str(value).replace(" ", ""))).replace(",", " ")

    # On prend la dernière ligne de la campagne
    # pour récupérer les valeurs cumulées finales
    if client_fiche :
        derniere_ligne = client_fiche[-1]

        totals["cumul"] = clean_number(
            derniere_ligne.get("cumul")
        )
        totals["poids"] = clean_number(
            derniere_ligne.get("cumul_poids_net")
        )

        totals["livraison"] = clean_number(
            derniere_ligne.get("cumul_montant_livraison")
        )

        totals["resultat"] = clean_number(
            derniere_ligne.get("resultat_livraison")
        )

        totals["sac"] = clean_number(
            derniere_ligne.get("sac_restant")
        )

    # =========================================================
    # 5. Récupérer les informations générales du client
    # =========================================================
    cursor.execute("""
        SELECT * 
        FROM client
        WHERE nom = %s""", 
        (nom,))
    
    client_info = cursor.fetchone()

    # =========================================================
    # 6. Récupérer la photo de l'utilisateur connecté
    # =========================================================
    cursor.execute("""
        SELECT photo
        FROM utilisateur
        WHERE username = %s""",
        (session["user"],))
    
    user_photo = cursor.fetchone()

    # ==========================================================
    # 7. Affichage
    # ==========================================================

    return render_template(
        "select_client.html",
        nom_client = nom, campagnes = campagnes, campagne_selected = campagne_selected, client_info = client_info, totals=totals, client_select = client_fiche, user = session["user"],
        role = session["role"], format_number=format_number, format_number_after=format_number_after, photo=user_photo["photo"] if user_photo else None)
@app.route("/clients/<nom>")
def voir_client(nom):
    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("SELECT * FROM fiche_client WHERE client = %s", (nom,))
    client = cursor.fetchall()

    return render_template(
        "select_client.html",
        nom_client = nom,
        client_select = client,
        user = session["user"],
        role = session["role"],
        format_number = clean_number,
        format_number_after = format_number_after
    )
@app.route("/clients/delete_fiche/<int:id>", methods = ["POST"])
def delete_client_fiche(id):
    if "user" not in session:
        return redirect("/")

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("SELECT client, campagne FROM fiche_client WHERE id = %s", (id,))
    result = cursor.fetchone()

    if result is None:
        return "Fiche introuvable", 404

    client_nom = result[0]
    campagne = result[1]

    cursor.execute("DELETE FROM fiche_client WHERE id = %s", (id,))
    conn.commit()
    recalculate_fiche_client(client_nom, campagne)
    cursor.close()
    conn.close()
    flash("Fiche Client supprimée avec succès ✅", "success")
    return redirect(url_for("select_client", nom = client_nom))

@app.route("/clients/edit_fiche/<int:id>", methods = ["GET"])
def edit_fiche_client(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary = True, buffered=True)

    cursor.execute("SELECT * FROM fiche_client WHERE id = %s", (id,))
    client = cursor.fetchone()

    return render_template("edit_fiche_client.html", client = client)
@app.route("/clients/update_fiche/<int:id>", methods = ["POST"])
def update_fiche_client(id):
    montant = request.form["montant"]
    date = request.form["date"]
    date_dechargement = request.form["date_dechargement"]
    numero_camion = request.form["numero_camion"]
    numero_fiche = request.form["numero_fiche"]
    poids_net = request.form["poids_net"]
    prix = request.form["prix"]
    sac_reçu = request.form["sac_reçu"]
    sac_livre = request.form["sac_livre"]
    campagne = request.form["campagne"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary = True, buffered=True)

    cursor.execute("SELECT client FROM fiche_client WHERE id = %s", (id,))
    result = cursor.fetchone()

    if result is None:
        return "Fiche introuvable", 404

    client_nom = result["client"]

    montant_livraison = clean_number(poids_net) * clean_number(prix)

    cursor.execute("""
        UPDATE fiche_client 
        SET date = %s, date_dechargement = %s, numero_camion = %s, numero_fiche = %s,
                   poids_net = %s, prix = %s, montant_livraison = %s, 
                   sac_reçu = %s, sac_livre = %s,
                   montant = %s, campagne = %s
        WHERE id = %s
    """, (date, date_dechargement, numero_camion, numero_fiche, poids_net,
           prix, montant_livraison, sac_reçu, sac_livre, montant, campagne, id))

    conn.commit()
    recalculate_fiche_client(client_nom, campagne)
    flash("Fiche Client modifiée avec succès ✅", "success")
    return redirect(url_for("select_client", nom = client_nom))
@app.route("/clients/fiche_clients/add", methods=["POST"])
def add_fiche_client():
    nom = request.form["client"]
    montant = request.form["montant"]
    date = request.form["date"]
    date_dechargement = request.form["date_dechargement"]
    numero_camion = request.form["numero_camion"]
    numero_fiche = request.form["numero_fiche"]
    poids_net = request.form["poids_net"]
    prix = request.form["prix"]
    sac_reçu = request.form["sac_reçu"]
    sac_livre = request.form["sac_livre"]
    campagne = request.form["campagne"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    # 🔥 dernière ligne du pisteur pour cette campagne
    cursor.execute("""
        SELECT *
        FROM fiche_client
        WHERE client = %s AND campagne = %s
        ORDER BY id DESC
        LIMIT 1
    """, (nom, campagne))

    last = cursor.fetchone()

    # =========================
    # INITIALISATION
    # =========================

    last_cumul = 0
    last_poids = 0
    last_cumul_montant_livraison = 0
    last_sac = 0

    if last:
        last_cumul = last["cumul"] or 0
        last_poids = last["cumul_poids_net"] or 0
        last_cumul_montant_livraison = last["cumul_montant_livraison"] or 0
        last_sac = last["sac_restant"] or 0
    
    cumul_poids_net = clean_number(last_poids) + clean_number(poids_net)

    cumul = clean_number(last_cumul) + clean_number(montant)

    montant_livraison = clean_number(poids_net) * clean_number(prix)

    cumul_montant_livraison = clean_number(last_cumul_montant_livraison) + clean_number(montant_livraison)

    sac_restant = clean_number(last_sac) + clean_number(sac_reçu) - clean_number(sac_livre)

    resultat_livraison = cumul - cumul_montant_livraison

    cursor.execute("""
        INSERT INTO fiche_client (client, cumul, date, date_dechargement, numero_camion, numero_fiche,
                   poids_net, cumul_poids_net, prix, montant_livraison, 
                   cumul_montant_livraison, resultat_livraison, sac_reçu, 
                   sac_livre, sac_restant,montant, campagne) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (nom, cumul, date, date_dechargement, numero_camion, numero_fiche, poids_net, cumul_poids_net,
           prix, montant_livraison, cumul_montant_livraison, resultat_livraison, sac_reçu, sac_livre,
            sac_restant,montant, campagne))

    conn.commit()
    return redirect(url_for("select_client", nom = nom))
@app.route("/clients/export/excel")
def export_clients_excel():

    conn = get_db_connection()

    query = "SELECT nom, contact, localisation FROM client"

    df = pd.read_sql(query, conn)

    file_path = "clients.xlsx"

    df.to_excel(file_path, index=False)

    return send_file(
        file_path,
        as_attachment=True
    )
@app.route("/clients/export/pdf")
def export_clients_pdf():

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("""
        SELECT nom, contact, localisation
        FROM client
    """)

    data = cursor.fetchall()

    file_path = "clients.pdf"

    pdf = SimpleDocTemplate(file_path, pagesize=landscape(letter))

    elements = []

    # =========================
    # LOGO
    # =========================
    logo_path = os.path.join("static", "images", "logo.png")

    logo = Image(logo_path, width=80, height=80)

    elements.append(logo)

    # espace
    elements.append(Spacer(1, 20))

    # =========================
    # TITRE
    # =========================

    styles = getSampleStyleSheet()

    date_text = Paragraph( f"Généré le : {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal'])

    elements.append(date_text)

    elements.append(Spacer(1, 20))

    company = Paragraph( "<b>SOCIETE COOPÉRATIVE DES PRODUCTEURS AGRICOLES WOTAGAWENA DE KORHOGO</b>", styles['Heading2'] )

    elements.append(company)

    elements.append(Spacer(1, 20))

    title = Paragraph(
        "<b>Liste des clients</b>",
        styles['Title']
    )

    elements.append(title)

    elements.append(Spacer(1, 20))
    # =========================
    # TABLEAU
    # =========================

    table_data = [
        ["Nom", "Contact", "Localisation"]
    ]

    for row in data:
        table_data.append(list(row))

    table = Table(table_data, repeatRows=1)

    table.setStyle(TableStyle([

        ('BACKGROUND', (0,0), (-1,0), colors.green),

        ('TEXTCOLOR', (0,0), (-1,0), colors.white),

        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),

        ('BOTTOMPADDING', (0,0), (-1,0), 12),

        ('GRID', (0,0), (-1,-1), 1, colors.black),

    ]))

    elements.append(table)

    # =========================
    # BUILD PDF
    # =========================

    pdf.build(elements)

    return send_file(
        file_path,
        as_attachment=True
    )
#------------------------------
@app.route("/fiche_clients/<nom>/export/excel")
def export_fiche_clients_excel(nom):

    conn = get_db_connection()

    query = "SELECT date, montant, cumul, date_dechargement, numero_camion, numero_fiche, poids_net, cumul_poids_net, prix, montant_livraison, cumul_montant_livraison, resultat_livraison, sac_reçu, sac_livre, sac_restant, campagne FROM fiche_client WHERE client = %s"

    df = pd.read_sql(query, conn, params=(nom,))

    file_path = "fiche_clients.xlsx"

    df.to_excel(file_path, index=False)

    return send_file(
        file_path,
        as_attachment=True
    )
@app.route("/fiche_clients/<nom>/export/pdf")
def export_fiche_clients_pdf(nom):

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("""
        SELECT date, montant, cumul, date_dechargement, numero_camion, numero_fiche, poids_net, cumul_poids_net, prix, montant_livraison, cumul_montant_livraison, resultat_livraison, sac_reçu, sac_livre, sac_restant, campagne
        FROM fiche_client
        WHERE client = %s
    """, (nom,))

    data = cursor.fetchall()

    file_path = "fiche_clients.pdf"

    pdf = SimpleDocTemplate(file_path,pagesize=landscape(letter))

    elements = []

    # =========================
    # LOGO
    # =========================
    logo_path = os.path.join("static", "images", "logo.png")

    logo = Image(logo_path, width=80, height=80)

    elements.append(logo)

    # espace
    elements.append(Spacer(1, 20))

    # =========================
    # TITRE
    # =========================

    styles = getSampleStyleSheet()

    date_text = Paragraph( f"Généré le : {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal'])

    elements.append(date_text)

    elements.append(Spacer(1, 20))

    company = Paragraph( "<b>SOCIETE COOPÉRATIVE DES PRODUCTEURS AGRICOLES WOTAGAWENA DE KORHOGO</b>", styles['Heading2'] )

    elements.append(company)

    elements.append(Spacer(1, 20))

    title = Paragraph(
        f"<b>fiche du client : {nom}</b>",
        styles['Title']
    )

    elements.append(title)

    elements.append(Spacer(1, 20))
    # =========================
    # TABLEAU
    # =========================

    table_data = [
        ["Date", "Montant", "Cumul", "Date de déchargement", "Numéro camion", "Numéro fiche", "Poids net", "Cumul poids net", "Prix", "Montant livraison", "Cumul montant livraison", "Résultat livraison", "Sac reçu", "Sac livré", "Sac restant", "Campagne"]
    ]

    for row in data:
        table_data.append(list(row))

    table = Table(table_data, repeatRows=1)

    table.setStyle(TableStyle([

        ('BACKGROUND', (0,0), (-1,0), colors.orange),

        ('TEXTCOLOR', (0,0), (-1,0), colors.white),

        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),

        ('BOTTOMPADDING', (0,0), (-1,0), 12),

        ('GRID', (0,0), (-1,-1), 1, colors.black),

    ]))

    elements.append(table)

    # =========================
    # BUILD PDF
    # =========================

    pdf.build(elements)

    return send_file(
        file_path,
        as_attachment=True
    )
#-------------------------------------------------------------------------------------------
# Routes pisteurs
#-------------------------------------------------------------------------------------------
@app.route("/pisteurs")
def pisteurs():
    if "user" not in session:
        return redirect("/")
    search = request.args.get("search", "").strip()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute("SELECT DISTINCT campagne FROM client")
    campagnes = cursor.fetchall()
    
    campagne = request.args.get("campagne")

    if search:
        cursor.execute("SELECT * FROM pisteur WHERE nom LIKE %s", (f"%{search}%",))
    elif campagne:
        cursor.execute("SELECT * FROM pisteur WHERE campagne = %s ORDER BY nom", (campagne,))
    else:
        cursor.execute("SELECT * FROM pisteur ORDER BY nom")
    data = cursor.fetchall()
    cursor.execute("SELECT photo FROM utilisateur WHERE username=%s", (session["user"],))
    user_photo = cursor.fetchone()
    return render_template("pisteurs.html", campagnes = campagnes, pisteurs = data, user = session["user"],role = session["role"],photo = user_photo["photo"] if user_photo else None)
@app.route("/pisteurs/add", methods=["POST"])
def add_pisteur():
    nom = request.form["nom"]
    zone = request.form["zone"]
    contact = request.form["contact"]
    campagne = request.form["campagne"]

    conn = get_db_connection()
    cursor = conn.cursor()

    # Vérifier si la zone existe
    cursor.execute(
        "SELECT id FROM zone WHERE nom = %s",
        (zone,)
    )

    zone_existante = cursor.fetchone()

    if zone_existante:
        # La zone existe → +1 pisteur
        cursor.execute(
            "UPDATE zone SET nombre_pisteur = nombre_pisteur + 1 WHERE id = %s",
            (zone_existante[0],)
        )
    else:
        # Nouvelle zone → création avec 1 pisteur
        cursor.execute(
            "INSERT INTO zone (nom, nombre_pisteur) VALUES (%s, 1)",
            (zone,)
        )

    cursor.execute(
        "INSERT INTO pisteur (nom, contact, campagne, zone) VALUES (%s, %s, %s, %s)",
        (nom, contact, campagne, zone)
    )

    conn.commit()
    return redirect("/pisteurs")
@app.route("/pisteurs/delete/<int:id>", methods=["POST"])
def delete_pisteur(id):
    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    # Vérifier si la zone existe
    cursor.execute(
        "SELECT nom FROM pisteur WHERE id = %s",
        (id,)
    )

    zone_existante = cursor.fetchone()
    cursor.execute(
        "UPDATE zone SET nombre_pisteur = nombre_pisteur - 1 WHERE nom = %s",
        (zone_existante[0],)
    )
    cursor.execute(
        "DELETE FROM zone WHERE nom = %s AND nombre_pisteur <= 0",
        (zone_existante[0],)
    )
    cursor.execute("DELETE FROM pisteur WHERE id = %s", (id,))

    conn.commit()
    flash("Pisteur supprimé avec succès ✅", "success")
    return redirect("/pisteurs")
@app.route("/pisteurs/edit/<int:id>", methods=["GET"])
def edit_pisteur(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute("SELECT * FROM pisteur WHERE id = %s", (id,))
    pisteur = cursor.fetchone()

    return render_template("edit_pisteur.html", pisteur = pisteur)
@app.route("/pisteurs/update/<int:id>", methods=["POST"])
def update_pisteur(id):
    nom = request.form["nom"]
    zone = request.form["zone"]
    contact = request.form["contact"]
    campagne = request.form["campagne"]

    conn = get_db_connection()
    cursor = conn.cursor()

    # Récupérer l'ancienne zone
    cursor.execute(
        "SELECT zone FROM pisteur WHERE id = %s",
        (id,)
    )

    ancienne_zone = cursor.fetchone()[0]

    if ancienne_zone != zone:
        # Décrémenter le nombre de pisteurs dans l'ancienne zone
        cursor.execute(
            "UPDATE zone SET nombre_pisteur = nombre_pisteur - 1 WHERE nom = %s",
            (ancienne_zone,)
        )

        # Vérifier si la nouvelle zone existe
        cursor.execute(
            "SELECT id FROM zone WHERE nom = %s",
            (zone,)
        )

        nouvelle_zone_existante = cursor.fetchone()

        if nouvelle_zone_existante:
            # La nouvelle zone existe → +1 pisteur
            cursor.execute(
                "UPDATE zone SET nombre_pisteur = nombre_pisteur + 1 WHERE id = %s",
                (nouvelle_zone_existante[0],)
            )
        else:
            # Nouvelle zone → création avec 1 pisteur
            cursor.execute(
                "INSERT INTO zone (nom, nombre_pisteur) VALUES (%s, 1)",
                (zone,)
            )
    else:
        # La zone n'a pas changé, donc on ne fait rien pour les zones
        pass

    cursor.execute("""
        UPDATE pisteur 
        SET nom = %s, zone = %s, contact = %s, campagne = %s
        WHERE id = %s
    """, (nom, zone, contact, campagne, id))

    conn.commit()
    flash("Pisteur modifié avec succès ✅", "success")
    return redirect("/pisteurs")
@app.route("/pisteurs/select/<string:nom>", methods=["GET"])
def select_pisteur(nom):
    if "user" not in session:
        return redirect("/")
    search = request.args.get("search", "").strip()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered= True)

    # =========================================================
    # 1. Récupérer les campagnes disponibles pour CE client
    # =========================================================
    cursor.execute("""
        SELECT DISTINCT campagne
        FROM fiche_pisteur
        WHERE pisteur = %s
        ORDER BY campagne DESC""", (nom,))
    campagnes = cursor.fetchall()

    # =========================================================
    # 2. Récupérer la campagne sélectionnée
    # =========================================================
    #campagne_selected = pisteur_info["campagne"]
    campagne_selected = request.args.get("campagne")

    # Si aucune campagne n'est sélectionnée,
    # prendre la première campagne disponible
    if not campagne_selected and campagnes:
        campagne_selected = campagnes[0]["campagne"]

    # =========================================================
    # 3. Récupérer les dernières données du client
    #    pour la campagne sélectionnée
    # =========================================================
    pisteur_fiche = []

    if campagne_selected:

        if search:
            cursor.execute("""
                SELECT * 
                FROM fiche_pisteur
                WHERE pisteur = %s
                AND campagne = %s
                AND date LIKE %s
                ORDER BY date DESC
            """, (nom, campagne_selected, f"%{search}"))
            pisteur_fiche = cursor.fetchall()

        else:
            cursor.execute("""
                SELECT *
                FROM fiche_pisteur
                WHERE pisteur = %s
                AND campagne = %s
                ORDER BY date ASC""",(nom, campagne_selected))
            pisteur_fiche = cursor.fetchall()
    # =========================================================
    # 4. Calculer les statistiques de la campagne
    # =========================================================
    totals = {
        "poids": 0,
        "debit": 0,
        "credit": 0,
        "solde": 0,
        "sac": 0
    }
    # On prend la dernière ligne de la campagne
    # pour récupérer les valeurs cumulées finales
    if pisteur_fiche:

        derniere_ligne = pisteur_fiche[-1]

        totals["poids"] = clean_number(
            derniere_ligne.get("poids_cumul"))
        
        totals["debit"] = clean_number(
            derniere_ligne.get("debit_cumul"))
        
        totals["credit"] = clean_number(
            derniere_ligne.get("credit_cumul"))
        
        totals["solde"] = clean_number(
            derniere_ligne.get("solde"))
        
        totals["sac"] = clean_number(
            derniere_ligne.get("sac_restant"))
    # =========================================================
    # 5. Récupérer les informations générales du client
    # =========================================================
    cursor.execute("""
        SELECT *
        FROM pisteur
        WHERE nom = %s
    """, (nom,))
        
    pisteur_info = cursor.fetchone()

    # =========================================================
    # 6. Récupérer la photo de l'utilisateur connecté
    # =========================================================
    cursor.execute("""SELECT photo FROM utilisateur WHERE username = %s""", (session["user"],))
    user_photo = cursor.fetchone()

    return render_template("select_pisteur.html",campagnes = campagnes, campagne_selected = campagne_selected, totals = totals, pisteur_info = pisteur_info, nom_pisteur = nom, pisteur_select = pisteur_fiche, user = session["user"],
        role=session["role"], format_number = clean_number, format_number_after = format_number_after, photo = user_photo["photo"] if user_photo else None)
@app.route("/pisteurs/<nom>")
def voir_pisteur(nom):
    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("SELECT * FROM fiche_pisteur WHERE pisteur = %s", (nom,))
    pisteur = cursor.fetchall()

    return render_template(
        "select_pisteur.html",
        nom_pisteur = nom,
        pisteur_select = pisteur,
        user = session["user"],
        role = session["role"],
        format_number = clean_number,
        format_number_after = format_number_after
    )
@app.route("/pisteurs/delete_fiche/<int:id>", methods = ["POST"])
def delete_pisteur_fiche(id):
    if "user" not in session:
        return redirect("/")

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("SELECT pisteur, campagne FROM fiche_pisteur WHERE id = %s", (id,))
    result = cursor.fetchone()

    if result is None:
        return "Fiche introuvable", 404

    pisteur_nom = result[0]
    campagne = result[1]

    cursor.execute("DELETE FROM fiche_pisteur WHERE id = %s", (id,))
    conn.commit()
    recalculate_fiche_pisteur(pisteur_nom, campagne)
    cursor.close()
    conn.close()
    flash("Fiche Pisteur supprimée avec succès ✅", "success")
    return redirect(url_for("select_pisteur", nom=pisteur_nom))

@app.route("/pisteurs/edit_fiche/<int:id>", methods=["GET"])
def edit_fiche_pisteur(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary = True, buffered=True)

    cursor.execute("SELECT * FROM fiche_pisteur WHERE id = %s", (id,))
    pisteur = cursor.fetchone()

    return render_template("edit_fiche_pisteur.html", pisteur = pisteur)
@app.route("/pisteurs/update_fiche/<int:id>", methods = ["POST"])
def update_fiche_pisteur(id):
    date = request.form["date"]

    prix = int(request.form["prix"])
    poids_net = int(request.form["poids_net"])

    debit = int(request.form["debit"])
    #credit = int(request.form["credit"])

    sac_reçu = int(request.form["sac_reçu"])
    sac_livre = int(request.form["sac_livre"])

    detail = request.form["detail"]
    campagne = request.form["campagne"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute("SELECT pisteur FROM fiche_pisteur WHERE id = %s", (id,))
    result = cursor.fetchone()

    if result is None:
        return "Fiche introuvable", 404

    pisteur_nom = result["pisteur"]
    credit = clean_number(poids_net) * clean_number(prix)

    cursor.execute("""
            UPDATE fiche_pisteur
            SET
                date = %s, prix = %s, poids_net = %s, debit = %s, credit = %s,
                sac_reçu = %s, sac_livre = %s, detail = %s, campagne = %s
            WHERE id = %s
        """, ( date, prix, poids_net, debit, credit, sac_reçu,
            sac_livre, detail, campagne, id ))

    conn.commit()
    recalculate_fiche_pisteur(pisteur_nom, campagne)
    flash("Fiche Pisteur modifiée avec succès ✅", "success")
    return redirect(url_for("select_pisteur", nom = pisteur_nom))

@app.route("/pisteurs/fiche_pisteur/add", methods = ["POST"])
def add_fiche_pisteur():
    pisteur = request.form["pisteur"]
    date = request.form["date"]

    prix = request.form["prix"]
    poids_net = request.form["poids_net"]

    debit = request.form["debit"]

    sac_recu = request.form["sac_reçu"]
    sac_livre = request.form["sac_livre"]

    detail = request.form["detail"]
    campagne = request.form["campagne"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    # 🔥 dernière ligne du pisteur pour cette campagne
    cursor.execute("""
        SELECT *
        FROM fiche_pisteur
        WHERE pisteur = %s AND campagne = %s
        ORDER BY id DESC
        LIMIT 1
    """, (pisteur, campagne))

    last = cursor.fetchone()

    # =========================
    # INITIALISATION
    # =========================

    last_poids = 0
    last_debit = 0
    last_credit = 0
    last_sac = 0

    if last:
        last_poids = last["poids_cumul"] or 0
        last_debit = last["debit_cumul"] or 0
        last_credit = last["credit_cumul"] or 0
        last_sac = last["sac_restant"] or 0

    # =========================
    # CALCULS AUTOMATIQUES
    # =========================
    credit = clean_number(poids_net) * clean_number(prix)

    poids_cumul = clean_number(last_poids) + clean_number(poids_net)

    debit_cumul = clean_number(last_debit) + clean_number(debit)

    credit_cumul = clean_number(last_credit) + clean_number(credit)

    solde = debit_cumul - credit_cumul

    sac_restant = clean_number(last_sac) + clean_number(sac_recu) - clean_number(sac_livre)

    # =========================
    # INSERT
    # =========================

    cursor.execute("""
        INSERT INTO fiche_pisteur (
            pisteur, date, prix, poids_net, poids_cumul, debit, debit_cumul, credit, credit_cumul,
            solde, sac_reçu, sac_livre, sac_restant, detail, campagne ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (pisteur, date, prix, poids_net, poids_cumul, debit, debit_cumul, credit, credit_cumul,
        solde, sac_recu, sac_livre, sac_restant, detail, campagne ))

    conn.commit()

    flash("Fiche ajoutée avec succès ✅", "success")

    return redirect(url_for("select_pisteur", nom = pisteur))
@app.route("/pisteurs/export/excel")
def export_pisteurs_excel():

    conn = get_db_connection()

    query = "SELECT nom, contact, zone FROM pisteur"

    df = pd.read_sql(query, conn)

    file_path = "pisteurs.xlsx"

    df.to_excel(file_path, index=False)

    return send_file(
        file_path,
        as_attachment=True
    )
@app.route("/pisteurs/export/pdf")
def export_pisteurs_pdf():

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("""
        SELECT nom, contact, zone
        FROM pisteur
    """)

    data = cursor.fetchall()

    file_path = "pisteurs.pdf"

    pdf = SimpleDocTemplate(file_path, pagesize=landscape(letter))

    elements = []

    # =========================
    # LOGO
    # =========================
    logo_path = os.path.join("static", "images", "logo.png")

    logo = Image(logo_path, width=80, height=80)

    elements.append(logo)

    # espace
    elements.append(Spacer(1, 20))

    # =========================
    # TITRE
    # =========================

    styles = getSampleStyleSheet()

    date_text = Paragraph( f"Généré le : {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal'])

    elements.append(date_text)

    elements.append(Spacer(1, 20))

    company = Paragraph( "<b>SOCIETE COOPÉRATIVE DES PRODUCTEURS AGRICOLES WOTAGAWENA DE KORHOGO</b>", styles['Heading2'] )

    elements.append(company)

    elements.append(Spacer(1, 20))

    title = Paragraph(
        "<b>Liste des pisteurs</b>",
        styles['Title']
    )

    elements.append(title)

    elements.append(Spacer(1, 20))
    # =========================
    # TABLEAU
    # =========================

    table_data = [
        ["Nom", "Contact", "Zone"]
    ]

    for row in data:
        table_data.append(list(row))

    table = Table(table_data, repeatRows=1)

    table.setStyle(TableStyle([

        ('BACKGROUND', (0,0), (-1,0), colors.orange),

        ('TEXTCOLOR', (0,0), (-1,0), colors.white),

        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),

        ('BOTTOMPADDING', (0,0), (-1,0), 12),

        ('GRID', (0,0), (-1,-1), 1, colors.black),

    ]))

    elements.append(table)

    # =========================
    # BUILD PDF
    # =========================

    pdf.build(elements)

    return send_file(
        file_path,
        as_attachment=True
    )
@app.route("/fiche_pisteurs/<nom>/export/excel")
def export_fiche_pisteurs_excel(nom):

    conn = get_db_connection()

    query = "SELECT detail, date, prix, poids_net, poids_cumul, debit, debit_cumul, credit, credit_cumul, solde, sac_reçu, sac_livre, sac_restant, campagne FROM fiche_pisteur WHERE pisteur = %s"

    df = pd.read_sql(query, conn, params=(nom,))

    file_path = "fiche_pisteurs.xlsx"

    df.to_excel(file_path, index=False)

    return send_file(file_path, as_attachment=True)
@app.route("/fiche_pisteurs/<nom>/export/pdf")
def export_fiche_pisteurs_pdf(nom):

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("""
        SELECT detail, date, prix, poids_net, poids_cumul, debit, debit_cumul, credit, credit_cumul, solde, sac_reçu, sac_livre, sac_restant, campagne
        FROM fiche_pisteur WHERE pisteur = %s
    """, (nom,))

    data = cursor.fetchall()

    file_path = "fiche_pisteurs.pdf"

    pdf = SimpleDocTemplate(file_path, pagesize=landscape(letter))

    elements = []

    # =========================
    # LOGO
    # =========================
    logo_path = os.path.join("static", "images", "logo.png")

    logo = Image(logo_path, width=80, height=80)

    elements.append(logo)

    # espace
    elements.append(Spacer(1, 20))

    # =========================
    # TITRE
    # =========================

    styles = getSampleStyleSheet()

    date_text = Paragraph( f"Généré le : {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal'])

    elements.append(date_text)

    elements.append(Spacer(1, 20))

    company = Paragraph( "<b>SOCIETE COOPÉRATIVE DES PRODUCTEURS AGRICOLES WOTAGAWENA DE KORHOGO</b>", styles['Heading2'] )

    elements.append(company)

    elements.append(Spacer(1, 20))

    title = Paragraph(
        f"<b>fiche du pisteur : {nom}</b>",
        styles['Title']
    )

    elements.append(title)

    elements.append(Spacer(1, 20))
    # =========================
    # TABLEAU
    # =========================

    table_data = [
        ["Détail", "Date", "Prix", "Poids Net", "Poids Cumul", "Débit", "Débit Cumul", "Crédit", "Crédit Cumul", "Solde", "Sac Reçu", "Sac Livré", "Sac Restant", "Campagne"]
    ]

    for row in data:
        table_data.append(list(row))

    table = Table(table_data, repeatRows=1)

    table.setStyle(TableStyle([

        ('BACKGROUND', (0,0), (-1,0), colors.orange),

        ('TEXTCOLOR', (0,0), (-1,0), colors.white),

        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),

        ('BOTTOMPADDING', (0,0), (-1,0), 12),

        ('GRID', (0,0), (-1,-1), 1, colors.black),

    ]))

    elements.append(table)

    # =========================
    # BUILD PDF
    # =========================

    pdf.build(elements)

    return send_file(
        file_path,
        as_attachment=True
    )
#----------------------------------------------------------------
# Routes Missions Camions
#----------------------------------------------------------------
@app.route("/transports")
def mission_camions():
    if "user" not in session:
        return redirect("/")
    
    search = request.args.get("search", "").strip()
    campagne_selected = request.args.get("campagne", "")
    client_selected = request.args.get("client", "")
    destination_selected = request.args.get("destination", "")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered = True)

    # =====================================================
    # 1. Historique des mouvements
    # =====================================================
    query = """ SELECT * FROM mission_camion WHERE 1=1"""
    params = []

    if search:
        query += " AND (client LIKE %s OR campagne LIKE %s OR destination LIKE %s)"
        params.extend([
            f"%{search}"
            f"%{search}"
            f"%{search}"
        ])
    if campagne_selected:
        query += " AND campagne =%s"
        params.append(campagne_selected)
    if client_selected:
        query += " AND client = %s"
        params.append(client_selected)
    if destination_selected:
        query += " AND destination = %s"
        params.append(destination_selected)

    query += " ORDER BY date_depart DESC"

    cursor.execute(query, params)
    data = cursor.fetchall()

    # =====================================================
    # 2. Résumé actuel des livraisons
    # =====================================================
    
    query_mission = """ 
        SELECT
            campagne,
            client,
            destination,

            COUNT(*) AS nombre_livraisons,

            COUNT(DISTINCT camion) AS nombre_camions,

            SUM(quantite_poids) AS poids_total,

            SUM(nombre_sacs) AS sacs_total

        FROM mission_camion

        WHERE etat = 'LIVRE'

        GROUP BY campagne, client, destination
        ORDER BY campagne DESC, client, destination
    """
    cursor.execute(query_mission)
    mission_summary = cursor.fetchall()

    # =====================================================
    # 3. Campagnes disponibles
    # =====================================================
    cursor.execute("""
        SELECT DISTINCT campagne 
        FROM mission_camion
        ORDER BY campagne DESC
    """)
    campagnes = cursor.fetchall()

    # =====================================================
    # 4. Total livraisons
    # =====================================================
    total_poids = sum(
        row["poids_total"] or 0
        for row in mission_summary
    )

    total_sacs = sum(
        row["sacs_total"] or 0
        for row in mission_summary
    )

    total_livraisons = sum(
        row["nombre_livraisons"] or 0
        for row in mission_summary
    )

    # =====================================================
    # 5. Clients disponibles
    # =====================================================
    cursor.execute("""
        SELECT DISTINCT client
        FROM mission_camion
        ORDER BY client
    """)
    clients = cursor.fetchall()

    # =====================================================
    # 6. Photo utilisateur
    # =====================================================
    cursor.execute("SELECT photo FROM utilisateur WHERE username=%s", (session["user"],))
    user_photo = cursor.fetchone()

    return render_template("camions.html", camions = data,format_number =clean_number, format_number_after = format_number_after, mission_summary = mission_summary, total_poids = total_poids, total_sacs = total_sacs, total_livraisons = total_livraisons, campagnes = campagnes, user = session["user"],
        role = session["role"], clients = clients, campagne_selected = campagne_selected, destination_selected = destination_selected, client_selected = client_selected, photo = user_photo["photo"] if user_photo else None)
@app.route("/transports/add", methods=["POST"])
def add_mission_camions():
    camion = request.form["camion"]
    client = request.form["client"]
    campagne = request.form["campagne"]
    date_depart = request.form["date_depart"]
    destination = request.form["destination"]
    quantite_poids = request.form["quantite_poids"]
    nombre_sacs = request.form["nombre_sacs"]
    etat = request.form["etat"]

    conn = get_db_connection()
    cursor = conn.cursor(buffered = True)

    cursor.execute(
        "INSERT INTO mission_camion (camion, client, campagne, date_depart, destination, quantite_poids, nombre_sacs, etat) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (camion, client, campagne, date_depart, destination, quantite_poids, nombre_sacs, etat )
    )
    conn.commit()
    flash("Ligne ajoutée avec succès ✅", "success")
    return redirect(url_for("mission_camions"))
@app.route("/transports/delete/<int:id>", methods=["POST"])
def delete_mission_camion(id):
    conn = get_db_connection()
    cursor = conn.cursor(buffered = True)

    cursor.execute("DELETE FROM mission_camion WHERE id = %s", (id,))

    conn.commit()
    flash("Ligne supprimée avec succès ✅", "success")
    return redirect("/transports")
@app.route("/transports/edit/<int:id>", methods=["GET"])
def edit_mission_camion(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute("SELECT * FROM mission_camion WHERE id = %s", (id,))
    livraison = cursor.fetchone()

    return render_template("edit_mission_camion.html", livraison = livraison)
@app.route("/transports/update/<int:id>", methods=["POST"])
def update_mission_camion(id):
    camion = request.form["camion"]
    client = request.form["client"]
    campagne = request.form["campagne"]
    date_depart = request.form["date_depart"]
    destination = request.form["destination"]
    quantite_poids = request.form["quantite_poids"]
    nombre_sacs = request.form["nombre_sacs"]
    etat = request.form["etat"]

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE mission_camion
        SET camion = %s, client = %s, campagne = %s, date_depart =%s, destination = %s, quantite_poids = %s,
        nombre_sacs = %s, etat = %s
        WHERE id = %s
    """, (camion, client, campagne, date_depart, destination, quantite_poids, nombre_sacs, etat, id))

    conn.commit()
    flash("Ligne modifiée avec succès ✅", "success")
    return redirect(url_for("mission_camions"))
@app.route("/transports/export/excel")
def export_mission_camion_excel():

    conn = get_db_connection()

    query = "SELECT * FROM mission_camion"

    df = pd.read_sql(query, conn)

    file_path = "historique_mission_camions.xlsx"

    df.to_excel(file_path, index=False)

    return send_file(
        file_path,
        as_attachment=True
    )
@app.route("/transports/export/pdf")
def export_mission_camion_pdf():

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("""SELECT
            camion,
            client,
            campagne,
            date_depart,
            destination,
            quantite_poids,
            nombre_sacs,
            etat
        FROM mission_camion """)

    data = cursor.fetchall()

    file_path = "historique_livraisons.pdf"

    pdf = SimpleDocTemplate(file_path, pagesize=landscape(letter))

    elements = []

    # =========================
    # LOGO
    # =========================
    logo_path = os.path.join("static", "images", "logo.png")

    logo = Image(logo_path, width=80, height=80)

    elements.append(logo)

    # espace
    elements.append(Spacer(1, 20))

    # =========================
    # TITRE
    # =========================

    styles = getSampleStyleSheet()

    date_text = Paragraph( f"Généré le : {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal'])

    elements.append(date_text)

    elements.append(Spacer(1, 20))

    company = Paragraph( "<b>SOCIETE COOPÉRATIVE DES PRODUCTEURS AGRICOLES WOTAGAWENA DE KORHOGO</b>", styles['Heading2'] )

    elements.append(company)

    elements.append(Spacer(1, 20))

    title = Paragraph(
        "<b>Histique des livraisons enregistrées</b>",
        styles['Title']
    )

    elements.append(title)

    elements.append(Spacer(1, 20))
    # =========================
    # TABLEAU
    # =========================

    table_data = [
        ["N° camion", "Client", "Campagne", "Date départ", "Destination", "Qté Poids", "Nombre sacs", "Etat"]
    ]

    for row in data:
        table_data.append(list(row))

    table = Table(table_data, repeatRows=1)

    table.setStyle(TableStyle([

        ('BACKGROUND', (0,0), (-1,0), colors.orange),

        ('TEXTCOLOR', (0,0), (-1,0), colors.white),

        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),

        ('BOTTOMPADDING', (0,0), (-1,0), 12),

        ('GRID', (0,0), (-1,-1), 1, colors.black),

    ]))

    elements.append(table)

    # =========================
    # BUILD PDF
    # =========================

    pdf.build(elements)

    return send_file(
        file_path,
        as_attachment=True
    )
#-----------------------------------------------------------------------
# Routes Zones
#------------------------------------------------------------------------
@app.route("/zones")
def zones():
    if "user" not in session:
        return redirect("/")
    search = request.args.get("search", "").strip()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)
    if search:
        cursor.execute("""
            SELECT *
            FROM zone
            WHERE nom LIKE %s
            ORDER BY nom
        """, (f"%{search}%",))
    else:
        cursor.execute("""
            SELECT *
            FROM zone
            ORDER BY nom
        """)

    data = cursor.fetchall()
    cursor.execute("SELECT photo FROM utilisateur WHERE username=%s", (session["user"],))
    user_photo = cursor.fetchone()
    return render_template("zones.html", zones=data, user=session["user"],
        role=session["role"], photo = user_photo["photo"] if user_photo else None)
@app.route("/zones/add", methods=["POST"])
def add_zone():
    nom = request.form["nom"]
    nombre_pisteur = request.form["nombre_pisteur"]

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute(
        "INSERT INTO zone (nom, nombre_pisteur) VALUES (%s, %s)",
        (nom, nombre_pisteur)
    )
    conn.commit()
    return redirect("/zones")
@app.route("/zones/delete/<int:id>", methods=["POST"])
def delete_zone(id):
    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("DELETE FROM zone WHERE id = %s", (id,))

    conn.commit()
    flash("Zone supprimée avec succès ✅", "success")
    return redirect("/zones")
@app.route("/zones/edit/<int:id>", methods=["GET"])
def edit_zone(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute("SELECT * FROM zone WHERE id = %s", (id,))
    zone = cursor.fetchone()

    return render_template("edit_zone.html", zone=zone)
@app.route("/zones/update/<int:id>", methods=["POST"])
def update_zone(id):
    nom = request.form["nom"]
    nombre_pisteur = request.form["nombre_pisteur"]

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("""
        UPDATE zone 
        SET nom = %s, nombre_pisteur = %s
        WHERE id = %s
    """, (nom, nombre_pisteur, id))

    conn.commit()
    flash("Zone modifiée avec succès ✅", "success")
    return redirect("/zones")
@app.route("/zones/export/excel")
def export_zones_excel():

    conn = get_db_connection()

    query = "SELECT nom, nombre_pisteur FROM zone"

    df = pd.read_sql(query, conn)

    file_path = "zones.xlsx"

    df.to_excel(file_path, index=False)

    return send_file(
        file_path,
        as_attachment=True
    )
@app.route("/zones/export/pdf")
def export_zones_pdf():

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("""
        SELECT nom, nombre_pisteur
        FROM zone
    """)

    data = cursor.fetchall()

    file_path = "zones.pdf"

    pdf = SimpleDocTemplate(file_path, pagesize=landscape(letter))

    elements = []

    # =========================
    # LOGO
    # =========================
    logo_path = os.path.join("static", "images", "logo.png")

    logo = Image(logo_path, width=80, height=80)

    elements.append(logo)

    # espace
    elements.append(Spacer(1, 20))

    # =========================
    # TITRE
    # =========================

    styles = getSampleStyleSheet()

    date_text = Paragraph( f"Généré le : {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal'])

    elements.append(date_text)

    elements.append(Spacer(1, 20))

    company = Paragraph( "<b>SOCIETE COOPÉRATIVE DES PRODUCTEURS AGRICOLES WOTAGAWENA DE KORHOGO</b>", styles['Heading2'] )

    elements.append(company)

    elements.append(Spacer(1, 20))

    title = Paragraph(
        "<b>Liste des zones enregistrées</b>",
        styles['Title']
    )

    elements.append(title)

    elements.append(Spacer(1, 20))
    # =========================
    # TABLEAU
    # =========================

    table_data = [
        ["Zone", "Nombre de pisteurs"]
    ]

    for row in data:
        table_data.append(list(row))

    table = Table(table_data, repeatRows=1)

    table.setStyle(TableStyle([

        ('BACKGROUND', (0,0), (-1,0), colors.orange),

        ('TEXTCOLOR', (0,0), (-1,0), colors.white),

        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),

        ('BOTTOMPADDING', (0,0), (-1,0), 12),

        ('GRID', (0,0), (-1,-1), 1, colors.black),

    ]))

    elements.append(table)

    # =========================
    # BUILD PDF
    # =========================

    pdf.build(elements)

    return send_file(
        file_path,
        as_attachment=True
    )
#----------------------------------------------------------------
# Routes Produits
#----------------------------------------------------------------
@app.route("/produits")
def produits():
    if "user" not in session:
        return redirect("/")
    search = request.args.get("search", "").strip()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)
    if search:
        cursor.execute("""
            SELECT *
            FROM produit
            WHERE nom LIKE %s
            ORDER BY nom
        """, (f"%{search}%",))
    else:
        cursor.execute("""
            SELECT *
            FROM produit
            ORDER BY nom
        """)
    data = cursor.fetchall()
    cursor.execute("SELECT photo FROM utilisateur WHERE username=%s", (session["user"],))
    user_photo = cursor.fetchone()
    return render_template("produits.html", produits=data, user=session["user"],
        role=session["role"], photo = user_photo["photo"] if user_photo else None)
@app.route("/produits/add", methods=["POST"])
def add_produit():
    nom = request.form["nom"]

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute(
        "INSERT INTO produit (nom) VALUES (%s)",
        (nom,)
    )
    conn.commit()
    return redirect("/produits")
@app.route("/produits/delete/<int:id>", methods=["POST"])
def delete_produit(id):
    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("DELETE FROM produit WHERE id = %s", (id,))

    conn.commit()
    flash("Produit supprimé avec succès ✅", "success")
    return redirect("/produits")
@app.route("/produits/edit/<int:id>", methods=["GET"])
def edit_produit(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute("SELECT * FROM produit WHERE id = %s", (id,))
    produit = cursor.fetchone()

    return render_template("edit_produit.html", produit=produit)
@app.route("/produits/update/<int:id>", methods=["POST"])
def update_produit(id):
    nom = request.form["nom"]

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("""
        UPDATE produit 
        SET nom = %s
        WHERE id = %s
    """, (nom, id))

    conn.commit()
    flash("Produit modifié avec succès ✅", "success")
    return redirect("/produits")
@app.route("/produits/export/excel")
def export_produits_excel():

    conn = get_db_connection()

    query = "SELECT nom FROM produit"

    df = pd.read_sql(query, conn)

    file_path = "produits.xlsx"

    df.to_excel(file_path, index=False)

    return send_file(
        file_path,
        as_attachment=True
    )
@app.route("/produits/export/pdf")
def export_produits_pdf():

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("""
        SELECT nom
        FROM produit
    """)

    data = cursor.fetchall()

    file_path = "produits.pdf"

    pdf = SimpleDocTemplate(file_path, pagesize=landscape(letter))

    elements = []

    # =========================
    # LOGO
    # =========================
    logo_path = os.path.join("static", "images", "logo.png")

    logo = Image(logo_path, width=80, height=80)

    elements.append(logo)

    # espace
    elements.append(Spacer(1, 20))

    # =========================
    # TITRE
    # =========================

    styles = getSampleStyleSheet()

    date_text = Paragraph( f"Généré le : {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal'])

    elements.append(date_text)

    elements.append(Spacer(1, 20))

    company = Paragraph( "<b>SOCIETE COOPÉRATIVE DES PRODUCTEURS AGRICOLES WOTAGAWENA DE KORHOGO</b>", styles['Heading2'] )

    elements.append(company)

    elements.append(Spacer(1, 20))

    title = Paragraph(
        "<b>Liste des produits enregistrés</b>",
        styles['Title']
    )

    elements.append(title)

    elements.append(Spacer(1, 20))
    # =========================
    # TABLEAU
    # =========================

    table_data = [
        ["Produits"]
    ]

    for row in data:
        table_data.append(list(row))

    table = Table(table_data, repeatRows=1)

    table.setStyle(TableStyle([

        ('BACKGROUND', (0,0), (-1,0), colors.orange),

        ('TEXTCOLOR', (0,0), (-1,0), colors.white),

        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),

        ('BOTTOMPADDING', (0,0), (-1,0), 12),

        ('GRID', (0,0), (-1,-1), 1, colors.black),

    ]))

    elements.append(table)

    # =========================
    # BUILD PDF
    # =========================

    pdf.build(elements)

    return send_file(
        file_path,
        as_attachment=True
    )
#----------------------------------------------------------------
# Routes stocks
#----------------------------------------------------------------
@app.route("/stocks")
def stocks():
    if "user" not in session:
        return redirect("/")
    
    search = request.args.get("search", "").strip()
    campagne_selected = request.args.get("campagne", "")
    produit_selected = request.args.get("produit", "")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered = True)

    # =====================================================
    # 1. Historique des mouvements
    # =====================================================
    query = """ SELECT * FROM mouvement_stock WHERE 1=1"""
    params = []

    if search:
        query += " AND (produit LIKE %s OR campagne LIKE %s)"
        params.extend([
            f"%{search}"
            f"%{search}"
        ])
    if campagne_selected:
        query += " AND campagne =%s"
        params.append(campagne_selected)
    if produit_selected:
        query += " AND produit = %s"
        params.append(produit_selected)

    query += " ORDER BY date_mouvement DESC"

    cursor.execute(query, params)
    data = cursor.fetchall()

    # =====================================================
    # 2. Résumé actuel des stocks
    # =====================================================
    
    query_stock = """ 
        SELECT produit, campagne, 
            SUM( 
                CASE
                    WHEN type_mouvement = 'ENTREE'
                    THEN quantite_poids
                    ELSE 0
                END
            ) AS total_entree_poids,
            SUM(
                CASE
                    WHEN type_mouvement = 'SORTIE'
                    THEN quantite_poids
                    ELSE 0
                END
            )AS total_sortie_poids,
            SUM(
                CASE
                    WHEN type_mouvement = 'ENTREE'
                    THEN nombre_sacs
                    ELSE 0
                END
            ) AS total_entree_sacs,
            SUM(
                CASE 
                    WHEN type_mouvement = 'SORTIE'
                    THEN nombre_sacs
                    ELSE 0
                END
            ) AS total_sortie_sacs

        FROM mouvement_stock
        GROUP BY produit, campagne
        ORDER BY campagne, produit
    """
    cursor.execute(query_stock)
    stock_summary = cursor.fetchall()

    # =====================================================
    # 3. Calcul du stock disponible
    # =====================================================
    for stock in stock_summary :
        stock["stock_poids"] = (
            (stock["total_entree_poids"] or 0) - (stock["total_sortie_poids"] or 0)
        )
        stock["stock_sacs"] = (
            (stock["total_entree_sacs"] or 0) - (stock["total_sortie_sacs"] or 0)
        )
    # =====================================================
    # 4. Campagnes disponibles
    # =====================================================
    cursor.execute("""
        SELECT DISTINCT campagne 
        FROM mouvement_stock
        ORDER BY campagne DESC
    """)
    campagnes = cursor.fetchall()

    # =====================================================
    # ! Stock dispo
    # =====================================================
    total_poids_stock = sum(
        stock["stock_poids"] or 0
        for stock in stock_summary
    )

    total_sacs_stock = sum(
        stock["stock_sacs"] or 0
        for stock in stock_summary
    )

    total_produits = len(stock_summary)

    # =====================================================
    # 5. Produits disponibles
    # =====================================================
    cursor.execute("""
        SELECT DISTINCT produit
        FROM mouvement_stock
        ORDER BY produit
    """)
    produits = cursor.fetchall()

    # =====================================================
    # 6. Photo utilisateur
    # =====================================================
    cursor.execute("SELECT photo FROM utilisateur WHERE username=%s", (session["user"],))
    user_photo = cursor.fetchone()

    return render_template("stocks.html",format_number = clean_number, format_number_after = format_number_after, stocks = data, stock_summary = stock_summary, total_poids_stock = total_poids_stock, total_sacs_stock = total_sacs_stock, total_produits = total_produits, campagnes = campagnes, user = session["user"],
        role = session["role"], produits = produits, campagne_selected = campagne_selected, produit_selected = produit_selected, photo = user_photo["photo"] if user_photo else None)
@app.route("/stocks/add", methods=["POST"])
def add_stock():
    created_at = request.form["created_at"]
    produit = request.form["produit"]
    type_mouvement = request.form["type_mouvement"]
    date_mouvement = request.form["date_mouvement"]
    quantite_poids = request.form["quantite_poids"]
    nombre_sacs = request.form["nombre_sacs"]
    campagne = request.form["campagne"]

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute(
        "INSERT INTO mouvement_stock (produit, type_mouvement, quantite_poids, nombre_sacs, date_mouvement," \
        "campagne, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (produit, type_mouvement, quantite_poids, nombre_sacs, date_mouvement, campagne, created_at )
    )
    conn.commit()
    flash("Ligne ajoutée avec succès ✅", "success")
    return redirect(url_for("stocks"))
@app.route("/stocks/delete/<int:id>", methods=["POST"])
def delete_stock(id):
    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("DELETE FROM mouvement_stock WHERE id = %s", (id,))

    conn.commit()
    flash("Ligne supprimée avec succès ✅", "success")
    return redirect("/stocks")
@app.route("/stocks/edit/<int:id>", methods=["GET"])
def edit_stock(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute("SELECT * FROM mouvement_stock WHERE id = %s", (id,))
    stock = cursor.fetchone()

    return render_template("edit_stock.html", stock = stock)
@app.route("/stocks/update/<int:id>", methods=["POST"])
def update_stock(id):
    produit = request.form["produit"]
    type_mouvement = request.form["type_mouvement"]
    quantite_poids = request.form["quantite_poids"]
    nombre_sacs = request.form["nombre_sacs"]
    date_mouvement = request.form["date_mouvement"]
    campagne = request.form["campagne"]
    created_at = request.form["created_at"]

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("""
        UPDATE mouvement_stock
        SET produit = %s, type_mouvement = %s, quantite_poids = %s, nombre_sacs = %s,
        date_mouvement = %s, campagne = %s, created_at = %s 
        WHERE id = %s
    """, (produit, type_mouvement, quantite_poids, nombre_sacs, date_mouvement, campagne,
        created_at, id))

    conn.commit()
    flash("Ligne modifiée avec succès ✅", "success")
    return redirect(url_for("stocks"))
@app.route("/stocks/export/excel")
def export_stocks_excel():

    conn = get_db_connection()

    query = "SELECT * FROM mouvement_stock"

    df = pd.read_sql(query, conn)

    file_path = "historique_stocks.xlsx"

    df.to_excel(file_path, index=False)

    return send_file(
        file_path,
        as_attachment=True
    )
@app.route("/stocks/export/pdf")
def export_stocks_pdf():

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("""SELECT
            created_at,
            produit,
            type_mouvement,
            date_mouvement,
            quantite_poids,
            nombre_sacs,
            campagne
        FROM mouvement_stock """)

    data = cursor.fetchall()

    file_path = "historique_stock.pdf"

    pdf = SimpleDocTemplate(file_path, pagesize=landscape(letter))

    elements = []

    # =========================
    # LOGO
    # =========================
    logo_path = os.path.join("static", "images", "logo.png")

    logo = Image(logo_path, width=80, height=80)

    elements.append(logo)

    # espace
    elements.append(Spacer(1, 20))

    # =========================
    # TITRE
    # =========================

    styles = getSampleStyleSheet()

    date_text = Paragraph( f"Généré le : {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal'])

    elements.append(date_text)

    elements.append(Spacer(1, 20))

    company = Paragraph( "<b>SOCIETE COOPÉRATIVE DES PRODUCTEURS AGRICOLES WOTAGAWENA DE KORHOGO</b>", styles['Heading2'] )

    elements.append(company)

    elements.append(Spacer(1, 20))

    title = Paragraph(
        "<b>Histique des stocks enregistrés</b>",
        styles['Title']
    )

    elements.append(title)

    elements.append(Spacer(1, 20))
    # =========================
    # TABLEAU
    # =========================

    table_data = [
        ["Date enregistrement", "Produit", "ENTREE/SORTIE", "Date E/S", "Qté Poids", "Nombre sacs", "Campagne"]
    ]

    for row in data:
        table_data.append(list(row))

    table = Table(table_data, repeatRows=1)

    table.setStyle(TableStyle([

        ('BACKGROUND', (0,0), (-1,0), colors.orange),

        ('TEXTCOLOR', (0,0), (-1,0), colors.white),

        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),

        ('BOTTOMPADDING', (0,0), (-1,0), 12),

        ('GRID', (0,0), (-1,-1), 1, colors.black),

    ]))

    elements.append(table)

    # =========================
    # BUILD PDF
    # =========================

    pdf.build(elements)

    return send_file(
        file_path,
        as_attachment=True
    )
#----------------------------------------------------------------
# Routes campagnes
#----------------------------------------------------------------
@app.route("/campagnes")
def campagnes():
    if "user" not in session:
        return redirect("/")
    search = request.args.get("search", "").strip()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    if search:
        cursor.execute("""
            SELECT *
            FROM campagne
            WHERE nom LIKE %s
            ORDER BY nom
        """, (f"%{search}%",))
    else:
        cursor.execute("""
            SELECT *
            FROM campagne
            ORDER BY nom
        """)

    data = cursor.fetchall()
    cursor.execute("SELECT photo FROM utilisateur WHERE username=%s", (session["user"],))
    user_photo = cursor.fetchone()
    return render_template("campagnes.html", campagnes=data, user=session["user"],
        role=session["role"], photo = user_photo["photo"] if user_photo else None)
@app.route("/campagnes/add", methods=["POST"])
def add_campagne():
    nom = request.form["nom"]
    statut = request.form["statut"]

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute(
        "INSERT INTO campagne (nom, statut) VALUES (%s, %s)",
        (nom,statut)
    )
    conn.commit()
    return redirect("/campagnes")
@app.route("/campagnes/delete/<int:id>", methods=["POST"])
def delete_campagne(id):
    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("DELETE FROM campagne WHERE id = %s", (id,))

    conn.commit()
    flash("Campagne supprimée avec succès ✅", "success")
    return redirect("/campagnes")
@app.route("/campagnes/edit/<int:id>", methods=["GET"])
def edit_campagne(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute("SELECT * FROM campagne WHERE id = %s", (id,))
    campagne = cursor.fetchone()

    return render_template("edit_campagnes.html", campagne=campagne)
@app.route("/campagnes/update/<int:id>", methods=["POST"])
def update_campagne(id):
    nom = request.form["nom"]
    statut = request.form["statut"]

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("""
        UPDATE campagne 
        SET nom = %s, statut = %s
        WHERE id = %s
    """, (nom, statut,id))

    conn.commit()
    flash("Campagne modifiée avec succès ✅", "success")
    return redirect("/campagnes")
@app.route("/campagnes/export/excel")
def export_campagnes_excel():

    conn = get_db_connection()

    query = "SELECT nom, statut FROM campagne"

    df = pd.read_sql(query, conn)

    file_path = "campagnes.xlsx"

    df.to_excel(file_path, index=False)

    return send_file(
        file_path,
        as_attachment=True
    )
@app.route("/campagnes/export/pdf")
def export_campagnes_pdf():

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute(""" SELECT nom, statut FROM campagne """)

    data = cursor.fetchall()

    file_path = "campagnes.pdf"

    pdf = SimpleDocTemplate(file_path, pagesize=landscape(letter))

    elements = []

    # =========================
    # LOGO
    # =========================
    logo_path = os.path.join("static", "images", "logo.png")

    logo = Image(logo_path, width=80, height=80)

    elements.append(logo)

    # espace
    elements.append(Spacer(1, 20))

    # =========================
    # TITRE
    # =========================

    styles = getSampleStyleSheet()

    date_text = Paragraph( f"Généré le : {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal'])

    elements.append(date_text)

    elements.append(Spacer(1, 20))

    company = Paragraph( "<b>SOCIETE COOPÉRATIVE DES PRODUCTEURS AGRICOLES WOTAGAWENA DE KORHOGO</b>", styles['Heading2'] )

    elements.append(company)

    elements.append(Spacer(1, 20))

    title = Paragraph(
        "<b>Liste des campagnes enregistrées</b>",
        styles['Title']
    )

    elements.append(title)

    elements.append(Spacer(1, 20))
    # =========================
    # TABLEAU
    # =========================

    table_data = [
        ["Campagnes"], ["Statut"]
    ]

    for row in data:
        table_data.append(list(row))

    table = Table(table_data, repeatRows=1)

    table.setStyle(TableStyle([

        ('BACKGROUND', (0,0), (-1,0), colors.orange),

        ('TEXTCOLOR', (0,0), (-1,0), colors.white),

        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),

        ('BOTTOMPADDING', (0,0), (-1,0), 12),

        ('GRID', (0,0), (-1,-1), 1, colors.black),

    ]))

    elements.append(table)

    # =========================
    # BUILD PDF
    # =========================

    pdf.build(elements)

    return send_file(
        file_path,
        as_attachment=True
    )
#----------------------------------------------------------------
# routes settings
#----------------------------------------------------------------
@app.route("/settings", methods=["GET", "POST"])
def settings():
    if "user" not in session:
        return redirect("/")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary = True, buffered = True)

    # 👉 GESTION DU FORMULAIRE
    if request.method == "POST":
        app_name = request.form.get("app_name")
        file = request.files.get("logo")

        if file and allowed_file(file.filename):
            import uuid
            filename = str(uuid.uuid4()) + "_" + secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            cursor.execute(
                "UPDATE settings SET logo=%s, app_name=%s WHERE id=1",
                (filename, app_name)
            )
        else:
            cursor.execute(
                "UPDATE settings SET app_name=%s WHERE id=1",
                (app_name,)
            )

        conn.commit()
    cursor.execute("SELECT photo FROM utilisateur WHERE username=%s", (session["user"],))
    user_photo = cursor.fetchone()
    # 👉 RÉCUPÉRATION SETTINGS
    cursor.execute("SELECT * FROM settings WHERE id=1")
    settings_data = cursor.fetchone()

    # 👉 STATS
    stats = {}

    cursor.execute("SELECT COUNT(*) as total FROM client")
    stats["clients"] = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM pisteur")
    stats["pisteurs"] = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM produit")
    stats["produits"] = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM campagne")
    stats["campagnes"] = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM utilisateur")
    stats["utilisateurs"] = cursor.fetchone()["total"]

    cursor.execute("SELECT DISTINCT produit FROM mouvement_stock")
    produit_stock = cursor.fetchall()
    stats["produits_stock"] = len(produit_stock)

    return render_template(
        "settings.html",
        settings=settings_data,
        stats=stats,
        user=session["user"],
        role=session["role"],
        photo = user_photo["photo"] if user_photo else None
    )
#----------------------------------------------------------------
# Routes clients statistiques
#----------------------------------------------------------------
@app.route("/clients-statistiques")
def clients_statistiques():
    if "user" not in session:
        return redirect("/")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)
    # 👉 récupérer les campagnes disponibles
    cursor.execute("SELECT DISTINCT campagne FROM fiche_client")
    campagnes = cursor.fetchall()

    campagne = request.args.get("campagne")
    #campagne = "CAJOU 2026"
    
    query = """
        SELECT 
            c.id,
            cl.nom AS client,
            c.campagne,
            c.cumul,
            c.cumul_poids_net,
            c.cumul_montant_livraison,
            c.resultat_livraison,
            c.sac_restant
        FROM fiche_client c
        JOIN client cl ON cl.nom = c.client
        WHERE c.id IN (
            SELECT MAX(id)
            FROM fiche_client
            WHERE campagne = %s
            GROUP BY client
        )
        AND c.campagne = %s
    """
    cursor.execute(query, (campagne,campagne))
    data = cursor.fetchall()

    # 👉 calcul des totaux en Python (simple et clair)
    totals = {
        "cumul": 0,
        "poids": 0,
        "livraison": 0,
        "resultat": 0,
        "sac": 0
    }
    def clean_number(value):
        if value is None:
            return 0
        if value == '':
            return 0
        if value == 'None':
            return 0
        return int(str(value).replace(" ", ""))
    def format_number(value):
        if value is None or str(value).strip() == "":
            return ""
        if value == 'None':
            return ""
        return "{:,}".format(int(str(value).replace(" ", ""))).replace(",", " ")
    for row in data:
        totals["cumul"] += clean_number(row["cumul"]) or 0
        totals["poids"] += clean_number(row["cumul_poids_net"]) or 0
        totals["livraison"] += clean_number(row["cumul_montant_livraison"]) or 0
        totals["resultat"] += clean_number(row["resultat_livraison"]) or 0
        totals["sac"] += clean_number(row["sac_restant"]) or 0
    cursor.execute("SELECT photo FROM utilisateur WHERE username=%s", (session["user"],))
    user_photo = cursor.fetchone()
    return render_template(
        "clients-statistiques.html",
        data = data,
        totals = totals,
        format_number = format_number,
        campagnes = campagnes,
        user = session["user"],
        role = session["role"],
        photo = user_photo["photo"] if user_photo else None
    )
#----------------------------------------------------------------
# Routes pisteurs statistiques
#----------------------------------------------------------------
@app.route("/pisteurs-statistiques")
def pisteurs_statistiques():
    if "user" not in session:
        return redirect("/")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)
    # 👉 récupérer les campagnes disponibles
    cursor.execute("SELECT DISTINCT campagne FROM fiche_pisteur")
    campagnes = cursor.fetchall()

    campagne = request.args.get("campagne")
    #campagne = "CAJOU 2026"
    
    query = """
        SELECT 
            c.id,
            cl.nom AS pisteur,
            c.campagne,
            c.poids_cumul,
            c.debit_cumul,
            c.credit_cumul,
            c.solde,
            c.sac_restant
        FROM fiche_pisteur c
        JOIN pisteur cl ON cl.nom = c.pisteur
        WHERE c.id IN (
            SELECT MAX(id)
            FROM fiche_pisteur
            WHERE campagne = %s
            GROUP BY pisteur
        )
        AND c.campagne = %s
    """
    cursor.execute(query, (campagne,campagne))
    data = cursor.fetchall()

    # 👉 calcul des totaux en Python (simple et clair)
    totals = {
        "poids": 0,
        "debit": 0,
        "credit": 0,
        "solde": 0,
        "sac": 0
    }
    def format_number(value):
        if value is None or str(value).strip() == "":
            return ""
        if value == 'None':
            return ""
        return "{:,}".format(int(str(value).replace(" ", ""))).replace(",", " ")
    for row in data:
        totals["poids"] += clean_number(row["poids_cumul"]) or 0
        totals["debit"] += clean_number(row["debit_cumul"]) or 0
        totals["credit"] += clean_number(row["credit_cumul"]) or 0
        totals["solde"] += clean_number(row["solde"]) or 0
        totals["sac"] += clean_number(row["sac_restant"]) or 0
    cursor.execute("SELECT photo FROM utilisateur WHERE username=%s", (session["user"],))
    user_photo = cursor.fetchone()
    return render_template(
        "pisteurs-statistiques.html",
        data = data,
        totals = totals,
        format_number = format_number,
        campagnes = campagnes,
        user = session["user"],
        role = session["role"],
        photo = user_photo["photo"] if user_photo else None
    )
#----------------------------------------------------------------
# Routes utilisateurs
#----------------------------------------------------------------
@app.route("/users")
def users():
    if "user" not in session:
        return redirect("/")
    role = session["role"]
    if role != "Admin":
        return render_template("acces-denied.html")
    search = request.args.get("search", "").strip()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    if search:
        cursor.execute("""
            SELECT *
            FROM utilisateur
            WHERE username LIKE %s
            ORDER BY username
        """, (f"%{search}%",))
    else:
        cursor.execute("SELECT * FROM utilisateur")
    users = cursor.fetchall()
    cursor.execute("SELECT photo FROM utilisateur WHERE username=%s", (session["user"],))
    user_photo = cursor.fetchone()
    return render_template(
        "users.html",
        user=session["user"],
        role=session["role"],
        users=users,
        photo=user_photo["photo"] if user_photo else None
    )
@app.route("/users/add", methods=["POST"])
def add_user():
    username = request.form["username"]
    email = request.form["email"]
    password = request.form["password"]
    role = request.form["role"]

    hashed = hashlib.sha256(password.encode()).hexdigest()

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute(
        "INSERT INTO utilisateur (email,username, password, role) VALUES (%s, %s, %s, %s)",
        (email,username, hashed, role)
    )

    conn.commit()
    return redirect("/users")
@app.route("/users/delete/<int:id>", methods=["POST"])
def delete_user(id):
    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("DELETE FROM utilisateur WHERE id = %s", (id,))

    conn.commit()
    flash("Utilisateur supprimé avec succès ✅", "success")
    return redirect("/users")
@app.route("/users/edit/<int:id>", methods=["GET"])
def edit_user(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    cursor.execute("SELECT * FROM utilisateur WHERE id = %s", (id,))
    user = cursor.fetchone()

    return render_template("edit_user.html", user=user)
@app.route("/users/update/<int:id>", methods=["POST"])
def update_user(id):
    username = request.form["username"]
    email = request.form["email"]
    password = request.form["password"]
    role = request.form["role"]

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)
    if password:
        hashed = hashlib.sha256(password.encode()).hexdigest()
        password_final = hashed
    else:
        cursor.execute("SELECT password FROM utilisateur WHERE id = %s", (id,))
        result = cursor.fetchone()
        if result is None:
            return "Utilisateur introuvable", 404
        password_final = result[0]

    cursor.execute("""
        UPDATE utilisateur 
        SET email = %s, username = %s, password = %s, role = %s
        WHERE id = %s 
    """, (email, username, password_final, role, id))

    conn.commit()
    flash("Utilisateur modifié avec succès ✅", "success")
    return redirect("/users")
@app.route("/users/export/excel")
def export_users_excel():

    conn = get_db_connection()

    query = "SELECT username, email, role FROM utilisateur"

    df = pd.read_sql(query, conn)

    file_path = "users.xlsx"

    df.to_excel(file_path, index=False)

    return send_file(
        file_path,
        as_attachment=True
    )
@app.route("/users/export/pdf")
def export_users_pdf():

    conn = get_db_connection()
    cursor = conn.cursor(buffered=True)

    cursor.execute("""
        SELECT username, email, role
        FROM utilisateur
    """)

    data = cursor.fetchall()

    file_path = "users.pdf"

    pdf = SimpleDocTemplate(file_path, pagesize=landscape(letter))

    elements = []

    # ======================================
    # LOGO
    # ======================================
    logo_path = os.path.join("static", "images", "logo.png")

    logo = Image(logo_path, width=80, height=80)

    elements.append(logo)

    # espace
    elements.append(Spacer(1, 20))

    # ======================================
    # TITRE
    # ======================================

    styles = getSampleStyleSheet()

    date_text = Paragraph( f"Généré le : {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal'])

    elements.append(date_text)

    elements.append(Spacer(1, 20))

    company = Paragraph( "<b>SOCIETE COOPÉRATIVE DES PRODUCTEURS AGRICOLES WOTAGAWENA DE KORHOGO</b>", styles['Heading2'] )

    elements.append(company)

    elements.append(Spacer(1, 20))

    title = Paragraph(
        "<b>Liste des utilisateurs enregistrés</b>",
        styles['Title']
    )

    elements.append(title)

    elements.append(Spacer(1, 20))
    # =========================
    # TABLEAU
    # =========================

    table_data = [
        ["Username", "Email", "Role"]
    ]

    for row in data:
        table_data.append(list(row))

    table = Table(table_data, repeatRows=1)

    table.setStyle(TableStyle([

        ('BACKGROUND', (0,0), (-1,0), colors.orange),

        ('TEXTCOLOR', (0,0), (-1,0), colors.white),

        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),

        ('BOTTOMPADDING', (0,0), (-1,0), 12),

        ('GRID', (0,0), (-1,-1), 1, colors.black),

    ]))

    elements.append(table)

    # =========================
    # BUILD PDF
    # =========================

    pdf.build(elements)

    return send_file(
        file_path,
        as_attachment=True
    )
#----------------------------------------------------------------
#  Gestion du profil
#----------------------------------------------------------------
@app.route("/profil", methods=["GET", "POST"])
def profil():
    if "user" not in session:
        return redirect("/")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    # récupération de l'utilisateur connecté
    cursor.execute(
        "SELECT * FROM utilisateur WHERE username=%s",
        (session["user"],)
    )
    user = cursor.fetchone()

    if request.method == "POST":

        nouveau_nom = request.form.get("username")
        ancien_mdp = request.form.get("old_password")
        nouveau_mdp = request.form.get("new_password")
        confirmation = request.form.get("confirm_password")

        # changement du nom
        if nouveau_nom and nouveau_nom != user["username"]:
            cursor.execute(
                "UPDATE utilisateur SET username=%s WHERE id=%s",
                (nouveau_nom, user["id"])
            )
            session["user"] = nouveau_nom

        # changement du mot de passe
        if ancien_mdp and nouveau_mdp:

            cursor.execute(
                "SELECT password FROM utilisateur WHERE id=%s",
                (user["id"],)
            )
            current_password = cursor.fetchone()["password"]
            #hash_password(password) == user["password"]
            if hash_password(ancien_mdp) != current_password:
                flash("Ancien mot de passe incorrect.", "danger")
                return redirect("/profil")

            elif nouveau_mdp != confirmation:
                flash("Les deux nouveaux mots de passe sont différents.", "danger")
                return redirect("/profil")
            else:
                hashed = hashlib.sha256(nouveau_mdp.encode()).hexdigest()
                password_final = hashed
                cursor.execute(
                    "UPDATE utilisateur SET password=%s WHERE id=%s",
                    (password_final, user["id"])
                )
                flash("Mot de passe modifié avec succès.", "success")
                return redirect("/profil")
            
        file = request.files.get("photo")

        # changement de la photo de profil
        if file and allowed_file(file.filename):
            import uuid

            filename = str(uuid.uuid4()) + "_" + secure_filename(file.filename)

            filepath = os.path.join(
                app.config["PROFILE_UPLOAD_FOLDER"],
                filename
            )

            file.save(filepath)

            cursor.execute("""
                UPDATE utilisateur
                SET photo=%s
                WHERE id=%s
            """, (filename, user["id"]))

        conn.commit()

        return redirect("/profil")

    return render_template(
        "profil.html",
        user=user
    )
#----------------------------------------------------------------
# Log out
#----------------------------------------------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))
#----------------------------------------------------------------
# Pour lancer l'app
#----------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)