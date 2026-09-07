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
print(json.dumps({'result':'CPU_EMBEDDING_OFFLINE_OK','fingerprint':embedding.fingerprint,
                  'dimension':384,'scope':'three synthetic sentences; not an independent benchmark'}))
