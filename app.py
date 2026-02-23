import os
import json
import urllib.request
import urllib.parse
import random
from flask import Flask, render_template, request, jsonify, make_response
from werkzeug.utils import secure_filename

app = Flask(__name__)

# --- 설정 (Configuration) ---
COMFYUI_URL = "http://192.168.3.15:8189"  # 오빠가 알려준 8189 포트로 수정 완료!
UPLOAD_FOLDER = 'uploads'
TEMPLATE_PATH = 'knight_v7_struct_template.json' 

if not os.path.exists(TEMPLATE_PATH):
    TEMPLATE_PATH = '/home/aura/open_storage/projects/granado_espada/knight_v7_struct_template.json'

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
    char_name = request.form.get('char_name', 'Unknown')
    save_path_prefix = request.form.get('save_path', 'WAN/GE_SD/PC/').rstrip('/')
    batch_count = int(request.form.get('batch_count', 2))
    duration = float(request.form.get('duration', 1.2))
    
    selected_motions = request.form.getlist('motions')
    prompts = {}
    for m in selected_motions:
        prompts[m] = request.form.get(f'prompt_{m}', '')

    file = request.files.get('image')
    if not file: return jsonify({"error": "이미지 파일이 없습니다."}), 400
    
    filepath = os.path.join(UPLOAD_FOLDER, secure_filename(file.filename))
    file.save(filepath)

    try:
        upload_res = upload_to_comfyui(filepath)
        blackwell_filename = upload_res['name']

        with open(TEMPLATE_PATH, 'r') as f:
            template = json.load(f)

        results = []
        for m_type, custom_prompt in prompts.items():
            for v in range(1, batch_count + 1):
                payload = json.loads(json.dumps(template))
                
                full_save_path = f"{save_path_prefix}/{char_name}/{char_name}_{m_type}_v{v}"
                payload["398"]["inputs"]["filename_prefix"] = full_save_path
                payload["408"]["inputs"]["value"] = custom_prompt + " Style: Clean 2D Chibi art, Granado Espada aesthetic. 512x512, white background."
                payload["426"]["inputs"]["Xi"] = duration
                payload["426"]["inputs"]["Xf"] = duration
                payload["516"]["inputs"]["image"] = blackwell_filename
                payload["552"]["inputs"]["seed"] = random.randint(100000, 999999)

                req = urllib.request.Request(f"{COMFYUI_URL}/prompt", 
                                             data=json.dumps({"prompt": payload}).encode("utf-8"),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req) as res:
                    res_data = json.loads(res.read().decode())
                    results.append({"type": m_type, "version": v, "prompt_id": res_data.get("prompt_id")})

        return jsonify({"status": "Success", "queued": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
    app.run(host='0.0.0.0', port=3031)
