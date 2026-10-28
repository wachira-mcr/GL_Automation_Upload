import os
import re
import json
import glob
import time
import tempfile
import subprocess
from datetime import datetime
import paramiko

# Try importing oracledb for machines that do not have Oracle DevSuite installed
try:
    import oracledb
except ImportError:
    oracledb = None

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
CONFIG_EXAMPLE = os.path.join(os.path.dirname(__file__), "config.example.json")

# Default configuration — matches the original setup for this PC
DEFAULT_CONFIG = {
    "db": {
        "host": "192.168.225.118",
        "port": 1541,
        "service_name": "ebs_TEST",
        "user": "apps",
        "password": "apps",
        "tns_name": "SME_TEST_8020"
    },
    "sftp": {
        "host": "192.168.225.117",
        "port": 22,
        "user": "appltest",
        "password": "appltest",
        "remote_path": "/data/TEST/apps/IMPORT/GL/DATA"
    },
    "ebs": {
        "user_name": "MERCURY",
        "user_id": 7484,
        "resp_id": 20434,
        "appl_id": 101,
        "ledger_id": 1001,
        "coa_id": 50268
    },
    "app": {
        "local_gl_path": r"C:\Users\MBx13\Downloads\GL",
        "sqlplus_path": r"D:\DevSuiteHome_1\bin\sqlplus.exe"
    }
}

def load_config():
    """Load configuration from config.json, fallback to DEFAULT_CONFIG."""
    target_file = CONFIG_FILE if os.path.exists(CONFIG_FILE) else (CONFIG_EXAMPLE if os.path.exists(CONFIG_EXAMPLE) else None)
    if target_file:
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg = json.loads(json.dumps(DEFAULT_CONFIG))
                for k in ["db", "sftp", "ebs", "app"]:
                    if k in data and isinstance(data[k], dict):
                        cfg[k].update(data[k])
                return cfg
        except Exception as e:
            print(f"[engine] Warning loading config: {e}")
    return json.loads(json.dumps(DEFAULT_CONFIG))

