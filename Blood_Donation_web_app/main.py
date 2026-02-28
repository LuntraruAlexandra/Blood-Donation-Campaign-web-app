from flask import Flask, render_template, request, redirect, url_for, session
import pyodbc
import hashlib
import os
import random
from datetime import datetime, timedelta
app = Flask(__name__)
# A secret key is required for sessions.
app.secret_key = 'cheie_secreta_si_complexa_pentru_sesiuni' 

# --- DB CONNECTION DETAILS ---
server = 'bdplatforma.database.windows.net' 
database = 'Tema_38_gestiune_platforma_donare_sange'
username = 'student_login'
password = 'ParolaMea123!' 

def get_connection():
    # conexiune cu server sql
    conn_string = (
        f"Driver={{ODBC Driver 17 for SQL Server}};"
        f"Server=tcp:{server},1433;"
        f"Database={database};"
        f"Uid={username};"
        f"Pwd={password};"
    )
    try:
        conn = pyodbc.connect(conn_string)
        return conn
    except pyodbc.Error as e:
        print(f"DB connection error: {e}")
        return None

def hash_password(password):
    # Hash parola cu SHA256
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def sign_up(nume, prenume, email, parola, rol, cnp=None, data_nasterii=None, grupa_sange=None, oras=None):
    if rol == 'donator' and cnp and len(cnp) != 13:
        return False
        
    valid_blood_groups = ['0pos', '0neg', 'Apos', 'Aneg', 'Bpos', 'Bneg', 'ABpos', 'ABneg']
    if rol == 'donator' and grupa_sange and grupa_sange not in valid_blood_groups:
        return False

    conn = get_connection()
    if conn is None: return False
    
    cursor = conn.cursor()
    hashed_password = hash_password(parola)
    
    try:
        insert_user_query = "INSERT INTO Utilizator (Nume, Prenume, Email, ParolaCriptata, Rol, DataInregistrarii) OUTPUT INSERTED.IDUtilizator VALUES (?, ?, ?, ?, ?, GETDATE())"
        #OUTPUT INSERTED, forteaza baza de date sa trimita inapoi o valoare dupa inserare
        #trimite ID ul(generat automat cu autoincrement)--> util pt cazul Donator
        #GETDATE() pt returnarea datei inregistrarii
        #? --> placeholderi pt prevenirea atacuri asupra bazei de date(se da o comanda care o afecteaza)
        valid_roles = ['donator', 'doctor', 'organizator_campanie', 'utilizator_standard']
        rol = rol if rol in valid_roles else 'utilizator_standard'

        cursor.execute(insert_user_query, nume, prenume, email, hashed_password, rol)
        user_id_row = cursor.fetchone()
        if not user_id_row:
            conn.rollback()
            return False
        
        user_id = user_id_row[0]

        if rol == 'donator':
            if not all([cnp, data_nasterii, grupa_sange, oras]):
                conn.rollback()
                return False 
            
            grupa_sange_db = grupa_sange[:3] 
            #explicatie ca mai sus pt cazul cand utilizatorul este Donator
            insert_donor_query = "INSERT INTO Donator (Nume, Prenume, CNP, DataNasterii, GrupaSange, Oras, IDUtilizator) VALUES (?, ?, ?, ?, ?, ?, ?)"
            cursor.execute(insert_donor_query, nume, prenume, cnp, data_nasterii, grupa_sange_db, oras, user_id)

        conn.commit()#salveaz definitiv modificarile
        return True
    except pyodbc.Error:
        conn.rollback()#gestionare erori(pt a nu ramane date incomplete)
        return False
    finally:
        conn.close()

def login(email, parola):
    conn = get_connection()
    if conn is None: return None
    cursor = conn.cursor()
    #din nou un placeholder pentru SELECT dar query ul primeste parola criptata dupa ce a fost prelucrata de fct python
    select_query = "SELECT IDUtilizator, Nume, Prenume, ParolaCriptata, Rol FROM Utilizator WHERE Email = ?"
    try:
        cursor.execute(select_query, email)
        user_data = cursor.fetchone()
        if user_data:
            user_id, nume, prenume, stored_hash, rol = user_data
            if hash_password(parola) == stored_hash:
                return {'ID': user_id, 'Email': email, 'Rol': rol, 'nume': nume, 'prenume': prenume}
        return None
    finally:
        conn.close()

