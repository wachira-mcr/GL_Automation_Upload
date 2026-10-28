import os
import json
import threading
import time
from datetime import datetime
from flask import Flask, render_template, jsonify, request
import engine

app = Flask(__name__)

STEPS = ["step0", "step1", "step2", "step2_5", "step3", "step4"]

# Global Automation State
state = {
    "is_running": False,
    "current_step": "idle",
    "step_statuses": {
        "step0": "idle",   # Pre-check & SFTP Upload
        "step1": "idle",   # Load to Temp
        "step2": "idle",   # Validate & Auto Journal Import
        "step2_5": "idle", # GL Daily Posting
        "step3": "idle",   # Summary & Clean Temp
        "step4": "idle"    # Consolidate to Monthly Ledger
    },
    "auto_post": True,
    "waiting_post_confirm": False,
    "batch_info": None,
    "reconcile_info": None,
    "logs": [],
    "error_message": None,
    "selected_file": None,
    "queue": None,         # "n/total" while sending many files
    "stop_requested": False,
    "progress_percent": 0
}

def log(msg):
    t_str = datetime.now().strftime("%H:%M:%S")
    entry = f"[{t_str}] {msg}"
    state["logs"].append(entry)
    print(entry)

class StopRequested(Exception):
    pass

def check_stop():
    """Safe stop point: never while a concurrent request is running, only between steps / while waiting for Post."""
    if state["stop_requested"]:
        raise StopRequested()

def begin(step):
    state["current_step"] = step  # set first so a stop here reports the step that was not started
    check_stop()
    state["step_statuses"][step] = "running"

def finish(step):
    state["step_statuses"][step] = "success"
    state["progress_percent"] = round((STEPS.index(step) + 1) * 100 / len(STEPS))

def run_step4(fnd_date):
    begin("step4")
    log("--> Step 4: รวมยอดจากสมุดรายวันเข้าสู่สมุดรายเดือน (SMECONSOLDAILY_MONTHLY_TFRS9)...")
    s4_req = engine.submit_concurrent_request(
        "SMECONSOLDAILY_MONTHLY_TFRS9",
        [engine.USER_ID, fnd_date],
        "SME - Consolidate จาก Daily ไป Monthly (TFRS9)",
        log_cb=log
    )
    s4_ok, _, s4_st = engine.wait_for_request(s4_req, timeout_sec=900, log_cb=log)
    if not s4_ok:
        raise Exception(f"Step 4 รันไม่สำเร็จ (Status: {s4_st})! กรุณาเช็ค Log ของ Request {s4_req}")
    log(f"Step 4 Consolidate เข้าสู่สมุดรายเดือน (Ledger {engine.CONFIG['ebs'].get('monthly_ledger_id', '1002')}) สำเร็จสมบูรณ์ 100%!")
    finish("step4")

def post_after_sweep(items, with_step4, poll_sec=30):
    """Post after: re-check each batch until it is Posted (P), then run Step 4 for it.
    Only checks/waits — posting itself is done in GL (manual or AutoPost). items: [{file, batch_name, fnd_date}]."""
    pending = list(items)
    done, last_note = 0, None
    for k in STEPS:
        state["step_statuses"][k] = "skipped"
    state["step_statuses"]["step2_5"] = "waiting"
    if with_step4:
        state["step_statuses"]["step4"] = "pending"
    state["current_step"] = "step2_5"
    log(f"===== 🔁 Post after: ไล่เช็คสถานะ Post {len(pending)} batch (เช็คทุก {poll_sec} วินาที, กด Stop เพื่อหยุด) =====")
    while pending:
        for it in list(pending):
            check_stop()
            b = engine.get_batch_info(it["batch_name"])
            if not b:
                if engine.get_interface_batches([it["batch_name"]]):
                    continue  # Journal Import ยังไม่เสร็จ รอรอบหน้า
                log(f"⚠️ ไม่พบ batch '{it['batch_name']}' ใน GL — ตัดออกจากรายการ")
                pending.remove(it)
                continue
            if b["status"] != "P":
                continue
            log(f"✅ Posted แล้ว: {b['name']}")
            if with_step4:
                state["selected_file"] = it["file"]
                state["batch_info"] = b
                run_step4(it["fnd_date"])
                state["step_statuses"]["step4"] = "pending"
            pending.remove(it)
            done += 1
        state["queue"] = f"รอ Post {len(pending)} batch" if pending else None
        if pending:
            note = ", ".join(i["batch_name"] for i in pending)
            if note != last_note:
                log(f"⏳ ยังไม่ Post ({len(pending)} batch): {note}")
                last_note = note
            state["current_step"] = "step2_5"
            for _ in range(poll_sec):
                check_stop()
                time.sleep(1)
    state["step_statuses"]["step2_5"] = "success"
    if with_step4:
        state["step_statuses"]["step4"] = "success"
    state["current_step"] = "completed"
    log(f"🏁 Post after เสร็จ: Post แล้ว{' + รัน Step 4' if with_step4 else ''} {done} batch")

