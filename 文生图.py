import requests
import json
import os
import uuid
import webbrowser
from pathlib import Path


API_KEY = "你在agnes-ai的API key（免费无限量）"
URL = "https://apihub.agnes-ai.com/v1/images/generations"
IMAGE_DIR = "images"


# 创建保存目录
Path(IMAGE_DIR).mkdir(exist_ok=True)


def generate_image(prompt: str, size: str = "1024x768", model: str = "agnes-image-2.1-flash") -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "extra_body": {
            "response_format": "url"
        }
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    response = requests.post(URL, headers=headers, data=json.dumps(payload))
    response.raise_for_status()
    data = response.json()
    return data["data"][0]["url"]


def save_image(image_url: str, save_dir: str = IMAGE_DIR) -> str:
    """下载图片到本地并返回文件路径"""
    response = requests.get(image_url)
    response.raise_for_status()
    
    # 生成唯一文件名
    file_ext = image_url.split('.')[-1].split('?')[0]
    filename = f"{uuid.uuid4().hex}.{file_ext}"
    file_path = os.path.join(save_dir, filename)
    
    with open(file_path, 'wb') as f:
        f.write(response.content)
    
    return file_path


if __name__ == "__main__":
    prompt = input("请输入描述：")
    image_url = generate_image(prompt)
    print(f"图片 URL: {image_url}")
    
    try:
        file_path = save_image(image_url)
        print(f"图片已保存到：{file_path}")
        
        # 自动打开图片
        webbrowser.open(f"file:///{os.path.abspath(file_path)}")
        print("图片已自动打开")
    except Exception as e:
        print(f"保存或打开图片失败：{e}")
