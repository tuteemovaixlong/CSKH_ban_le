"""Run against prepared real weights with networking disabled. No generation/provider API."""
import json
import math
import sys
from retailops.knowledge.embedding import CpuEmbedding

embedding = CpuEmbedding(sys.argv[1] if len(sys.argv)>1 else '/data/embedding-model')
vectors = embedding.encode(['Khách có thể đổi trả sản phẩm trong bảy ngày.',
                            'Returns are accepted within seven days.',
                            'Cách cài đặt hệ điều hành máy tính.'])
assert len(vectors) == 3 and all(len(v)==384 for v in vectors)
assert all(abs(sum(x*x for x in v)-1)<1e-5 for v in vectors)
same = sum(a*b for a,b in zip(vectors[0],vectors[1]))
unrelated = sum(a*b for a,b in zip(vectors[0],vectors[2]))
assert math.isfinite(same) and same > unrelated
from pathlib import Path
from retailops.core import ROOT
from retailops.knowledge.store import MIN_SCORE, chunks
collection = json.loads((ROOT/'data/knowledge/demo.json').read_text())
parts = [(d['id'], part) for d in collection for part in chunks(d['content'])]
encoded = embedding.encode([p for _,p in parts])
for query, expected in [('Chính sách đổi trả thế nào?','POL-RETURN'),
                        ('Áo thun chất liệu gì?','GUIDE-MATERIAL'),
                        ('Tôi có thể hủy đơn đã giao không?','POL-CANCEL')]:
    q = embedding.encode([query])[0]
    ranked = sorted([(sum(a*b for a,b in zip(q,v)), identity) for (identity,_),v in zip(parts,encoded)], reverse=True)
    assert ranked[0][1] == expected and ranked[0][0] >= MIN_SCORE
print(json.dumps({'result':'CPU_EMBEDDING_OFFLINE_OK','fingerprint':embedding.fingerprint,
                  'dimension':384,'scope':'synthetic embedding and retrieval smoke only; not an independent benchmark'}))
