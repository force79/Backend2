from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, time
import analyze
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException


app = Flask(__name__)
CORS(app)  # Allow all origins, needed for Vercel/Netlify frontend
from flask_cors import CORS
CORS(app, resources={r"/*": {"origins": "https://frontend2-bice.vercel.app"}})


DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def fetch_attendance(roll_no, password, term):
    try:
        options = uc.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-popup-blocking")
        options.add_experimental_option("prefs", {
            "download.default_directory": DOWNLOAD_DIR,
            "plugins.always_open_pdf_externally": True,
            "download.prompt_for_download": False
        })

        driver = uc.Chrome(version_main=139, options=options)
        wait = WebDriverWait(driver, 20)
        downloaded_file = None

        # Login Page
        driver.get("https://eyojan.srmu.ac.in/psc/ps/?cmd=login&languageCd=ENG")
        wait.until(EC.presence_of_element_located((By.ID, "userid"))).send_keys(roll_no)
        wait.until(EC.presence_of_element_located((By.ID, "pwd"))).send_keys(password)
        wait.until(EC.element_to_be_clickable((By.NAME, "Submit"))).click()

        # ✅ Detect invalid login
        try:
            # if login failed, usually an error message div/alert appears
            error_element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "login_error"))  # change ID if different
            )
            if error_element.is_displayed():
                return "INVALID_CREDENTIALS"
        except TimeoutException:
            # no error element -> assume login success
            pass

        # Attendance Page
        driver.get("https://eyojan.srmu.ac.in/psp/ps/EMPLOYEE/SA/c/SRM_STDNT_ATT_MNU.SRM_STDNT_AT_CMP.GBL?FolderPath=PORTAL_ROOT_OBJECT.STUDENT_ACADEMIC_REPORTS.SRM_STDNT_AT_PG&IsFolder=false&IgnoreParamTempl=FolderPath%2cIsFolder")
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.TAG_NAME, "iframe")))

        wait.until(EC.presence_of_element_located((By.ID, "SRM_STDNT_L0_TB_RUN_CNTL_ID"))).send_keys(roll_no)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[id='\\#ICSearch']"))).click()

        input2 = wait.until(EC.presence_of_element_located((By.ID, "SRM_STDNT_L0_TB_STRM")))
        input2.clear()
        input2.send_keys(term)

        wait.until(EC.element_to_be_clickable((By.ID, "SRM_STDNT_WRK_BUTTON1"))).click()

        try:
            wait.until(EC.element_to_be_clickable((By.ID, "SRM_STDNT_ATT_PDF"))).click()
        except TimeoutException:
            print("Download button not found or already processing.")

        # Wait for download
        timeout = 40
        end_time = time.time() + timeout
        while time.time() < end_time:
            files = os.listdir(DOWNLOAD_DIR)
            pdf_files = [f for f in files if f.endswith(".pdf")]
            crdownload_files = [f for f in files if f.endswith(".crdownload")]

            if pdf_files and not crdownload_files:
                pdf_files.sort(key=lambda x: os.path.getmtime(os.path.join(DOWNLOAD_DIR, x)), reverse=True)
                candidate = os.path.join(DOWNLOAD_DIR, pdf_files[0])
                if os.path.getsize(candidate) > 0:
                    downloaded_file = candidate
                    break
            time.sleep(1)

        if downloaded_file:
            try:
                analyze.run_analysis()
            except Exception as e:
                print("Analysis error:", e)
            return os.path.basename(downloaded_file)
        else:
            return None

    except WebDriverException as e:
        print("WebDriver error:", e)
        return None
    finally:
        try:
            driver.quit()
        except:
            pass


# -------------------------------
# API Endpoints
# -------------------------------

@app.before_request
def log_request_info():
    print(f"[REQ] {request.method} {request.path} from {request.remote_addr}")
    if request.is_json:
        try:
            print(f"[REQ BODY] {request.get_json()}")
        except Exception:
            print("[REQ BODY] Failed to parse JSON")
    else:
        print("[REQ BODY] Not JSON")


@app.route("/api/check", methods=["POST"])
def api_check():
    data = request.get_json(force=True, silent=True)
    if not data:
        print("[ERROR] No JSON body received")
        return jsonify({"status": "error", "message": "Invalid request body"}), 400

    roll_no = data.get("roll_no")
    password = data.get("password")
    term = data.get("term")

    if not roll_no or not password or not term:
        print("[ERROR] Missing required fields:", data)
        return jsonify({"status": "error", "message": "Missing required fields"}), 400


    try:
        result = fetch_attendance(roll_no, password, term)
        if result == "INVALID_CREDENTIALS":
            return jsonify({"status": "error", "message": "Invalid Roll Number or Password"}), 401
        elif result:
            pdf_url = f"/api/download/{result}"
            return jsonify({"status": "success", "pdf_url": pdf_url})
        else:
            return jsonify({"status": "error", "message": "Failed to fetch attendance"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": f"Server error: {str(e)}"}), 500

@app.after_request
def after_request(response):
    print(f"[RESP] {request.method} {request.path} → {response.status}")
    return response

@app.route("/api/download/<filename>")
def api_download(filename):
    if os.path.exists(os.path.join(DOWNLOAD_DIR, filename)):
        return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)
    else:
        return jsonify({"status": "error", "message": "File not found"}), 404

# -------------------------------

if __name__ == "__main__":
    print("Flask server starting on 0.0.0.0:5500")
    app.run(host="0.0.0.0", port=5500)
