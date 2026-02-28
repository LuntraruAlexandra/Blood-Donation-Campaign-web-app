import pyodbc
import hashlib
import os


server = 'bdplatforma.database.windows.net'  
database = 'Tema_38_gestiune_platforma_donare_sange'  
username = 'student_login'
password = 'ParolaMea123!' 


def get_connection():
    """Stabilește și returnează o conexiune la baza de date."""
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
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        print(f"Eroare la conectare: Verificați detaliile conexiunii sau starea serverului. SQLSTATE: {sqlstate}")
        return None

def hash_password(password):
    """Criptează parola folosind SHA-256."""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def sign_up(nume, prenume, email, parola, rol='utilizator_standard'):
    """Înregistrează un utilizator nou."""
    conn = get_connection()
    if conn is None: return False
        
    cursor = conn.cursor()
    hashed_password = hash_password(parola)
    
    insert_query = """
    INSERT INTO Utilizator 
    (Nume, Prenume, Email, ParolaCriptata, Rol, DataInregistrarii) 
    VALUES (?, ?, ?, ?, ?, GETDATE())
    """
    
    try:
        cursor.execute(
            insert_query, 
            nume, prenume, email, hashed_password, rol
        )
        conn.commit()
        print(f"Utilizatorul '{email}' a fost înregistrat cu succes!")
        return True
    except pyodbc.ProgrammingError as pe:
        print(f"Eroare la înregistrare: {pe}")
        return False
    except pyodbc.Error as ex:
        print(f"O eroare SQL a apărut la înregistrare: {ex}")
        return False
    finally:
        conn.close()

def login(email, parola):
    """Verifică credențialele utilizatorului."""
    conn = get_connection()
    if conn is None: return None

    cursor = conn.cursor()
    select_query = """
    SELECT IDUtilizator, ParolaCriptata, Rol 
    FROM Utilizator 
    WHERE Email = ?
    """
    
    try:
        cursor.execute(select_query, email)
        user_data = cursor.fetchone()
        
        if user_data:
            user_id, stored_hash, rol = user_data
            input_hash = hash_password(parola)
            
            if input_hash == stored_hash:
                print(f"Login reușit! Bun venit, utilizator ID: {user_id} (Rol: {rol})")
                return {'ID': user_id, 'Email': email, 'Rol': rol}
            else:
                print("Parolă incorectă.")
                return None
        else:
            print(f"Utilizatorul cu email-ul '{email}' nu a fost găsit.")
            return None
            
    except pyodbc.Error as ex:
        print(f"O eroare SQL a apărut la login: {ex}")
        return None
    finally:
        conn.close()


def run_interactive_menu():
    """Rulează un meniu interactiv în consolă."""
    
    while True:
        print("\n" + "="*30)
        print("Sistem de Autentificare Utilizator")
        print("="*30)
        print("1. Înregistrare (Sign-Up)")
        print("2. Autentificare (Login)")
        print("3. Ieșire")
        
        choice = input("Alege o opțiune (1, 2, 3): ")
        print("-" * 30)

        if choice == '1':
            print("--- Înregistrare ---")
            nume = input("Nume: ")
            prenume = input("Prenume: ")
            email = input("Email: ")
            parola = input("Parolă: ")
            rol = input("Rol (Opțional, default: utilizator_standard): ") or 'utilizator_standard'
            
            sign_up(nume, prenume, email, parola, rol)

        elif choice == '2':
            print("--- Autentificare ---")
            email = input("Email: ")
            parola = input("Parolă: ")
            
            login(email, parola)

        elif choice == '3':
            print("Sistemul s-a oprit.")
            break
            
        else:
            print("Opțiune invalidă. Încearcă din nou.")


if __name__ == "__main__":
    run_interactive_menu()