# ----------------------------------------------------------------------
# Flask Routes
# ----------------------------------------------------------------------
#mai jos ruta principala pentru Dashbord(pt index) in functie de rolul utilizatorului
@app.route('/')
def index():
    if 'user' not in session:
        return redirect(url_for('login_page'))
    
    user = session['user']
    conn = get_connection()
    data = {}

    if conn:
        cursor = conn.cursor()
        try:
            if user['Rol'] == 'donator':
                # maparea intre utilizator si Donator pentru a selecta informatiile
                #"extra" specifice doar donatorului
                #semnul intrebarii se inlocuieste cu user['ID'] la rulare
                #in tabelul Donator avem si IDUtilizator
                cursor.execute("""
                    SELECT d.IDDonator, d.GrupaSange, d.Oras 
                    FROM Donator d 
                    WHERE d.IDUtilizator = ?
                """, user['ID'])
                donor_info = cursor.fetchone()
                
                if donor_info:
                    id_donator = donor_info[0]
                    data['donor_details'] = {'grupa': donor_info[1], 'oras': donor_info[2]}
                    
                    #ii dam ca parametru (in loc de "?") pe id_donator
                    #extrage ultima evaluare(le ia descrescator dupa data si apoi extrage pe prima->top 1)
                    cursor.execute("""
                        SELECT TOP 1 DataEvaluarii, Tensiune, Greutate, Hemoglobina, Eligibil 
                        FROM IstoricSanatate 
                        WHERE IDDonator = ? 
                        ORDER BY DataEvaluarii DESC
                    """, id_donator)
                    data['last_health'] = cursor.fetchone()
                    
                    #aici se afiseaza ultimele 3 programari alte utilizatorului
                    #vrem sa afisam si cu campania corespunzatoare deci join pe tabelul cu campanii
                    #am folosit cast pentru ca aveam erori atunci cand incercam sa compar cu data de azi
                    #comparatie cu data de azi pentru a nu ma raporta la date din trecut
                    cursor.execute("""
                        SELECT TOP 3 p.DataProgramare, c.Nume, p.Status 
                        FROM Programare p 
                        JOIN Campanie c ON p.IDCampanie = c.IDCampanie 
                        WHERE p.IDDonator = ? 
                        AND CAST(p.DataProgramare AS DATE) >= CAST(GETDATE() AS DATE)
                        ORDER BY p.DataProgramare ASC
                    """, id_donator)
                    data['programari'] = cursor.fetchall()
                    #logica pentru notificari
                    #dar notificrile i le-am trimis numai utilizatorului care era donator
                    #deci a trebuit sa folosesc subcerere pentru potrivirea id-urilor
                    cursor.execute("""
                    SELECT n.Titlu, n.Mesaj, n.DataTrimiterii, n.Citita 
                    FROM Notificare n
                    JOIN Programare p ON n.IDProgramare = p.IDProgramare
                    WHERE p.IDDonator = (SELECT IDDonator FROM Donator WHERE IDUtilizator = ?)
                    ORDER BY n.DataTrimiterii DESC
                """, user['ID'])
                data['notificari'] = cursor.fetchall()
                data['nr_notificari_noi'] = sum(1 for n in data['notificari'] if not n.Citita)

            elif user['Rol'] == 'organizator_campanie':
                #am relatia N:N intre Locatii si campanii in ideea ca pot 
                #sa am aceeasi campanie in mai multe locatii
                #si aceeasi locatie sa sustina mai multe campanii
                #de aceea atunci cand e nevoie de afisare si a locatiei si a campaniei
                #este nevoie de un JOIN (de exemplu la verificare campaniilor pt a face o programare)
                query_campanii = """
                    SELECT 
                        c.IDCampanie,       -- index 0
                        c.Nume,             -- index 1
                        c.DataInceput,      -- index 2
                        c.DataSfarsit,      -- index 3
                        l.Nume as Locatie,  -- index 4 (venit din Locatie)
                        (SELECT COUNT(*) FROM Programare p WHERE p.IDCampanie = c.IDCampanie) as NrInscrisi, -- index 5
                        (SELECT COUNT(*) FROM Donatie d WHERE d.IDCampanie = c.IDCampanie) as NrDonatii,     -- index 6
                        c.TelefonCampanie,  -- index 7
                        c.EmailCampanie,    -- index 8
                        c.Organizator       -- index 9 (Entitatea: ex. Crucea Roșie)
                    FROM Campanie c
                    LEFT JOIN Locatie l ON c.IDLocatie = l.IDLocatie
                    ORDER BY c.DataInceput DESC
                """
                cursor.execute(query_campanii)
                data['campanii_proprii'] = cursor.fetchall()
                
                #locatii preluate din dropdown-ul din modal
                cursor.execute("SELECT IDLocatie, Nume, Oras FROM Locatie ORDER BY Oras ASC")
                data['locatii_disponibile'] = cursor.fetchall()
        except Exception as e:
            print(f"Eroare Index: {e}")
        finally:
            conn.close()

    # mesaj succes/eroare ce se afiseaza in interfata
    message = request.args.get('message')
    return render_template('index.html', user=user, data=data, message=message)

