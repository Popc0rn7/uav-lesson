# /// script
# requires-python = ">=3.12"
# dependencies = ["requests", "python-dotenv"]
# ///
"""运行：uv run stage3/demo.py；自定义输入：uv run stage3/demo.py '这个产品太好用了！'"""

import sys

import requests

from jev import JevClient, make_noul, make_choice, make_score


def main():
    client = JevClient()

    text = " ".join(sys.argv[1:]) or "这个产品太好用了，下次还会买！"

    questions = {
        **make_noul("is_positive", "text 是否表达了正面情绪？", {
            "true": "表达满意、喜欢或赞扬。",
            "false": "中性描述，或表达不满、失望、批评。",
        }),
        **make_choice("sentiment", "判断 text 的情感倾向。", {
            "正面": "表达满意、喜欢或赞扬。",
            "中性": "客观描述，没有明显情绪。",
            "负面": "表达不满、失望或批评。",
        }),
        **make_score("satisfaction", "根据 text 判断满意程度。", [
            "非常不满意", "不满意", "一般", "满意", "非常满意",
        ]),
    }
    try:
        result = client.request(questions, state={"text": text})
    except requests.RequestException as exc:
        sys.exit(f"请求失败：{exc}")
    answers = result["answers"]
    print(f"输入：{text}")
    print(f"noul  正面情绪的概率：{answers['is_positive']['noul']:.1%}")
    result = answers["sentiment"]
    print(f"choice 情感分类：{result['choice']}")
    print("各选项概率：")
    for label, probability in result["probabilities"].items():
        print(f"  {label}：{probability:.1%}")
    print(
        f"score 满意程度：{answers['satisfaction']['score']:.2f} / 4（0=非常不满意，4=非常满意）"
    )


if __name__ == "__main__":
    main()
