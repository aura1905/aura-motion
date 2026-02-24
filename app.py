import os
import sys
import subprocess
import json
import urllib.request
import urllib.parse
import random
import traceback
import webbrowser
from threading import Timer
from flask import Flask, render_template, request, jsonify, make_response
from werkzeug.utils import secure_filename

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

app = Flask(__name__, template_folder=get_resource_path('templates'))

# --- 설정 (Configuration) ---
COMFYUI_URL = "http://192.168.3.15:8189" 
UPLOAD_FOLDER = os.path.join(os.path.abspath("."), 'uploads')
TEMPLATE_FILENAME = get_resource_path('wan_api_aura.json')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

CLASS_PRESETS = {
    "warrior": { "name": "전사형 (Warrior)", "mod": "무거운 무기로 크게 내리치는" },
    "mage": { "name": "마법사형 (Mage)", "mod": "우아하게 지팡이를 휘두르는" },
    "musketeer": { "name": "총사형 (Musketeer)", "mod": "빠르게 사격하는" },
    "martial_artist": { "name": "무도가형 (Martial Artist)", "mod": "날카로운 발차기를 하는" }
}

def upload_to_comfyui(filepath):
    filename = os.path.basename(filepath)
    with open(filepath, 'rb') as f: file_data = f.read()
    boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
    body = b'\r\n'.join([
        b'--' + boundary.encode(),
        b'Content-Disposition: form-data; name="image"; filename="' + filename.encode() + b'"',
        b'Content-Type: image/jpeg', b'', file_data,
        b'--' + boundary.encode() + b'--', b''
    ])
    req_up = urllib.request.Request(f"{COMFYUI_URL}/upload/image", data=body)
    req_up.add_header('Content-Type', 'multipart/form-data; boundary=%s' % boundary)
    with urllib.request.urlopen(req_up) as res_up: return json.loads(res_up.read().decode())

@app.route('/')
def index():
    return render_template('index.html', classes=CLASS_PRESETS)

@app.route('/generate', methods=['POST'])
def generate():
    try:
        char_name = request.form.get('char_name', 'Unknown')
        save_path_prefix = request.form.get('save_path', 'WAN/GE_SD/PC/').rstrip('/')
        batch_count = int(request.form.get('batch_count', 1))
        duration = float(request.form.get('duration', 1.2))
        remove_bg = request.form.get('remove_bg', 'true').lower() == 'true'
        
        selected_motions = request.form.getlist('motions')
        file = request.files.get('image')
        if not file: return jsonify({"error": "이미지가 없습니다."}), 400
        
        filepath = os.path.join(UPLOAD_FOLDER, secure_filename(file.filename))
        file.save(filepath)

        with open(TEMPLATE_FILENAME, 'r', encoding='utf-8') as f: template = json.load(f)
        print(f"[*] Template loaded. Node count: {len(template)}. Has node 1788: {'1788' in template}")
        upload_res = upload_to_comfyui(filepath)
        blackwell_filename = upload_res['name']

        results = []
        for m_type in selected_motions:
            custom_prompt = request.form.get(f'prompt_{m_type}', '')
            for v in range(1, batch_count + 1):
                payload = json.loads(json.dumps(template))
                
                # 1. 원화 주입 (시작/끝 프레임 고정)
                payload["23"]["inputs"]["image"] = blackwell_filename
                payload["24"]["inputs"]["image"] = blackwell_filename
                payload["1370"]["inputs"]["text"] = custom_prompt
                payload["1512:1668"]["inputs"]["value"] = int(duration) 
                
                # 2. 배경 제거(RMBG) 스위칭 로직
                if remove_bg:
                    # 제거 활성화: 워크플로우 원본 그대로 유지 (28 -> 1788 -> 1512:1731:1099)
                    # wan_api_aura.json에 이미 올바르게 설정되어 있으므로 추가 조작 불필요
                    print(f"  [+] RMBG ON: 1788 in payload={('1788' in payload)}, 28.images={payload['28']['inputs']['images']}")
                else:
                    # 제거 비활성화: RMBG 노드(1788)를 페이로드에서 완전 제거
                    if "1788" in payload:
                        del payload["1788"]
                    payload["28"]["inputs"]["images"] = ["1512:1731:1099", 0]
                    print(f"  [-] RMBG OFF: 1788 removed, 28.images={payload['28']['inputs']['images']}")
                
                # 최종 전송 전 검증 로그
                print(f"  [DEBUG] Final 28.images: {payload['28']['inputs']['images']}, Total nodes: {len(payload)}")

                full_save_path = f"{save_path_prefix}/{char_name}/{char_name}_{m_type}_v{v}"
                payload["28"]["inputs"]["filename_prefix"] = full_save_path
                payload["1512:1670"]["inputs"]["value"] = random.randint(1000000000, 9999999999)

                req_p = urllib.request.Request(f"{COMFYUI_URL}/prompt", 
                                             data=json.dumps({"prompt": payload}).encode("utf-8"),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req_p) as res_p:
                    results.append({"type": m_type, "version": v, "prompt_id": json.loads(res_p.read().decode())['prompt_id']})

        return jsonify({"status": "Success", "queued": results})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/status/<prompt_id>')
