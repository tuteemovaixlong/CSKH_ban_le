"""The only decisions the customer agent takes out of the model's hands before it runs (W3.2-D9).

Three safety rails, all in code: a forbidden topic, a customer who is extremely upset (a threat to
post the case publicly, sue, or report to a platform), and a request to speak to a person. Everything
else, including what the customer wants and which tools to use, is the model's call. The legacy
supervisor graph shares these rails.
"""
from dataclasses import dataclass
import re

from retailops.guardrails.topic_filter import check_topic_safety, is_read_only_lookup_intent

HUMAN_REQUEST_KEYWORDS = [
    "gặp nhân viên", "gặp người", "gặp quản lý", "gặp tư vấn viên", "chuyển máy",
    "nói chuyện với người", "nhân viên đâu", "admin đâu", "human agent", "talk to human",
    "gặp người thật", "người thật", "tư vấn viên", "kết nối nhân viên", "gặp cskh",
    "nhân viên hỗ trợ", "chuyên viên", "nhân viên trực tiếp", "gặp người trực tiếp",
    "chuyển người", "người hỗ trợ", "quản lý đâu", "cho gặp quản lý", "nhân viên trực",
    "nói chuyện với nhân viên", "gọi người thật", "gọi nhân viên", "không muốn chat với bot",
    "không làm việc với bot", "đừng trả lời tự động", "chuyển qua cskh", "chuyển cho nhân viên",
    "bấm nút gặp nhân viên", "kết nối với tư vấn viên", "gọi tư vấn viên", "yêu cầu gặp người thật",
    "yêu cầu gặp quản lý", "chuyển em sang người thật", "kết nối giúp em với người thật",
    "nối máy ngay cho quản lý", "nối máy cho quản lý", "kêu người có trách nhiệm",
    "yêu cầu nhân viên thật", "gọi quản lý ra đây", "người quản lý ra đây", "nhân viên cskh",
    "chuyển sang nhân viên", "gặp quản lý gấp", "gặp nhân viên quản lý", "đang bực lắm",
]

EXTREME_RAGE_KEYWORDS = [
    "bóc phốt", "tẩy chay", "báo công an", "sập tiệm", "khởi kiện", "thưa kiện", "kiện cáo",
    "quay clip đăng tiktok", "quay clip", "livestream",
    "đăng bài tố cáo", "đăng bài facebook", "đăng facebook tố cáo", "báo cơ quan chức năng",
    "đồ vô trách nhiệm", "làm ăn chụp giật", "chửi cho các người", "ăn cướp",
    "khiếu nại lên sàn", "khiếu nại sàn", "báo sàn", "báo lên sàn",
    "khiếu nại lên shopee", "khiếu nại lên lazada", "khiếu nại lên tiktok",
    "hiệp hội bảo vệ người tiêu dùng", "tố cáo khắp nơi", "không tự chịu nổi", "đăng tiktok bóc phốt",
    "quay clip tiktok bóc phốt", "đăng lên các hội nhóm mua sắm",
]

_HOURS_QUESTION = ("khung giờ", "giờ làm việc", "mấy giờ đến mấy giờ", "khi nào có", "kênh hotline")
_SUE = re.compile(r"(?<!điều )\bkiện\b")

RAGE_REPLY = (
    "Dạ shop thành thật xin lỗi vì trải nghiệm rất không tốt vừa qua của anh/chị! Shop hoàn toàn hiểu sự bức xúc "
    "của anh/chị và xin cam kết chịu trách nhiệm xử lý thỏa đáng 100%. Em đã gửi cảnh báo đỏ trực tiếp đến Quản lý "
    "cửa hàng để tiếp nhận và gọi lại hỗ trợ anh/chị ngay lập tức ạ!"
)
HUMAN_REPLY = (
    "Dạ em đã ghi nhận yêu cầu của anh/chị và đang kết nối tới nhân viên tư vấn trực ca. "
    "Nhân viên sẽ phản hồi lại anh/chị trong ít phút nữa nhé ạ!"
)


@dataclass(frozen=True)
class SafetyVerdict:
    rail: str                      # 'forbidden_topic' | 'extreme_rage' | 'human_request'
    reply: str
    human_reason: str | None = None  # set when a person must be called in
    strict_mode: bool = False


def human_request_text(text, *, read_only: bool | None = None) -> bool:
    lower = (text or "").lower()
    if read_only is None:
        read_only = is_read_only_lookup_intent(text)
    asks_hours = any(w in lower for w in _HOURS_QUESTION)
    return not read_only and not asks_hours and any(kw in lower for kw in HUMAN_REQUEST_KEYWORDS)


def extreme_rage_text(text, *, read_only: bool | None = None) -> bool:
    lower = (text or "").lower()
    if read_only is None:
        read_only = is_read_only_lookup_intent(text)
    return (not read_only) and (any(kw in lower for kw in EXTREME_RAGE_KEYWORDS) or bool(_SUE.search(lower)))


def safety_gate(text) -> SafetyVerdict | None:
    """The verdict of the three rails for one customer message, or None when the model should handle it."""
    topic = check_topic_safety(text)
    if not topic.is_safe:
        return SafetyVerdict('forbidden_topic', topic.refusal_message)
    read_only = is_read_only_lookup_intent(text)
    if extreme_rage_text(text, read_only=read_only):
        return SafetyVerdict(
            'extreme_rage', RAGE_REPLY,
            human_reason="SOP 5: Khách hàng bức xúc cực độ / đe dọa bóc phốt / khiếu nại sàn TMĐT (Strict Mode)",
            strict_mode=True)
    if human_request_text(text, read_only=read_only):
        return SafetyVerdict(
            'human_request', HUMAN_REPLY,
            human_reason="SOP 6: Khách hàng bấm nút hoặc yêu cầu gặp trực tiếp nhân viên tư vấn")
    return None
