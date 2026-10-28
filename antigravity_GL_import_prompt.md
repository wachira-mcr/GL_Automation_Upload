# เตรียมไฟล์ให้ Antigravity — SME GL Import (TFRS9)

## โครงสร้างโฟลเดอร์ที่แนะนำ
```
SME_GL_IMPORT\
  01_SMELDRCCFGLINT\      SMELDRCCFGLINT_new.prog (host script จาก $SQLGL_TOP/bin) + ไฟล์ .ctl ที่มันเรียก
  02_SMECHKCCFGLINT\      SMECHKCCFGLINT.rdf + SMECHKCCFGLINT.xml (convert ด้วย rwconverter)
  03_SMESUMGLINT\         SMESUMGLINT.rdf + SMESUMGLINT.xml
  04_CONSOL_TFRS9\        SME_DAILY_MONTHLY_INF_TFRS9_SPEC.sql + _BODY.sql
  DDL\                    DDL ของ temp table (ชื่ออยู่ใน .ctl) + SMEDAILY_GL_INTERFACE_TFRS9
  CONC_DEF\               parameter ของแต่ละ concurrent (ตารางด้านล่างพอ หรือ FNDLOAD .ldt)
  SAMPLE_DATA\            GLTFRS9.TXT 1 วัน (ตัดเหลือ ~200 บรรทัดก็พอ) + Glreconcile/AfterGlreconcile/Gldetail ของ 1 เดือน
  LOGS\                   log/output ของ concurrent request ตอนรันจริง (ถ้ามี)
```

**ข้อมูลที่เช็คจาก SME_TEST_8020 แล้ว**

| Step | Program | Executable | ประเภท | Parameters |
|---|---|---|---|---|
| 1 | SMELDRCCFGLINT | SMELDRCCFGLINT_new | **Host (shell)** ใน SQLGL | EFFECTIVE DATE, File Name |
| 2 | SMECHKCCFGLINT | SMECHKCCFGLINT | Oracle Reports | effective date, sets of books id, user id, chart of account id |
| 2.1 | Journal Import | (standard GLLEZL) | ถูก submit อัตโนมัติจาก step 2 | — |
| 3 | SMESUMGLINT | SMESUMGLINT | Oracle Reports | effective date |
| 4 | SMECONSOLDAILY_MONTHLY_TFRS9 | SME_DAILY_MONTHLY_INF_TFRS9.SME_GET_DATA | PL/SQL procedure | User ID, Account Date |

ใน `Downloads\GL` ตอนนี้มีแค่ **ข้อมูล** (GLTFRS9.TXT รายวัน 1–31 มี.ค., สิ้นเดือน เม.ย./พ.ค. + Excel reconcile) — **ยังไม่มี source code เลย** ต้องดึง 4 อย่างนี้เพิ่ม:
1. `SMELDRCCFGLINT_new.prog` + `.ctl` — จาก server `$SQLGL_TOP/bin` (ดูใน .prog ว่าเรียก ctl ตัวไหน, ctl มักอยู่ `$SQLGL_TOP/bin` หรือ `$XX_TOP/bin`)
2. `SMECHKCCFGLINT.rdf`, `SMESUMGLINT.rdf` — จาก `$SQLGL_TOP/reports/US/` แล้ว convert เป็น XML ให้ AI อ่านได้:
   `rwconverter.exe source=SMECHKCCFGLINT.rdf dest=SMECHKCCFGLINT.xml dtype=xmlfile overwrite=yes batch=yes`
   (.rdf เป็น binary — AI อ่านไม่ได้ ต้องส่ง .xml)
3. Package `SME_DAILY_MONTHLY_INF_TFRS9` spec+body — จาก `dba_source` (APPS, SME_TEST_8020)
4. DDL ของ temp table + `SMEDAILY_GL_INTERFACE_TFRS9` — `DBMS_METADATA.GET_DDL`

ไม่ต้องส่ง: GLTFRS9.TXT ทั้ง 33 วัน (ไฟล์ละ 3–15MB) — ส่ง 1 วันแบบตัดสั้นพอ

---

## Prompt สำหรับ Antigravity

```
บริบท: Oracle EBS R12 (DB 11.2), Module GL, ลูกค้า SME, ทำงานบน SME_TEST_8020
ฉันต้องรันและทำความเข้าใจ process Import GL Journal (TFRS9) ซึ่งรันตามลำดับ:

1. SME-Load GL Journal into temp table  (SMELDRCCFGLINT, host script SMELDRCCFGLINT_new + SQL*Loader)
   params: EFFECTIVE DATE, File Name
2. SME-Validate GL Journal in temp table and insert into gl interface  (SMECHKCCFGLINT.rdf)
   params: effective date, set of books id, user id, chart of accounts id
   2.1 Journal Import (standard) ถูก submit อัตโนมัติ
3. SME-Summary Interface to GL Report  (SMESUMGLINT.rdf)  params: effective date
4. SME - Consolidate จาก Daily ไป Monthly (TFRS9)
   (SMECONSOLDAILY_MONTHLY_TFRS9 -> SME_DAILY_MONTHLY_INF_TFRS9.SME_GET_DATA) params: User ID, Account Date

ไฟล์ในโฟลเดอร์นี้: source ของทั้ง 4 โปรแกรม (rdf แปลงเป็น xml แล้ว), DDL ตาราง,
ไฟล์ตัวอย่าง GLTFRS9.TXT (pipe-delimited มี header) และ Excel reconcile สิ้นเดือน

สิ่งที่ต้องการ (ยังไม่ต้องแก้โค้ด แค่อ่านและอธิบาย):
1. Data flow ทีละ step: อ่านจากตาราง/ไฟล์ไหน -> เขียนลงตาราง/ไฟล์ไหน
   (ไฟล์ -> temp table -> GL_INTERFACE -> GL_JE_* -> SMEDAILY_GL_INTERFACE_TFRS9 ...)
2. Mapping column ของ GLTFRS9.TXT -> temp table -> GL_INTERFACE (ตาราง)
3. Validation rule ทั้งหมดใน SMECHKCCFGLINT: เช็คอะไร, error แล้วเกิดอะไร (reject ทั้ง batch หรือรายบรรทัด), ดู error ได้ที่ไหน
4. Journal Import ถูก submit อย่างไร (FND_REQUEST.SUBMIT_REQUEST? GROUP_ID/JE_SOURCE อะไร)
5. Step 3 report สรุปอะไร ใช้ reconcile กับอะไร
6. Step 4 logic Consolidate Daily -> Monthly: เงื่อนไขเลือกข้อมูล, การ group/sum, มี DELETE/UPDATE/COMMIT ตรงไหน
   ถ้ารันซ้ำวันเดียวกันจะเกิดอะไร (idempotent หรือไม่)
7. Checklist การรัน: ก่อนรันต้องเตรียมอะไร (วางไฟล์ที่ path ไหน, ชื่อไฟล์, period ต้อง open)
   และ SQL สำหรับเช็คผลหลังแต่ละ step (นับ row, sum DR/CR เทียบกับไฟล์)
8. จุดเสี่ยง/ข้อสงสัยในโค้ด

สรุปเป็นภาษาไทย ใส่ชื่อ object/บรรทัดอ้างอิงจาก source จริง ห้ามเดา ถ้าข้อมูลไม่พอให้ระบุว่าขาดไฟล์อะไร
ห้ามรัน DDL/DML ใดๆ บน DB
```
