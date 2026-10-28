import os
import re
import json
import glob
import time
import tempfile
import subprocess
from datetime import datetime
import oracledb
import paramiko

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
CONFIG_EXAMPLE = os.path.join(os.path.dirname(__file__), "config.example.json")

DEFAULT_CONFIG = {
    "db": {
        "host": "192.168.225.118",
        "port": 1541,
        "service_name": "ebs_TEST",
        "user": "apps",
        "password": "",
        "tns_name": "SME_TEST_8020"
    },
    "sftp": {
        "host": "192.168.225.117",
        "port": 22,
        "user": "appltest",
        "password": "",
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
        "local_gl_path": os.path.join(os.path.expanduser("~"), "Downloads", "GL"),
        "sqlplus_path": r"D:\DevSuiteHome_1\bin\sqlplus.exe",
        "use_sqlplus_fallback": False
    }
}

def load_config():
    """Load configuration from config.json, fallback to config.example.json or DEFAULT_CONFIG."""
    target_file = CONFIG_FILE if os.path.exists(CONFIG_FILE) else (CONFIG_EXAMPLE if os.path.exists(CONFIG_EXAMPLE) else None)
    if target_file:
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg = dict(DEFAULT_CONFIG)
                for k in ["db", "sftp", "ebs", "app"]:
                    if k in data:
                        cfg[k] = {**DEFAULT_CONFIG[k], **data[k]}
                return cfg
        except Exception as e:
            print(f"[engine] Warning loading config: {e}")
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    """Save configuration to config.json and reload module variables."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    apply_config(cfg)

CONFIG = load_config()

# Module-level exported variables for backward compatibility
SQLPLUS_PATH = ""
DB_CONN = ""
SSH_HOST = ""
SSH_PORT = 22
SSH_USER = ""
SSH_PASS = ""
REMOTE_DATA_PATH = ""
LOCAL_GL_PATH = ""
LEDGER_ID = "1001"
USER_ID = "7484"
COA_ID = "50268"
RESP_ID = "20434"
RESP_APPL_ID = "101"
USE_SQLPLUS_FALLBACK = False

def apply_config(cfg):
    global CONFIG, SQLPLUS_PATH, DB_CONN, SSH_HOST, SSH_PORT, SSH_USER, SSH_PASS
    global REMOTE_DATA_PATH, LOCAL_GL_PATH, LEDGER_ID, USER_ID, COA_ID, RESP_ID, RESP_APPL_ID, USE_SQLPLUS_FALLBACK
    CONFIG = cfg
    db = cfg.get("db", {})
    sftp = cfg.get("sftp", {})
    ebs = cfg.get("ebs", {})
    app = cfg.get("app", {})

    SQLPLUS_PATH = app.get("sqlplus_path", r"D:\DevSuiteHome_1\bin\sqlplus.exe")
    DB_CONN = f"{db.get('user', 'apps')}/{db.get('password', '')}@{db.get('tns_name', 'SME_TEST_8020')}"
    SSH_HOST = sftp.get("host", "192.168.225.117")
    SSH_PORT = int(sftp.get("port", 22) or 22)
    SSH_USER = sftp.get("user", "appltest")
    SSH_PASS = sftp.get("password", "")
    REMOTE_DATA_PATH = sftp.get("remote_path", "/data/TEST/apps/IMPORT/GL/DATA")
    LOCAL_GL_PATH = app.get("local_gl_path") or os.path.join(os.path.expanduser("~"), "Downloads", "GL")
    LEDGER_ID = str(ebs.get("ledger_id", "1001"))
    USER_ID = str(ebs.get("user_id", "7484"))
    COA_ID = str(ebs.get("coa_id", "50268"))
    RESP_ID = str(ebs.get("resp_id", "20434"))
    RESP_APPL_ID = str(ebs.get("appl_id", "101"))
    USE_SQLPLUS_FALLBACK = app.get("use_sqlplus_fallback", False)

apply_config(CONFIG)

def get_db_connection(cfg=None, timeout=None):
    """Create an oracledb connection in Thin mode (pure python, no Oracle client needed)."""
    c = cfg or CONFIG.get("db", {})
    user = c.get("user", "apps")
    password = c.get("password", "")
    host = c.get("host", "")
    port = int(c.get("port", 1521) or 1521)
    service_name = c.get("service_name", "")
    tns_name = c.get("tns_name", "")

    kwargs = {}
    if timeout:
        kwargs["tcp_connect_timeout"] = float(timeout)

    if host and service_name:
        dsn = oracledb.makedsn(host, port, service_name=service_name)
        return oracledb.connect(user=user, password=password, dsn=dsn, **kwargs)
    elif tns_name:
        return oracledb.connect(user=user, password=password, dsn=tns_name, **kwargs)
    else:
        raise ValueError("ข้อมูลเชื่อมต่อ DB ไม่ครบถ้วน (ต้องระบุ Host และ Service Name หรือ TNS Name)")

def test_db_connection(cfg=None):
    """Test Oracle DB connection and retrieve instance info."""
    c = cfg or CONFIG.get("db", {})
    try:
        conn = get_db_connection(c, timeout=3.5)
        with conn.cursor() as cur:
            cur.execute("SELECT instance_name, host_name, version FROM v$instance")
            row = cur.fetchone()
            inst_info = f"Instance: {row[0]}, Host: {row[1]}, Version: {row[2]}" if row else "OK"
        conn.close()
        return True, f"เชื่อมต่อ Oracle DB สำเร็จ! ({inst_info})"
    except Exception as e:
        return False, f"เชื่อมต่อ Oracle DB ไม่สำเร็จ: {str(e)}"

def test_sftp_connection(cfg=None):
    """Test SFTP connection and remote directory access."""
    c = cfg or CONFIG.get("sftp", {})
    host = c.get("host")
    port = int(c.get("port", 22) or 22)
    user = c.get("user")
    password = c.get("password", "")
    r_path = c.get("remote_path", "/data/TEST/apps/IMPORT/GL/DATA")

    if not host or not user:
        return False, "กรุณาระบุ SFTP Host และ Username"

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username=user, password=password, timeout=3.5)
        sftp = ssh.open_sftp()
        try:
            sftp.listdir(r_path)
            dir_msg = f"ไดเรกทอรี '{r_path}' พร้อมใช้งาน"
        except Exception:
            dir_msg = f"⚠️ เชื่อมต่อได้ แต่ไม่พบไดเรกทอรี '{r_path}' หรือไม่มีสิทธิ์เข้าถึง"
        sftp.close()
        ssh.close()
        return True, f"เชื่อมต่อ SFTP ({host}:{port}) สำเร็จ! {dir_msg}"
    except Exception as e:
        return False, f"เชื่อมต่อ SFTP ไม่สำเร็จ: {str(e)}"

def test_ebs_user(username, password=None):
    """Verify EBS user in fnd_user and query General Ledger responsibilities."""
    if not username:
        return False, "กรุณากรอก Username ของ EBS", []
    username = username.strip().upper()
    try:
        conn = get_db_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id, user_name FROM apps.fnd_user WHERE user_name = :u", {"u": username})
                row = cur.fetchone()
                if not row:
                    return False, f"ไม่พบชื่อผู้ใช้ '{username}' ในระบบ EBS (apps.fnd_user)", []
                uid = row[0]

                pwd_ok = None
                if password:
                    try:
                        res_var = cur.var(str)
                        cur.execute("BEGIN :r := apps.fnd_web_sec.validate_login(:u, :p); END;", {"r": res_var, "u": username, "p": password})
                        pwd_ok = (res_var.getvalue() == 'Y')
                    except Exception:
                        pass

                sql_resp = """
                SELECT r.responsibility_id, r.application_id, t.responsibility_name
                FROM apps.fnd_user u
                JOIN apps.fnd_user_resp_groups g ON u.user_id = g.user_id
                JOIN apps.fnd_responsibility r ON g.responsibility_id = r.responsibility_id AND g.responsibility_application_id = r.application_id
                JOIN apps.fnd_responsibility_tl t ON r.responsibility_id = t.responsibility_id AND r.application_id = t.application_id AND t.language = 'US'
                WHERE u.user_name = :u
                  AND (g.end_date IS NULL OR g.end_date > SYSDATE)
                  AND (u.end_date IS NULL OR u.end_date > SYSDATE)
                ORDER BY CASE WHEN t.responsibility_name LIKE '%General Ledger%' THEN 1 ELSE 2 END, t.responsibility_name
                """
                cur.execute(sql_resp, {"u": username})
                resps = [{"resp_id": r[0], "appl_id": r[1], "resp_name": r[2]} for r in cur.fetchall()]

                msg = f"พบผู้ใช้งาน '{username}' (User ID: {uid})"
                if pwd_ok is False:
                    msg += " (⚠️ หมายเหตุ: รหัสผ่านไม่ตรงกับใน EBS)"
                elif pwd_ok is True:
                    msg += " (✅ รหัสผ่านถูกต้อง)"
                return True, msg, {"user_id": uid, "user_name": username, "responsibilities": resps}
    except Exception as e:
        return False, f"ตรวจสอบผู้ใช้ EBS ไม่สำเร็จ (DB Error): {str(e)}", []

def run_sql(sql_text):
    """Execute SQL via SQL*Plus (fallback compatibility)."""
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

def scan_available_dates(base=None):
    """Find *TFRS9*.TXT in base folder and sub-folders."""
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
    """{batch_name: count} in Ledger of files already imported."""
    names = sorted({n for n in batch_names if re.fullmatch(r"[\w-]+", n or "")})
    if not names:
        return {}
    bind_keys = [f"n{i}" for i in range(len(names))]
    in_clause = ",".join(f":{k}" for k in bind_keys)
    binds = {f"n{i}": name for i, name in enumerate(names)}
    binds["lid"] = int(LEDGER_ID)

    sql = f"""
    SELECT SUBSTR(b.name, 1, INSTR(b.name || ' ', ' ') - 1), COUNT(*)
    FROM apps.gl_je_batches b
    WHERE b.name LIKE 'TFRS9-%'
      AND SUBSTR(b.name, 1, INSTR(b.name || ' ', ' ') - 1) IN ({in_clause})
      AND EXISTS (SELECT 1 FROM apps.gl_je_headers h WHERE h.je_batch_id = b.je_batch_id AND h.ledger_id = :lid)
    GROUP BY SUBSTR(b.name, 1, INSTR(b.name || ' ', ' ') - 1)
    """
    try:
        conn = get_db_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, binds)
                return {row[0].strip(): int(row[1]) for row in cur.fetchall() if row[0]}
    except Exception as e:
        if USE_SQLPLUS_FALLBACK and os.path.exists(SQLPLUS_PATH):
            in_list = ",".join(f"'{n}'" for n in names)
            sql_fallback = f"""
            SELECT SUBSTR(b.name, 1, INSTR(b.name || ' ', ' ') - 1), COUNT(*)
            FROM apps.gl_je_batches b
            WHERE b.name LIKE 'TFRS9-%'
              AND SUBSTR(b.name, 1, INSTR(b.name || ' ', ' ') - 1) IN ({in_list})
              AND EXISTS (SELECT 1 FROM apps.gl_je_headers h WHERE h.je_batch_id = b.je_batch_id AND h.ledger_id = {LEDGER_ID})
            GROUP BY SUBSTR(b.name, 1, INSTR(b.name || ' ', ' ') - 1);
            """
            result = {}
            for line in run_sql(sql_fallback).splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1].isdigit():
                    result[parts[0]] = int(parts[1])
            return result
        return {}

def get_interface_batches(batch_names):
    """{batch_name: count} still in GL_INTERFACE."""
    names = sorted({n for n in batch_names if re.fullmatch(r"[\w-]+", n or "")})
    if not names:
        return {}
    bind_keys = [f"n{i}" for i in range(len(names))]
    in_clause = ",".join(f":{k}" for k in bind_keys)
    binds = {f"n{i}": name for i, name in enumerate(names)}
    sql = f"SELECT reference1, COUNT(*) FROM apps.gl_interface WHERE reference1 IN ({in_clause}) GROUP BY reference1"
    try:
        conn = get_db_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, binds)
                return {row[0].strip(): int(row[1]) for row in cur.fetchall() if row[0]}
    except Exception as e:
        if USE_SQLPLUS_FALLBACK and os.path.exists(SQLPLUS_PATH):
            in_list = ",".join(f"'{n}'" for n in names)
            sql_fallback = f"SELECT reference1, COUNT(*) FROM apps.gl_interface WHERE reference1 IN ({in_list}) GROUP BY reference1;"
            result = {}
            for line in run_sql(sql_fallback).splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1].isdigit():
                    result[parts[0]] = int(parts[1])
            return result
        return {}

def sftp_upload_file(local_path, remote_filename="GLTFRS9.TXT", log_cb=None):
    """Upload local file to Linux Application server via SFTP."""
    if log_cb: log_cb(f"Connecting SFTP to {SSH_HOST}:{SSH_PORT} as {SSH_USER}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER, password=SSH_PASS, timeout=15)

    sftp = ssh.open_sftp()
    remote_full = f"{REMOTE_DATA_PATH}/{remote_filename}"
    try:
        stat = sftp.stat(remote_full)
        if log_cb: log_cb(f"⚠️ พบไฟล์ชื่อเดียวกันบนเซิร์ฟเวอร์อยู่แล้ว ({stat.st_size:,} bytes) จะเขียนทับ")
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
    sql = """
    SELECT closing_status
    FROM apps.gl_period_statuses
    WHERE set_of_books_id = :lid
      AND application_id = 101
      AND adjustment_period_flag = 'N'
      AND TO_DATE(:dt, 'DD-MM-YYYY') BETWEEN start_date AND end_date
    """
    try:
        conn = get_db_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, {"lid": int(LEDGER_ID), "dt": ora_date})
                row = cur.fetchone()
                status = row[0].strip() if row and row[0] else ""
                return status in ('O', 'F'), status
    except Exception as e:
        if USE_SQLPLUS_FALLBACK and os.path.exists(SQLPLUS_PATH):
            sql_fallback = f"""
            SELECT closing_status
            FROM apps.gl_period_statuses
            WHERE set_of_books_id = {LEDGER_ID}
              AND application_id = 101
              AND adjustment_period_flag = 'N'
              AND TO_DATE('{ora_date}', 'DD-MM-YYYY') BETWEEN start_date AND end_date;
            """
            out = run_sql(sql_fallback).strip()
            return out in ('O', 'F'), out
        raise e

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
     AND p.set_of_books_id = :lid AND p.application_id = 101 AND p.adjustment_period_flag = 'N'
    """
    try:
        conn = get_db_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, {"lid": int(LEDGER_ID)})
                return {row[0].strip(): row[1].strip() for row in cur.fetchall() if row[0]}
    except Exception:
        return {}