def run_one_file(file_path, start_from, stop_after, auto_post, auto_clean_temp, force, skip_post=False):
    """Run one file (called by run_queue_thread). Returns 'done' / 'skipped' (duplicate) / 'skipped_period' (period closed) / None on error."""
    try:
        state["current_step"] = "precheck"
        state["selected_file"] = file_path
        state["auto_post"] = auto_post
        state["waiting_post_confirm"] = False
        state["error_message"] = None
        state["batch_info"] = None
        state["reconcile_info"] = None
        state["progress_percent"] = 0

        i_start, i_stop = STEPS.index(start_from), STEPS.index(stop_after)
        want = lambda step: i_start <= STEPS.index(step) <= i_stop and not (skip_post and step == "step2_5")
        for k in STEPS:
            state["step_statuses"][k] = "pending" if want(k) else "skipped"

        info = engine.read_file_info(file_path)
        batch_name, eff_date = info["batch_name"], info["eff_date"]
        if not eff_date:
            raise Exception(f"อ่าน JE_BATCH_NAME / EFFECTIVE_DATE จากไฟล์ไม่ได้: {file_path}")
        fnd_date = f"{eff_date.replace('-', '/')} 00:00:00"   # FND_STANDARD_DATE
        file_stem = os.path.splitext(os.path.basename(file_path))[0]

        log(f"=== เริ่มต้นกระบวนการ TFRS9 Automation ===")
        log(f"ไฟล์: {file_path}")
        log(f"Batch: {batch_name} | Effective Date: {eff_date} | รัน {start_from} → {stop_after}")
        log(f"ตัวเลือก: Auto Post = {'เปิด' if auto_post else 'ปิด (รอคลิกยืนยัน)'}")

        # -------------------------------------------------------------
        # งวดบัญชีต้องเปิด (เช็คก่อนเริ่ม Step 0) — งวดปิดให้ข้ามไฟล์นี้ไปไฟล์ถัดไป
        # -------------------------------------------------------------
        if want("step0"):
            log(f"กำลังตรวจสอบสถานะงวดบัญชี (GL Period) ของ {eff_date} ใน SME Daily Book ({engine.LEDGER_ID})...")
            is_open, period_status = engine.check_gl_period(eff_date)
            if not is_open:
                log(f"⏭️ ข้ามไฟล์: งวดบัญชีของวันที่ {eff_date} ไม่ได้เปิด (สถานะ = '{period_status}') ต้องเปิดงวดใน GL ก่อน")
                for k in STEPS:
                    state["step_statuses"][k] = "skipped"
                return "skipped_period"
            log(f"สถานะงวดบัญชี: OPEN ({period_status}) ผ่านเรียบร้อย")

        # -------------------------------------------------------------
        # กันนำเข้าซ้ำ: ถ้าจะรันถึง Step 1/2 (load + Journal Import) ต้องยังไม่มี batch นี้ใน GL
        # -------------------------------------------------------------
        if i_start <= STEPS.index("step2"):
            in_iface = engine.get_interface_batches([batch_name]).get(batch_name, 0)
            if in_iface:  # Journal Import ยังรันอยู่/ค้าง: ยังไม่มี batch ใน GL แต่ข้อมูลเข้าไปแล้ว — ห้ามซ้ำแม้เปิด force
                log(f"⏭️ ข้ามไฟล์: '{batch_name}' ยังอยู่ใน GL_INTERFACE {in_iface:,} แถว (Journal Import กำลังรันหรือค้าง) ตรวจใน GL ก่อน")
                for k in STEPS:
                    state["step_statuses"][k] = "skipped"
                return "skipped"
            dup = engine.get_imported_batches([batch_name]).get(batch_name, 0)
            if dup and not force:
                log(f"⏭️ ข้ามไฟล์: batch '{batch_name}' มีใน GL แล้ว {dup} batch (ถ้าตั้งใจนำเข้าซ้ำ ให้เปิด 'อนุญาตนำเข้าซ้ำ')")
                for k in STEPS:
                    state["step_statuses"][k] = "skipped"
                return "skipped"
            if dup:
                log(f"⚠️ batch '{batch_name}' มีใน GL แล้ว {dup} batch แต่ผู้ใช้เลือกอนุญาตนำเข้าซ้ำ")
            else:
                log(f"ตรวจไฟล์ซ้ำ: ยังไม่เคยนำเข้า '{batch_name}' ผ่าน")

        # -------------------------------------------------------------
        # STEP 0: Pre-check & SFTP Upload
        # -------------------------------------------------------------
        if want("step0"):
            begin("step0")
            log("--> Step 0: ตรวจสอบความพร้อมและอัปโหลดไฟล์ขึ้นเซิร์ฟเวอร์...")

            temp_rows = engine.get_temp_table_count()
            log(f"จำนวนข้อมูลในตารางพัก SME_CCF_GL_INTERFACE ปัจจุบัน: {temp_rows} แถว")
            if temp_rows > 0:
                if auto_clean_temp:
                    log("พบข้อมูลเก่าค้างในตารางพัก! กำลังรัน SMESUMGLINT เพื่อเคลียร์ตารางให้สะอาด...")
                    clean_req = engine.submit_concurrent_request("SMESUMGLINT", [fnd_date], "Auto Clean Temp Table", log_cb=log)
                    engine.wait_for_request(clean_req, log_cb=log)
                    time.sleep(2)
                    log(f"เคลียร์ตารางพักเรียบร้อย ข้อมูลคงเหลือ: {engine.get_temp_table_count()} แถว")
                else:
                    log("คำเตือน: มีข้อมูลเก่าค้างในตารางพัก แนะนำให้เปิดตัวเลือก Auto-clean Temp")

            engine.sftp_upload_file(file_path, f"{file_stem}.TXT", log_cb=log)
            finish("step0")

        # -------------------------------------------------------------
        # STEP 1: Load to Temp Table (SMELDRCCFGLINT) — param เดียวคือชื่อไฟล์ไม่มี .TXT
        # -------------------------------------------------------------
        if want("step1"):
            begin("step1")
            log(f"--> Step 1: สั่งรันโปรแกรมโหลดไฟล์ {file_stem} เข้าตารางพัก (SMELDRCCFGLINT)...")
            s1_req = engine.submit_concurrent_request("SMELDRCCFGLINT", [file_stem], "SME-Load GL Journal into temp table", log_cb=log)
            s1_ok, _, s1_st = engine.wait_for_request(s1_req, log_cb=log)
            if not s1_ok:
                raise Exception(f"Step 1 รันไม่สำเร็จ (Status: {s1_st})! ตรวจสอบ Log ของ Request ID {s1_req}")
            rows_loaded = engine.get_temp_table_count()
            log(f"Step 1 สำเร็จสมบูรณ์! โหลดเข้าตารางพักแล้วทั้งหมด {rows_loaded:,} แถว")
            finish("step1")

        # -------------------------------------------------------------
        # STEP 2: Validate & Auto Journal Import (SMECHKCCFGLINT)
        # -------------------------------------------------------------
        if want("step2"):
            begin("step2")
            log("--> Step 2: ตรวจสอบความถูกต้องและส่งเข้า GL (SMECHKCCFGLINT)...")
            s2_req = engine.submit_concurrent_request(
                "SMECHKCCFGLINT",
                [fnd_date, engine.LEDGER_ID, engine.USER_ID, engine.COA_ID],
                "SME-Validate GL Journal in temp table",
                log_cb=log
            )
            s2_ok, _, s2_st = engine.wait_for_request(s2_req, log_cb=log)

            err_report = engine.get_step2_errors()
            if err_report:
                log(f"❌ พบข้อผิดพลาดใน Step 2:\n{err_report}")
                raise Exception(f"Step 2 พบข้อผิดพลาดในการตรวจสอบข้อมูล:\n{err_report}")
            if not s2_ok:
                raise Exception(f"Step 2 รันไม่สำเร็จ (Status: {s2_st})! ตรวจสอบ Log ของ Request ID {s2_req}")

            log("Step 2 ตรวจสอบข้อมูลผ่านทั้งหมด 100%!")
            log("กำลังรอการสร้าง Journal Import (GLLEZL) อัตโนมัติ...")
            time.sleep(5)

            jv_req, jv_ph, jv_st = engine.get_latest_sub_request(s2_req)
            if jv_req:
                log(f"พบ Journal Import Request ID: {jv_req} กำลังรอให้รันเสร็จ...")
                engine.wait_for_request(jv_req, log_cb=log)
                log(f"Journal Import Request {jv_req} ประมวลผลเสร็จสิ้น")

            batch = engine.get_batch_info(batch_name)
            if batch:
                state["batch_info"] = batch
                log(f"สร้าง Journal Batch ใน GL สำเร็จ: {batch['name']} (Status: {batch['status']})")
            finish("step2")

        # -------------------------------------------------------------
        # STEP 2.5: GL Daily Posting
        # -------------------------------------------------------------
        if want("step2_5"):
            begin("step2_5")
            log("--> Step 2.5: ขั้นตอนการ Post รายการบัญชีในสมุดรายวัน...")

            if not auto_post:
                state["waiting_post_confirm"] = True
                log("⏸️ ระบบหยุดรอการยืนยัน: ผู้ใช้เลือกให้หยุดตรวจทานก่อน Post")
                log("👉 กรุณาเปิดจอ Journals > Enter ใน GL เพื่อตรวจยอดและกดปุ่ม Post")
                log("👉 เมื่อ Post เสร็จเรียบร้อยแล้ว ให้กดปุ่ม 'ยืนยันให้รันต่อ' ที่หน้าจอ Dashboard นี้")

                while state["waiting_post_confirm"]:
                    check_stop()
                    b_chk = engine.get_batch_info(batch_name)
                    if b_chk and b_chk["status"] == 'P':
                        log("ตรวจพบสถานะ Batch ใน GL เปลี่ยนเป็น 'P' (Posted) แล้ว ดำเนินการต่ออัตโนมัติ!")
                        state["waiting_post_confirm"] = False
                        break
                    time.sleep(3)
            else:
                log("กำลังตรวจสอบสถานะการ Post อัตโนมัติ...")
                for _ in range(60):
                    check_stop()
                    b_chk = engine.get_batch_info(batch_name)
                    if b_chk and b_chk["status"] == 'P':
                        log(f"Batch {b_chk['name']} โพสต์เสร็จสมบูรณ์แล้ว (Status: P)")
                        break
                    time.sleep(3)

            b_final = engine.get_batch_info(batch_name)
            state["batch_info"] = b_final
            if not b_final or b_final["status"] != 'P':
                log("⚠️ คำเตือน: สถานะ Batch ยังไม่เป็น 'P' (อาจติดคิว Posting) แต่จะพยายามดำเนินการต่อ")
            finish("step2_5")

        # -------------------------------------------------------------
        # STEP 3: Reconcile Summary & Clean Temp (SMESUMGLINT)
        # -------------------------------------------------------------
        if want("step3"):
            begin("step3")
            log("--> Step 3: สรุปยอดกระทบยอดและล้างตารางพัก (SMESUMGLINT)...")

            s_info = engine.get_reconcile_summary()
            state["reconcile_info"] = s_info
            log(f"สรุปยอดนำเข้า: จำนวน {s_info['rows']} แถว | ยอด Entered DR: {s_info['dr']} บาท")

            s3_req = engine.submit_concurrent_request("SMESUMGLINT", [fnd_date], "SME-Summary Interface to GL Report", log_cb=log)
            engine.wait_for_request(s3_req, log_cb=log)
            time.sleep(2)
            log(f"Step 3 เสร็จสิ้น! ตารางพักถูกล้างเหลือ: {engine.get_temp_table_count()} แถว")
            finish("step3")

        # -------------------------------------------------------------
        # STEP 4: Consolidate to Monthly Ledger (SMECONSOLDAILY_MONTHLY_TFRS9)
        # -------------------------------------------------------------
        if want("step4"):
            run_step4(fnd_date)

        state["current_step"] = "completed"
        state["progress_percent"] = 100
        if stop_after == "step4":
            log("🎉 ประมวลผลทุกขั้นตอนเสร็จสิ้นเรียบร้อยแล้ว")
        else:
            log(f"✅ หยุดหลัง {stop_after} ตามที่เลือก — รันต่อได้โดยเลือก 'เริ่มที่ step' ถัดไป")
        return "done"

    except StopRequested:
        state["waiting_post_confirm"] = False
        log(f"⏹️ หยุดตามคำสั่งผู้ใช้ ก่อนเริ่ม/ระหว่างรอ {state['current_step']} — รันต่อได้โดยเลือก 'เริ่มที่ step' นี้")
        for k, st in state["step_statuses"].items():
            if st in ("pending", "running"):
                state["step_statuses"][k] = "stopped"
        state["current_step"] = "stopped"
        return "stopped"
    except Exception as e:
        err = str(e)
        state["error_message"] = err
        log(f"❌ เกิดข้อผิดพลาดในขั้นตอน {state['current_step']}: {err}")
        if state["current_step"] in state["step_statuses"]:
            state["step_statuses"][state["current_step"]] = "error"

