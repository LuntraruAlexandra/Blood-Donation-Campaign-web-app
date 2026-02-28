import pyodbc

server = 'bdplatforma.database.windows.net'  
database = 'Tema_38_gestiune_platforma_donare_sange'                       
username = 'student_login'                          
password = 'ParolaMea123!'       

conn = pyodbc.connect(
    f"Driver={{ODBC Driver 17 for SQL Server}};"
    f"Server=tcp:{server},1433;"
    f"Database={database};"
    f"Uid={username};"
    f"Pwd={password};"
)

cursor = conn.cursor()
cursor.execute("SELECT * FROM Campanie")

for row in cursor.fetchall():
    print(row)

conn.close()