def get_temp_table_count():
    """Get row count in SME_CCF_GL_INTERFACE."""
    sql = "SELECT COUNT(*) FROM apps.sme_ccf_gl_interface"
    try:
        conn = get_db_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
                return int(row[0]) if row else 0
    except Exception:
        return 0

def submit_concurrent_request(program_name, arguments, description="", log_cb=None):
    """Submit Concurrent Program via fnd_request.submit_request."""
    arg_binds = {}
    arg_lines = []
    for i, a in enumerate(arguments, 1):
        arg_binds[f"arg{i}"] = str(a) if a is not None else ""
        arg_lines.append(f"argument{i} => :arg{i}")
    arg_str = (",\n        " + ",\n        ".join(arg_lines)) if arg_lines else ""

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
        sub_request => FALSE{arg_str}
      );
      COMMIT;
      :req_out := v_req;
    END;
    """
    try:
        conn = get_db_connection()
        with conn:
            with conn.cursor() as cur:
                req_var = cur.var(int)
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
                else:
                    raise Exception(f"fnd_request.submit_request returned 0 for {program_name}")
    except Exception as e:
        if USE_SQLPLUS_FALLBACK and os.path.exists(SQLPLUS_PATH):
            arg_list_str = ",\n        ".join(f"argument{i} => '{str(a or '').replace(chr(39), chr(39) * 2)}'" for i, a in enumerate(arguments, 1))
            plsql_fallback = f"""
            SET SERVEROUTPUT ON;
            DECLARE
              v_req NUMBER;
            BEGIN
              fnd_global.apps_initialize({USER_ID}, {RESP_ID}, {RESP_APPL_ID});
              v_req := fnd_request.submit_request(
                application => 'SQLGL',
                program     => '{program_name}',
                description => '{description}',
                start_time  => SYSDATE,
                sub_request => FALSE,
                {arg_list_str}
              );
              COMMIT;
              dbms_output.put_line('REQ_ID:' || v_req);
            END;
            /
            """
            out = run_sql(plsql_fallback)
            for line in out.splitlines():
                if "REQ_ID:" in line:
                    req_id = int(line.split("REQ_ID:")[-1].strip())
                    if log_cb: log_cb(f"Submitted {program_name} successfully -> Request ID: {req_id}")
                    return req_id
            raise Exception(f"SQL*Plus fallback failed for {program_name}. Output:\n{out}")
        raise Exception(f"Failed to submit request for {program_name}: {e}")

def wait_for_request(request_id, timeout_sec=600, poll_sec=3, log_cb=None):
    """Poll fnd_concurrent_requests until Phase = 'C' (Completed)."""
    start_t = time.time()
    last_status = None
    sql = "SELECT phase_code, status_code FROM apps.fnd_concurrent_requests WHERE request_id = :rid"
    while time.time() - start_t < timeout_sec:
        try:
            conn = get_db_connection()
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql, {"rid": request_id})
                    row = cur.fetchone()
                    if row:
                        phase, status = row[0].strip(), row[1].strip()
                        status_text = f"Phase: {phase}, Status: {status}"
                        if status_text != last_status:
                            if log_cb: log_cb(f"Request {request_id} -> {status_text}")
                            last_status = status_text
                        if phase == 'C':
                            return status == 'C', phase, status
        except Exception as e:
            if log_cb: log_cb(f"Warning polling request {request_id}: {e}")
        time.sleep(poll_sec)
    raise TimeoutError(f"Request {request_id} timed out after {timeout_sec}s")

def get_latest_sub_request(parent_req_id):
    """Check if Journal Import was submitted automatically."""
    sql = """
    SELECT r.request_id, r.phase_code, r.status_code
    FROM apps.fnd_concurrent_requests r
    WHERE r.description LIKE '%(AUTO CCF)Journal Import%'
      AND r.request_date >= SYSDATE - 1/24
    ORDER BY r.request_id DESC
    """
    try:
        conn = get_db_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
                if row:
                    return int(row[0]), row[1].strip(), row[2].strip()
    except Exception:
        pass
    return None, None, None

def get_batch_info(batch_name):
    """Latest GL batch in Ledger imported from this file's JE_BATCH_NAME."""
    if not re.fullmatch(r"[\w-]+", batch_name or ""):
        return None
    sql = """
    SELECT b.je_batch_id, b.status, NVL(b.attribute10, 'N'), b.name
    FROM apps.gl_je_batches b
    WHERE b.name LIKE :pname
      AND EXISTS (SELECT 1 FROM apps.gl_je_headers h WHERE h.je_batch_id = b.je_batch_id AND h.ledger_id = :lid)
    ORDER BY b.je_batch_id DESC
    """
    try:
        conn = get_db_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, {"pname": f"{batch_name} %", "lid": int(LEDGER_ID)})
                row = cur.fetchone()
                if row:
                    return {
                        "batch_id": str(row[0]),
                        "status": row[1].strip(),
                        "consolidated": row[2].strip(),
                        "name": row[3].strip()
                    }
    except Exception:
        pass
    return None

def get_step2_errors():
    """Get errors from SME_CCF_GL_INTERFACE if Step 2 failed."""
    sql = "SELECT err, count(*) FROM apps.sme_ccf_gl_interface WHERE eflag = 'E' GROUP BY err"
    try:
        conn = get_db_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
                if rows:
                    return "\n".join(f"{r[0]}: {r[1]}" for r in rows)
                return ""
    except Exception as e:
        return str(e)

def get_reconcile_summary():
    """Get summary counts and amounts for Reconcile."""
    sql = "SELECT count(*), sum(nvl(entered_dr,0)), sum(nvl(entered_cr,0)) FROM apps.sme_ccf_gl_interface WHERE eflag = 'P'"
    try:
        conn = get_db_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
                if row and row[0] is not None:
                    dr = float(row[1]) if row[1] is not None else 0.0
                    cr = float(row[2]) if row[2] is not None else 0.0
                    return {
                        "rows": str(row[0]),
                        "dr": f"{dr:,.2f}",
                        "cr": f"{cr:,.2f}"
                    }
    except Exception:
        pass
    return {"rows": 0, "dr": "0.00", "cr": "0.00"}