def run_queue_thread(file_paths, start_from, stop_after, auto_post, auto_clean_temp, force, skip_post, post_after=False):
    """Run files one by one (same step settings); skip duplicates / closed periods, stop at the first error.
    post_after: phase 1 runs each file up to Step 3 without waiting for Post; phase 2 sweeps the batches until Posted, then Step 4."""
    state["is_running"] = True
    state["stop_requested"] = False
    state["logs"] = []
    results = {"done": 0, "skipped": 0, "skipped_period": 0}
    sweep_items, finished = [], True
    if post_after:  # steps ที่ต้องรอ Post (2.5, 4) ย้ายไปทำใน phase 2
        skip_post = True
        phase1_stop = STEPS[min(STEPS.index(stop_after), STEPS.index("step3"))]
    else:
        phase1_stop = stop_after
    try:
        for n, fp in enumerate(file_paths, 1):
            if state["stop_requested"]:
                log(f"⏹️ หยุดคิวตามคำสั่งผู้ใช้ก่อนไฟล์ {n}/{len(file_paths)} (ไฟล์ที่เหลือยังไม่ได้รัน)")
                finished = False
                break
            state["queue"] = f"{n}/{len(file_paths)}"
            log(f"########## ไฟล์ {n}/{len(file_paths)}: {fp} ##########")
            if STEPS.index(start_from) <= STEPS.index(phase1_stop):
                r = run_one_file(fp, start_from, phase1_stop, auto_post, auto_clean_temp, force, skip_post)
            else:
                r = "done"  # post after อย่างเดียว (เริ่มที่ Step 4): ไม่มี step ใน phase 1
                log("Post after: ไม่มี step ก่อน Post ให้รัน — รอไล่เช็ค Post")
            if r is None:
                log(f"⛔ หยุดคิวที่ไฟล์ {n}/{len(file_paths)} เพราะเกิดข้อผิดพลาด (ไฟล์ที่เหลือยังไม่ได้รัน)")
                finished = False
                break
            if r == "stopped":
                log(f"⏹️ หยุดคิวที่ไฟล์ {n}/{len(file_paths)} (ไฟล์ที่เหลือยังไม่ได้รัน)")
                finished = False
                break
            results[r] += 1
            if post_after and r in ("done", "skipped"):  # skipped = นำเข้าไว้แล้ว ก็ไล่เช็ค Post ได้
                info = engine.read_file_info(fp)
                sweep_items.append({"file": fp, "batch_name": info["batch_name"],
                                    "fnd_date": f"{info['eff_date'].replace('-', '/')} 00:00:00"})
        log(f"📦 สรุปคิว: ส่งแล้ว {results['done']} ไฟล์ | ข้ามเพราะซ้ำ {results['skipped']} ไฟล์ | ข้ามเพราะงวดปิด {results['skipped_period']} ไฟล์ | ทั้งหมด {len(file_paths)} ไฟล์")

        if post_after and finished and sweep_items:
            try:
                post_after_sweep(sweep_items, with_step4=(stop_after == "step4"))
            except StopRequested:
                log("⏹️ หยุดการไล่เช็ค Post ตามคำสั่งผู้ใช้ — กลับมาไล่ต่อได้: เลือกไฟล์เดิม ติ๊ก Post after แล้ว 'เริ่มที่ step' = 4")
                state["current_step"] = "stopped"
            except Exception as e:
                state["error_message"] = str(e)
                log(f"❌ เกิดข้อผิดพลาดระหว่างไล่เช็ค Post: {e}")
                state["current_step"] = "error"
    finally:
        state["queue"] = None
        state["stop_requested"] = False
        state["is_running"] = False

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/config", methods=["GET", "POST"])
def manage_config():
    if request.method == "POST":
        data = request.json or {}
        cfg = engine.load_config()
        for k in ["db", "sftp", "ebs", "app"]:
            if k in data and isinstance(data[k], dict):
                # If password in request is empty, preserve existing password if present
                for pk in ["password"]:
                    if pk in cfg.get(k, {}) and (pk not in data[k] or data[k][pk] == ""):
                        data[k][pk] = cfg[k][pk]
                cfg[k].update(data[k])
        engine.save_config(cfg)
        return jsonify({"status": "saved", "config": sanitize_config(cfg)})

    # GET
    return jsonify(sanitize_config(engine.CONFIG))

