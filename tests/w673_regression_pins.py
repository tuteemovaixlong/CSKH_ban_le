"""SHA256 đầu ra giả, sinh một lần từ mã mốc; test không cần lịch sử Git.

Chỉ chuẩn hóa CRLF thành LF và đường dẫn JSON nằm dưới workspace tạm
thành <WORKSPACE>/... để cùng pin dùng được trên Windows/Linux.
Giữ nguyên thứ tự, trường dữ liệu và các byte nội dung khác.
"""
import hashlib
import json
import re
from pathlib import Path

JSON_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')


def canonical_bytes(data: bytes, workspace: Path) -> bytes:
    text = data.decode('utf-8').replace('\r\n', '\n')
    roots = sorted({str(workspace), str(workspace.resolve())}, key=len, reverse=True)

    def replace_path(match):
        token = match.group(0)
        try:
            value = json.loads(token)
        except ValueError:
            return token
        for root in roots:
            if value == root or value.startswith((root + '/', root + '\\')):
                tail = value[len(root):].replace('\\', '/')
                return json.dumps('<WORKSPACE>' + tail, ensure_ascii=False)
        return token

    return JSON_STRING.sub(replace_path, text).encode('utf-8')


def snapshot(data, workspace):
    if isinstance(data, dict):
        return {name: snapshot(content, workspace) for name, content in data.items()}
    return hashlib.sha256(canonical_bytes(data, workspace)).hexdigest()


def assert_snapshot(test, name, data, workspace):
    test.assertEqual(snapshot(data, workspace), PINS[name], f'Đầu ra giả lệch mốc đã ghim: {name}')


# Nguồn: pipeline = 0780af0207c858c993e6d745923feb000bdf1e4d;
# G = 0f21789f1a37dd99d38dc31d46fd3e930e6c3c85.
# Không cập nhật các pin chỉ vì mã hiện tại tạo ra kết quả khác.
PINS = {'g_build': {'build_report.md': '7e786e6d9ed3db87217c00c0ba9b3333f25ab8082bd9efdc3037aaa53b145e4e',
             'stats.json': '50f69a2743a50ca196a4fee6ec2f47faf7cb962eaeac1fb8451c8ffb17cb3aa3',
             'train.jsonl': 'ef3218b410b999fc0d3b07b7223f345881b3626d56dd4869b130d5d8cc9af7f7',
             'val.jsonl': '933ce48df17f82ded7daea26fd8b705e09452b27364a7137c7c4cbaecfa3b204'},
 'g_legacy_scores': 'e74347ae729ece1ffde342ca5c3a80bd06de50fb6db8075787072592554e7276',
 'g_runs_scores': '0874607ed43259be12d4a97ca2ddd2234e93026b614c18f8d3c0f220b1ccfaca',
 'pipeline_build': {'build_report.md': '7e786e6d9ed3db87217c00c0ba9b3333f25ab8082bd9efdc3037aaa53b145e4e',
                    'stats.json': '50f69a2743a50ca196a4fee6ec2f47faf7cb962eaeac1fb8451c8ffb17cb3aa3',
                    'train.jsonl': 'ef3218b410b999fc0d3b07b7223f345881b3626d56dd4869b130d5d8cc9af7f7',
                    'val.jsonl': '933ce48df17f82ded7daea26fd8b705e09452b27364a7137c7c4cbaecfa3b204'},
 'pipeline_cjk_export': '44414ee8c3c0d1d3fa4132bb8cb53b143cab647c0ae4a1fbc1f680c3891d9103',
 'pipeline_cjk_import': '9f9850d79c0bff3905ad9b701b5aac1bdfcd44a3c3ac54c96d3a5172cbd7c97a',
 'pipeline_import': '5d3a0ba78c369a15557f750abdb417a67a171f7e8ad14f231bcaadc7f7053f28',
 'pipeline_round_1': {'map.json': '17b357cc72c5fb3c766cc5659fba35e4bb99c1b029d5cf576d581c772f7597aa',
                      'packets/batch-01.jsonl': '8e793031f829a26ec9c9d8eea3d07e85b237465feb0791a55a43749838d50d11'},
 'pipeline_round_2': {'map.json': 'be53c53c3b0c4e12fb929a4b4a85ebdae8d0cd232bd9167f325e6b8e11c4234b'},
 'pipeline_scores': '732568b36c20238fb34348a268ff8ef4dfd42452b729854dd72a5bf63f566fd1',
 'pipeline_select': {'selection': '9107d0ca9cea4f1dc9cba924b86f44d607a8a8299c5d8c2a4bb8b2b8ab7076ae',
                     'selection_report.md': '13a9092c2036c4744d6b8814a40636f724ce3772b287fa467d90d84f2c8498ef'}}
