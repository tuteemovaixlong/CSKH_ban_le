"""Validate citation provenance, not semantic entailment. No model-authored sources."""
import copy
import re

REFERENCE = re.compile(r"\[([Kk][Bb]:[^\]\r\n]*)\]")
CITATION_ID = re.compile(r"KB:[a-f0-9]{24}")


class CitationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def cited_sources(answer, evidence):
    """Only accept references to snippets actually returned in this turn.

    Missing citations after successful retrieval fail closed. This does not prove
    that an answer follows from a passage; that is a separate evaluation task.
    """
    by_id = {s['citation_id']: s for s in evidence
             if isinstance(s, dict) and isinstance(s.get('citation_id'), str) and CITATION_ID.fullmatch(s['citation_id'])}
    refs = list(dict.fromkeys(REFERENCE.findall(answer)))
    if any(ref not in by_id for ref in refs):
        raise CitationError('knowledge_citation_invalid')
    if by_id and not refs:
        raise CitationError('knowledge_citation_missing')
    return [copy.deepcopy(by_id[ref]) for ref in refs]