def sanitize_config(cfg):
    """Return config with password presence indicators instead of clear text if needed, or masked."""
    out = json.loads(json.dumps(cfg))
    # Provide flags indicating if passwords are set
    out["db"]["has_password"] = bool(out["db"].get("password"))
    out["sftp"]["has_password"] = bool(out["sftp"].get("password"))
    return out

@app.route("/api/test/db", methods=["POST"])
def api_test_db():
    data = request.json or {}
    cfg = dict(engine.CONFIG.get("db", {}))
    cfg.update(data)
    ok, msg = engine.test_db_connection(cfg)
    return jsonify({"success": ok, "message": msg})

@app.route("/api/test/sftp", methods=["POST"])
def api_test_sftp():
    data = request.json or {}
    cfg = dict(engine.CONFIG.get("sftp", {}))
    cfg.update(data)
    ok, msg = engine.test_sftp_connection(cfg)
    return jsonify({"success": ok, "message": msg})

@app.route("/api/test/ebs_user", methods=["POST"])
def api_test_ebs_user():
    data = request.json or {}
    username = data.get("user_name") or engine.CONFIG["ebs"].get("user_name", "")
    password = data.get("password")
    ok, msg, user_data = engine.test_ebs_user(username, password)
    return jsonify({"success": ok, "message": msg, "data": user_data})

