"""Topic guardrail for filtering forbidden/sensitive domains.
Disallows medical diagnosis, legal counsel, politics, religious controversy, and violent/illegal content.
"""
import re
from dataclasses import dataclass

FORBIDDEN_TOPICS = {
    "medical": {
        "patterns": [
            r"\b(uống thuốc|liều lượng|đau bụng|ung thư|khám bệnh|chữa bệnh|chẩn đoán|bệnh viện|bác sĩ|triệu chứng|dược phẩm|kháng sinh)\b",
            r"\b(doctor|medicine|disease|symptom|prescription|hospital|treatment|cancer)\b"
        ],
        "refusal": "Dạ em là trợ lý bán hàng nên không có chuyên môn y tế. Đối với các vấn đề sức khỏe hoặc thuốc men, anh/chị vui lòng tham khảo ý kiến bác sĩ hoặc cơ sở y tế gần nhất để được hỗ trợ tốt nhất nhé ạ!"
    },
    "legal": {
        "patterns": [
            r"\b(luật sư|khởi kiện|tòa án|vi hiến|hình sự|tội phạm|lách luật|hối lộ|tham nhũng)\b",
            r"\b(lawyer|lawsuit|attorney|court|criminal|bribe|illegal)\b"
        ],
        "refusal": "Dạ em chỉ có thể tư vấn các chính sách bán hàng và đổi trả của shop, không thể đưa ra lời khuyên pháp lý. Anh/chị có câu hỏi nào về sản phẩm hay đơn hàng của shop không ạ?"
    },
    "politics_religion": {
        "patterns": [
            r"\b(chính trị|đảng|nhà nước|biểu tình|bầu cử|tôn giáo|phản động|bộ chính trị)\b",
            r"\b(politics|government|election|protest|religion)\b"
        ],
        "refusal": "Dạ em xin phép không thảo luận về các chủ đề chính trị hay tôn giáo. Shop luôn sẵn sàng hỗ trợ anh/chị về các sản phẩm và đơn hàng mua sắm ạ!"
    },
    "harassment_violence": {
        "patterns": [
            r"\b(tự tử|tự hại|đánh bom|vũ khí|giết|tự sát)\b",
            r"\b(suicide|self-harm|bomb|weapon|kill)\b"
        ],
        "refusal": "Dạ em xin phép từ chối phản hồi nội dung này. Nếu anh/chị đang gặp khó khăn hoặc cần hỗ trợ, xin vui lòng liên hệ các đường dây trợ giúp khẩn cấp ạ."
    }
}


@dataclass
class TopicFilterResult:
    is_safe: bool
    category: str | None = None
    refusal_message: str | None = None


def check_topic_safety(text: str) -> TopicFilterResult:
    """Check whether the user input touches on forbidden domains."""
    if not text:
        return TopicFilterResult(is_safe=True)

    lower = text.lower()
    for category, details in FORBIDDEN_TOPICS.items():
        for pattern in details["patterns"]:
            if re.search(pattern, lower):
                return TopicFilterResult(
                    is_safe=False,
                    category=category,
                    refusal_message=details["refusal"]
                )

    return TopicFilterResult(is_safe=True)