@app.route('/signup', methods=['GET', 'POST'])
def signup_page():
    roles = [{'value': 'donator', 'name': 'Donator'}, {'value': 'doctor', 'name': 'Doctor'}, {'value': 'organizator_campanie', 'name': 'Organizator'}, {'value': 'utilizator_standard', 'name': 'Utilizator Standard'}]
    blood_groups = ['0pos', '0neg', 'Apos', 'Aneg', 'Bpos', 'Bneg', 'ABpos', 'ABneg']

    if request.method == 'POST':
        nume, prenume, email = request.form['nume'], request.form['prenume'], request.form['email']
        parola, rol = request.form['parola'], request.form.get('rol', 'utilizator_standard')
        cnp, data_nasterii, grupa_sange, oras = request.form.get('cnp'), request.form.get('data_nasterii'), request.form.get('grupa_sange'), request.form.get('oras')
        
        if sign_up(nume, prenume, email, parola, rol, cnp, data_nasterii, grupa_sange, oras):
            return redirect(url_for('login_page', message='Înregistrare reușită!'))
        return render_template('signup.html', roles=roles, blood_groups=blood_groups, error='Eroare la înregistrare.')
    return render_template('signup.html', roles=roles, blood_groups=blood_groups) 

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        user_info = login(request.form['email'], request.form['parola'])
        if user_info:
            session['user'] = user_info
            return redirect(url_for('index'))
        return render_template('login.html', error='Email sau parolă incorectă.')
    return render_template('login.html', message=request.args.get('message'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login_page', message='Deconectat cu succes.'))

@app.route('/campanii')
def campanii():
    if 'user' not in session: return redirect(url_for('login_page'))
    conn = get_connection()
    if not conn: return "Eroare DB", 500
    cur = conn.cursor()
    #afisarea camapniilor(fara cele din trecut (terminate)) de la cea mai apropiata pana la cea mai departata in viitor
    cur.execute("SELECT IDCampanie, Nume, Organizator, DataInceput, DataSfarsit FROM Campanie WHERE DataSfarsit >= GETDATE() ORDER BY DataInceput ASC")
    rows = cur.fetchall()
    campaigns = [{'id': r[0], 'nume': r[1], 'organizator': r[2], 'inceput': r[3].strftime('%d.%m.%Y'), 'sfarsit': r[4].strftime('%d.%m.%Y')} for r in rows]
    conn.close()
    return render_template('campanii.html', user=session['user'], campaigns=campaigns)



# --- RUTE DOCTOR ---
@app.route('/doctor/cauta_pacient', methods=['GET', 'POST'])
def cauta_pacient():
    if 'user' not in session or session['user']['Rol'] != 'doctor': return redirect(url_for('login_page'))
    pacienti, nume_cautat = [], request.form.get('nume_cautat', '')
    if request.method == 'POST' and nume_cautat:
        conn = get_connection()
        cur = conn.cursor()
        #cautam donatorul la care doctorul vrea sa ii vada/modifice istoricul
        #LIkE in loc de "=" pentru o cautare mai usoara
        #de exemplu "Popes" va afisa "Popescu"
        cur.execute("SELECT IDDonator, Nume, Prenume, CNP, GrupaSange FROM Donator WHERE Nume LIKE ? OR Prenume LIKE ?", (f'%{nume_cautat}%', f'%{nume_cautat}%'))
        pacienti = cur.fetchall()
        conn.close()
    return render_template('doctor_cauta.html', pacienti=pacienti, nume_cautat=nume_cautat)

@app.route('/doctor/adauga_istoric/<int:id_donator>', methods=['GET', 'POST'])
def adauga_istoric(id_donator):
    if 'user' not in session or session['user']['Rol'] != 'doctor': 
        return redirect(url_for('login_page'))
        
    if request.method == 'POST':
        # preluarea datelor scrise de doctor pt un nou istoric de sanatate
        tensiune = request.form.get('tensiune')
        greutate = request.form.get('greutate')
        hemoglobina = request.form.get('hemoglobina')
        eligibil = request.form.get('eligibil')
        puls = request.form.get('puls')
        observatii = request.form.get('observatii')
        full_obs = f"Puls: {puls} bpm. {observatii}"

        conn = get_connection()
        if conn:
            try:
                cur = conn.cursor()
                #acum se vor insera datele in tabel
                #data automata a istoricului cu GETDATE()
                query = """
                    INSERT INTO IstoricSanatate 
                    (IDDonator, DataEvaluarii, Tensiune, Greutate, Hemoglobina, Eligibil, Observatii) 
                    VALUES (?, GETDATE(), ?, ?, ?, ?, ?)
                """
                cur.execute(query, (id_donator, tensiune, greutate, hemoglobina, eligibil, full_obs))
                
                # commit pt salvarea modificarilor in baza de date
                conn.commit() 
                print(f"Istoric salvat cu succes pentru donatorul {id_donator}")
                
            except Exception as e:
                print(f"Eroare la scrierea în baza de date: {e}")
                conn.rollback() #anulare operatie daca avem eroare
            finally:
                conn.close()
                
        #redirect pt doctor inapoi la dashboard
        return redirect(url_for('index', message="Evaluarea a fost salvată în baza de date!"))
        
    return render_template('doctor_form_istoric.html', id_donator=id_donator)

@app.route('/doctor/programari', methods=['GET', 'POST'])
def gestiune_programari():
    if 'user' not in session or session['user']['Rol'] != 'doctor': 
        return redirect(url_for('login_page'))
    
    conn = get_connection()
    if not conn: return "Eroare DB", 500
    
    cursor = conn.cursor()
    if request.method == 'POST':
        id_prog = request.form.get('id_programare')
        #actiunea de finalizare a unei programari pt doctor
        try:
            cursor.execute("UPDATE Programare SET Status = 'incheiata' WHERE IDProgramare = ?", id_prog)
            conn.commit()
        except:
            cursor.execute("UPDATE Programare SET Status = 'finalizata' WHERE IDProgramare = ?", id_prog)
            conn.commit()

    try:
        # pt afisarea programarilor si join pt asocierea lor cu donatorii
        cursor.execute("""
            SELECT p.IDProgramare, d.Nume, d.Prenume, p.DataProgramare, p.Status 
            FROM Programare p 
            JOIN Donator d ON p.IDDonator = d.IDDonator 
            ORDER BY p.DataProgramare DESC
        """)
        programari = cursor.fetchall()
    except Exception as e:
        print(f"Eroare afișare programări doctor: {e}")
        programari = []
    finally:
        conn.close()
        
    return render_template('doctor_programari.html', programari=programari)
@app.route('/get_istoric_sanatate')
def get_istoric_sanatate():
    if 'user' not in session: 
        return {"error": "Unauthorized"}, 401
    
    user = session['user']
    conn = get_connection()
    istoric_list = []
    
    if conn:
        cursor = conn.cursor()
        try:
            # folosim JOIN pentru a lega Utilizatorul de Donator si apoi de IstoricSanatate
            query = """
                SELECT 
                    i.DataEvaluarii, 
                    i.Tensiune, 
                    i.Greutate, 
                    i.Hemoglobina, 
                    i.Eligibil, 
                    i.Observatii 
                FROM IstoricSanatate i
                JOIN Donator d ON i.IDDonator = d.IDDonator
                WHERE d.IDUtilizator = ?
                ORDER BY i.DataEvaluarii DESC
            """
            cursor.execute(query, user['ID'])
            rows = cursor.fetchall()
            
            for r in rows:
                istoric_list.append({
                    'data': r[0].strftime('%d.%m.%Y') if r[0] else "N/A",
                    'tensiune': r[1],
                    'greutate': r[2],
                    'hemoglobina': r[3],
                    'eligibil': r[4],
                    'observatii': r[5] if r[5] else "Fără observații"
                })
        except Exception as e:
            print(f"Eroare SQL Istoric JOIN: {e}")
        finally:
            conn.close()
            
    return {"istoric": istoric_list}

@app.route('/rezerva_loc/<int:id_campanie>', methods=['POST'])
def rezerva_loc(id_campanie):
    if 'user' not in session: return redirect(url_for('login_page'))
    
    conn = get_connection()
    if not conn: return "Eroare DB", 500
    
    cur = conn.cursor()
    try:
        # extragerea intervalul campaniei
        cur.execute("SELECT DataInceput, DataSfarsit FROM Campanie WHERE IDCampanie = ?", id_campanie)
        campanie = cur.fetchone()
        
        if not campanie:
            return redirect(url_for('index', message="Campania nu există."))

        data_start = campanie[0]
        data_sfarsit = campanie[1]

        #pt logica programarii doar am generat o data random in acel interval 
        delta = data_sfarsit - data_start
        int_delta = int(delta.total_seconds())
        
        if int_delta > 0:
            random_second = random.randrange(int_delta)
            data_random_programare = data_start + timedelta(seconds=random_second)
        else:
            data_random_programare = data_start # Dacă campania e de o singură zi

        #inserarea programarii
        #se pune implicit ca este in asteptare
        #se verifica daca ultimul istoric este eligibil
        query = """
            INSERT INTO Programare (IDDonator, IDCampanie, DataProgramare, Status)
            SELECT d.IDDonator, ?, ?, 'in_asteptare'
            FROM Donator d
            WHERE d.IDUtilizator = ? 
            AND 'DA' = (
                SELECT TOP 1 Eligibil FROM IstoricSanatate 
                WHERE IDDonator = d.IDDonator ORDER BY DataEvaluarii DESC
            )
        """
        cur.execute(query, (id_campanie, data_random_programare, session['user']['ID']))
        
        if cur.rowcount > 0:
            conn.commit()
            message = f"Loc rezervat cu succes pentru data de: {data_random_programare.strftime('%d.%m.%Y %H:%M')}"
        else:
            message = "Eroare: Nu ești eligibil medical sau contul nu este configurat corect."
            
    except Exception as e:
        print(f"Eroare rezervare: {e}")
        message = f"Eroare la procesarea rezervării."
    finally:
        conn.close()
        
    return redirect(url_for('index', message=message))
@app.route('/get_toate_programarile')
def get_toate_programarile():
    if 'user' not in session:
        return {"error": "Neautorizat"}, 401
    
    user = session['user']
    conn = get_connection()
    programari_lista = []
    
    if conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT IDDonator FROM Donator WHERE IDUtilizator = ?", user['ID'])
            row = cursor.fetchone()
            if row:
                id_donator = row[0]
                #toate programarile si asocierea cu campaniile la care sunt
                cursor.execute("""
                    SELECT p.DataProgramare, c.Nume, p.Status, p.IDProgramare 
                    FROM Programare p 
                    JOIN Campanie c ON p.IDCampanie = c.IDCampanie 
                    WHERE p.IDDonator = ?
                    ORDER BY p.DataProgramare DESC
                """, id_donator)
                
                for r in cursor.fetchall():
                    programari_lista.append({
                        'data': r[0].strftime('%d.%m.%Y %H:%M'),
                        'campanie': r[1],
                        'status': r[2],
                        'id': r[3]  # ID-ul necesar pentru butonul de anulare
                    })
        finally:
            conn.close()
            
    return {"programari": programari_lista}
@app.route('/organizator/adauga_campanie', methods=['POST'])
def adauga_campanie():
    if 'user' not in session or session['user']['Rol'] != 'organizator_campanie':
        return redirect(url_for('login_page'))
    
    # date preluate din formularul organizatorului
    nume = request.form.get('nume')
    entitate = request.form.get('organizator_entitate') 
    start = request.form.get('data_inceput').replace('T', ' ')
    sfarsit = request.form.get('data_sfarsit').replace('T', ' ')
    descriere = request.form.get('descriere')
    id_locatie = request.form.get('id_locatie')
    telefon = request.form.get('telefon')
    email_c = request.form.get('email_campanie')
    
    conn = get_connection()
    if conn:
        cursor = conn.cursor()
        try:
            #insert cu schimbarile
            #output folosit pt a stii ce id avea campania chiar si dupa modificari
            query = """
                INSERT INTO Campanie (Nume, Organizator, DataInceput, DataSfarsit, Descriere, IDLocatie, TelefonCampanie, EmailCampanie)
                OUTPUT INSERTED.IDCampanie
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            cursor.execute(query, (nume, entitate, start, sfarsit, descriere, id_locatie, telefon, email_c))
            new_id = cursor.fetchone()[0]
            
            #trebuie sa se faca legatura si cu tabelul ce leaga locatia de campanie
            cursor.execute("INSERT INTO LocatieCampanie (IDLocatie, IDCampanie) VALUES (?, ?)", (id_locatie, new_id))
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Eroare SQL: {e}")
        finally:
            conn.close()
            
    return redirect(url_for('index', message="Campania a fost creată cu succes!"))
@app.route('/organizator/sterge_campanie/<int:id_campanie>', methods=['POST'])
def sterge_campanie(id_campanie):
    if 'user' not in session or session['user']['Rol'] != 'organizator_campanie':
        return redirect(url_for('login_page'))

    conn = get_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            #verificam daca exista programari(nu se sterge o campanie la care exista programari)
            cursor.execute("SELECT COUNT(*) FROM Programare WHERE IDCampanie = ?", (id_campanie,))
            if cursor.fetchone()[0] > 0:
                return redirect(url_for('index', message="Nu se poate șterge o campanie care are deja donatori înscriși!"))

            #daca a fost stearsa campania va trebui stearsa si legatura ei cu locatia
            cursor.execute("DELETE FROM LocatieCampanie WHERE IDCampanie = ?", (id_campanie,))
            
            #stergem campania
            cursor.execute("DELETE FROM Campanie WHERE IDCampanie = ?", (id_campanie,))
            
            conn.commit()
            message = "Campania a fost ștearsă cu succes!"
        except Exception as e:
            conn.rollback()
            print(f"Eroare la ștergere: {e}")
            message = "A apărut o eroare tehnică la ștergerea campaniei."
        finally:
            conn.close()
    return redirect(url_for('index', message=message))
@app.route('/get_centru_suport')
def get_centru_suport():
    if 'user' not in session: return {"error": "Unauthorized"}, 401
    conn = get_connection()
    suport_list = []
    if conn:
        cursor = conn.cursor()
        try:
            #aici se afiseaza toate combinatiile existente intre locatie si campanie
            #cat si informatiile relevante pentru un utilizator care se informeza despre campanie
            query = """
                SELECT 
                    c.Nume as Campanie,
                    l.Nume as Locatie,
                    l.Oras,
                    c.EmailCampanie,
                    c.TelefonCampanie
                FROM Campanie c
                JOIN LocatieCampanie lc ON c.IDCampanie = lc.IDCampanie
                JOIN Locatie l ON lc.IDLocatie = l.IDLocatie
                ORDER BY l.Oras ASC
            """
            cursor.execute(query)
            rows = cursor.fetchall()
            for r in rows:
                suport_list.append({
                    'campanie': r[0],
                    'locatie': f"{r[1]} ({r[2]})",
                    'email': r[3] if r[3] else "suport@bloodhelp.ro",
                    'telefon': r[4] if r[4] else "Nespecificat"
                })
        except Exception as e:
            print(f"Eroare: {e}")
        finally:
            conn.close()
    return {"suport": suport_list}
def sterge_programari_vechi():
    conn = get_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # functie care se apeleaza la rularea scriptului pt a sterge notificari vechi
            # comparam in subcere daca programarea din nodtificare are data inainte de cea actuala
            query_notificari = """
                DELETE FROM Notificare 
                WHERE IDProgramare IN (
                    SELECT IDProgramare FROM Programare WHERE DataProgramare < GETDATE()
                )
            """
            cursor.execute(query_notificari)
            
            #stergere programari
            query_programari = "DELETE FROM Programare WHERE DataProgramare < GETDATE()"
            cursor.execute(query_programari)
            
            deleted_count = cursor.rowcount
            conn.commit()
            
            if deleted_count > 0:
                print(f"Cleanup: S-au șters {deleted_count} programări și notificările lor.")
        except Exception as e:
            print(f"Eroare la cleanup: {e}")
            conn.rollback()
        finally:
            conn.close()
def proceseaza_notificari():
    conn = get_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            #stergere automata a notificarilor mai vechi de 10 zile
            query_delete = "DELETE FROM Notificare WHERE DataTrimiterii < DATEADD(day, -10, GETDATE())"
            cursor.execute(query_delete)
            
            #notificare pentru reminder
            #dn nou cast din cauza erorii  de comparare cu getdate
            #verificam daca programarea este peste o zi
            #daca nu e anulata(inca in asteptare)
            #si daca nu exista deja pentru a nu face spam cu aceeasi notificare
            query_reminder = """
                INSERT INTO Notificare (Titlu, Mesaj, DataTrimiterii, Citita, IDProgramare)
                SELECT 
                    'Reminder Programare', 
                    'Nu uita! Ai o programare pentru donare mâine.', 
                    GETDATE(), 
                    0, 
                    p.IDProgramare
                FROM Programare p
                WHERE CAST(p.DataProgramare AS DATE) = CAST(DATEADD(day, 1, GETDATE()) AS DATE)
                AND p.Status = 'in_asteptare'
                AND NOT EXISTS (
                    SELECT 1 FROM Notificare n 
                    WHERE n.IDProgramare = p.IDProgramare AND n.Titlu = 'Reminder Programare'
                )
            """
            cursor.execute(query_reminder)
            conn.commit()
        except Exception as e:
            print(f"Eroare logica notificari: {e}")
        finally:
            conn.close()
@app.route('/anuleaza_programare/<int:id_prog>', methods=['POST'])
def anuleaza_programare(id_prog):
    if 'user' not in session: 
        return {"success": False, "error": "Neautorizat"}, 401
    
    conn = get_connection()
    if conn:
        try:
            cursor = conn.cursor()
            #daca un utilizator anuleaza programarea facem update la status
            cursor.execute("UPDATE Programare SET Status = 'anulata' WHERE IDProgramare = ?", (id_prog,))
            
            # adaugarea unei notificari care confirma anularea
            cursor.execute("""
                INSERT INTO Notificare (Titlu, Mesaj, DataTrimiterii, Citita, IDProgramare)
                VALUES ('Programare Anulată', 'Programarea ta a fost anulată cu succes.', GETDATE(), 0, ?)
            """, (id_prog,))
            
            conn.commit()
            return {"success": True} 
        except Exception as e:
            print(f"Eroare anulare: {e}")
            return {"success": False, "error": str(e)}, 500
        finally:
            conn.close()
    return {"success": False, "error": "Eroare conexiune DB"}, 500
@app.route('/organizator/edit_campanie/<int:id_campanie>', methods=['POST'])
def edit_campanie(id_campanie):
    # verificare daca user este organizator
    if 'user' not in session or session['user']['Rol'] != 'organizator_campanie':
        return redirect(url_for('login_page'))
    
    #preluare date despre campanie din formular
    nume = request.form.get('nume')
    entitate = request.form.get('organizator_entitate') # diferit de organizatorul care pune datele
    raw_start = request.form.get('data_inceput')
    raw_sfarsit = request.form.get('data_sfarsit')
    descriere = request.form.get('descriere', '')
    id_locatie_noua = request.form.get('id_locatie')
    telefon = request.form.get('telefon', '')
    email_c = request.form.get('email_campanie', '')

    message = ""
    conn = get_connection()
    
    if conn:
        try:
            cursor = conn.cursor()
            
            #formatarea datelor
            start_nou = raw_start.replace('T', ' ') if raw_start else None
            sfarsit_nou = raw_sfarsit.replace('T', ' ') if raw_sfarsit else None

            # verificam daca s-au schimbat datele pt a trimite o notificare userului
            cursor.execute("SELECT DataInceput, IDLocatie FROM Campanie WHERE IDCampanie = ?", (id_campanie,))
            vechi = cursor.fetchone()
            
            schimbare_majora = False
            if vechi and start_nou:
                data_veche = vechi[0].strftime('%Y-%m-%d %H:%M')
                if data_veche != start_nou or str(vechi[1]) != str(id_locatie_noua):
                    schimbare_majora = True

            # update in tabelul Campanie cu noile date introduse de utilizatorul organizator
            query_update = """
                UPDATE Campanie 
                SET Nume = ?, Organizator = ?, DataInceput = ?, DataSfarsit = ?, 
                    Descriere = ?, IDLocatie = ?, TelefonCampanie = ?, EmailCampanie = ?
                WHERE IDCampanie = ?
            """
            cursor.execute(query_update, (nume, entitate, start_nou, sfarsit_nou, 
                                        descriere, id_locatie_noua, telefon, email_c, id_campanie))

            #daca avem schimbare majora(de locatie sau de data) se trimite notificare donatorului
            if schimbare_majora:
                # preluam numele locatiei pt a fi afisat in notificare
                cursor.execute("SELECT Nume, Oras FROM Locatie WHERE IDLocatie = ?", (id_locatie_noua,))
                locatie_row = cursor.fetchone()
                nume_locatie = f"{locatie_row[0]} ({locatie_row[1]})" if locatie_row else "Locație nespecificată"

                # afisarea notificarii notificarii
                mesaj_notificare = (
                    f"Atenție: Detaliile campaniei '{nume}' au fost actualizate. "
                    f"Dată: {start_nou}. Locație: {nume_locatie}. "
                    "Te rugăm să verifici secțiunea Programări pentru detalii."
                )
                #adaugarea noii notificari 
                #aici SELCt are alt rol, de a scrie in coloana titlului Notificarii
                # la fel si pt ceilalti parametrii
                cursor.execute("""
                    INSERT INTO Notificare (Titlu, Mesaj, DataTrimiterii, Citita, IDProgramare)
                    SELECT 'Modificare Campanie', ?, GETDATE(), 0, p.IDProgramare
                    FROM Programare p
                    WHERE p.IDCampanie = ? AND p.Status = 'in_asteptare'
                """, (mesaj_notificare, id_campanie))

            conn.commit()
            message = "Campania a fost actualizată cu succes!"
        except Exception as e:
            conn.rollback()
            message = f"Eroare la actualizare: {str(e)}"
        finally:
            conn.close()
    else:
        message = "Eroare de conexiune la baza de date."

    return redirect(url_for('index', message=message))
@app.before_request
def cleanup_la_inceput():
    # clean care sterge notificarile si programarile vechi
    if not hasattr(app, 'cleanup_done'):
        proceseaza_notificari()
        sterge_programari_vechi()
        
if __name__ == '__main__':
    app.run(debug=True)