def save_config(cfg):
    """Save configuration to config.json and refresh variables."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    apply_config(cfg)

CONFIG = load_config()

# Exported variables for backward compatibility
SQLPLUS_PATH = r"D:\DevSuiteHome_1\bin\sqlplus.exe"
DB_CONN = "apps/apps@SME_TEST_8020"
SSH_HOST = "192.168.225.117"
SSH_USER = "appltest"
SSH_PASS = "appltest"
REMOTE_DATA_PATH = "/data/TEST/apps/IMPORT/GL/DATA"
LOCAL_GL_PATH = r"C:\Users\MBx13\Downloads\GL"
LEDGER_ID = "1001"
USER_ID = "7484"
COA_ID = "50268"
RESP_ID = "20434"
RESP_APPL_ID = "101"

def is_sqlplus_available():
    """True if this machine has sqlplus.exe installed (e.g. original PC)."""
    return os.path.exists(SQLPLUS_PATH)

def apply_config(cfg):
    global CONFIG, SQLPLUS_PATH, DB_CONN, SSH_HOST, SSH_USER, SSH_PASS
    global REMOTE_DATA_PATH, LOCAL_GL_PATH, LEDGER_ID, USER_ID, COA_ID, RESP_ID, RESP_APPL_ID
    CONFIG = cfg
    db = cfg.get("db", {})
    sftp = cfg.get("sftp", {})
    ebs = cfg.get("ebs", {})
    app = cfg.get("app", {})

    SQLPLUS_PATH = app.get("sqlplus_path", r"D:\DevSuiteHome_1\bin\sqlplus.exe")
    tns = db.get("tns_name") or "SME_TEST_8020"
    u = db.get("user") or "apps"
    p = db.get("password") or "apps"
    DB_CONN = f"{u}/{p}@{tns}"

    SSH_HOST = sftp.get("host", "192.168.225.117")
    SSH_USER = sftp.get("user", "appltest")
    SSH_PASS = sftp.get("password", "appltest")
    REMOTE_DATA_PATH = sftp.get("remote_path", "/data/TEST/apps/IMPORT/GL/DATA")
    LOCAL_GL_PATH = app.get("local_gl_path", r"C:\Users\MBx13\Downloads\GL")
    LEDGER_ID = str(ebs.get("ledger_id", "1001"))
    USER_ID = str(ebs.get("user_id", "7484"))
    COA_ID = str(ebs.get("coa_id", "50268"))
    RESP_ID = str(ebs.get("resp_id", "20434"))
    RESP_APPL_ID = str(ebs.get("appl_id", "101"))

apply_config(CONFIG)

# -------------------------------------------------------------
# Core SQL Execution: Original SQL*Plus on this PC, oracledb Thin Mode on other PCs
# -------------------------------------------------------------
def run_sql(sql_text):
    """Execute SQL. On this PC uses SQL*Plus (original way). On other PCs uses oracledb Thin mode."""
    if is_sqlplus_available():
        full_script = f"SET PAGESIZE 50000 LINESIZE 3000 FEEDBACK OFF TRIMSPOOL ON ECHO OFF HEADING OFF;\n{sql_text}\nEXIT;\n"
        with tempfile.NamedTemporaryFile("w", suffix=".sql", encoding="utf-8", delete=False) as f:
            f.write(full_script)
        tmp_sql = f.name
        cmd = [SQLPLUS_PATH, "-s", DB_CONN, f"@{tmp_sql}"]
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="cp874", errors="replace")
        if os.path.exists(tmp_sql):
            try: os.remove(tmp_sql)
            except: pass
        return p.stdout
    else:
        # Fallback to oracledb Thin Mode
        return run_sql_oracledb(sql_text)

def get_oracledb_conn(cfg=None, timeout=5.0):
    if not oracledb:
        raise ImportError("oracledb library is not installed. Please install it with: pip install oracledb")
    c = cfg or CONFIG.get("db", {})
    user = c.get("user", "apps")
    password = c.get("password", "apps")
    host = c.get("host", "192.168.225.118")
    port = int(c.get("port", 1541) or 1541)
    service_name = c.get("service_name", "ebs_TEST")
    tns_name = c.get("tns_name", "SME_TEST_8020")

    kwargs = {"tcp_connect_timeout": float(timeout)}
    if host and service_name:
        dsn = oracledb.makedsn(host, port, service_name=service_name)
        return oracledb.connect(user=user, password=password, dsn=dsn, **kwargs)
    elif tns_name:
        return oracledb.connect(user=user, password=password, dsn=tns_name, **kwargs)
    else:
        raise ValueError("ข้อมูลเชื่อมต่อ DB ไม่ครบถ้วน")

def run_sql_oracledb(sql_text):
    """Execute SQL query via oracledb and simulate stdout output."""
    conn = get_oracledb_conn()
    out_lines = []
    with conn:
        with conn.cursor() as cur:
            clean = sql_text.strip().rstrip(";")
            cur.execute(clean)
            if cur.description:
                for row in cur.fetchall():
                    out_lines.append(" ".join(str(c) if c is not None else "" for c in row))
    return "\n".join(out_lines)

# -------------------------------------------------------------
# Connection Test Functions (for Settings Modal)
# -------------------------------------------------------------
def test_db_connection(cfg=None):
    """Test DB connection using SQL*Plus or oracledb."""
    c = cfg or CONFIG.get("db", {})
    tns = c.get("tns_name") or "SME_TEST_8020"
    u = c.get("user") or "apps"
    p = c.get("password") or "apps"
    conn_str = f"{u}/{p}@{tns}"

    if is_sqlplus_available():
        test_script = "SELECT instance_name FROM v$instance;\nEXIT;\n"
        with tempfile.NamedTemporaryFile("w", suffix=".sql", encoding="utf-8", delete=False) as f:
            f.write(test_script)
        tmp_sql = f.name
        cmd = [SQLPLUS_PATH, "-s", conn_str, f"@{tmp_sql}"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="cp874", errors="replace")
        if os.path.exists(tmp_sql):
            try: os.remove(tmp_sql)
            except: pass
        out = res.stdout.strip()
        if "ORA-" in out or "SP2-" in out:
            return False, f"SQL*Plus error: {out}"
        inst = out.splitlines()[-1] if out.splitlines() else "OK"
        return True, f"เชื่อมต่อ DB สำเร็จผ่าน SQL*Plus ({tns} - Instance: {inst})"
    elif oracledb:
        try:
            conn = get_oracledb_conn(c, timeout=3.5)
            with conn.cursor() as cur:
                cur.execute("SELECT instance_name FROM v$instance")
                row = cur.fetchone()
                inst = row[0] if row else "OK"
            conn.close()
            return True, f"เชื่อมต่อ DB สำเร็จผ่าน oracledb Thin Mode (Instance: {inst})"
        except Exception as e:
            return False, f"เชื่อมต่อ DB ไม่สำเร็จ: {e}"
    else:
        return False, "ไม่พบ SQL*Plus และยังไม่ได้ติดตั้ง oracledb"

def test_sftp_connection(cfg=None):
    """Test SFTP connection."""
    c = cfg or CONFIG.get("sftp", {})
    host = c.get("host", "192.168.225.117")
    port = int(c.get("port", 22) or 22)
    user = c.get("user", "appltest")
    pwd = c.get("password", "appltest")
    r_path = c.get("remote_path", "/data/TEST/apps/IMPORT/GL/DATA")
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username=user, password=pwd, timeout=3.5)
        sftp = ssh.open_sftp()
        try:
            sftp.listdir(r_path)
            dir_msg = f"ไดเรกทอรี '{r_path}' พร้อมใช้งาน"
        except Exception:
            dir_msg = f"เชื่อมต่อสำเร็จ (ตรวจสอบไดเรกทอรี '{r_path}')"
        sftp.close()
        ssh.close()
        return True, f"เชื่อมต่อ SFTP ({host}:{port}) สำเร็จ! {dir_msg}"
    except Exception as e:
        return False, f"เชื่อมต่อ SFTP ไม่สำเร็จ: {e}"

def test_ebs_user(username, password=None):
    """Verify EBS user in apps.fnd_user."""
    if not username:
        return False, "กรุณากรอก Username ของ EBS", []
    username = username.strip().upper()
    sql = f"""
    SELECT u.user_id, r.responsibility_id, r.application_id, t.responsibility_name
    FROM apps.fnd_user u
    JOIN apps.fnd_user_resp_groups g ON u.user_id = g.user_id
    JOIN apps.fnd_responsibility r ON g.responsibility_id = r.responsibility_id AND g.responsibility_application_id = r.application_id
    JOIN apps.fnd_responsibility_tl t ON r.responsibility_id = t.responsibility_id AND r.application_id = t.application_id AND t.language = 'US'
    WHERE u.user_name = '{username}'
      AND (g.end_date IS NULL OR g.end_date > SYSDATE)
      AND (u.end_date IS NULL OR u.end_date > SYSDATE)
    ORDER BY CASE WHEN t.responsibility_name LIKE '%General Ledger%' THEN 1 ELSE 2 END, t.responsibility_name;
    """
    out = run_sql(sql)
    lines = [l.strip() for l in out.splitlines() if l.strip() and not l.startswith("ORA-")]
    if not lines:
        return False, f"ไม่พบผู้ใช้ '{username}' หรือไม่มีสิทธิ์ในระบบ EBS", []
    
    parts = lines[0].split(None, 3)
    uid = int(parts[0])
    resps = []
    for l in lines:
        p = l.split(None, 3)
        if len(p) >= 4:
            resps.append({"resp_id": int(p[1]), "appl_id": int(p[2]), "resp_name": p[3]})
    return True, f"พบผู้ใช้งาน '{username}' (User ID: {uid})", {"user_id": uid, "user_name": username, "responsibilities": resps}

# -------------------------------------------------------------
# Business Workflow Functions (Original Logic Preserved 100%)
# -------------------------------------------------------------
def read_file_info(path):
    """Read JE_BATCH_NAME and EFFECTIVE_DATE (-> 'YYYY-MM-DD') from the first data line."""
    with open(path, encoding="cp874", errors="replace") as f:
        f.readline()  # header
        cols = f.readline().split("|")
    try:
        eff = datetime.strptime(cols[2].strip(), "%d-%b-%Y").strftime("%Y-%m-%d")
        return {"batch_name": cols[1].strip(), "eff_date": eff}
    except (IndexError, ValueError):
        return {"batch_name": None, "eff_date": None}

def scan_available_dates(base=LOCAL_GL_PATH):
    """Find *TFRS9*.TXT in base and all sub-folders."""
    base = base or LOCAL_GL_PATH
    if not os.path.isdir(base):
        return []
    paths = glob.glob(os.path.join(base, "**", "*TFRS9*.TXT"), recursive=True)
    files = []
    for p in sorted(set(paths)):
        files.append({
            "folder": os.path.basename(os.path.dirname(p)),
            "name": os.path.basename(p),
            "file_path": p,
            "size_kb": round(os.path.getsize(p) / 1024, 1),
            **read_file_info(p),
        })
    names = [f["batch_name"] for f in files if f["batch_name"]]
    imported = get_imported_batches(names)
    in_iface = get_interface_batches(names)
    periods = get_period_statuses([f["eff_date"] for f in files])
    for f in files:
        f["imported_count"] = imported.get(f["batch_name"], 0)
        f["interface_rows"] = in_iface.get(f["batch_name"], 0)
        f["period_status"] = periods.get(f["eff_date"], "?")
        f["period_open"] = f["period_status"] in ("O", "F")
    return files

def get_imported_batches(batch_names):
    """{batch_name: count} in Ledger 1001 of files already imported."""
    names = sorted({n for n in batch_names if re.fullmatch(r"[\w-]+", n)})
    if not names:
        return {}
    in_list = ",".join(f"'{n}'" for n in names)
    sql = f"""
    SELECT SUBSTR(b.name, 1, INSTR(b.name || ' ', ' ') - 1), COUNT(*)
    FROM apps.gl_je_batches b
    WHERE b.name LIKE 'TFRS9-%'
      AND SUBSTR(b.name, 1, INSTR(b.name || ' ', ' ') - 1) IN ({in_list})
      AND EXISTS (SELECT 1 FROM apps.gl_je_headers h WHERE h.je_batch_id = b.je_batch_id AND h.ledger_id = {LEDGER_ID})
    GROUP BY SUBSTR(b.name, 1, INSTR(b.name || ' ', ' ') - 1);
    """
    result = {}
    for line in run_sql(sql).splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            result[parts[0]] = int(parts[1])
    return result

def get_interface_batches(batch_names):
    """{batch_name: rows} still in GL_INTERFACE."""
    names = sorted({n for n in batch_names if re.fullmatch(r"[\w-]+", n)})
    if not names:
        return {}
    in_list = ",".join(f"'{n}'" for n in names)
    sql = f"SELECT reference1, COUNT(*) FROM apps.gl_interface WHERE reference1 IN ({in_list}) GROUP BY reference1;"
    result = {}
    for line in run_sql(sql).splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            result[parts[0]] = int(parts[1])
    return result

def sftp_upload_file(local_path, remote_filename="GLTFRS9.TXT", log_cb=None):
    """Upload local file to Linux Application server via SFTP."""
    if log_cb: log_cb(f"Connecting SFTP to {SSH_HOST} as {SSH_USER}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SSH_HOST, port=22, username=SSH_USER, password=SSH_PASS, timeout=10)

    sftp = ssh.open_sftp()
    remote_full = f"{REMOTE_DATA_PATH}/{remote_filename}"
    try:
        if log_cb: log_cb(f"⚠️ พบไฟล์ชื่อเดียวกันบนเซิร์ฟเวอร์อยู่แล้ว ({sftp.stat(remote_full).st_size:,} bytes) จะเขียนทับ")
    except (FileNotFoundError, IOError):
        pass
    if log_cb: log_cb(f"Uploading '{local_path}' to '{remote_full}'...")
    sftp.put(local_path, remote_full)
    sftp.close()
    ssh.close()
    if log_cb: log_cb(f"Upload complete successfully! ({remote_full})")

def check_gl_period(date_str):
    """Check if the date is in an OPEN period in Ledger."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    ora_date = dt.strftime("%d-%m-%Y")
    sql = f"""
    SELECT closing_status
    FROM apps.gl_period_statuses
    WHERE set_of_books_id = {LEDGER_ID}
      AND application_id = 101
      AND adjustment_period_flag = 'N'
      AND TO_DATE('{ora_date}', 'DD-MM-YYYY') BETWEEN start_date AND end_date;
    """
    out = run_sql(sql).strip()
    return out == 'O' or out == 'F', out

