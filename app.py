from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file
from datetime import datetime, date
import sqlite3, hashlib, os, io, csv

app = Flask(__name__)

DB_PATH    = os.environ.get("DB_PATH", "igplan.db")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "admin123")

TIP_LABEL  = {"egitim":"Eğitim","vaka":"Vaka","motivasyon":"Motivasyon","duyuru":"Duyuru","reel":"Reel"}

# ── VERİTABANI ────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS icerik (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                tarih     TEXT    NOT NULL,
                tip       TEXT    NOT NULL DEFAULT 'egitim',
                konu      TEXT    NOT NULL,
                yazi      TEXT    DEFAULT '',
                durum     TEXT    DEFAULT 'taslak',
                olusturma TEXT    DEFAULT (datetime('now')),
                guncelleme TEXT   DEFAULT (datetime('now'))
            );
        """)
        conn.commit()

def admin_kontrol(sifre):
    return sifre == ADMIN_PASS

# ── SAYFALAR ──────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return redirect(url_for("admin_giris"))

@app.route("/admin")
def admin_giris():
    return render_template("giris.html")

@app.route("/admin/<sifre>")
def admin_panel(sifre):
    if not admin_kontrol(sifre):
        return "<h2 style='font-family:sans-serif;color:red;padding:40px'>❌ Erişim Reddedildi</h2>", 403
    return render_template("panel.html", s=sifre)

# ── İÇERİK API ────────────────────────────────────────────────────────────────
@app.route("/api/icerikler")
def api_icerikler():
    if not admin_kontrol(request.args.get("s", "")):
        return jsonify({"hata": "Yetkisiz"}), 401
    bas = request.args.get("bas", date.today().strftime("%Y-%m-%d"))
    bit = request.args.get("bit", date.today().strftime("%Y-%m-%d"))
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM icerik WHERE tarih BETWEEN ? AND ? ORDER BY tarih, id",
            (bas, bit)
        ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/icerik_ekle", methods=["POST"])
def api_icerik_ekle():
    if not admin_kontrol(request.args.get("s", "")):
        return jsonify({"hata": "Yetkisiz"}), 401
    d = request.get_json()
    tarih = d.get("tarih", "").strip()
    konu  = d.get("konu",  "").strip()
    if not tarih or not konu:
        return jsonify({"ok": False, "mesaj": "Tarih ve konu zorunludur."})
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO icerik (tarih, tip, konu, yazi, durum) VALUES (?,?,?,?,?)",
            (tarih, d.get("tip","egitim"), konu, d.get("yazi",""), d.get("durum","taslak"))
        )
        conn.commit()
        row = conn.execute("SELECT * FROM icerik WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify({"ok": True, "icerik": dict(row)})

@app.route("/api/icerik_guncelle/<int:iid>", methods=["POST"])
def api_icerik_guncelle(iid):
    if not admin_kontrol(request.args.get("s", "")):
        return jsonify({"hata": "Yetkisiz"}), 401
    d = request.get_json()
    konu = d.get("konu", "").strip()
    if not konu:
        return jsonify({"ok": False, "mesaj": "Konu zorunludur."})
    with get_db() as conn:
        conn.execute(
            "UPDATE icerik SET tarih=?, tip=?, konu=?, yazi=?, durum=?, guncelleme=datetime('now') WHERE id=?",
            (d.get("tarih"), d.get("tip","egitim"), konu, d.get("yazi",""), d.get("durum","taslak"), iid)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM icerik WHERE id=?", (iid,)).fetchone()
    return jsonify({"ok": True, "icerik": dict(row)})

@app.route("/api/icerik_sil/<int:iid>", methods=["POST"])
def api_icerik_sil(iid):
    if not admin_kontrol(request.args.get("s", "")):
        return jsonify({"hata": "Yetkisiz"}), 401
    with get_db() as conn:
        conn.execute("DELETE FROM icerik WHERE id=?", (iid,))
        conn.commit()
    return jsonify({"ok": True})

@app.route("/api/istatistik")
def api_istatistik():
    if not admin_kontrol(request.args.get("s", "")):
        return jsonify({"hata": "Yetkisiz"}), 401
    with get_db() as conn:
        toplam  = conn.execute("SELECT COUNT(*) FROM icerik").fetchone()[0]
        yayinda = conn.execute("SELECT COUNT(*) FROM icerik WHERE durum='yayinda'").fetchone()[0]
        hazir   = conn.execute("SELECT COUNT(*) FROM icerik WHERE durum='hazir'").fetchone()[0]
        taslak  = conn.execute("SELECT COUNT(*) FROM icerik WHERE durum='taslak'").fetchone()[0]
        bu_ay   = conn.execute(
            "SELECT COUNT(*) FROM icerik WHERE strftime('%Y-%m', tarih)=strftime('%Y-%m', 'now')"
        ).fetchone()[0]
    return jsonify({"toplam":toplam,"yayinda":yayinda,"hazir":hazir,"taslak":taslak,"bu_ay":bu_ay})

# ── EXPORT ────────────────────────────────────────────────────────────────────
@app.route("/export/csv")
def export_csv():
    if not admin_kontrol(request.args.get("s", "")):
        return "Yetkisiz", 401
    bas = request.args.get("bas", "2020-01-01")
    bit = request.args.get("bit", "2030-12-31")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT tarih,tip,konu,yazi,durum,olusturma FROM icerik WHERE tarih BETWEEN ? AND ? ORDER BY tarih",
            (bas, bit)
        ).fetchall()
    buf = io.StringIO()
    yaz = csv.writer(buf)
    yaz.writerow(["Tarih","Tip","Konu","Yazı","Durum","Oluşturma"])
    for r in rows:
        yaz.writerow([r["tarih"], TIP_LABEL.get(r["tip"],r["tip"]), r["konu"], r["yazi"], r["durum"], r["olusturma"]])
    bbuf = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    return send_file(bbuf, mimetype="text/csv", as_attachment=True,
                     download_name=f"igplan_{bas}_{bit}.csv")

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
