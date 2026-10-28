# ⚡ SME Bank - GL TFRS9 Automation Engine

ระบบประมวลผลและนำเข้าข้อมูลบัญชี **GL TFRS9 แบบอัตโนมัติ (End-to-End Workflow Pipeline)** เข้าสู่ระบบ **Oracle E-Business Suite (EBS) R12** สำหรับธนาคารพัฒนาวิสาหกิจขนาดกลางและขนาดย่อมแห่งประเทศไทย (SME Bank)

---

## 📋 สารบัญ
1. [ภาพรวมระบบและขั้นตอนการทำงาน (Pipeline Architecture)](#-ภาพรวมระบบและขั้นตอนการทำงาน)
2. [การนำไปใช้งานบนเครื่องอื่น (Cross-Machine Compatibility)](#-การนำไปใช้งานบนเครื่องอื่น)
3. [ความต้องการของระบบ (Prerequisites)](#-ความต้องการของระบบ)
4. [ขั้นตอนการติดตั้งและการเริ่มใช้งาน (Quick Start)](#-ขั้นตอนการติดตั้งและการเริ่มใช้งาน)
5. [คู่มือการตั้งค่าหน้าจอเชื่อมต่อ (Connection Setup)](#-คู่มือการตั้งค่าหน้าจอเชื่อมต่อ)
6. [ฟีเจอร์เด่นบนหน้า Dashboard](#-ฟีเจอร์เด่นบนหน้า-dashboard)
7. [โครงสร้างโปรเจกต์ (Project Structure)](#-โครงสร้างโปรเจกต์)

---

## 🔄 ภาพรวมระบบและขั้นตอนการทำงาน

ระบบทำหน้าที่รันกระบวนการนำเข้าข้อมูล GL TFRS9 รายวันตามลำดับขั้นตอนมาตรฐานของ Oracle EBS R12:

```
[ ไฟล์ GLTFRS9.TXT ] 
       │
       ▼
 [ Step 0: SFTP Pre-check & Put ] ───▶ อัปโหลดไฟล์ขึ้น Linux App Server (/data/TEST/apps/IMPORT/GL/DATA)
       │
       ▼
 [ Step 1: Load to Temp Table ]   ───▶ รัน SMELDRCCFGLINT โหลดข้อมูลเข้าตารางพัก SME_CCF_GL_INTERFACE
       │
       ▼
 [ Step 2: Validate & Import ]    ───▶ รัน SMECHKCCFGLINT ตรวจสอบความถูกต้อง และส่งเข้า Journal Import (GLLEZL)
       │
       ▼
 [ Step 2.5: GL Posting Check ]  ───▶ ตรวจสอบสถานะการ Post บัญชีในสมุดรายวัน (Ledger 1001) เป็น 'Posted (P)'
       │
       ▼
 [ Step 3: Reconcile & Clean ]    ───▶ รัน SMESUMGLINT สรุปยอดกระทบยอด (DR/CR) และล้างตารางพัก
       │
       ▼
 [ Step 4: Consolidate Monthly ] ───▶ รัน SMECONSOLDAILY_MONTHLY_TFRS9 รวมยอดจาก Daily เข้าสู่สมุดรายเดือน (Ledger 1002)
```

---

## 💻 การนำไปใช้งานบนเครื่องอื่น

### ❓ เครื่องอื่นจะสามารถใช้งานได้หรือไม่?

**ตอบ:** 
เดิมที **ไม่สามารถใช้ได้ทันที** เนื่องจากโค้ดเวอร์ชันเริ่มต้นมีการผูกติดกับสภาพแวดล้อมเฉพาะเครื่อง:
1. ผูกติดกับ Path ของ Oracle Developer Suite (`D:\DevSuiteHome_1\bin\sqlplus.exe`)
2. ผูกติดกับ TNS Alias (`SME_TEST_8020`) ในไฟล์ `tnsnames.ora` ของเครื่องเดิม
3. ฮาร์ดโค้ดรหัสผ่าน, IP เซิร์ฟเวอร์, สิทธิ์ User EBS (`MERCURY` / 7484) และโฟลเดอร์ไฟล์ในเครื่อง (`C:\Users\MBx13\...`)

---

### 🚀 สิ่งที่ปรับปรุงและพัฒนาเพิ่มเติมเพื่อให้ใช้งานได้ทุกเครื่อง:

1. **เปลี่ยนมาใช้ `python-oracledb` Thin Driver (Pure Python)**:
   - **ไม่ต้องติดตั้ง Oracle Client, Instant Client หรือ Oracle Developer Suite เลยแม้แต่น้อย!**
   - เชื่อมต่อผ่าน TCP Port โดยตรง (`1541` หรือ `1521`) เข้าฐานข้อมูล Oracle DB ได้ทันทีในทุกระบบปฏิบัติการ
2. **หน้าจอ Modal ตั้งค่าการเชื่อมต่อ (🔌 Connection Setup Modal)**:
   - มีหน้าต่างให้กรอก **Database Username & Password**, Host, Port, Service Name เพื่อเชื่อมต่อฐานข้อมูล
   - มีหน้าต่างให้กรอก **SFTP Username & Password**, Host, Port, Remote Upload Path สำหรับส่งไฟล์ข้อมูล
   - มีหน้าต่างให้กรอก **EBS Application Username & Password** สำหรับรัน Concurrent Program โดยระบบจะค้นหา **User ID**, **Responsibility ID** (สิทธิ์ General Ledger) ให้อัตโนมัติ
   - มีปุ่ม **ทดสอบการเชื่อมต่อ (Test Connection)** แยกแต่ละส่วนอย่างชัดเจน
   - บันทึกการตั้งค่าลงไฟล์ `config.json` ภายในเครื่องอัตโนมัติ (และตั้งค่า `.gitignore` เพื่อไม่ให้รหัสผ่านถูกส่งขึ้น GitHub เพื่อความปลอดภัย)
3. **ปรับสคริปต์ `start_automation.bat`**:
   - ใช้อ้างอิงโฟลเดอร์ปัจจุบันแบบยืดหยุ่น (`%~dp0`) สามารถวางโปรแกรมไว้ในไดรฟ์หรือโฟลเดอร์ใดก็ได้
   - ตรวจสอบและติดตั้ง Python Package ที่จำเป็นให้อัตโนมัติในครั้งแรกที่เปิดใช้งาน

---

## 📦 ความต้องการของระบบ

1. **Python 3.8** หรือใหม่กว่า
2. **การเชื่อมต่อเครือข่าย**: เครื่องต้องเชื่อมต่อเครือข่ายภายในหรือเปิด **VPN ของธนาคาร SME Bank** เพื่อให้เข้าถึง:
   - ฐานข้อมูล Oracle Database (เช่น `192.168.225.118:1541`)
   - เซิร์ฟเวอร์ SFTP Linux Application Server (เช่น `192.168.225.117:22`)

---

## 🛠️ ขั้นตอนการติดตั้งและการเริ่มใช้งาน

### 1. โคลน Repository
```bash
git clone https://github.com/wachira-mcr/GL_Automation_Upload.git
cd GL_Automation_Upload
```

### 2. ติดตั้ง Dependencies
```bash
pip install -r requirements.txt
```
*(หรือเพียงแค่ดับเบิ้ลคลิกไฟล์ `start_automation.bat` ระบบจะติดตั้งให้อัตโนมัติ)*

### 3. เริ่มต้นใช้งาน
ดับเบิ้ลคลิกที่ไฟล์ **`start_automation.bat`** หรือรันผ่าน Command Line:
```bash
python app.py
```
โปรแกรมจะเปิดเว็บเบราว์เซอร์ให้อัตโนมัติที่: **`http://127.0.0.1:5056`**

---

## 🔌 คู่มือการตั้งค่าหน้าจอเชื่อมต่อ (Connection Setup)

เมื่อเปิดโปรแกรมขึ้นมา ให้คลิกที่ปุ่ม **🔌 ตั้งค่าการเชื่อมต่อ** (หรือคลิกที่ Badge สถานะด้านบน) เพื่อตั้งค่า:

### 1. แท็บ 💾 ฐานข้อมูล DB (Oracle Database)
- **Host / IP**: `192.168.225.118` (หรือ `fidevdb12.smebank.co.th`)
- **Port**: `1541` (หรือพอร์ตของ DB ปลายทาง)
- **Service Name**: `ebs_TEST`
- **DB Username**: `apps`
- **DB Password**: รหัสผ่านของ user `apps`
- กดปุ่ม **🧪 ทดสอบเชื่อมต่อฐานข้อมูล (Test DB)** เพื่อยืนยันผล

### 2. แท็บ 📤 เซิร์ฟเวอร์ SFTP (Linux Application Server)
- **Host / IP**: `192.168.225.117` (หรือ `fidevapp12.smebank.co.th`)
- **Port**: `22`
- **Username**: `appltest`
- **Password**: รหัสผ่านของ user `appltest`
- **Remote Upload Path**: `/data/TEST/apps/IMPORT/GL/DATA`
- กดปุ่ม **🧪 ทดสอบเชื่อมต่อ SFTP (Test SFTP)** เพื่อยืนยันผล

### 3. แท็บ 👤 ผู้ใช้ EBS Concurrent (EBS Application User)
- **EBS Username**: เช่น `MERCURY` หรือ Username EBS ของท่าน
- **EBS Password**: รหัสผ่านผู้ใช้ใน EBS (ใส่หรือไม่ใส่ก็ได้)
- กดปุ่ม **🔍 ตรวจสอบสิทธิ์ผู้ใช้ EBS (Verify User)**:
  - ระบบจะตรวจสอบตาราง `apps.fnd_user` และดึงรายชื่อ Responsibility ด้าน GL มาให้เลือกใน Dropdown
  - ระบบจะบันทึกค่า `User ID`, `Resp ID`, `Appl ID` ให้โดยอัตโนมัติ

### 4. แท็บ ⚙️ ตั้งค่าทั่วไป
- **โฟลเดอร์ไฟล์ข้อมูล GL**: โฟลเดอร์ที่จัดเก็บไฟล์ `*TFRS9*.TXT` ในเครื่องคอมพิวเตอร์ของคุณ

> 💡 **หมายเหตุ**: เมื่อกรอกครบแล้ว ให้กดปุ่ม **💾 บันทึกและเชื่อมต่อ (Save & Connect)** การตั้งค่าจะถูกเก็บไว้ในไฟล์ `config.json` ครั้งต่อไปไม่ต้องกรอกใหม่

---

## 🌟 ฟีเจอร์เด่นบนหน้า Dashboard

| ฟีเจอร์ | คำอธิบาย |
|---|---|
| **Multiple File Batch Queue** | สามารถติ๊กเลือกไฟล์หลายวันพร้อมกันเพื่อรันต่อเนื่องอัตโนมัติทีละวัน |
| **Duplicate Prevention** | ตรวจสอบอัตโนมัติว่าไฟล์ใดเคย Import เข้า GL แล้ว เพื่อป้องกันการนำเข้าข้อมูลซ้ำซ้อน |
| **GL Period Status Check** | ตรวจสอบสถานะงวดบัญชีก่อนรัน หากงวดปิด (Closed) ระบบจะข้ามไฟล์ให้อัตโนมัติ |
| **Post After Sweep** | นำเข้าไฟล์ทุกวันจนถึง Step 3 ก่อน แล้วค่อยวนลูปตรวจการ Post ใน GL ทุก 30 วินาที เมื่อโพสต์ครบจึงทำ Step 4 ต่อจนเสร็จ |
| **Custom Step Range** | สามารถเลือกช่วง Step ได้อย่างอิสระ เช่น รันเฉพาะ Step 0 ถึง 2 หรือรันต่อตั้งแต่ Step 4 |
| **Safe Stop Point** | ปุ่มหยุดการทำงานแบบปลอดภัย (Safe Stop) ระบบจะไม่ตัดจบขณะที่ Concurrent รันอยู่ใน Oracle EBS แต่จะรอให้จบกระบวนการปัจจุบันก่อนจึงหยุด |
| **Real-time Terminal Logs** | แสดงข้อความบันทึกการทำงานสดจากเซิร์ฟเวอร์แบบ Real-time พร้อมแสดง Request ID ทุกขั้นตอน |

---

## 📂 โครงสร้างโปรเจกต์

```
GL_Automation_Upload/
├── app.py                      # Flask Web Application & REST API Controllers
├── engine.py                   # Core Automation Engine (oracledb, paramiko SFTP, EBS execution)
├── start_automation.bat        # สคริปต์ Launch โปรแกรมแบบ One-Click รันได้ทุกเครื่อง
├── requirements.txt            # รายการ Python dependencies (Flask, oracledb, paramiko)
├── config.example.json         # แม่แบบไฟล์การตั้งค่าการเชื่อมต่อ (Template)
├── .gitignore                  # ป้องกันการ Push รหัสผ่าน config.json และไฟล์แคชขึ้น Git
├── README.md                   # คู่มือการติดตั้งและการใช้งานภาษาไทยฉบับสมบูรณ์
├── templates/
│   └── index.html              # หน้าเว็บ Dashboard พร้อม Connection Setup Modal
└── static/                     # ไฟล์ Asset เพิ่มเติม (CSS, JS, Images)
```

---

## 📞 การดูแลรักษาและการแก้ปัญหา (Troubleshooting)

- **ปัญหา `cannot connect to database / timed out`**: ตรวจสอบว่าได้เปิด VPN ของ SME Bank หรือไม่ และ IP / Port ของฐานข้อมูลถูกต้องหรือไม่
- **ปัญหา `SFTP connection failed`**: ตรวจสอบสิทธิ์การเข้าถึง Port 22 ของเครื่อง Linux Server และรหัสผ่านของ `appltest`
- **ปัญหา `Request ID status Error`**: สามารถดู Request ID ที่แสดงใน Terminal Logs แล้วนำไปเปิดตรวจสอบ Error Log ในหน้าจอ Concurrent Requests ของระบบ Oracle EBS ได้ทันที