def get_period_statuses(dates):
    """{'YYYY-MM-DD': closing_status} for many effective dates in one query."""
    dates = sorted({d for d in dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d or "")})
    if not dates:
        return {}
    in_list = " UNION ALL ".join(f"SELECT DATE '{d}' d FROM dual" for d in dates)
    sql = f"""
    SELECT TO_CHAR(x.d, 'YYYY-MM-DD'), p.closing_status
    FROM ({in_list}) x
    JOIN apps.gl_period_statuses p
      ON x.d BETWEEN p.start_date AND p.end_date
     AND p.set_of_books_id = {LEDGER_ID} AND p.application_id = 101 AND p.adjustment_period_flag = 'N';
    """
    return dict(line.split() for line in run_sql(sql).splitlines() if len(line.split()) == 2)

def get_temp_table_count():
    """Get row count in SME_CCF_GL_INTERFACE."""
    sql = "SELECT COUNT(*) FROM apps.sme_ccf_gl_interface;"
    out = run_sql(sql).strip()
    try:
        return int(out.split()[-1])
    except:
        return 0

def submit_concurrent_request(program_name, arguments, description="", log_cb=None):
    """Submit Concurrent Program via fnd_request.submit_request."""
    if is_sqlplus_available():
        arg_list = ",\n        ".join(f"argument{i} => '{str(a or '').replace(chr(39), chr(39) * 2)}'" for i, a in enumerate(arguments, 1))
        plsql = f"""
        SET SERVEROUTPUT ON;
        DECLARE
          v_req NUMBER;
        BEGIN
          fnd_global.apps_initialize({USER_ID}, {RESP_ID}, {RESP_APPL_ID}); -- {USER_ID}, General Ledger Super User, SQLGL
          v_req := fnd_request.submit_request(
            application => 'SQLGL',
            program     => '{program_name}',
            description => '{description}',
            start_time  => SYSDATE,
            sub_request => FALSE,
            {arg_list}
          );
          COMMIT;
          dbms_output.put_line('REQ_ID:' || v_req);
        END;
        /
        """
        out = run_sql(plsql)
        for line in out.splitlines():
            if "REQ_ID:" in line:
                req_id = int(line.split("REQ_ID:")[-1].strip())
                if log_cb: log_cb(f"Submitted {program_name} successfully -> Request ID: {req_id}")
                return req_id
        raise Exception(f"Failed to submit request for {program_name}. Output:\n{out}")
    else:
        # oracledb submission
        conn = get_oracledb_conn()
        with conn:
            with conn.cursor() as cur:
                req_var = cur.var(int)
                arg_binds = {f"arg{i}": str(a or "") for i, a in enumerate(arguments, 1)}
                arg_list = ",\n        ".join(f"argument{i} => :arg{i}" for i in range(1, len(arguments) + 1))
                if arg_list:
                    arg_list = ", " + arg_list
                plsql = f"""
                DECLARE
                  v_req NUMBER;
                BEGIN
                  fnd_global.apps_initialize(:uid, :rid, :aid);
                  v_req := fnd_request.submit_request(
                    application => 'SQLGL',
                    program     => :prog,
                    description => :descr,
                    start_time  => SYSDATE,
                    sub_request => FALSE{arg_list}
                  );
                  COMMIT;
                  :req_out := v_req;
                END;
                """
                binds = {
                    "uid": int(USER_ID),
                    "rid": int(RESP_ID),
                    "aid": int(RESP_APPL_ID),
                    "prog": program_name,
                    "descr": description,
                    "req_out": req_var,
                    **arg_binds
                }
                cur.execute(plsql, binds)
                req_id = req_var.getvalue()
                if req_id and req_id > 0:
                    if log_cb: log_cb(f"Submitted {program_name} successfully -> Request ID: {req_id}")
                    return req_id
                raise Exception(f"Failed to submit request for {program_name}")

