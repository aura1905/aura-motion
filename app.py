import os
import json
import urllib.request
import urllib.parse
import random
import traceback
from flask import Flask, render_template, request, jsonify, make_response
from werkzeug.utils import secure_filename

app = Flask(__name__)

# --- 설정 (Configuration) ---
COMFYUI_URL = "http://127.0.0.1:8189"  # 블랙웰 서버 내부에서 직접 통신!
UPLOAD_FOLDER = 'uploads'
TEMPLATE_FILENAME = 'knight_v7_struct_template.json'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

CLASS_PRESETS = {
    "warrior": { "name": "전사형 (Warrior)", "mod": "무거운 무기로 머리 위에서부터 바닥까지 크게 내리치는" },
    "mage": { "name": "마법사형 (Mage)", "mod": "우아하게 지팡이를 휘두르는" },
    "musketeer": { "name": "총사형 (Musketeer)", "mod": "빠르게 조준하고 사격 후의 반동이 느껴지는" },
    "martial_artist": { "name": "무도가형 (Martial Artist)", "mod": "날카로운 하이킥과 펀치를 조합한" }
}

def upload_to_comfyui(filepath):
    filename = os.path.basename(filepath)
    with open(filepath, 'rb') as f:
        file_data = f.read()
    boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
    parts = [
        '--' + boundary,
        'Content-Disposition: form-data; name="image"; filename="%s"' % filename,
        'Content-Type: image/jpeg', '', file_data,
        '--' + boundary + '--', ''
    ]
    body = b'\r\n'.join([p if isinstance(p, bytes) else p.encode('utf-8') for p in parts])
    req = urllib.request.Request(f"{COMFYUI_URL}/upload/image", data=body)
    req.add_header('Content-Type', 'multipart/form-data; boundary=%s' % boundary)
    with urllib.request.urlopen(req) as res:
        return json.loads(res.read().decode())

@app.route('/')
def index():
    return render_template('index.html', classes=CLASS_PRESETS)

@app.route('/generate', methods=['POST'])
def generate():
    try:
        char_name = request.form.get('char_name', 'Unknown')
        save_path_prefix = request.form.get('save_path', 'WAN/GE_SD/PC/').rstrip('/')
        batch_count = int(request.form.get('batch_count', 2))
        duration = float(request.form.get('duration', 1.2))
        
        selected_motions = request.form.getlist('motions')
        if not selected_motions:
            return jsonify({"error": "동작을 최소 하나 이상 선택해 주세요."}), 400

        file = request.files.get('image')
        if not file: return jsonify({"error": "이미지 파일이 없습니다."}), 400
        
        filepath = os.path.join(UPLOAD_FOLDER, secure_filename(file.filename))
        file.save(filepath)

        # 1. 템플릿 파일 존재 확인
        if not os.path.exists(TEMPLATE_FILENAME):
            print(f"!!! Error: {TEMPLATE_FILENAME} not found in current directory: {os.getcwd()}")
            return jsonify({"error": f"서버에 {TEMPLATE_FILENAME} 파일이 없습니다. 확인해 주세요."}), 500

        # 2. 블랙웰 서버로 업로드
        print(f"Uploading {filepath} to ComfyUI at {COMFYUI_URL}...")
        upload_res = upload_to_comfyui(filepath)
        blackwell_filename = upload_res['name']

        # 3. 템플릿 로드
        with open(TEMPLATE_FILENAME, 'r') as f:
            template = json.load(f)

        results = []
        for m_type in selected_motions:
            custom_prompt = request.form.get(f'prompt_{m_type}', '')
            for v in range(1, batch_count + 1):
                payload = json.loads(json.dumps(template))
                
                full_save_path = f"{save_path_prefix}/{char_name}/{char_name}_{m_type}_v{v}"
                
                # 워크플로우 내의 노드 데이터 수정 (v2.9.1 기준 노드 ID)
                payload["398"]["inputs"]["filename_prefix"] = full_save_path
                payload["408"]["inputs"]["value"] = custom_prompt + " Style: Clean 2D Chibi art, Granado Espada aesthetic. 512x512, white background."
                payload["426"]["inputs"]["Xi"] = duration
                payload["426"]["inputs"]["Xf"] = duration
                payload["516"]["inputs"]["image"] = blackwell_filename
                payload["552"]["inputs"]["seed"] = random.randint(100000, 999999)

                # ComfyUI API 호출
                req = urllib.request.Request(f"{COMFYUI_URL}/prompt", 
                                             data=json.dumps({"prompt": payload}).encode("utf-8"),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req) as res:
                    res_data = json.loads(res.read().decode())
                    results.append({"type": m_type, "version": v, "prompt_id": res_data.get("prompt_id")})

        print(f"Successfully queued {len(results)} jobs.")
        return jsonify({"status": "Success", "queued": results})

    except Exception as e:
        print("!!! UNEXPECTED ERROR !!!")
        traceback.print_exc()
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

@app.route('/status/<prompt_id>')
def get_status(prompt_id):
    try:
        with urllib.request.urlopen(f"{COMFYUI_URL}/history/{prompt_id}") as res:
            history = json.loads(res.read().decode())
        if prompt_id in history:
            outputs = history[prompt_id].get('outputs', {})
            for node_id in outputs:
                if 'images' in outputs[node_id]:
                    img_data = outputs[node_id]['images'][0]
                    img_url = f"{COMFYUI_URL}/view?filename={img_data['filename']}&subfolder={img_data['subfolder']}&type=output"
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

if __name__ == '__main__':
    # 디버그 모드를 켜서 에러 메시지가 브라우저와 터미널에 상세히 찍히도록 함
    app.run(host='0.0.0.0', port=3031, debug=True)