@app.route("/api/connection_status")
def connection_status():
    db_ok, db_msg = engine.test_db_connection()
    sftp_ok, sftp_msg = engine.test_sftp_connection()
    return jsonify({
        "db": {
            "ok": db_ok,
            "message": db_msg,
            "info": f"{engine.CONFIG['db'].get('user', '')}@{engine.CONFIG['db'].get('host', '')}:{engine.CONFIG['db'].get('port', '')}/{engine.CONFIG['db'].get('service_name', '')}"
        },
        "sftp": {
            "ok": sftp_ok,
            "message": sftp_msg,
            "info": f"{engine.CONFIG['sftp'].get('user', '')}@{engine.CONFIG['sftp'].get('host', '')}"
        },
        "ebs": {
            "user_name": engine.CONFIG['ebs'].get('user_name', ''),
            "user_id": engine.CONFIG['ebs'].get('user_id', ''),
            "resp_id": engine.CONFIG['ebs'].get('resp_id', '')
        }
    })

@app.route("/api/dates")
def get_dates():
    folder = request.args.get("folder") or engine.LOCAL_GL_PATH
    if not os.path.isdir(folder):
        return jsonify({"status": "error", "message": f"ไม่พบโฟลเดอร์: {folder}", "dates": []}), 400
    return jsonify({"folder": folder, "dates": engine.scan_available_dates(folder)})

