import os
import requests


def upload_image(file_path):
    """上传图片到图床并返回链接

    :param file_path: 本地图片路径
    :return: 成功返回图片URL，失败返回 None
    """
    url = "http://api.hanak.cn/ajax.php?act=upload"

    # 设置请求头（保持和你抓包的数据一致，避免被服务器拒绝）
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Proxy-Connection": "keep-alive",
        "Referer": "http://api.hanak.cn/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
        # 注意：不要手动在这里加 'Content-Type': 'multipart/form-data'，
        # 也不要加 boundary，requests 库会自动生成正确的 boundary
    }

    # 检查文件是否存在
    if not os.path.exists(file_path):
        print(f"错误: 文件 {file_path} 不存在！")
        return None

    try:
        # 以二进制只读模式打开图片
        with open(file_path, "rb") as f:
            # 这里的 "file" 对应你抓包数据中的 name="file"
            files = {"file": (os.path.basename(file_path), f, "image/jpeg")}

            # 发送 POST 请求
            response = requests.post(url, headers=headers, files=files)

            # 判断状态码
            if response.status_code == 200:
                # 解析返回的 JSON 数据
                res_json = response.json()
                if res_json.get("code") == 1:
                    print("上传成功！")
                    return res_json.get("url")
                else:
                    print(f"上传失败，服务器返回: {res_json.get('msg')}")
                    return None
            else:
                print(f"网络请求失败，状态码: {response.status_code}")
                return None

    except Exception as e:
        print(f"发生异常: {e}")
        return None


# --- 测试调用 ---
if __name__ == "__main__":
    # 替换为你电脑上真实的图片路径
    img_path = "./images/frames/b07e8411_scene05_lastframe.jpg"

    img_url = upload_image(img_path)
    if img_url:
        print(f"图床链接: {img_url}")