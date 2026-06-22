import requests

# ========== 配置 ==========
API_KEY = "你在agnes-ai的API key（免费无限量）"
API_URL = "https://apihub.agnes-ai.com/v1/chat/completions"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# ========== 生成文本 ==========
def generate_text(prompt, max_tokens=1024, temperature=0.7):
    """
    使用 Agnes-2.0-Flash 生成文本
    
    :param prompt: 用户输入文本
    :param max_tokens: 最大输出 token 数
    :param temperature: 随机性
    :return: 模型生成文本
    """
    payload = {
        "model": "agnes-2.0-flash",
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful AI assistant."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "max_tokens": max_tokens,
        "temperature": temperature
    }

    response = requests.post(API_URL, headers=HEADERS, json=payload)

    if response.status_code != 200:
        print("请求失败")
        print(response.status_code)
        print(response.text)
        return None

    data = response.json()
    choices = data.get("choices", [])
    if not choices:
        print("没有返回内容")
        return None

    # 返回第一条生成结果
    return choices[0]["message"]["content"]


# ========== 流程测试 ==========
if __name__ == "__main__":
    user_prompt = input("请输入你希望生成的内容：\n")
    result = generate_text(user_prompt)

    if result:
        print("\n=== 模型生成结果 ===")
        print(result)