def wait_for_request(request_id, timeout_sec=600, poll_sec=3, log_cb=None):
    """Poll fnd_concurrent_requests until Phase = 'C' (Completed)."""
    start_t = time.time()
    last_status = None
    while time.time() - start_t < timeout_sec:
        sql = f"""
        SELECT phase_code, status_code 
        FROM apps.fnd_concurrent_requests 
        WHERE request_id = {request_id};
        """
        out = run_sql(sql).strip().split()
        if len(out) >= 2:
            phase, status = out[0], out[1]
            status_text = f"Phase: {phase}, Status: {status}"
            if status_text != last_status:
                if log_cb: log_cb(f"Request {request_id} -> {status_text}")
                last_status = status_text
                
            if phase == 'C':
                return status == 'C', phase, status
        time.sleep(poll_sec)
    raise TimeoutError(f"Request {request_id} timed out after {timeout_sec}s")

def get_latest_sub_request(parent_req_id):
    """Check if Journal Import was submitted automatically."""
    sql = f"""
    SELECT r.request_id, r.phase_code, r.status_code
    FROM apps.fnd_concurrent_requests r
    WHERE r.description LIKE '%(AUTO CCF)Journal Import%'
      AND r.request_date >= SYSDATE - 1/24
    ORDER BY r.request_id DESC;
    """
    out = run_sql(sql).strip().split()
    if len(out) >= 3:
        return int(out[0]), out[1], out[2]
    return None, None, None