@app.route("/api/browse", methods=["POST"])
def browse_folder():
    """Open a native folder picker on this PC (app runs locally)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        init_dir = (request.json or {}).get("folder") or engine.LOCAL_GL_PATH
        if not os.path.isdir(init_dir):
            init_dir = os.path.expanduser("~")
        folder = filedialog.askdirectory(initialdir=init_dir)
        root.destroy()
        return jsonify({"folder": os.path.normpath(folder) if folder else ""})
    except Exception as e:
        return jsonify({"folder": "", "error": str(e)})

@app.route("/api/start", methods=["POST"])
def start_automation():
    if state["is_running"]:
        return jsonify({"status": "error", "message": "ระบบกำลังทำงานอยู่แล้ว"}), 400

    # Validate connection credentials only on machines without sqlplus / default setup
    if not engine.is_sqlplus_available():
        db_cfg = engine.CONFIG.get("db", {})
        sftp_cfg = engine.CONFIG.get("sftp", {})
        if not db_cfg.get("user") or not (db_cfg.get("host") or db_cfg.get("tns_name")):
            return jsonify({"status": "error", "message": "กรุณาตั้งค่าการเชื่อมต่อ DB ให้ครบถ้วนก่อนเริ่ม (คลิก 'ตั้งค่าการเชื่อมต่อ')"}), 400
        if not sftp_cfg.get("host") or not sftp_cfg.get("user"):
            return jsonify({"status": "error", "message": "กรุณาตั้งค่าการเชื่อมต่อ SFTP ให้ครบถ้วนก่อนเริ่ม (คลิก 'ตั้งค่าการเชื่อมต่อ')"}), 400

    data = request.json or {}
    file_paths = data.get("file_paths") or [data.get("file_path")]
    start_from = data.get("start_from", "step0")
    stop_after = data.get("stop_after", "step4")

    if not all(p and os.path.isfile(p) for p in file_paths):
        return jsonify({"status": "error", "message": "กรุณาเลือกไฟล์"}), 400
    if start_from not in STEPS or stop_after not in STEPS or STEPS.index(start_from) > STEPS.index(stop_after):
        return jsonify({"status": "error", "message": "'เริ่มที่ step' ต้องอยู่ก่อน 'ทำถึง step'"}), 400
    loads = STEPS.index(start_from) <= STEPS.index("step2")
    if len(file_paths) > 1 and loads and (start_from != "step0" or STEPS.index(stop_after) < STEPS.index("step3")):
        return jsonify({"status": "error", "message": "ส่งหลายไฟล์ต้อง 'เริ่มที่ step' = 0 และ 'ทำถึง step' ตั้งแต่ 3 ขึ้นไป (หรือเริ่มที่ 2.5 ขึ้นไปเพื่อไล่ Post ไฟล์ที่นำเข้าแล้ว)"}), 400
    post_after = data.get("post_after", False)
    if post_after and STEPS.index(stop_after) < STEPS.index("step2_5"):
        return jsonify({"status": "error", "message": "Post after ต้องตั้ง 'ทำถึง step' ตั้งแต่ 2.5 ขึ้นไป"}), 400

    opts = (start_from, stop_after, data.get("auto_post", True), data.get("auto_clean_temp", True), data.get("force", False), data.get("skip_post", False), post_after)
    threading.Thread(target=run_queue_thread, args=(file_paths, *opts), daemon=True).start()
    return jsonify({"status": "started", "files": len(file_paths)})

@app.route("/api/status")
def get_status():
    return jsonify(state)

@app.route("/api/stop", methods=["POST"])
def stop_automation():
    if state["is_running"] and not state["stop_requested"]:
        state["stop_requested"] = True
        log("⏹️ ได้รับคำสั่งหยุด: จะหยุดเมื่อ concurrent request ที่รันอยู่ตอนนี้เสร็จ (ไม่ตัดกลางคันใน EBS)")
    return jsonify({"status": "stopping"})

@app.route("/api/confirm_post", methods=["POST"])
def confirm_post():
    state["waiting_post_confirm"] = False
    log("ผู้ใช้กดยืนยันการ Post ใน GL เรียบร้อยแล้ว กำลังดำเนินการต่อ...")
    return jsonify({"status": "resumed"})

@app.route("/api/reset", methods=["POST"])
def reset_state():
    if not state["is_running"]:
        for k in state["step_statuses"]:
            state["step_statuses"][k] = "idle"
        state["current_step"] = "idle"
        state["logs"] = []
        state["error_message"] = None
        state["progress_percent"] = 0
        state["batch_info"] = None
        state["reconcile_info"] = None
    return jsonify({"status": "reset"})

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Starting SME GL TFRS9 Automation Dashboard...")
    print("👉 Open Browser at: http://127.0.0.1:5056")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5056, debug=False)