def get_status(prompt_id):
    try:
        with urllib.request.urlopen(f"{COMFYUI_URL}/history/{prompt_id}") as res:
            history = json.loads(res.read().decode())
        if prompt_id in history:
            entry = history[prompt_id]
            status = entry.get('status', {})
            # ComfyUI가 아직 처리 중이면 Processing 반환
            if not status.get('completed', False):
                return jsonify({"status": "Processing"})
            # 에러로 완료된 경우
            if status.get('status_str') == 'error':
                return jsonify({"status": "Failed"})
            # 정상 완료 → GIF 출력 확인
            outputs = entry.get('outputs', {})
            if "28" in outputs:
                out = outputs["28"]
                gif_data = out.get("gifs", out.get("images", [None]))[0]
                if gif_data:
                    img_url = f"{COMFYUI_URL}/view?filename={gif_data['filename']}&subfolder={gif_data['subfolder']}&type=output"
                    return jsonify({"status": "Completed", "url": img_url})
            return jsonify({"status": "Failed"})
        return jsonify({"status": "Processing"})
    except: return jsonify({"status": "Processing"})

@app.route('/proxy_download')
def proxy_download():
    url = request.args.get('url')
    filename = request.args.get('filename', 'animation.gif')
    try:
        with urllib.request.urlopen(url) as res: data = res.read()
        response = make_response(data)
        response.headers.set('Content-Type', 'image/gif')
        response.headers.set('Content-Disposition', 'attachment', filename=filename)
        return response
    except: return "Error", 500

def kill_port(port):
    """시작 전 해당 포트를 점유하는 기존 프로세스를 자동 종료"""
    try:
        result = subprocess.run(
            ['netstat', '-ano'], capture_output=True, text=True, timeout=5
        )
        my_pid = os.getpid()
        killed = []
        for line in result.stdout.splitlines():
            if f':{port}' in line and 'LISTENING' in line:
                parts = line.split()
                pid = int(parts[-1])
                if pid != my_pid and pid != 0:
                    try:
                        subprocess.run(['taskkill', '/PID', str(pid), '/F'],
                                       capture_output=True, timeout=5)
                        killed.append(pid)
                    except: pass
        if killed:
            print(f"[*] 기존 포트 {port} 프로세스 정리 완료: {killed}")
            import time; time.sleep(1)
    except: pass

def open_browser(): webbrowser.open_new("http://127.0.0.1:3031")

if __name__ == '__main__':
    kill_port(3031)
    Timer(1.5, open_browser).start()
    app.run(host='0.0.0.0', port=3031, debug=False)