def get_batch_info(batch_name):
    """Latest GL batch in Ledger 1001 imported from this file's JE_BATCH_NAME."""
    if not re.fullmatch(r"[\w-]+", batch_name or ""):
        return None
    sql = f"""
    SELECT b.je_batch_id, b.status, NVL(b.attribute10, 'N'), b.name
    FROM apps.gl_je_batches b
    WHERE b.name LIKE '{batch_name} %'
      AND EXISTS (SELECT 1 FROM apps.gl_je_headers h WHERE h.je_batch_id = b.je_batch_id AND h.ledger_id = {LEDGER_ID})
    ORDER BY b.je_batch_id DESC;
    """
    lines = [l.strip() for l in run_sql(sql).splitlines() if l.strip()]
    if lines:
        parts = lines[0].split(None, 3)
        if len(parts) == 4:
            return {
                "batch_id": parts[0],
                "status": parts[1],
                "consolidated": parts[2],
                "name": parts[3]
            }
    return None

def get_step2_errors():
    """Get errors from SME_CCF_GL_INTERFACE if Step 2 failed."""
    sql = """
    SELECT err, count(*) 
    FROM apps.sme_ccf_gl_interface 
    WHERE eflag = 'E' 
    GROUP BY err;
    """
    return run_sql(sql).strip()

def get_reconcile_summary():
    """Get summary counts and amounts for Reconcile."""
    sql = """
    SELECT count(*), sum(nvl(entered_dr,0)), sum(nvl(entered_cr,0))
    FROM apps.sme_ccf_gl_interface
    WHERE eflag = 'P';
    """
    out = run_sql(sql).strip().split()
    if len(out) >= 3:
        return {
            "rows": out[0],
            "dr": f"{float(out[1]):,.2f}",
            "cr": f"{float(out[2]):,.2f}"
        }
    return {"rows": 0, "dr": "0.00", "cr": "0.00"}
